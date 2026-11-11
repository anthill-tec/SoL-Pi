/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */
/**
 * Action Fusion's `then_run` guidance: the snippet and guidelines the fused `edit` and `write` add
 * to Pi's own, and the `then_run` parameter descriptions. Every expected Pi snippet or guideline is
 * read at run time from `createEditToolDefinition`/`createWriteToolDefinition`, never written as a
 * literal, so these tests hold on every tested Pi version.
 */
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";
import {
	CONFIG_DIR_NAME,
	createAgentSession,
	createEditToolDefinition,
	createWriteToolDefinition,
	DefaultResourceLoader,
	SessionManager,
	SettingsManager,
	type AgentSession,
	type ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { fauxProvider } from "@earendil-works/pi-ai/providers/faux";
// A namespace import, so a missing `fusedToolPrompt` export fails each helper test on its own
// instead of failing the whole file at module load.
import * as actionFusion from "../src/sol-pi/extensions/action-fusion/index.ts";
import { DEFAULT_CONFIG } from "../src/sol-pi/config.ts";
import { loadFusedTools } from "./helpers.ts";

type FusedToolName = "edit" | "write";
type ObjectSchema = { properties: Record<string, { description?: string }> };

const TOOL_NAMES: readonly FusedToolName[] = ["edit", "write"];

function baseTool(name: FusedToolName, cwd = process.cwd()): ToolDefinition {
	return (name === "edit" ? createEditToolDefinition(cwd) : createWriteToolDefinition(cwd)) as unknown as ToolDefinition;
}

/** The three guidelines SoL-Pi appends after the base tool's own. */
function addedGuidelines(tool: ToolDefinition, base: ToolDefinition): string[] {
	return (tool.promptGuidelines ?? []).slice((base.promptGuidelines ?? []).length);
}

function bulletLineCount(prompt: string, rule: string): number {
	const bullet = `- ${rule.trim()}`;
	return prompt.split("\n").filter((line) => line === bullet).length;
}

describe("action fusion then_run guidance on the registered tools", () => {
	it.each(TOOL_NAMES)("gives the fused %s a snippet that starts with Pi's snippet and names then_run", (name) => {
		const base = baseTool(name);
		const fused = loadFusedTools()[name];

		expect(typeof base.promptSnippet).toBe("string");
		expect(fused.promptSnippet?.startsWith(base.promptSnippet!)).toBe(true);
		expect(fused.promptSnippet).toContain("then_run");
		expect(fused.promptSnippet!.length).toBeGreaterThan(base.promptSnippet!.length);
	});

	it.each(TOOL_NAMES)("keeps Pi's %s guidelines in order and appends exactly three then_run guidelines", (name) => {
		const base = baseTool(name);
		const fused = loadFusedTools()[name];
		const baseGuidelines = base.promptGuidelines ?? [];

		expect(fused.promptGuidelines).toHaveLength(baseGuidelines.length + 3);
		expect(fused.promptGuidelines!.slice(0, baseGuidelines.length)).toEqual(baseGuidelines);
		const added = addedGuidelines(fused, base);
		expect(added).toHaveLength(3);
		for (const guideline of added) {
			expect(guideline).toContain(name);
			expect(guideline).toContain("then_run");
		}
	});

	it("adds six then_run guidelines across edit and write that stay distinct after trimming", () => {
		const fused = loadFusedTools();
		const added = TOOL_NAMES.flatMap((name) => addedGuidelines(fused[name], baseTool(name)));
		const trimmed = added.map((guideline) => guideline.trim());

		expect(added).toHaveLength(6);
		expect(new Set(trimmed).size).toBe(6);
		expect(trimmed).not.toContain("");
	});

	it.each(TOOL_NAMES)("registers the %s prompt that the exported helper builds from Pi's definition", (name) => {
		const fused = loadFusedTools()[name];
		const built = actionFusion.fusedToolPrompt(baseTool(name), name);

		expect(built).toEqual({ promptSnippet: fused.promptSnippet!, promptGuidelines: fused.promptGuidelines! });
	});
});

describe("action fusion prompt helper without base guidance", () => {
	it.each(TOOL_NAMES)("returns SoL-Pi's %s snippet sentence and its three guidelines alone", (name) => {
		const { promptSnippet: _snippet, promptGuidelines: _guidelines, ...bare } = baseTool(name);
		const built = actionFusion.fusedToolPrompt(bare as ToolDefinition, name);
		const withBase = actionFusion.fusedToolPrompt(baseTool(name), name);

		expect(built.promptSnippet).toContain("then_run");
		// A full sentence on its own: capitalised, terminated, no leftover joiner from an absent base.
		expect(built.promptSnippet).toMatch(/^[A-Z].*\.$/su);
		expect(built.promptSnippet).not.toContain("undefined");
		expect(built.promptSnippet).toBe(built.promptSnippet.trim());
		expect(built.promptGuidelines).toHaveLength(3);
		expect(built.promptGuidelines).toEqual(withBase.promptGuidelines.slice(-3));
		for (const guideline of built.promptGuidelines) {
			expect(guideline).toContain(name);
			expect(guideline).toContain("then_run");
		}
	});
});

describe("action fusion then_run parameter descriptions", () => {
	it.each(TOOL_NAMES)("describes %s then_run examples as finishing commands, naming restart a service", (name) => {
		const description = (loadFusedTools()[name].parameters as unknown as ObjectSchema).properties.then_run?.description;

		expect(description).not.toContain("start/restart");
		expect(description).toContain("restart a service");
		expect(description).toContain("run, build, test, check, install, or restart a service");
	});
});

async function sessionSystemPrompt(actionFusionEnabled: boolean): Promise<{ prompt: string; cwd: string }> {
	const cwd = await mkdtemp(join(tmpdir(), "sol-pi-guidance-"));
	// An empty agent dir of the test's own: no SYSTEM.md, APPEND_SYSTEM.md or user settings leak in.
	const agentDir = join(cwd, "agent");
	let session: AgentSession | undefined;
	try {
		await mkdir(agentDir);
		await mkdir(join(cwd, CONFIG_DIR_NAME));
		await writeFile(join(cwd, CONFIG_DIR_NAME, "sol-pi.json"), JSON.stringify({
			...DEFAULT_CONFIG,
			actionFusion: actionFusionEnabled,
		}));
		const faux = fauxProvider({ provider: "sol-pi-guidance-test", api: "sol-pi-guidance-test-api" });
		const settingsManager = SettingsManager.inMemory({
			compaction: { enabled: false },
			retry: { enabled: false },
		}, { projectTrusted: true });
		// No `systemPrompt`: Pi's default prompt. No codemode extension or setting: codemode off.
		const resourceLoader = new DefaultResourceLoader({
			cwd,
			agentDir,
			settingsManager,
			additionalExtensionPaths: [join(process.cwd(), "src/sol-pi/index.ts")],
			extensionFactories: [{ name: "guidance-test-provider", factory: (pi) => pi.registerProvider(faux.provider) }],
			noExtensions: true,
			noSkills: true,
			noPromptTemplates: true,
			noThemes: true,
			noContextFiles: true,
		});
		await resourceLoader.reload();
		expect(resourceLoader.getExtensions().errors).toEqual([]);
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
		expect(errors).toEqual([]);
		expect(session.getActiveToolNames()).toEqual(expect.arrayContaining(["edit", "write"]));
		return { prompt: session.systemPrompt, cwd };
	} finally {
		session?.dispose();
		await rm(cwd, { recursive: true, force: true });
	}
}

describe("action fusion then_run guidance in Pi's default system prompt", () => {
	it("lists each fused snippet and every SoL-Pi and base guideline once with Action Fusion enabled", async () => {
		const { prompt } = await sessionSystemPrompt(true);
		const fused = loadFusedTools();

		for (const name of TOOL_NAMES) {
			const base = baseTool(name);
			const toolLine = prompt.split("\n").find((line) => line.startsWith(`- ${name}: `));
			expect(toolLine?.startsWith(`- ${name}: ${base.promptSnippet}`)).toBe(true);
			expect(toolLine).toContain("then_run");
			expect(toolLine).toBe(`- ${name}: ${fused[name].promptSnippet}`);
			for (const guideline of addedGuidelines(fused[name], base)) {
				expect({ name, guideline, count: bulletLineCount(prompt, guideline) }).toEqual({ name, guideline, count: 1 });
			}
			for (const guideline of base.promptGuidelines ?? []) {
				expect({ name, guideline, count: bulletLineCount(prompt, guideline) }).toEqual({ name, guideline, count: 1 });
			}
		}
		const sixAdded = TOOL_NAMES.flatMap((name) => addedGuidelines(fused[name], baseTool(name)));
		expect(sixAdded).toHaveLength(6);
	}, 30_000);

	it("keeps Pi's base edit and write guidance and no then_run with Action Fusion disabled", async () => {
		const { prompt } = await sessionSystemPrompt(false);

		for (const name of TOOL_NAMES) {
			const base = baseTool(name);
			expect(prompt).toContain(`- ${name}: ${base.promptSnippet}\n`);
			for (const guideline of base.promptGuidelines ?? []) {
				expect({ name, guideline, count: bulletLineCount(prompt, guideline) }).toEqual({ name, guideline, count: 1 });
			}
		}
		expect(prompt).not.toContain("then_run");
	}, 30_000);
});
