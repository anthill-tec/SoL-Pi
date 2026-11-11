/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

// The release workflow: `.github/workflows/release.yml` is the `modelb-axi release-workflow`
// rendering (committed verbatim as `tests/fixtures/release-workflow/rendered.yml`) with a fixed,
// enumerated set of hand edits. Re-rendering drops the hand edits; these tests catch that.

import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";
import { rootFile } from "./helpers.ts";

type Step = Record<string, unknown> & { name?: string; uses?: string; run?: string; with?: Record<string, unknown>; env?: Record<string, unknown> };
type Job = Record<string, unknown> & { steps: Step[]; needs?: string[]; permissions?: Record<string, string>; env?: Record<string, unknown> };
type Workflow = { on: { push: { branches: string[] } }; jobs: Record<string, Job> };

const RELEASE_PATH = ".github/workflows/release.yml";
const RENDERED_PATH = "tests/fixtures/release-workflow/rendered.yml";
const PUBLISHING_JOBS = ["create-release", "rehearse", "publish-pypi", "publish-npm"];
const TEST_JOBS = ["test-bun", "test-python"];
const BUN_VERSION = "1.4.4";
const DISCOVERY = "python -m unittest discover -s tests -t .";
/** The values `PI_BIN` may take: the development dependency's `pi`, relative or under the workspace. */
const PI_BIN_VALUES = ["node_modules/.bin/pi", "${{ github.workspace }}/node_modules/.bin/pi", "$GITHUB_WORKSPACE/node_modules/.bin/pi"];

function parse(text: string): Workflow {
	return Bun.YAML.parse(text) as Workflow;
}

const releaseText = (): string => rootFile(RELEASE_PATH);
const renderedText = (): string => rootFile(RENDERED_PATH);
const release = (): Workflow => parse(releaseText());
const rendered = (): Workflow => parse(renderedText());

/** The single pin of `action` (e.g. `actions/setup-node`) used throughout the rendering. */
function renderingPin(action: string): string {
	const pins = new Set<string>();
	for (const job of Object.values(rendered().jobs)) {
		for (const step of job.steps) if (step.uses?.startsWith(`${action}@`)) pins.add(step.uses);
	}
	if (pins.size !== 1) throw new Error(`the rendering pins ${action} ${pins.size} ways: ${[...pins].join(", ")}`);
	const [pin] = [...pins];
	if (!/@[0-9a-f]{40}$/u.test(pin!)) throw new Error(`the rendering's ${action} pin is not a commit SHA: ${pin}`);
	return pin!;
}

function withoutName(step: Step): Step {
	const { name: _name, ...rest } = step;
	return rest as Step;
}

function isTestStep(step: Step): boolean {
	return step.name === "Run the tests";
}

function stepIndex(steps: Step[], predicate: (step: Step) => boolean, what: string): number {
	const indices = steps.flatMap((step, index) => (predicate(step) ? [index] : []));
	if (indices.length !== 1) throw new Error(`expected exactly one ${what} step, found ${indices.length}`);
	return indices[0]!;
}

