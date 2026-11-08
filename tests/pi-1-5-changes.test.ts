/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */
/**
 * How SoL-Pi behaves on the Pi 1.4/1.5 changes reviewed in docs/compatibility.md (CR-SLP-002 §S3),
 * each through a real Pi AgentSession on the development dependency: tool argument validation and
 * coercion by pi-schema, extension update changelogs, and the codemode worker queue.
 */
import { cp, mkdir, mkdtemp, readFile, rm, stat, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fauxAssistantMessage, fauxProvider, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import * as piCodingAgent from "@earendil-works/pi-coding-agent";
import {
	CONFIG_DIR_NAME,
	createAgentSession,
	DefaultResourceLoader,
	InteractiveMode,
	SessionManager,
	SettingsManager,
	type AgentSession,
	type ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { DEFAULT_CONFIG, loadSolPiConfig } from "../src/sol-pi/config.ts";
import { THEN_RUN_FAILED, THEN_RUN_SKIPPED, THEN_RUN_SUCCEEDED } from "../src/sol-pi/extensions/action-fusion/index.ts";
import { createSolPiExtension } from "../src/sol-pi/index.ts";
import { settleWorkerExits, trackWorkerExits } from "./helpers.ts";

/** Pi 1.0 codemode; the development dependency, Pi 1.5.0, ships it. */
const createCodemodeExtension = (piCodingAgent as unknown as Record<string, unknown>).createCodemodeExtension as
	| ((options: { mode: "on" | "only" }) => ExtensionFactory)
	| undefined;

type ToolResultMessage = {
	toolCallId: string;
	toolName: string;
	isError: boolean;
	content: { type: string; text?: string }[];
	details?: unknown;
};

function textOf(message: ToolResultMessage | undefined): string {
	return (message?.content ?? []).flatMap((block) => (block.type === "text" ? [block.text ?? ""] : [])).join("\n");
}

function toolResults(session: AgentSession): Map<string, ToolResultMessage> {
	const results = new Map<string, ToolResultMessage>();
	for (const entry of session.sessionManager.getBranch()) {
		if (entry.type === "message" && entry.message.role === "toolResult") {
			const message = entry.message as unknown as ToolResultMessage;
			results.set(message.toolCallId, message);
		}
	}
	return results;
}

const tempDirs: string[] = [];

async function tempDir(prefix: string): Promise<string> {
	const dir = await mkdtemp(join(tmpdir(), prefix));
	tempDirs.push(dir);
	return dir;
}

afterEach(async () => {
	await Promise.all(tempDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

describe("Pi 1.5.0 tool argument validation and coercion (pi-schema)", () => {
	type FauxToolCallArgs = Parameters<typeof fauxToolCall>[1];

	/**
	 * Runs one tool call from the model through a real Pi session with SoL-Pi loaded from this checkout
	 * (Action Fusion and Online Context Compact on), so Pi 1.5.0 validates and coerces its arguments
	 * with pi-schema before SoL-Pi's tool runs. Returns the session's working directory and the call's
	 * tool result.
	 */
	async function runToolCall(name: string, args: FauxToolCallArgs, id: string): Promise<{ cwd: string; result: ToolResultMessage | undefined }> {
		const cwd = await tempDir("sol-pi-pi-schema-");
		const agentDir = join(cwd, "agent");
		await mkdir(agentDir);
		await mkdir(join(cwd, CONFIG_DIR_NAME));
		await writeFile(
			join(cwd, CONFIG_DIR_NAME, "sol-pi.json"),
			JSON.stringify({ ...DEFAULT_CONFIG, actionFusion: true, onlineContextCompact: true }),
		);
		const faux = fauxProvider({ provider: "sol-pi-pi-schema", api: "sol-pi-pi-schema-api" });
		faux.setResponses([
			fauxAssistantMessage(fauxToolCall(name, args, { id }), { stopReason: "toolUse" }),
			fauxAssistantMessage("validation checked"),
		]);
		const settingsManager = SettingsManager.inMemory(
			{ compaction: { enabled: false }, retry: { enabled: false } },
			{ projectTrusted: true },
		);
		const resourceLoader = new DefaultResourceLoader({
			cwd,
			agentDir,
			settingsManager,
			additionalExtensionPaths: [join(process.cwd(), "src/sol-pi/index.ts")],
			extensionFactories: [{ name: "pi-schema-test-provider", factory: (pi) => pi.registerProvider(faux.provider) }],
			noExtensions: true,
			noSkills: true,
			noPromptTemplates: true,
			noThemes: true,
			noContextFiles: true,
			systemPrompt: "You are a deterministic validation test assistant.",
		});
		await resourceLoader.reload();
		expect(resourceLoader.getExtensions().errors).toEqual([]);
		let session: AgentSession | undefined;
		try {
			({ session } = await createAgentSession({
				cwd,
				agentDir,
				model: faux.getModel(),
				thinkingLevel: "off",
				resourceLoader,
				sessionManager: SessionManager.inMemory(cwd),
				settingsManager,
			}));
			const errors: unknown[] = [];
			await session.bindExtensions({ onError: (error) => errors.push(error) });
			await session.prompt("check validation", { expandPromptTemplates: false });
			expect(session.getLastAssistantText()).toBe("validation checked");
			expect(errors).toEqual([]);
			return { cwd, result: toolResults(session).get(id) };
		} finally {
			session?.dispose();
		}
	}

	it("coerces a numeric-string then_run.timeout to the number of seconds SoL-Pi's then_run waits", async () => {
		const { cwd, result } = await runToolCall(
			"write",
			{ path: "timed.txt", content: "timed\n", then_run: { command: "sleep 5", timeout: "1" } },
			"timeout-string",
		);
		// The coerced timeout reached then_run: the command was cut off after one second.
		expect(result?.isError).toBe(true);
		expect(textOf(result)).toContain(THEN_RUN_FAILED);
		expect(textOf(result)).toMatch(/timed out after 1 second/iu);
		expect(textOf(result)).not.toContain("Validation failed");
		expect(await readFile(join(cwd, "timed.txt"), "utf8")).toBe("timed\n");
	}, 30_000);

	it("treats then_run: null as an omitted then_run, so the write is a plain write", async () => {
		const { cwd, result } = await runToolCall("write", { path: "plain.txt", content: "plain\n", then_run: null }, "then-run-null");
		expect(result?.isError, textOf(result)).toBe(false);
		for (const marker of [THEN_RUN_SUCCEEDED, THEN_RUN_FAILED, THEN_RUN_SKIPPED]) expect(textOf(result)).not.toContain(marker);
		expect(await readFile(join(cwd, "plain.txt"), "utf8")).toBe("plain\n");
	}, 30_000);

	it("records a single update_plan step as a one-step plan", async () => {
		const { result } = await runToolCall("update_plan", { steps: { id: "ship", goal: "ship it", status: "in_progress" } }, "single-step");
		expect(result?.isError, textOf(result)).toBe(false);
		// pi-schema wrapped the step into a one-item array, and update_plan recorded exactly that plan.
		const plan = [{ id: "ship", goal: "ship it", status: "in_progress" }];
		expect((result?.details as { plan?: unknown } | undefined)?.plan).toEqual(plan);
		expect(textOf(result)).toContain(`<sol-pi-plan task_status="active">${JSON.stringify({ steps: plan })}</sol-pi-plan>`);
	}, 30_000);

	it("rejects an update_plan step status outside the schema with pi-schema's message before update_plan runs", async () => {
		const { result } = await runToolCall("update_plan", { steps: [{ id: "ship", goal: "ship it", status: "done" }] }, "bad-status");
		// Coercion cannot repair an unknown status, so the model sees pi-schema's message.
		expect(result?.isError).toBe(true);
		expect(textOf(result)).toContain('Validation failed for tool "update_plan"');
		expect(textOf(result)).toMatch(/^ {2}- steps\.0\.status: /mu);
		expect(textOf(result)).not.toContain("<sol-pi-plan");
	}, 30_000);
});

describe("Pi 1.5.0 extension update changelogs", () => {
	/** A Keep a Changelog preamble, as CHANGELOG.md has it. */
	const PREAMBLE = [
		"# Changelog",
		"",
		"All notable changes to this project are documented in this file. The format is based on",
		"[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to",
		"[Semantic Versioning](https://semver.org/spec/v2.0.0.html).",
		"",
		"",
	].join("\n");

	/** An `[Unreleased]` section holding an entry not yet released. */
	const UNRELEASED = "## [Unreleased]\n\n### Added\n\n- Pending entry.\n\n";

	/** The 0.2.0 release's section, as a release writes it: the entries moved from `[Unreleased]` under its version heading. */
	const RELEASE_0_2_0 = [
		"## [0.2.0] - 2026-11-08",
		"",
		"### Added",
		"",
		"- Pi 1.5.0 support: Pi 1.5.0 joins the tested set as the latest tested release.",
		"",
		"### Security",
		"",
		"- The development dependencies no longer resolve an affected `undici`.",
	].join("\n");

	/** An older release, at the version Pi last saw. */
	const RELEASE_0_1_1 = "## [0.1.1] - 2026-10-01\n\n### Fixed\n\n- Older entry.\n";

	/** CHANGELOG.md before any release: only the `[Unreleased]` section. */
	const UNRELEASED_CHANGELOG = `${PREAMBLE}${UNRELEASED}`;

	/** CHANGELOG.md after the 0.2.0 release, with a new `[Unreleased]` entry above it and an older release below. */
	const RELEASED_CHANGELOG = `${PREAMBLE}${UNRELEASED}${RELEASE_0_2_0}\n\n${RELEASE_0_1_1}`;

	/** A SoL-Pi package at `version` built from this checkout's manifest and extension source, with `changelog` as its CHANGELOG.md. */
	async function solPiPackage(root: string, version: string, changelog: string): Promise<string> {
		const dir = join(root, "sol-pi");
		await mkdir(dir);
		await cp(join(process.cwd(), "src"), join(dir, "src"), { recursive: true });
		await symlink(join(process.cwd(), "node_modules"), join(dir, "node_modules"));
		const manifest = JSON.parse(await readFile(join(process.cwd(), "package.json"), "utf8")) as Record<string, unknown>;
		await writeFile(join(dir, "package.json"), JSON.stringify({ ...manifest, version }));
		await writeFile(join(dir, "CHANGELOG.md"), changelog);
		return dir;
	}

	/** The extension changelog updates Pi's interactive mode shows on a fresh launch of a session with SoL-Pi installed. */
	async function changelogUpdates(packageDir: string, lastSeen: string | undefined) {
		const cwd = await tempDir("sol-pi-changelog-cwd-");
		const agentDir = join(cwd, "agent");
		await mkdir(agentDir);
		const faux = fauxProvider({ provider: "sol-pi-changelog", api: "sol-pi-changelog-api" });
		const settingsManager = SettingsManager.inMemory(
			{ packages: [packageDir], compaction: { enabled: false }, retry: { enabled: false } },
			{ projectTrusted: true },
		);
		const key = JSON.stringify({ source: packageDir, scope: "user" });
		if (lastSeen) settingsManager.setExtensionChangelogVersion(key, lastSeen);
		const resourceLoader = new DefaultResourceLoader({
			cwd,
			agentDir,
			settingsManager,
			extensionFactories: [{ name: "changelog-test-provider", factory: (pi) => pi.registerProvider(faux.provider) }],
			noSkills: true,
			noPromptTemplates: true,
			noThemes: true,
			noContextFiles: true,
		});
		await resourceLoader.reload();
		expect(resourceLoader.getExtensions().errors).toEqual([]);
		const solPi = resourceLoader.getExtensions().extensions.find((extension) => extension.sourceInfo.origin === "package");
		// Pi finds SoL-Pi's changelog at the package root; SoL-Pi sets no pi.changelogPath.
		expect(solPi?.sourceInfo.changelogPath).toBe(join(packageDir, "CHANGELOG.md"));
		const { session } = await createAgentSession({
			cwd,
			agentDir,
			model: faux.getModel(),
			thinkingLevel: "off",
			resourceLoader,
			sessionManager: SessionManager.inMemory(cwd),
			settingsManager,
		});
		try {
			// Pi's own startup step, run on this session as InteractiveMode runs it on a fresh launch.
			const mode = InteractiveMode.prototype as unknown as {
				getExtensionChangelogUpdates(this: unknown): { name: string; version: string; markdown: string }[];
				readPackageJson: unknown;
			};
			// A private step of Pi's InteractiveMode.init, the only public path to it, which needs a TUI.
			// docs/compatibility.md records the coupling; a Pi that renames or drops it fails here.
			expect(typeof mode.getExtensionChangelogUpdates, "Pi's InteractiveMode.init step getExtensionChangelogUpdates").toBe("function");
			expect(typeof mode.readPackageJson, "Pi's InteractiveMode readPackageJson").toBe("function");
			const updates = mode.getExtensionChangelogUpdates.call({
				session,
				settingsManager,
				readPackageJson: mode.readPackageJson,
			});
			return { updates, recorded: settingsManager.getExtensionChangelogVersion(key) };
		} finally {
			session.dispose();
		}
	}

	it("shows a release's Keep a Changelog section after an update and never the [Unreleased] section", async () => {
		const root = await tempDir("sol-pi-changelog-");
		const packageDir = await solPiPackage(root, "0.2.0", RELEASED_CHANGELOG);
		const { updates, recorded } = await changelogUpdates(packageDir, "0.1.1");
		expect(updates).toHaveLength(1);
		const copied = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8")) as { name: string };
		expect(updates[0]?.name).toBe(copied.name);
		expect(updates[0]?.version).toBe("0.2.0");
		// Pi matches the heading's version and prefixes it with the package name. The update is exactly
		// the 0.2.0 section: not the [Unreleased] section above it, whose heading carries no version, and
		// not the 0.1.1 section at the version Pi last saw.
		expect(updates[0]?.markdown).toBe(RELEASE_0_2_0.replace(/^## /u, `## ${copied.name} `));
		expect(updates[0]?.markdown).not.toContain("[Unreleased]");
		expect(updates[0]?.markdown).not.toContain("Pending entry");
		expect(updates[0]?.markdown).not.toContain("Older entry");
		expect(recorded).toBe("0.2.0");
	}, 30_000);

	it("shows nothing for SoL-Pi's changelog until a release adds a version heading", async () => {
		const root = await tempDir("sol-pi-changelog-");
		const packageDir = await solPiPackage(root, "0.2.0", UNRELEASED_CHANGELOG);
		const { updates, recorded } = await changelogUpdates(packageDir, "0.1.1");
		expect(updates).toEqual([]);
		expect(recorded).toBe("0.1.1");
	}, 30_000);

	it("records the installed version without showing a changelog the first time Pi sees SoL-Pi", async () => {
		const root = await tempDir("sol-pi-changelog-");
		const packageDir = await solPiPackage(root, "0.2.0", RELEASED_CHANGELOG);
		const { updates, recorded } = await changelogUpdates(packageDir, undefined);
		expect(updates).toEqual([]);
		expect(recorded).toBe("0.2.0");
	}, 30_000);

	it("keeps CHANGELOG.md's sections under the Keep a Changelog headings the tests above give Pi", async () => {
		// Holds before and after a release: a release moves the [Unreleased] entries under a
		// "## [x.y.z] - YYYY-MM-DD" heading and leaves "## [Unreleased]" above it.
		const changelog = await readFile(join(process.cwd(), "CHANGELOG.md"), "utf8");
		expect(changelog.startsWith(PREAMBLE)).toBe(true);
		const headings = changelog.split("\n").filter((line) => line.startsWith("## "));
		expect(headings[0]).toBe("## [Unreleased]");
		for (const heading of headings.slice(1)) expect(heading).toMatch(/^## \[\d+\.\d+\.\d+\] - \d{4}-\d{2}-\d{2}$/u);
	});
});

describe("Pi 1.5.0 codemode worker queue", () => {
	beforeEach(trackWorkerExits);
	afterEach(settleWorkerExits);

	// Pi reads PI_CODEMODE_MAX_WORKERS on every script; pin Pi's default of two workers for these tests.
	let maxWorkers: string | undefined;
	beforeEach(() => {
		maxWorkers = process.env.PI_CODEMODE_MAX_WORKERS;
		delete process.env.PI_CODEMODE_MAX_WORKERS;
	});
	afterEach(() => {
		if (maxWorkers === undefined) delete process.env.PI_CODEMODE_MAX_WORKERS;
		else process.env.PI_CODEMODE_MAX_WORKERS = maxWorkers;
	});

	it("completes fused writes from more parallel scripts than codemode has workers", async () => {
		expect(createCodemodeExtension).toBeDefined();
		const cwd = await tempDir("sol-pi-codemode-queue-");
		const agentDir = join(cwd, "agent");
		await mkdir(agentDir);
		await writeFile(join(agentDir, "sol-pi.json"), JSON.stringify({ ...DEFAULT_CONFIG, actionFusion: true }));
		const faux = fauxProvider({ provider: "sol-pi-codemode-queue", api: "sol-pi-codemode-queue-api" });
		// Pi's default is two codemode workers; three scripts run in parallel, so one waits for a worker.
		const scripts = ["one", "two", "three"].map((name) =>
			fauxToolCall(
				"codemode",
				{
					code: `text(await tools.write({ path: "${name}.txt", content: "${name}\\n", then_run: { command: "sleep 0.5; cat ${name}.txt" } }));`,
				},
				{ id: `script-${name}` },
			),
		);
		faux.setResponses([fauxAssistantMessage(scripts, { stopReason: "toolUse" }), fauxAssistantMessage("queued scripts done")]);
		const settingsManager = SettingsManager.inMemory({
			compaction: { enabled: false },
			retry: { enabled: false },
			defaultTools: ["+codemode"],
			codemode: { mode: "on" },
		});
		const resourceLoader = new DefaultResourceLoader({
			cwd,
			agentDir,
			settingsManager,
			extensionFactories: [
				{ name: "codemode-queue-provider", factory: (pi) => pi.registerProvider(faux.provider) },
				{ name: "sol-pi-codemode-queue", factory: createSolPiExtension((ctx) => loadSolPiConfig(ctx.cwd, agentDir, false)) },
				{ name: "codemode-queue", factory: createCodemodeExtension!({ mode: "on" }) },
			],
			noExtensions: true,
			noSkills: true,
			noPromptTemplates: true,
			noThemes: true,
			noContextFiles: true,
			systemPrompt: "You are a deterministic codemode queue test assistant.",
		});
		await resourceLoader.reload();
		expect(resourceLoader.getExtensions().errors).toEqual([]);
		let session: AgentSession | undefined;
		try {
			({ session } = await createAgentSession({
				cwd,
				agentDir,
				model: faux.getModel(),
				thinkingLevel: "off",
				tools: ["write", "codemode"],
				resourceLoader,
				sessionManager: SessionManager.inMemory(cwd),
				settingsManager,
			}));
			const errors: unknown[] = [];
			await session.bindExtensions({ onError: (error) => errors.push(error) });
			await session.prompt("write three files", { expandPromptTemplates: false });
			const results = toolResults(session);
			for (const name of ["one", "two", "three"]) {
				const result = results.get(`script-${name}`);
				expect(result?.isError, textOf(result)).toBe(false);
				expect(textOf(result)).toContain(THEN_RUN_SUCCEEDED);
				expect(textOf(result)).not.toMatch(/free codemode worker/u);
				expect(await readFile(join(cwd, `${name}.txt`), "utf8")).toBe(`${name}\n`);
			}
			// A script writes its file only once it holds a worker, and holds it through its half-second
			// then_run. The third script waited for one of the first two to finish, so its write came at
			// least half a second after the first.
			const written = await Promise.all(["one", "two", "three"].map(async (name) => (await stat(join(cwd, `${name}.txt`))).mtimeMs));
			expect(Math.max(...written) - Math.min(...written)).toBeGreaterThanOrEqual(450);
			expect(session.getLastAssistantText()).toBe("queued scripts done");
			expect(errors).toEqual([]);
		} finally {
			session?.dispose();
		}
	}, 60_000);
});
