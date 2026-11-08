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
		// Pi 1.5.0 joins the tested set as its latest release, the default install (CR-SLP-002 §S2, §S4).
		const versions = ["0.84.2", "1.0.4", "1.3.0", "1.5.0"];
		const latest = "1.5.0";
		expect(testedPiVersions()).toEqual(versions);
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
		// Pi 1.3.0 stays tested but is no longer the default install.
		for (const doc of [guide, readme]) {
			expect(doc).not.toContain("bun add --global @earendil-works/pi-coding-agent@1.3.0");
			expect(doc).not.toMatch(/npm install --global (--ignore-scripts )?@earendil-works\/pi-coding-agent@1\.3\.0/u);
		}
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
		// The notices table lists the four Pi packages at the development dependency, 1.5.0.
		const notices = rootFile("THIRD_PARTY_NOTICES.md");
		for (const name of ["pi-agent-core", "pi-ai", "pi-coding-agent", "pi-tui"]) {
			const rows = notices.match(new RegExp(`^\\| \`@earendil-works/${name}\` \\| [^|]+ \\|`, "gmu")) ?? [];
			expect(rows, name).toEqual([`| \`@earendil-works/${name}\` | ${latest} |`]);
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

/** A documented envelope key: written as code (`` `key` ``) or as a TOON field (`key:`, `key[2]:`). */
function documentsKey(text: string, key: string): boolean {
	return new RegExp(`\`${key}\`|(^|\\s)${key}(\\[\\d+\\])?:`, "mu").test(text);
}

/** The install lines of a document: every line that runs `pi install` or `uv tool install`. */
function installLines(text: string): string[] {
	return text.split(/\r?\n/u).filter((line) => /\b(pi install|uv tool install)\b/u.test(line));
}

/** The `[Unreleased]` section of the changelog, up to the next release heading. */
function unreleasedSection(changelog: string): string {
	const start = changelog.indexOf("## [Unreleased]");
	if (start < 0) throw new Error("CHANGELOG.md has no [Unreleased] section");
	const next = changelog.indexOf("\n## [", start + 1);
	return next < 0 ? changelog.slice(start) : changelog.slice(start, next);
}

// CR-SLP-004 §S5: the `sol-pi-axi` command, its `setup` verb and its install are documented.
describe("sol-pi-axi documentation", () => {
	const SETUP_FLAGS = ["--features", "--reducer", "--cache-ratio", "--format", "--non-interactive"];
	const ENVELOPE_KEYS = ["verb", "ok", "version", "warnings", "help", "error", "outcome", "path", "config", "context"];
	const OUTCOMES = ["written", "unchanged", "failed", "cancelled", "usage"];

	for (const name of ["README.md", "agents-install.md"]) {
		it(`${name} documents sol-pi-axi setup, its flags, envelope, home view and exit codes`, () => {
			const text = rootFile(name);
			expect(text).toContain("sol-pi-axi setup");
			for (const flag of SETUP_FLAGS) expect(text, flag).toContain(flag);
			for (const key of ENVELOPE_KEYS) expect(documentsKey(text, key), `envelope key ${key}`).toBe(true);
			for (const outcome of OUTCOMES) expect(text, outcome).toContain(outcome);
			expect(text).toContain("--format json");
			expect(text).toMatch(/home view/iu);
			for (const code of ["130", "143", "129"]) expect(text, `exit ${code}`).toMatch(new RegExp(`\\b${code}\\b`, "u"));
			expect(text).toMatch(/exit (code|status)/iu);
		});

		it(`${name} installs sol-pi-axi with uv tool install from anthill-tec/SoL-Pi`, () => {
			const text = rootFile(name);
			const version = JSON.parse(rootFile("package.json")).version as string;
			const escaped = version.replaceAll(".", "\\.");
			expect(text).toMatch(
				new RegExp(`uv tool install git\\+https://github\\.com/anthill-tec/SoL-Pi@(<version>|v?${escaped})`, "u"),
			);
			for (const line of installLines(text)) {
				expect(line).not.toContain("NVlabs/SoL-Pi");
				if (/github\.com/u.test(line)) expect(line).toContain("anthill-tec/SoL-Pi");
			}
		});
	}

	it("README's install lines name anthill-tec/SoL-Pi", () => {
		const lines = installLines(rootFile("README.md")).filter((line) => /github\.com/u.test(line));
		expect(lines.length).toBeGreaterThanOrEqual(2);
		for (const line of lines) expect(line).toContain("anthill-tec/SoL-Pi");
		expect(rootFile("README.md")).toContain("pi install git:github.com/anthill-tec/SoL-Pi");
	});

	it("states that the extension reads no environment variables and sol-pi-axi reads PI_CODING_AGENT_DIR", () => {
		for (const name of ["README.md", "agents-install.md", "docs/configuration.md"]) {
			const text = rootFile(name);
			// The old statement covered all of SoL-Pi; the extension alone now reads none.
			expect(text, name).not.toMatch(/SoL-Pi (reads|uses) no (dedicated )?environment variables/u);
			expect(text, name).toMatch(/extension[^\n]*\bno\b[^\n]*environment variables/iu);
			const lines = text.split(/\r?\n/u);
			expect(
				lines.some((line) => line.includes("sol-pi-axi") && line.includes("PI_CODING_AGENT_DIR")),
				`${name}: a statement that sol-pi-axi reads PI_CODING_AGENT_DIR`,
			).toBe(true);
		}
	});

	it("docs/configuration.md and agents-install.md state the layout each part supports", () => {
		for (const name of ["docs/configuration.md", "agents-install.md"]) {
			const lines = rootFile(name).split(/\r?\n/u);
			expect(
				lines.some((line) => line.includes("sol-pi-axi") && /official (Pi )?layout/iu.test(line)),
				`${name}: sol-pi-axi supports the official layout only`,
			).toBe(true);
			expect(
				lines.some((line) => /extension[^\n]*follows[^\n]*Pi/iu.test(line) && /agent director/iu.test(line)),
				`${name}: the extension follows Pi's configuration and agent directories`,
			).toBe(true);
			expect(rootFile(name), name).toContain("~/.pi/agent");
		}
	});

	it("docs/configuration.md says a project file needs trust and how setup chooses its values", () => {
		const text = rootFile("docs/configuration.md");
		expect(text).toMatch(/project[^\n]*\btrust/iu);
		expect(text).toContain("sol-pi-axi setup");
		for (const word of ["defaultProvider", "defaultModel", "settings.json", "--reducer"]) {
			expect(text, word).toContain(word);
		}
	});

	it("THIRD_PARTY_NOTICES.md lists toon-format 1.2.0 under MIT", () => {
		const rows = rootFile("THIRD_PARTY_NOTICES.md").match(/^\| `toon-format` \| [^|]+ \| [^|]+ \|/gmu) ?? [];
		expect(rows).toEqual(["| `toon-format` | 1.2.0 | MIT |"]);
	});

	it("CHANGELOG.md [Unreleased] records the sol-pi-axi command", () => {
		const section = unreleasedSection(rootFile("CHANGELOG.md"));
		expect(section).toContain("sol-pi-axi");
		expect(section).toContain("setup");
	});
});