const isSetupNode = (pin: string) => (step: Step) => step.uses === pin;
const isSetupBun = (step: Step) => typeof step.uses === "string" && step.uses.startsWith("oven-sh/setup-bun@");
const isBunInstall = (step: Step) => step.run === "bun install --frozen-lockfile";
/** Installs the project with its `dev` extra into the interpreter the discovery step runs. */
const isProjectInstall = (step: Step) =>
	typeof step.run === "string" && /\b(uv pip|pip) install\b[^\n]*(["']?)\.\[dev\]\2/u.test(step.run);
/** Writes `PI_BIN` to `$GITHUB_ENV`. */
const PI_BIN_ENV_STEP = /^echo ["']?PI_BIN=(.+?)["']? >> ["']?\$GITHUB_ENV["']?\s*$/u;
const isPiBinEnvStep = (step: Step) => typeof step.run === "string" && PI_BIN_ENV_STEP.test(step.run.trim());

/** Every place `test-python` sets `PI_BIN`, with the value set there. */
function piBinSettings(job: Job): { where: string; value: unknown; index: number }[] {
	const settings: { where: string; value: unknown; index: number }[] = [];
	if (job.env && "PI_BIN" in job.env) settings.push({ where: "job env", value: job.env.PI_BIN, index: -1 });
	job.steps.forEach((step, index) => {
		if (step.env && "PI_BIN" in step.env) settings.push({ where: `step ${index} env`, value: step.env.PI_BIN, index });
		if (isPiBinEnvStep(step)) {
			settings.push({ where: `step ${index} $GITHUB_ENV`, value: step.run!.trim().match(PI_BIN_ENV_STEP)![1], index });
		}
	});
	return settings;
}

// ---- Text-level split for the hand-edit comparison --------------------------------------------

/** The lines up to and including `jobs:`, and each job's lines (key line to the next job key). */
function splitJobs(text: string): { prelude: string[]; jobs: { name: string; lines: string[] }[] } {
	const lines = text.split("\n");
	const jobsAt = lines.indexOf("jobs:");
	if (jobsAt < 0) throw new Error("no top-level jobs: line");
	const jobs: { name: string; lines: string[] }[] = [];
	for (const line of lines.slice(jobsAt + 1)) {
		const key = line.match(/^ {2}([A-Za-z0-9_-]+):\s*$/u);
		if (key) jobs.push({ name: key[1]!, lines: [line] });
		else if (jobs.length > 0) jobs.at(-1)!.lines.push(line);
		else throw new Error(`line before the first job: ${line}`);
	}
	return { prelude: lines.slice(0, jobsAt + 1), jobs };
}

/** The production-branch hand edit: every `master` of the rendering becomes `main`. */
const toMain = (line: string): string => line.replaceAll("master", "main");

describe("release workflow", () => {
	it("pushes run on main, release/** and hotfix/** and nothing names master", () => {
		expect(release().on.push.branches).toEqual(["main", "release/**", "hotfix/**"]);
		expect(releaseText()).not.toContain("master");
	});

	it("every publishing job needs both test jobs", () => {
		const jobs = release().jobs;
		for (const name of PUBLISHING_JOBS) {
			expect(jobs[name], name).toBeDefined();
			expect([...(jobs[name]!.needs ?? [])].sort(), name).toEqual(TEST_JOBS);
		}
	});

	it("publish-pypi and rehearse have id-token write", () => {
		const jobs = release().jobs;
		for (const name of ["publish-pypi", "rehearse"]) {
			expect(jobs[name]?.permissions?.["id-token"], name).toBe("write");
		}
		expect(jobs.rehearse?.environment).toBe("testpypi");
	});

	it("both publish guards run: only an X.Y.Z tag ref whose commit is on origin/main passes", () => {
		const root = mkdtempSync(join(tmpdir(), "release-guard-"));
		const git = (cwd: string, ...args: string[]): string => {
			const result = spawnSync("git", args, { cwd, encoding: "utf8" });
			if (result.status !== 0) throw new Error(`git ${args.join(" ")}: ${result.stderr}`);
			return result.stdout.trim();
		};
		try {
			const origin = join(root, "origin.git");
			const work = join(root, "work");
			git(root, "init", "--bare", "--initial-branch=main", origin);
			git(root, "clone", origin, work);
			git(work, "config", "user.email", "ci@example.invalid");
			git(work, "config", "user.name", "ci");
			git(work, "commit", "--allow-empty", "-m", "on main");
			git(work, "push", "origin", "HEAD:main");
			const onMain = git(work, "rev-parse", "HEAD");
			git(work, "checkout", "-b", "release-candidate");
			git(work, "commit", "--allow-empty", "-m", "off main");
			const offMain = git(work, "rev-parse", "HEAD");

			const guard = (run: string, ref: string, sha: string) =>
				spawnSync("bash", ["-e", "-c", run], { cwd: work, encoding: "utf8", env: { ...process.env, GITHUB_REF: ref, GITHUB_SHA: sha } });

			const jobs = release().jobs;
			for (const name of ["publish-pypi", "publish-npm"]) {
				expect(jobs[name], name).toBeDefined();
				const guards = jobs[name]!.steps.filter((step) => step.name?.startsWith("Guard"));
				expect(guards.map((step) => step.name), name).toEqual(["Guard - a version tag on main's history"]);
				const run = guards[0]!.run!;
				expect(guard(run, "refs/tags/0.1.0", onMain).status, `${name}: tag on main`).toBe(0);
				const branch = guard(run, "refs/heads/main", onMain);
				expect(branch.status, `${name}: branch ref`).toBe(1);
				expect(branch.stdout).toContain("is not an X.Y.Z tag ref");
				const stray = guard(run, "refs/tags/0.1.0", offMain);
				expect(stray.status, `${name}: tag off main`).toBe(1);
				expect(stray.stdout).toContain("is not on origin/main");
			}
		} finally {
			rmSync(root, { recursive: true, force: true });
		}
	});

	it("create-release runs on main and checks the tag against pypi:. and npm:.", () => {
		const job = release().jobs["create-release"]!;
		expect(String(job.if)).toContain("github.ref == 'refs/heads/main'");
		const checks = job.steps.filter((step) => step.run?.includes("stamp_version.py check"));
		expect(checks.map((step) => step.run)).toEqual(['python3 .github/scripts/stamp_version.py check "$TAG" pypi:. npm:.']);
	});

	it("test-bun pins Bun 1.4.4 and runs bun test --timeout 30000", () => {
		const steps = release().jobs["test-bun"]!.steps;
		const setupBun = steps[stepIndex(steps, isSetupBun, "oven-sh/setup-bun")]!;
		expect(setupBun.with).toEqual({ "bun-version": BUN_VERSION });
		expect(steps[stepIndex(steps, isTestStep, "Run the tests")]!.run).toBe("bun test --timeout 30000");
	});

	it("test-python installs the project and the Bun dependencies and sets PI_BIN before discovery", () => {
		const job = release().jobs["test-python"]!;
		expect(job).toBeDefined();
		const steps = job.steps;
		const discovery = stepIndex(steps, isTestStep, "Run the tests");
		expect(steps[discovery]!.run).toBe(DISCOVERY);
		const setupPython = stepIndex(steps, (step) => step.uses?.startsWith("actions/setup-python@") ?? false, "setup-python");
		const project = stepIndex(steps, isProjectInstall, "project install with the dev extra");
		const setupBun = stepIndex(steps, isSetupBun, "oven-sh/setup-bun");
		const bunInstall = stepIndex(steps, isBunInstall, "bun install --frozen-lockfile");
		expect(steps[setupBun]!.uses).toBe(renderingPin("oven-sh/setup-bun"));
		expect(steps[setupBun]!.with).toEqual({ "bun-version": BUN_VERSION });
		expect(setupPython).toBeLessThan(project);
		expect(project).toBeLessThan(discovery);
		expect(setupBun).toBeLessThan(bunInstall);
		expect(bunInstall).toBeLessThan(discovery);
		const settings = piBinSettings(job);
		expect(settings.length, JSON.stringify(settings)).toBe(1);
		expect(PI_BIN_VALUES).toContain(settings[0]!.value as string);
		expect(settings[0]!.index).toBeLessThanOrEqual(discovery);
	});

	it("test-bun and test-python set up Node 22 with the rendering's setup-node pin before their tests", () => {
		const pin = renderingPin("actions/setup-node");
		for (const name of TEST_JOBS) {
			const steps = release().jobs[name]?.steps ?? [];
			const nodes = steps.flatMap((step, index) => (step.uses?.startsWith("actions/setup-node@") ? [index] : []));
			expect(nodes.length, `${name}: setup-node steps`).toBe(1);
			const node = steps[nodes[0]!]!;
			expect(node.uses, name).toBe(pin);
			expect(node.with, name).toEqual({ "node-version": "22" });
			expect(nodes[0]!, name).toBeLessThan(stepIndex(steps, isTestStep, `${name} Run the tests`));
		}
	});

	it("the header lists the one-time setup", () => {
		const header = releaseText().split("\n\n")[0]!;
		for (const text of [
			"One-time setup:",
			"RELEASE_PAT",
			"environments `pypi` and `testpypi`",
			"environment `npm`",
			"admits the version tags",
			"admits the `release/**` and `hotfix/**`",
			"pending trusted",
			"publishers on pypi.org and test.pypi.org",
			"NPM_TOKEN for\n#   the first publish",
		]) {
			expect(header, text).toContain(text);
		}
	});

	// The comparison, defined: release.yml is rendered.yml with exactly §S5's hand edits.
	//  (1) Text, line for line, outside `test-bun` and `test-python`: the prelude (every line up to
	//      and including `jobs:`, so the generator line 1 is kept verbatim and the header comment
	//      differs only by master→main) and each other job block equal the rendering's with every
	//      `master` replaced by `main`; the jobs appear in the rendering's order.
	//  (2) `test-bun`, parsed: the job equals the rendering's except that setup-bun gains exactly
	//      `with: {bun-version: 1.4.4}`, the test step runs `bun test --timeout 30000`, and exactly
	//      one step is inserted before the tests: setup-node at the rendering's pin with exactly
	//      `with: {node-version: "22"}` (a `name` allowed).
	//  (3) `test-python`, parsed: the rendering's steps appear unchanged and in order, the
	//      discovery step free only to gain `env: {PI_BIN}`; the only inserted steps are, once each
	//      and before discovery: setup-node (as above), setup-bun at the rendering's pin with exactly
	//      `with: {bun-version: 1.4.4}`, `bun install --frozen-lockfile`, a pip-style install of
	//      `.[dev]`, and at most one `echo PI_BIN=… >> $GITHUB_ENV`; the job may gain only
	//      `env: {PI_BIN}`. `PI_BIN` is set exactly once (see the test above).
	describe("differs from the committed rendering by exactly the hand edits", () => {
		it("the rendering fixture is the generator's bun,python / pypi,npm output", () => {
			const text = renderedText();
			expect(text.split("\n")[0]).toMatch(/^# generated by modelb-axi \(Model B release workflow\); sha256 [0-9a-f]{64}$/u);
			expect(Object.keys(rendered().jobs)).toEqual(["test-bun", "test-python", "create-release", "rehearse", "publish-pypi", "publish-npm"]);
			// Each `master` the rendering holds lies where the hand edit list puts it.
			const { prelude, jobs } = splitJobs(text);
			const where = [
				...prelude.flatMap((line) => (line.includes("master") ? [line.startsWith("#") ? "header" : "push trigger"] : [])),
				...jobs.flatMap((job) => job.lines.filter((line) => line.includes("master")).map(() => job.name)),
			];
			expect([...new Set(where)]).toEqual(["header", "push trigger", "create-release", "publish-pypi", "publish-npm"]);
		});

		it("outside the test jobs, release.yml is the rendering with master replaced by main", () => {
			const ours = splitJobs(releaseText());
			const theirs = splitJobs(renderedText());
			expect(ours.prelude).toEqual(theirs.prelude.map(toMain));
			expect(ours.jobs.map((job) => job.name)).toEqual(theirs.jobs.map((job) => job.name));
			for (const job of theirs.jobs.filter((candidate) => !TEST_JOBS.includes(candidate.name))) {
				const mine = ours.jobs.find((candidate) => candidate.name === job.name);
				expect(mine?.lines, job.name).toEqual(job.lines.map(toMain));
			}
		});

		it("test-bun is the rendering's with the Bun pin, the timeout and setup-node only", () => {
			const pin = renderingPin("actions/setup-node");
			const theirs = rendered().jobs["test-bun"]!;
			const mine = release().jobs["test-bun"]!;
			const { steps: mySteps, ...myRest } = mine;
			const { steps: theirSteps, ...theirRest } = theirs;
			expect(myRest).toEqual(theirRest);
			const expected = theirSteps.map((step): Step => {
				if (isSetupBun(step)) return { ...step, with: { "bun-version": BUN_VERSION } };
				if (isTestStep(step)) return { ...step, run: "bun test --timeout 30000" };
				return step;
			});
			const inserted = mySteps.filter(isSetupNode(pin));
			expect(inserted.map(withoutName)).toEqual([{ uses: pin, with: { "node-version": "22" } }]);
			expect(mySteps.filter((step) => !isSetupNode(pin)(step))).toEqual(expected);
		});

		it("test-python is the rendering's with only the install, Bun, Node and PI_BIN additions", () => {
			const nodePin = renderingPin("actions/setup-node");
			const bunPin = renderingPin("oven-sh/setup-bun");
			const theirs = rendered().jobs["test-python"]!;
			const mine = release().jobs["test-python"];
			expect(mine).toBeDefined();
			const { steps: mySteps, env: myEnv, ...myRest } = mine!;
			const { steps: theirSteps, ...theirRest } = theirs;
			expect(myRest).toEqual(theirRest);
			if (myEnv !== undefined) expect(Object.keys(myEnv)).toEqual(["PI_BIN"]);

			// Kinds of inserted step; each required kind exactly once, the PI_BIN step at most once.
			const kinds: Record<string, (step: Step) => boolean> = {
				"setup-node": (step) => JSON.stringify(withoutName(step)) === JSON.stringify({ uses: nodePin, with: { "node-version": "22" } }),
				"setup-bun": (step) => JSON.stringify(withoutName(step)) === JSON.stringify({ uses: bunPin, with: { "bun-version": BUN_VERSION } }),
				"bun install": (step) => isBunInstall(step) && Object.keys(withoutName(step)).length === 1,
				"project install": (step) => isProjectInstall(step) && Object.keys(withoutName(step)).length === 1,
				"PI_BIN env": (step) => isPiBinEnvStep(step) && Object.keys(withoutName(step)).length === 1,
			};
			const matched: string[] = [];
			let next = 0; // the next rendering step expected
			let discoveryAt = -1;
			mySteps.forEach((step, index) => {
				const original = theirSteps[next];
				if (original && isTestStep(original) && isTestStep(step)) {
					const { env, ...rest } = step;
					expect(rest, "the discovery step").toEqual(original);
					if (env !== undefined) expect(Object.keys(env), "the discovery step's env").toEqual(["PI_BIN"]);
					discoveryAt = index;
					next += 1;
					return;
				}
				if (original && JSON.stringify(step) === JSON.stringify(original)) {
					next += 1;
					return;
				}
				const kind = Object.keys(kinds).find((name) => kinds[name]!(step));
				expect(kind, `step ${index} is neither the rendering's next step nor a hand edit: ${JSON.stringify(step)}`).toBeDefined();
				expect(discoveryAt, `${kind} after discovery`).toBe(-1);
				matched.push(kind!);
			});
			expect(next, "the rendering's steps, in order").toBe(theirSteps.length);
			expect(matched.filter((kind) => kind !== "PI_BIN env").sort()).toEqual(["bun install", "project install", "setup-bun", "setup-node"]);
			expect(matched.filter((kind) => kind === "PI_BIN env").length).toBeLessThanOrEqual(1);
		});
	});
});
