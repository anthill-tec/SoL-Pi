/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */
/**
 * How SoL-Pi behaves on the Pi 1.4/1.5 changes reviewed in docs/compatibility.md (CR-SLP-002 §S3),
 * each through a real Pi AgentSession on the development dependency: tool argument validation and
 * coercion by pi-schema, extension update changelogs, and the codemode worker queue.
 */
import { cp, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
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

type ToolResultMessage = { toolCallId: string; toolName: string; isError: boolean; content: { type: string; text?: string }[] };

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
	it("coerces the arguments of SoL-Pi's tools before execute and rejects invalid ones with pi-schema's message", async () => {
		const cwd = await tempDir("sol-pi-pi-schema-");
		const agentDir = join(cwd, "agent");
		await mkdir(agentDir);
		await mkdir(join(cwd, CONFIG_DIR_NAME));
		await writeFile(
			join(cwd, CONFIG_DIR_NAME, "sol-pi.json"),
			JSON.stringify({ ...DEFAULT_CONFIG, actionFusion: true, onlineContextCompact: true }),
		);
		const faux = fauxProvider({ provider: "sol-pi-pi-schema", api: "sol-pi-pi-schema-api" });
		const call = (name: string, args: Parameters<typeof fauxToolCall>[1], id: string) =>
			fauxAssistantMessage(fauxToolCall(name, args, { id }), { stopReason: "toolUse" });
		faux.setResponses([
			// A numeric string for then_run.timeout: pi-schema coerces it to the number SoL-Pi passes to bash.
			call("write", { path: "timed.txt", content: "timed\n", then_run: { command: "sleep 5", timeout: "1" } }, "timeout-string"),
			// null for the optional then_run: pi-schema drops it, so the write runs unfused.
			call("write", { path: "plain.txt", content: "plain\n", then_run: null }, "then-run-null"),
			// A single step for the steps array: pi-schema wraps it into a one-step plan.
			call("update_plan", { steps: { id: "ship", goal: "ship it", status: "in_progress" } }, "single-step"),
			// A status outside the schema's literals is still rejected before update_plan runs.
			call("update_plan", { steps: [{ id: "ship", goal: "ship it", status: "done" }] }, "bad-status"),
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
			const results = toolResults(session);

			// The coerced timeout reached then_run: the command was cut off after one second.
			const timed = results.get("timeout-string");
			expect(timed?.isError).toBe(true);
			expect(textOf(timed)).toContain(THEN_RUN_FAILED);
			expect(textOf(timed)).toMatch(/timed out after 1 second/iu);
			expect(textOf(timed)).not.toContain("Validation failed");
			expect(await readFile(join(cwd, "timed.txt"), "utf8")).toBe("timed\n");

			// then_run: null is an omitted then_run, so the write is a plain write.
			const plain = results.get("then-run-null");
			expect(plain?.isError).toBe(false);
			for (const marker of [THEN_RUN_SUCCEEDED, THEN_RUN_FAILED, THEN_RUN_SKIPPED]) expect(textOf(plain)).not.toContain(marker);
			expect(await readFile(join(cwd, "plain.txt"), "utf8")).toBe("plain\n");

			// A single step is recorded as a one-step plan.
			expect(results.get("single-step")?.isError).toBe(false);

			// An invalid status never reaches update_plan; the model sees pi-schema's message.
			const bad = results.get("bad-status");
			expect(bad?.isError).toBe(true);
			expect(textOf(bad)).toContain('Validation failed for tool "update_plan"');
			expect(textOf(bad)).toMatch(/^ {2}- steps\.0\.status: /mu);

			expect(session.getLastAssistantText()).toBe("validation checked");
			expect(errors).toEqual([]);
		} finally {
			session?.dispose();
		}
	}, 30_000);
});

