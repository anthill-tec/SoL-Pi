/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */
/**
 * The suite's capability guards skip their tests when the installed Pi lacks a capability, so the
 * suite still runs against the older Pi the peer range admits. With the development dependency's
 * Pi none of them may skip: each test here runs a guard's own probe from `tests/helpers.ts` and
 * fails naming the capability it reports missing.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "bun:test";
import { bashReturnsNonZeroExit, buildSessionProjection, createCodemodeExtension } from "./helpers.ts";

const PI_PACKAGE = "@earendil-works/pi-coding-agent";

function readJson(path: string): Record<string, unknown> {
	return JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
}

/** Fails naming the capability, and the guarded files that would skip, when its probe reports it missing. */
function expectCapability(present: boolean, capability: string, guards: readonly string[]): void {
	expect(present, `Pi capability missing: ${capability} — the guards in ${guards.join(", ")} would skip`).toBe(true);
}

describe("Pi capabilities the capability guards probe", () => {
	it("the installed Pi is the development dependency's Pi", () => {
		const root = join(dirname(fileURLToPath(import.meta.url)), "..");
		const devDependencies = readJson(join(root, "package.json")).devDependencies as Record<string, string>;
		const installedRoot = dirname(dirname(fileURLToPath(import.meta.resolve(PI_PACKAGE))));
		expect(devDependencies[PI_PACKAGE]).toBe("1.5.0");
		expect(readJson(join(installedRoot, "package.json")).version).toBe(devDependencies[PI_PACKAGE]);
	});

	it("Pi codemode (createCodemodeExtension) is present", () => {
		expectCapability(typeof createCodemodeExtension === "function", "Pi codemode (createCodemodeExtension)", [
			"codemode-compat.test.ts",
			"observation-pack.test.ts",
			"online-context-compact-agent-session.test.ts",
		]);
	});

	it("Pi's session projection (buildSessionProjection) is present", () => {
		expectCapability(typeof buildSessionProjection === "function", "Pi's session projection (buildSessionProjection)", [
			"online-context-compact-projection.test.ts",
		]);
	});

	it("bash returns a non-zero then_run exit as a result (nonZeroExitIsResult)", async () => {
		expectCapability(
			await bashReturnsNonZeroExit(),
			"a non-zero then_run exit returned as a result (nonZeroExitIsResult)",
			["action-fusion.test.ts"],
		);
	});
});
