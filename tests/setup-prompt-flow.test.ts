/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "bun:test";

const have = (cmd: string) => spawnSync(cmd, ["--version"]).status === 0;
const canRun = have("fish") && have("python3");

const ESC = String.fromCharCode(27);
const stripAnsi = (s: string) => s.replace(new RegExp(`${ESC}\\[[0-9;?]*[A-Za-z]`, "gu"), "");

const script = readFileSync(join(process.cwd(), "setup-sol-pi.fish"), "utf8");
/** Extract a top-level fish function (from `function name` to the first column-0 `end`). */
function fishFunction(name: string): string {
	const m = new RegExp(`^function ${name}\\b[\\s\\S]*?^end$`, "mu").exec(script);
	if (!m) throw new Error(`function ${name} not found in setup-sol-pi.fish`);
	return m[0];
}
const functions = ["banner", "fail", "info", "yesno_prompt", "number_prompt", "generate_sol_pi_config"]
	.map(fishFunction)
	.join("\n\n");
const handler = fishFunction("__interrupt_handler");

const dirs: string[] = [];
afterEach(() => {
	while (dirs.length) rmSync(dirs.pop()!, { recursive: true, force: true });
});

interface Provider {
	id: string;
	models: string[];
}

/** Run generate_sol_pi_config under a real pty, feeding one input line per prompt. */
function runFlow(providers: Provider[], inputs: string[]): { output: string; exit: string } {
	const dir = mkdtempSync(join(tmpdir(), "sol-flow-"));
	dirs.push(dir);
	mkdirSync(join(dir, "scripts"));
	const payload = {
		providers: providers.map((p) => ({ id: p.id, name: p.id.toUpperCase(), models: p.models.map((id) => ({ id })) })),
	};
	writeFileSync(join(dir, "scripts", "query-pi-models.mjs"), `console.log(${JSON.stringify(JSON.stringify(payload))});\n`);
	writeFileSync(
		join(dir, "harness.fish"),
		[
			"set -g tmpdir (mktemp -d)",
			handler,
			functions,
			`generate_sol_pi_config ${dir}`,
			'echo "RESULT: $sol_pi_config_content"',
			'rm -rf "$tmpdir"',
		].join("\n"),
	);
	const res = spawnSync(
		"python3",
		[join(process.cwd(), "tests/fixtures/drive-pty.py"), JSON.stringify(inputs), "fish", join(dir, "harness.fish")],
		{ encoding: "utf8", timeout: 60_000 },
	);
	const text = stripAnsi(res.stdout).replace(/\r/gu, "");
	return { output: text, exit: /EXIT=(\S+)/u.exec(text)?.[1] ?? "?" };
}

const result = (output: string) => {
	const m = /RESULT:([\s\S]*?)\nEXIT=/u.exec(output);
	return m ? (JSON.parse(m[1]!.replace(/\s+/gu, " ")) as Record<string, unknown>) : undefined;
};

// 4 yes/no prompts + ratio prompt, then provider/model prompts.
const base = ["", "", "", "", ""];

describe.skipIf(!canRun)("setup-sol-pi.fish EPR prompt flow", () => {
	it("accepts defaults with Enter without re-prompting", () => {
		const { output, exit } = runFlow([{ id: "alpha", models: ["m1", "m2"] }], [...base, "", ""]);
		expect(exit).toBe("0");
		expect(output.match(/EPR details:/gu)).toHaveLength(1);
		expect(output.match(/Select model for/gu)).toHaveLength(1);
		const cfg = result(output);
		expect(cfg?.evidencePreservingReducerProvider).toBe("alpha");
		expect(cfg?.evidencePreservingReducerModel).toBe("m1");
	});

	it("accepts explicit y / yes", () => {
		const { output } = runFlow([{ id: "alpha", models: ["m1"] }], [...base, "y", "yes"]);
		expect(result(output)?.evidencePreservingReducerModel).toBe("m1");
	});

	it("s cycles to the next provider and next model", () => {
		const { output } = runFlow(
			[
				{ id: "alpha", models: ["a1"] },
				{ id: "beta", models: ["b1", "b2"] },
			],
			[...base, "s", "y", "s", "y"],
		);
		const cfg = result(output);
		expect(cfg?.evidencePreservingReducerProvider).toBe("beta");
		expect(cfg?.evidencePreservingReducerModel).toBe("b2");
	});

	it("c cancels with exit 0 and writes no config", () => {
		const { output, exit } = runFlow([{ id: "alpha", models: ["m1"] }], [...base, "c"]);
		expect(exit).toBe("0");
		expect(output).toContain("Installation cancelled");
		expect(output).not.toContain("RESULT:");
	});

	it("aborts with exit 1 when no providers exist", () => {
		const { output, exit } = runFlow([], base);
		expect(exit).toBe("1");
		expect(output).toContain("at least one provider and one model");
	});

	it("aborts with exit 1 when the provider has no models", () => {
		const { output, exit } = runFlow([{ id: "alpha", models: [] }], [...base, ""]);
		expect(exit).toBe("1");
		expect(output).toContain("has no models");
	});
});
