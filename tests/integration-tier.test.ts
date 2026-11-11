/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */
/**
 * The `test:integration` script in `package.json` is a hand-kept list of test modules. A
 * `tests/*.test.ts|js` module belongs to it when it starts a process — `Bun.spawn`, `Bun.spawnSync`,
 * `node:child_process` or the `piCliPath` helper of `tests/helpers.ts` — or starts a real Pi agent
 * session (`createAgentSession`). The rule is textual. The fixture sources below are assembled from
 * fragments, so this module's own text does not match it.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "bun:test";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const TEST_MODULE = /\.test\.(?:ts|js)$/;

const PROCESS_OR_SESSION = [
	/\bBun\.spawn(?:Sync)?\s*\(/,
	/["']node:child_process["']/,
	/\bpiCliPath\s*\(/,
	/\bcreateAgentSession\s*\(/,
] as const;

/** Whether a test module's source starts a process or a real Pi agent session. */
function belongsToIntegrationTier(source: string): boolean {
	return PROCESS_OR_SESSION.some((pattern) => pattern.test(source));
}

/** The modules a `test:integration` script lists, as paths relative to the repository root. */
function listedModules(script: string): string[] {
	return script
		.split(/\s+/)
		.filter((token) => /^(?:\.\/)?tests\//.test(token))
		.map((token) => token.replace(/^\.\//, ""));
}

/**
 * Every disagreement between the rule and the list: a selected module missing from the list, a
 * listed module that does not exist, a listed module the rule does not select.
 */
function tierMismatches(modules: ReadonlyMap<string, string>, listed: readonly string[]): string[] {
	const listedSet = new Set(listed);
	const missing = [...modules]
		.filter(([path, source]) => belongsToIntegrationTier(source) && !listedSet.has(path))
		.map(([path]) => `${path} starts a process or Pi agent session but is missing from test:integration`);
	const extra = [...listedSet].flatMap((path) => {
		const source = modules.get(path);
		if (source === undefined) return [`${path} is listed in test:integration but does not exist`];
		if (!belongsToIntegrationTier(source)) return [`${path} is listed in test:integration but starts no process or Pi agent session`];
		return [];
	});
	return [...missing, ...extra].sort();
}

function code(...fragments: string[]): string {
	return fragments.join("");
}

describe("integration tier rule", () => {
	it("selects a module that calls Bun's spawn or spawnSync", () => {
		expect(belongsToIntegrationTier(code("const child = Bun", ".spawn([\"true\"]);"))).toBe(true);
		expect(belongsToIntegrationTier(code("const result = Bun", ".spawnSync([\"true\"]);"))).toBe(true);
	});

	it("selects a module that imports node's child_process", () => {
		expect(belongsToIntegrationTier(code("import { execFile } from \"node:", "child_process\";"))).toBe(true);
		expect(belongsToIntegrationTier(code("import { spawnSync } from 'node:", "child_process';"))).toBe(true);
	});

	it("selects a module that runs the Pi CLI through the piCliPath helper", () => {
		expect(belongsToIntegrationTier(code("execFile(process.execPath, [piCli", "Path(), \"--print\"]);"))).toBe(true);
	});

	it("selects a module that starts a real Pi agent session", () => {
		expect(belongsToIntegrationTier(code("const { session } = await createAgent", "Session({ cwd });"))).toBe(true);
	});

	it("does not select a module that only imports fs, Pi's types or the helpers", () => {
		const source = [
			"import { readFile } from \"node:fs/promises\";",
			"import type { AgentSession } from \"@earendil-works/pi-coding-agent\";",
			"import { fakeToolContext } from \"./helpers.ts\";",
			"it(\"reads\", async () => { expect(await readFile(\"x\", \"utf8\")).toBe(\"\"); });",
		].join("\n");
		expect(belongsToIntegrationTier(source)).toBe(false);
	});

	it("reads the listed modules from the script without the runner or its options", () => {
		expect(listedModules("bun test --timeout 30000 ./tests/a.test.ts ./tests/b.test.js tests/c.test.ts")).toEqual([
			"tests/a.test.ts",
			"tests/b.test.js",
			"tests/c.test.ts",
		]);
	});

	it("reports nothing when the list holds exactly the selected modules", () => {
		const modules = new Map([
			["tests/spawns.test.ts", code("Bun", ".spawn([\"true\"]);")],
			["tests/pure.test.ts", "expect(1).toBe(1);"],
		]);
		expect(tierMismatches(modules, ["tests/spawns.test.ts"])).toEqual([]);
	});

	it("names a process-starting module left out of the list", () => {
		const modules = new Map([
			["tests/spawns.test.ts", code("Bun", ".spawn([\"true\"]);")],
			["tests/session.test.ts", code("await createAgent", "Session({});")],
		]);
		expect(tierMismatches(modules, ["tests/session.test.ts"])).toEqual([
			"tests/spawns.test.ts starts a process or Pi agent session but is missing from test:integration",
		]);
	});

	it("names a listed module that starts no process", () => {
		const modules = new Map([["tests/pure.test.ts", "expect(1).toBe(1);"]]);
		expect(tierMismatches(modules, ["tests/pure.test.ts"])).toEqual([
			"tests/pure.test.ts is listed in test:integration but starts no process or Pi agent session",
		]);
	});

	it("names a listed module that does not exist", () => {
		expect(tierMismatches(new Map(), ["tests/gone.test.ts"])).toEqual([
			"tests/gone.test.ts is listed in test:integration but does not exist",
		]);
	});
});

describe("package.json test:integration", () => {
	it("lists exactly the test modules that start a process or a real Pi agent session", () => {
		const manifest = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8")) as { scripts?: Record<string, string> };
		const script = manifest.scripts?.["test:integration"];
		expect(script, "package.json declares no test:integration script").toBeString();
		const modules = new Map<string, string>(
			readdirSync(join(ROOT, "tests"))
				.filter((name) => TEST_MODULE.test(name))
				.map((name) => [`tests/${name}`, readFileSync(join(ROOT, "tests", name), "utf8")]),
		);
		const listed = listedModules(script ?? "");

		expect(tierMismatches(modules, listed)).toEqual([]);
	});
});