describe("Pi 1.5.0 extension update changelogs", () => {
	/**
	 * A SoL-Pi package at `version` built from this checkout: its manifest, its extension source, and
	 * its CHANGELOG.md's preamble and `[Unreleased]` section. With `release` (a release's version
	 * heading), the changelog is cut as a release cuts it: the `[Unreleased]` entries move under that
	 * heading, and a new `[Unreleased]` section above it holds an entry not yet released. `released` is
	 * the text of the entries the release moved.
	 */
	async function solPiPackage(root: string, version: string, release?: string): Promise<{ dir: string; released: string }> {
		const dir = join(root, "sol-pi");
		await mkdir(dir);
		await cp(join(process.cwd(), "src"), join(dir, "src"), { recursive: true });
		await symlink(join(process.cwd(), "node_modules"), join(dir, "node_modules"));
		const manifest = JSON.parse(await readFile(join(process.cwd(), "package.json"), "utf8")) as Record<string, unknown>;
		await writeFile(join(dir, "package.json"), JSON.stringify({ ...manifest, version }));
		const changelog = await readFile(join(process.cwd(), "CHANGELOG.md"), "utf8");
		const section = /^## \[Unreleased\]\n([\s\S]*?)(?=^## |(?![\s\S]))/mu.exec(changelog);
		if (!section) throw new Error("CHANGELOG.md has no [Unreleased] section");
		const preamble = changelog.slice(0, section.index);
		const unreleased = section[1] ?? "";
		await writeFile(
			join(dir, "CHANGELOG.md"),
			release
				? `${preamble}## [Unreleased]\n\n### Added\n\n- Pending entry.\n\n${release}\n${unreleased}`
				: `${preamble}## [Unreleased]\n${unreleased}`,
		);
		return { dir, released: unreleased.trim() };
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
		const { dir: packageDir, released } = await solPiPackage(root, "0.2.0", "## [0.2.0] - 2026-11-08");
		const { updates, recorded } = await changelogUpdates(packageDir, "0.1.1");
		expect(updates).toHaveLength(1);
		expect(updates[0]?.name).toBe("sol-pi");
		expect(updates[0]?.version).toBe("0.2.0");
		// Pi matches the heading's version and prefixes it with the package name.
		expect(updates[0]?.markdown.startsWith("## sol-pi [0.2.0] - 2026-11-08\n")).toBe(true);
		// The released entries, which sat under [Unreleased] before the release.
		expect(released).not.toBe("");
		expect(updates[0]?.markdown).toBe(`## sol-pi [0.2.0] - 2026-11-08\n${released ? `\n${released}` : ""}`);
		// The [Unreleased] heading carries no version, so its entries are never shown.
		expect(updates[0]?.markdown).not.toContain("[Unreleased]");
		expect(updates[0]?.markdown).not.toContain("Pending entry");
		expect(recorded).toBe("0.2.0");
	}, 30_000);

	it("shows nothing for SoL-Pi's changelog until a release adds a version heading", async () => {
		const root = await tempDir("sol-pi-changelog-");
		const { dir: packageDir } = await solPiPackage(root, "0.2.0");
		const { updates, recorded } = await changelogUpdates(packageDir, "0.1.1");
		expect(updates).toEqual([]);
		expect(recorded).toBe("0.1.1");
	}, 30_000);

	it("records the installed version without showing a changelog the first time Pi sees SoL-Pi", async () => {
		const root = await tempDir("sol-pi-changelog-");
		const { dir: packageDir } = await solPiPackage(root, "0.2.0", "## [0.2.0] - 2026-11-08");
		const { updates, recorded } = await changelogUpdates(packageDir, undefined);
		expect(updates).toEqual([]);
		expect(recorded).toBe("0.2.0");
	}, 30_000);
});

describe("Pi 1.5.0 codemode worker queue", () => {
	beforeEach(trackWorkerExits);
	afterEach(settleWorkerExits);

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
			expect(session.getLastAssistantText()).toBe("queued scripts done");
			expect(errors).toEqual([]);
		} finally {
			session?.dispose();
		}
	}, 60_000);
});
