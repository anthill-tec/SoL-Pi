/*
 * SPDX-License-Identifier: MIT
 */

// The shared configuration conformance table and golden written files
// (tests/fixtures/sol-pi-config/), run through `loadSolPiConfig` and
// `scripts/check-sol-pi-config.mjs`. tests/test_sol_pi_config_conformance.py runs the same table
// against `sol_pi_axi.config`, and tests/test_sol_pi_axi_written_form.py asserts `sol-pi-axi`
// writes exactly the golden bytes, so the two runtimes stay equal without either runner needing
// the other's runtime.

import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "bun:test";
import { loadSolPiConfig } from "../src/sol-pi/config.ts";

const FIXTURES = join(process.cwd(), "tests/fixtures/sol-pi-config");
const SCRIPT = join(process.cwd(), "scripts/check-sol-pi-config.mjs");

interface ConformanceCase {
	readonly name: string;
	readonly file: string;
	readonly valid: boolean;
	readonly effective: Record<string, unknown> | null;
	readonly note: string;
}

interface GoldenCase {
	readonly name: string;
	readonly file: string;
	readonly args: string[];
	readonly piSettings: Record<string, unknown> | null;
	readonly note: string;
}

const CASES = (JSON.parse(readFileSync(join(FIXTURES, "cases.json"), "utf8")) as { cases: ConformanceCase[] })
	.cases;
const GOLDENS = (JSON.parse(readFileSync(join(FIXTURES, "written.json"), "utf8")) as { cases: GoldenCase[] })
	.cases;
const EXAMPLE_KEYS = Object.keys(JSON.parse(readFileSync("sol-pi.example.json", "utf8")) as object);

const roots: string[] = [];

afterEach(() => {
	for (const root of roots.splice(0)) rmSync(root, { force: true, recursive: true });
});

/** `loadSolPiConfig` over `file` as the agent directory's sol-pi.json, byte for byte. */
function load(file: string): Record<string, unknown> {
	const root = mkdtempSync(join(tmpdir(), "sol-pi-conformance-"));
	roots.push(root);
	const agentDir = join(root, "agent");
	const cwd = join(root, "project");
	mkdirSync(agentDir);
	mkdirSync(cwd);
	copyFileSync(file, join(agentDir, "sol-pi.json"));
	return { ...loadSolPiConfig(cwd, agentDir, true) };
}

function preflight(file: string, ...extra: string[]) {
	return spawnSync("node", [SCRIPT, "--config", file, ...extra], { cwd: process.cwd(), encoding: "utf8" });
}

describe("SoL-Pi configuration conformance table", () => {
	it("lists every case the configuration rules require, each with its own file", () => {
		const names = CASES.map((entry) => entry.name);
		for (const required of [
			"minimal-valid",
			"every-key-valid",
			"unknown-key",
			"version-2",
			"version-true",
			"version-1.0",
			"version-string",
			"feature-number",
			"ratio-negative",
			"ratio-string",
			"ratio-true",
			"ratio-nan",
			"ratio-infinity",
			"ratio-1e999",
			"reducer-empty",
			"reducer-whitespace-only",
			"reducer-padded",
			"json-array",
			"json-malformed",
		]) {
			expect(names).toContain(required);
		}
		expect(new Set(names).size).toBe(names.length);
		expect(new Set(CASES.map((entry) => entry.file)).size).toBe(CASES.length);
	});

	describe.each(CASES.map((entry) => [entry.name, entry] as const))("%s", (_name, entry) => {
		const file = join(FIXTURES, entry.file);

		if (entry.valid) {
			it("loadSolPiConfig accepts it with exactly its effective values", () => {
				expect(load(file)).toStrictEqual(entry.effective as Record<string, unknown>);
			});

			it("check-sol-pi-config.mjs accepts it with exactly its effective values", () => {
				const result = preflight(file);
				expect(result.status, result.stderr).toBe(0);
				expect({ ...JSON.parse(result.stdout).effective_config }).toStrictEqual(
					entry.effective as Record<string, unknown>,
				);
			});
		} else {
			it("loadSolPiConfig rejects it", () => {
				expect(entry.effective).toBeNull();
				expect(() => load(file)).toThrow();
			});

			it("check-sol-pi-config.mjs rejects it", () => {
				const result = preflight(file);
				expect(result.status).toBe(1);
				expect(result.stdout).toBe("");
				expect(result.stderr).toContain("SoL-Pi configuration preflight failed");
			});
		}
	});
});

describe("SoL-Pi golden written files", () => {
	it("cover the setup defaults, each feature-list form, the reducer off, and a custom ratio", () => {
		const args = GOLDENS.map((entry) => entry.args.join(" "));
		expect(args).toContain("");
		expect(args).toContain("--features all");
		expect(args).toContain("--features none");
		expect(args.some((value) => /^--features \w+,\w+/u.test(value))).toBe(true);
		expect(args.some((value) => value.startsWith("--cache-ratio "))).toBe(true);
		expect(GOLDENS.some((entry) => load(join(FIXTURES, entry.file)).evidencePreservingReducer === false)).toBe(
			true,
		);
	});

	describe.each(GOLDENS.map((entry) => [entry.name, entry] as const))("%s", (_name, entry) => {
		const file = join(FIXTURES, entry.file);
		const text = readFileSync(file, "utf8");
		const parsed = JSON.parse(text) as Record<string, unknown>;

		it("is in the written form: every key in sol-pi.example.json's order, tabs, a final newline", () => {
			expect(Object.keys(parsed)).toEqual(EXAMPLE_KEYS);
			expect(text).toBe(`${JSON.stringify(parsed, null, "\t")}\n`);
		});

		it("loadSolPiConfig accepts it with its written values as the effective values", () => {
			expect(load(file)).toStrictEqual(parsed);
		});

		it("check-sol-pi-config.mjs accepts it with its written values as the effective values", () => {
			const result = preflight(file);
			expect(result.status, result.stderr).toBe(0);
			expect({ ...JSON.parse(result.stdout).effective_config }).toStrictEqual(parsed);
		});
	});

	it("passes the all-enabled preflight for the setup defaults", () => {
		const result = preflight(join(FIXTURES, "written/setup-defaults.json"), "--require-all-enabled");
		expect(result.status, result.stderr).toBe(0);
		expect(JSON.parse(result.stdout).all_enabled).toBe(true);
	});
});
