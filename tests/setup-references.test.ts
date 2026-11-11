/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

/*
 * Every name this file searches for is assembled from parts, so that the file never matches its
 * own search: the searches below cover every tracked file outside docs/, this one included.
 */
const FISH_SCRIPT = ["setup", "sol", "pi"].join("-");
const MODELS_QUERY = ["query", "pi", "models"].join("-");
const PTY_DRIVER = ["drive", "pty"].join("-");

/** The five files CR-SLP-005 §S2 deletes. */
const RETIRED_FILES = [
	`${FISH_SCRIPT}.fish`,
	`${FISH_SCRIPT}-interactive.mjs`,
	`scripts/${MODELS_QUERY}.mjs`,
	"tests/setup-prompt-flow.test.ts",
	`tests/fixtures/${PTY_DRIVER}.py`,
];

/** `git grep` over the tracked files, run from the repository root. */
function gitGrep(args: string[]): { status: number | null; stdout: string; stderr: string } {
	const result = spawnSync("git", ["grep", ...args], { cwd: process.cwd(), encoding: "utf8" });
	return { status: result.status, stdout: result.stdout, stderr: result.stderr };
}

// CR-SLP-005 §S2: the fish setup script and its helpers are deleted and nothing names them.
describe("retired fish setup script", () => {
	for (const path of RETIRED_FILES) {
		it(`${path} is deleted from the working tree and the index`, () => {
			expect(existsSync(join(process.cwd(), path)), `${path} on disk`).toBe(false);
			const tracked = spawnSync("git", ["ls-files", "--", path], { cwd: process.cwd(), encoding: "utf8" });
			expect(tracked.status).toBe(0);
			expect(tracked.stdout).toBe("");
		});
	}

	it("no file outside docs/ and CHANGELOG.md names a deleted file", () => {
		const pattern = [FISH_SCRIPT, MODELS_QUERY, PTY_DRIVER].join("|");
		const result = gitGrep(["-n", "-E", pattern, "--", ".", ":!docs", ":!CHANGELOG.md"]);
		// git grep exits 1 when nothing matches (0 on a match, 128 on an error).
		expect(result.stdout).toBe("");
		expect(result.stderr).toBe("");
		expect(result.status).toBe(1);
	});
});

// CR-SLP-005 §S1: no file outside docs/ says the command does not prompt at all.
describe("retired no-prompt statement", () => {
	it("git grep -n -i for the phrase finds nothing outside docs/", () => {
		const phrase = ["never", "prompts"].join(" ");
		const result = gitGrep(["-n", "-i", phrase, "--", ".", ":!docs"]);
		// git grep exits 1 when nothing matches (0 on a match, 128 on an error).
		expect(result.stdout).toBe("");
		expect(result.stderr).toBe("");
		expect(result.status).toBe(1);
	});
});
