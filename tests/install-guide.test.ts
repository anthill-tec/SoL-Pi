/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

function rootFile(name: string): string {
	return readFileSync(join(process.cwd(), name), "utf8");
}

/** An npm/npx/node/Vitest development command that CR-SLP-001 §S6 replaces with its Bun form. */
const NPM_DEVELOPMENT_COMMAND = /\bnpx\b|\bnpm (ci|run|test|audit|pack)\b|\bnode scripts\/|vitest/u;

/** The tested Pi versions declared by the compatibility check, oldest first. */
function testedPiVersions(): string[] {
	const declaration = rootFile("scripts/check-pi-compat.mjs").match(/const TESTED_PI_VERSIONS = \[([^\]]*)\]/u);
	if (!declaration?.[1]) throw new Error("TESTED_PI_VERSIONS not found in scripts/check-pi-compat.mjs");
	return [...declaration[1].matchAll(/"([^"]+)"/gu)]
		.map((match) => match[1]!)
		.sort((left, right) => left.localeCompare(right, "en", { numeric: true }));
}

describe("agent installation instructions", () => {
	it("makes the canonical guide mandatory for Codex install and configuration work", () => {
		const instructions = rootFile("AGENTS.md");
		expect(instructions).toContain("agents-install.md");
		expect(instructions).toMatch(/read.+completely/is);
		expect(instructions).toMatch(/install|build|configur/i);
	});

	it("imports the same canonical guide for Claude Code", () => {
		const instructions = rootFile("CLAUDE.md");
		expect(instructions.split(/\r?\n/u)).toContain("@agents-install.md");
	});

	it("keeps the README pointed at the managed installation and configuration profile", () => {
		const readme = rootFile("README.md");
		expect(readme).toContain("[agent installation and configuration protocol](agents-install.md)");
		expect(readme).toContain("check-sol-pi-config.mjs --require-all-enabled");
	});

	it("defines a reproducible and all-enabled installation", () => {
		const guide = rootFile("agents-install.md");
		const requiredText = [
			"Node.js 22.19",
			// Bun 1.4.4 is a prerequisite (CR-SLP-001 §S6).
			"Bun 1.4.4",
			`@earendil-works/pi-coding-agent@${JSON.parse(rootFile("package.json")).devDependencies["@earendil-works/pi-coding-agent"]}`,
			"bun install --frozen-lockfile --ignore-scripts",
			"bun run check",
			"bun audit --audit-level=high",
			"bun scripts/check-pi-compat.mjs --strict",
			"bun test --timeout 30000 tests/all-mechanisms.test.ts",
			"pi install",
			'"actionFusion": true',
			'"observationPack": true',
			'"evidencePreservingReducer": true',
			'"evidencePreservingReducerProvider": "provider-id"',
			'"evidencePreservingReducerModel": "model-id"',
			'"onlineContextCompact": true',
			'"cacheWriteReadRatio": 12.5',
			"bun scripts/check-sol-pi-config.mjs",
			"pi list",
			"tests/all-mechanisms.test.ts",
			"check-pi-compat.mjs --strict --pi-root",
			// The compatibility check is documented for both global Pi locations.
			'--pi-root "$HOME/.bun/install/global/node_modules"',
			'--pi-root "$(npm root -g)"',
		];

		for (const text of requiredText) expect(guide).toContain(text);
		// The Bun commands replace the npm ones; npm stays only as the alternative for installing Pi.
		expect(guide).not.toMatch(NPM_DEVELOPMENT_COMMAND);
		for (const install of guide.match(/\bnpm install\b[^\n]*/gu) ?? []) {
			expect(install).toContain("@earendil-works/pi-coding-agent@");
		}
		expect(guide).toMatch(/do not (modify|patch|vendor).+upstream Pi/is);
		expect(guide).toMatch(/do not print.+secret/is);
	});

	it("installs the latest tested Pi and names every tested Pi version", () => {
		const versions = testedPiVersions();
		const latest = versions.at(-1);
		expect(versions.length).toBeGreaterThan(1);
		// The development dependency is the newest tested Pi.
		const manifest = JSON.parse(rootFile("package.json")) as { devDependencies: Record<string, string> };
		expect(manifest.devDependencies["@earendil-works/pi-coding-agent"]).toBe(latest);

		const guide = rootFile("agents-install.md");
		const readme = rootFile("README.md");
		// Pi is installed with Bun first; the npm command is kept as the alternative, after it.
		const bunInstall = `bun add --global @earendil-works/pi-coding-agent@${latest}`;
		const guideNpmInstall = `npm install --global --ignore-scripts @earendil-works/pi-coding-agent@${latest}`;
		const readmeNpmInstall = `npm install --global @earendil-works/pi-coding-agent@${latest}`;
		expect(guide).toContain(bunInstall);
		expect(guide).toContain(guideNpmInstall);
		expect(guide.indexOf(bunInstall)).toBeLessThan(guide.indexOf(guideNpmInstall));
		expect(readme).toContain(bunInstall);
		expect(readme).toContain(readmeNpmInstall);
		expect(readme.indexOf(bunInstall)).toBeLessThan(readme.indexOf(readmeNpmInstall));
		// The README lists Bun 1.4.4 as a prerequisite, uses the Bun development commands, and
		// documents the compatibility check for both global Pi locations.
		expect(readme).toContain("Bun 1.4.4");
		expect(readme).toContain("bun install --frozen-lockfile --ignore-scripts");
		expect(readme).toContain("bun run check");
		expect(readme).not.toMatch(NPM_DEVELOPMENT_COMMAND);
		expect(readme).toContain('--pi-root "$HOME/.bun/install/global/node_modules"');
		expect(readme).toContain('--pi-root "$(npm root -g)"');
		for (const version of versions) {
			expect(guide).toContain(`@earendil-works/pi-coding-agent@${version}`);
			expect(readme).toContain(version);
			expect(rootFile("docs/compatibility.md")).toContain(version);
			expect(rootFile("THIRD_PARTY_NOTICES.md")).toContain(version);
		}
	});

	it("documents codemode support for every mechanism", () => {
		const compatibility = rootFile("docs/compatibility.md");
		expect(compatibility).toMatch(/^## Codemode$/mu);
		expect(compatibility).toContain('codemode.mode: "on"');
		expect(compatibility).toContain('"only"');
		for (const mechanism of [
			"Action Fusion",
			"ObservationPack",
			"Evidence-Preserving Reducer",
			"Online Context Compact",
		]) {
			expect(compatibility).toMatch(new RegExp(`^\\| ${mechanism} \\|`, "mu"));
		}
		expect(rootFile("README.md")).toContain("(docs/compatibility.md#codemode)");
	});

	it("documents one configured ratio and no active-model cost inference", () => {
		for (const name of [
			"README.md",
			"agents-install.md",
			"docs/configuration.md",
			"docs/compatibility.md",
		]) {
			const text = rootFile(name);
			expect(text, name).toContain("cacheWriteReadRatio");
			expect(text, name).not.toContain("Model.cost");
			expect(text, name).not.toContain("cache_read_price_per_million");
			expect(text, name).not.toContain("cache_write_price_per_million");
		}
	});
});
