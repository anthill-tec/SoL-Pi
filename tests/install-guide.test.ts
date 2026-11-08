/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

import { existsSync, readFileSync, statSync } from "node:fs";
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
		// CR-SLP-007 §S6: README's repository links are absolute, so they resolve on PyPI and npm.
		expect(readme).toContain(
			"[agent installation and configuration protocol](https://github.com/anthill-tec/SoL-Pi/blob/main/agents-install.md)",
		);
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
		// CR-SLP-007 §S6: the absolute blob/main form of the former relative link.
		expect(rootFile("README.md")).toContain("(https://github.com/anthill-tec/SoL-Pi/blob/main/docs/compatibility.md#codemode)");
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

		// CR-SLP-007 §S6 migrates this from the git+https install to the PyPI one.
		it(`${name} installs sol-pi-axi with uv tool install sol-pi-axi==<version>`, () => {
			const text = rootFile(name);
			expect(text).toMatch(new RegExp(`uv tool install sol-pi-axi==${versionPattern()}`, "u"));
			expect(text).not.toContain("uv tool install git+");
			for (const line of installLines(text)) {
				expect(line).not.toContain("NVlabs/SoL-Pi");
				if (/github\.com/u.test(line)) expect(line).toContain("anthill-tec/SoL-Pi");
			}
		});
	}

	// CR-SLP-007 §S6 migrates this: the extension installs from npm, no longer from a git source, so
	// README need not hold any github.com install line; any it holds still names anthill-tec/SoL-Pi.
	it("README's install lines name anthill-tec/SoL-Pi and install the extension from npm", () => {
		const readme = rootFile("README.md");
		const lines = installLines(readme).filter((line) => /github\.com/u.test(line));
		for (const line of lines) expect(line).toContain("anthill-tec/SoL-Pi");
		expect(readme).toMatch(new RegExp(`pi install npm:@anthill-tec/sol-pi@${versionPattern()}`, "u"));
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

/** `<version>`, or the shared version itself (package.json's). */
function versionPattern(): string {
	const version = JSON.parse(rootFile("package.json")).version as string;
	return `(<version>|${version.replaceAll(".", "\\.")})`;
}

/** Each `##`/`###` section of a Markdown document (heading line included). */
function sections(text: string): string[] {
	return text.split(/\n(?=#{2,3} )/u);
}

/** Every link and image target of a Markdown/HTML document, with its kind. */
function targets(text: string): { kind: "image" | "link"; target: string }[] {
	const found: { kind: "image" | "link"; target: string }[] = [];
	for (const match of text.matchAll(/(!?)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)/gu)) {
		found.push({ kind: match[1] ? "image" : "link", target: match[2]! });
	}
	for (const match of text.matchAll(/\b(href|src)\s*=\s*(["'])([^"']*)\2/gu)) {
		found.push({ kind: match[1] === "src" ? "image" : "link", target: match[3]! });
	}
	for (const match of text.matchAll(/\bsrcset\s*=\s*(["'])([^"']*)\1/gu)) {
		for (const candidate of match[2]!.split(",")) {
			const target = candidate.trim().split(/\s+/u)[0];
			if (target) found.push({ kind: "image", target });
		}
	}
	return found;
}

const RAW_PREFIX = "https://raw.githubusercontent.com/anthill-tec/SoL-Pi/main/";
const BLOB_PREFIX = "https://github.com/anthill-tec/SoL-Pi/blob/main/";

/** The repository path a raw/blob URL names, without its query or anchor. */
function repositoryPath(url: string, prefix: string): string {
	return decodeURIComponent(url.slice(prefix.length).split(/[?#]/u)[0]!);
}

function isRepositoryFile(path: string): boolean {
	const full = join(process.cwd(), path);
	return path.length > 0 && !path.split("/").includes("..") && existsSync(full) && statSync(full).isFile();
}

// CR-SLP-007 §S6: the registry install, its commands and envelopes, and README for PyPI and npm.
describe("registry install documentation", () => {
	const INSTALL_OUTCOMES = ["installed", "unchanged", "failed", "cancelled"];
	const INSTALL_KEYS = ["extension", "source", "registered", "replaced", "agentDir"];

	for (const name of ["README.md", "agents-install.md"]) {
		it(`${name} installs sol-pi-axi from PyPI, then runs sol-pi-axi install, then setup per project`, () => {
			const text = rootFile(name);
			const uv = text.search(new RegExp(`uv tool install sol-pi-axi==${versionPattern()}`, "u"));
			expect(uv, "uv tool install sol-pi-axi==<version>").toBeGreaterThanOrEqual(0);
			const install = text.indexOf("sol-pi-axi install", uv);
			expect(install, "sol-pi-axi install after the uv install").toBeGreaterThan(uv);
			expect(text).toMatch(/sol-pi-axi setup <[^>\n]+>/u);
		});

		it(`${name} names the npm alternative and the version the two packages share`, () => {
			const text = rootFile(name);
			expect(text).toMatch(new RegExp(`pi install npm:@anthill-tec/sol-pi@${versionPattern()}`, "u"));
			expect(text).toMatch(/\b(the same|shares?|shared)\b[^.\n]{0,80}\bversion\b/iu);
		});

		it(`${name} documents install, uninstall, $PI_BIN, their envelopes and the home view's extension`, () => {
			const text = rootFile(name);
			expect(text).toContain("sol-pi-axi install");
			expect(text).toContain("sol-pi-axi uninstall");
			expect(text).toContain("$PI_BIN");
			for (const outcome of INSTALL_OUTCOMES) expect(text, outcome).toContain(outcome);
			expect(text, "uninstall outcome removed").toContain("removed");
			for (const key of INSTALL_KEYS) expect(documentsKey(text, key), `envelope key ${key}`).toBe(true);
			expect(documentsKey(text, "removed"), "uninstall's removed list").toBe(true);
			expect(
				sections(text).some((section) => /home view/iu.test(section) && documentsKey(section, "extension")),
				"a section documenting the home view's extension",
			).toBe(true);
		});

		it(`${name} installs nothing from a checkout path`, () => {
			const lines = installLines(rootFile(name));
			expect(lines.length, "install lines").toBeGreaterThanOrEqual(2);
			for (const line of lines) {
				expect(line).not.toMatch(/\bpi install\s+["']?(\/|\.{1,2}\/|~|\$|[A-Za-z]:\\)/u);
				expect(line).not.toMatch(/\buv tool install\s+(-e\b|--editable\b|["']?(\.|\/|~|\$|git\+))/u);
			}
		});

		it(`${name} states that pi install npm: runs npm or the npmCommand setting, on PATH`, () => {
			const statements = rootFile(name)
				.split(/\n\s*\n/u)
				.filter((paragraph) => paragraph.includes("npmCommand"));
			expect(statements.length, "a statement naming npmCommand").toBeGreaterThanOrEqual(1);
			expect(
				statements.some(
					(paragraph) =>
						/\bnpm\b(?![:/@-])/u.test(paragraph.replaceAll("npmCommand", "")) &&
						paragraph.includes("npm:") &&
						paragraph.includes("PATH"),
				),
				"the statement names npm, npm: sources, npmCommand and PATH",
			).toBe(true);
		});
	}

	it("README has no relative Markdown or HTML target except in-page anchors", () => {
		const readme = rootFile("README.md");
		const relative = targets(readme)
			.map(({ target }) => target)
			.filter((target) => !target.startsWith("#") && !/^[A-Za-z][A-Za-z0-9+.-]*:/u.test(target));
		expect(relative).toEqual([]);
		// In-page anchors are unchanged.
		expect(readme).toContain('href="#getting-started"');
	});

	it("README's repository images are raw main URLs and its repository links blob main URLs, to existing files", () => {
		const readme = rootFile("README.md");
		const found = targets(readme);
		// Each former repository-relative target, in its absolute form.
		expect(found).toContainEqual({ kind: "image", target: `${RAW_PREFIX}assets/sol-pi-hero.png` });
		for (const path of [
			"docs/configuration.md",
			"LICENSE",
			"examples/sol-pi-skill/README.md",
			"examples/solpi-visual/README.md",
			"sol-pi.example.json",
			"agents-install.md",
			"docs/compatibility.md#codemode",
			"docs/compatibility.md",
			"SECURITY.md",
			"CONTRIBUTING.md",
		]) {
			expect(found, path).toContainEqual({ kind: "link", target: `${BLOB_PREFIX}${path}` });
		}
		const repository = /^https:\/\/(raw\.githubusercontent\.com|github\.com)\/anthill-tec\/SoL-Pi\/(main|blob|raw|tree)\//iu;
		for (const { kind, target } of found.filter(({ target }) => repository.test(target))) {
			const prefix = kind === "image" ? RAW_PREFIX : BLOB_PREFIX;
			expect(target.startsWith(prefix), `${kind} ${target} uses ${prefix}`).toBe(true);
			expect(isRepositoryFile(repositoryPath(target, prefix)), `${target} names a repository file`).toBe(true);
		}
	});

	it("CONTRIBUTING.md covers checkout development, publishing with its one-time setup, and re-rendering", () => {
		const text = rootFile("CONTRIBUTING.md");
		// Installing from a checkout for development.
		expect(text).toMatch(/checkout/iu);
		expect(text).toMatch(/\bpi install\s+["']?(\/|\.{1,2}\/?|~|\$|<)/u);
		// The release's publishing.
		for (const word of ["release.yml", "sol-pi-axi", "@anthill-tec/sol-pi"]) expect(text, word).toContain(word);
		for (const word of [/\bPyPI\b/iu, /\bnpm\b/u]) expect(text).toMatch(word);
		// Its one-time setup (the workflow header's list).
		expect(text).toMatch(/one-time setup/iu);
		for (const word of ["RELEASE_PAT", "testpypi", "pypi.org", "test.pypi.org", "NPM_TOKEN"]) {
			expect(text, word).toContain(word);
		}
		expect(text).toMatch(/trusted publisher/iu);
		// Re-rendering the committed rendering.
		expect(text).toContain("modelb-axi release-workflow");
		expect(text).toContain("tests/fixtures/release-workflow/rendered.yml");
	});

	it("CHANGELOG.md [Unreleased] names the two packages, install and uninstall", () => {
		const section = unreleasedSection(rootFile("CHANGELOG.md"));
		expect(section).toContain("@anthill-tec/sol-pi");
		expect(section).toMatch(/`sol-pi-axi`|\bsol-pi-axi\b(?!-)/u);
		expect(section).toMatch(/sol-pi-axi install\b|`install`/u);
		expect(section).toMatch(/sol-pi-axi uninstall\b|`uninstall`/u);
	});
});
