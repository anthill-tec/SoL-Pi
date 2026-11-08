/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, sep } from "node:path";
import { pathToFileURL } from "node:url";
import {
	CONFIG_DIR_NAME,
	createAgentSession,
	DefaultResourceLoader,
	SessionManager,
	SettingsManager,
	type AgentSession,
} from "@earendil-works/pi-coding-agent";
import { fauxProvider } from "@earendil-works/pi-ai/providers/faux";
import { afterAll, beforeAll, describe, expect, it } from "bun:test";

interface PackageManifest {
	peerDependencies: Record<string, string>;
}

const piPackages = [
	"@earendil-works/pi-agent-core",
	"@earendil-works/pi-ai",
	"@earendil-works/pi-coding-agent",
	"@earendil-works/pi-tui",
];

function compareVersions(left: string, right: string): number {
	const leftParts = left.split(".").map(Number);
	const rightParts = right.split(".").map(Number);
	for (let index = 0; index < Math.max(leftParts.length, rightParts.length); index++) {
		const difference = (leftParts[index] ?? 0) - (rightParts[index] ?? 0);
		if (difference !== 0) return difference;
	}
	return 0;
}

function documentedFloor(): string {
	const match = /the declared floor is (\d+\.\d+\.\d+)/u.exec(readFileSync("docs/compatibility.md", "utf8"));
	if (!match?.[1]) throw new Error("docs/compatibility.md declares no peer dependency floor");
	return match[1];
}

function declaredFloor(range: string): string {
	const match = /\d+\.\d+\.\d+/u.exec(range);
	if (!match) throw new Error(`Peer range declares no version floor: ${range}`);
	return match[0];
}

/** The package's file paths, from the `packed <size> <path>` lines `bun pm pack --dry-run` prints. */
function packedFiles(): string[] {
	const result = spawnSync("bun", ["pm", "pack", "--dry-run"], {
		cwd: process.cwd(),
		encoding: "utf8",
		timeout: 25_000,
	});
	if (result.status !== 0) throw new Error(result.stderr || result.stdout);
	return result.stdout.split(/\r?\n/u).flatMap((line) => /^packed \S+ (.+)$/u.exec(line)?.[1] ?? []);
}

describe("published package", () => {
	let files: string[];
	beforeAll(() => {
		files = packedFiles();
	}, 30_000);

	it("ships the default cache write/read ratio in the example config", () => {
		const config = JSON.parse(readFileSync("sol-pi.example.json", "utf8")) as Record<string, unknown>;
		expect(config.cacheWriteReadRatio).toBe(12.5);
		expect(config.evidencePreservingReducerProvider).toBe("provider-id");
		expect(config.evidencePreservingReducerModel).toBe("model-id");
	});

	it("contains the standalone entrypoint and no Pi monorepo source", () => {
		expect(files).toContain("src/sol-pi/index.ts");
		expect(files).toContain("sol-pi.example.json");
		expect(files.some((file) => file.startsWith("packages/"))).toBe(false);
		expect(files.some((file) => file.startsWith("docs/superpowers/"))).toBe(false);
	});

	it("ships Online Context Compact from the standalone source tree", () => {
		expect(files).toContain("src/sol-pi/extensions/online-context-compact/index.ts");
		expect(files).toContain("scripts/check-sol-pi-config.mjs");
		expect(files).toContain("agents-install.md");
		expect(files).not.toContain("AGENTS.md");
		expect(files).not.toContain("CLAUDE.md");
	});

	it("ships no Python file and no pyproject.toml: sol-pi-axi is its own PyPI package", () => {
		expect(files.length).toBeGreaterThan(0);
		expect(files.filter((file) => file.endsWith(".py"))).toEqual([]);
		expect(files.filter((file) => file.split("/").pop() === "pyproject.toml")).toEqual([]);
	});
});

function runScript(script: string, args: string[]): { status: number | null; output: string } {
	const result = spawnSync("node", [script, ...args], { cwd: process.cwd(), encoding: "utf8" });
	return { status: result.status, output: `${result.stdout}${result.stderr}` };
}

function checkPiCompat(...args: string[]): { status: number | null; output: string } {
	return runScript("scripts/check-pi-compat.mjs", args);
}

// Every check starts a Node process that loads Pi; on slow shared file systems that takes longer than
// Bun's 5 s default, so each test has a 30 s timeout.
describe("Pi compatibility check", () => {
	const baseline = checkPiCompat();
	const detected = /^Pi: @earendil-works\/pi-coding-agent@(\S+) \((.+)\)$/m.exec(baseline.output);
	const roots: string[] = [];

	afterAll(() => {
		for (const root of roots) rmSync(root, { recursive: true, force: true });
	});

	function realPiDir(): string {
		const [, , realDir] = detected ?? [];
		if (!realDir) throw new Error(baseline.output);
		return realDir;
	}

	/** The installed Pi version, so a fake Pi with the real exports passes the VERSION check. */
	function realVersion(): string {
		const [, version] = detected ?? [];
		if (!version) throw new Error(baseline.output);
		return version;
	}

	function tempRoot(): string {
		const root = mkdtempSync(join(tmpdir(), "sol-pi-compat-"));
		roots.push(root);
		return root;
	}

	/**
	 * A Pi install whose pi-coding-agent claims `version` and re-exports `exports` from the real one.
	 * `body` is appended to its entry module; set `exports` to "" to replace the module entirely.
	 */
	function fakePi(version: string, exports: string, body = ""): string {
		const realDir = realPiDir();
		const root = tempRoot();
		const scope = join(root, "node_modules", "@earendil-works");
		const piDir = join(scope, "pi-coding-agent");
		mkdirSync(join(piDir, "dist"), { recursive: true });
		for (const sibling of ["pi-ai", "pi-tui"]) {
			symlinkSync(join(dirname(realDir), sibling), join(scope, sibling), "dir");
		}
		const realIndex = pathToFileURL(join(realDir, "dist", "index.js")).href;
		const manifest = {
			name: "@earendil-works/pi-coding-agent",
			version,
			type: "module",
			exports: { ".": { import: "./dist/index.js" } },
		};
		writeFileSync(join(piDir, "package.json"), JSON.stringify(manifest));
		const reexport = exports ? `export ${exports} from ${JSON.stringify(realIndex)};\n` : "";
		writeFileSync(join(piDir, "dist", "index.js"), `${reexport}${body}\n`);
		return root;
	}

	/**
	 * Pi 1.5.0's internal package graph: each package's exact `@earendil-works/pi-*` dependencies.
	 * pi-schema and pi-telemetry are reached only through pi-ai and pi-agent-core.
	 */
	const PI_1_5_0_INTERNALS: Record<string, string[]> = {
		"pi-agent-core": ["pi-ai", "pi-schema"],
		"pi-ai": ["pi-schema", "pi-telemetry"],
		"pi-codemode": [],
		"pi-mcp": [],
		"pi-schema": [],
		"pi-telemetry": [],
		"pi-tui": [],
	};
	const PI_1_5_0_DIRECT = ["pi-agent-core", "pi-ai", "pi-codemode", "pi-mcp", "pi-tui"];

	/** The file a real Pi sibling package exports at `subpath` (the conditions Pi packages use). */
	function realEntry(sibling: string, subpath: string): string {
		const dir = join(dirname(realPiDir()), sibling);
		const manifest = JSON.parse(readFileSync(join(dir, "package.json"), "utf8")) as {
			main?: string;
			exports?: Record<string, { import?: string } | string>;
		};
		const target = manifest.exports?.[subpath];
		const file = typeof target === "string" ? target : (target?.import ?? (subpath === "." ? manifest.main : undefined));
		if (!file) throw new Error(`${sibling} does not export ${subpath}`);
		return pathToFileURL(join(dir, file)).href;
	}

	/**
	 * A complete Pi `version` install shaped like Pi 1.5.0: pi-coding-agent exports its own `VERSION`
	 * (not the development dependency's) and re-exports every other name from the real one, and every
	 * internal package of Pi 1.5.0's graph is installed at `version` unless `installed` names another
	 * version for it. pi-ai and pi-tui re-export the real packages, so the API checks still load them.
	 */
	function fakePiRelease(version: string, installed: Record<string, string> = {}): string {
		const root = tempRoot();
		const scope = join(root, "node_modules", "@earendil-works");
		const pin = (names: string[]) =>
			Object.fromEntries(names.map((name) => [`@earendil-works/${name}`, version]));
		const reexports: Record<string, Record<string, string>> = {
			"pi-ai": { ".": realEntry("pi-ai", "."), "./compat": realEntry("pi-ai", "./compat") },
			"pi-tui": { ".": realEntry("pi-tui", ".") },
		};
		for (const [name, dependencies] of Object.entries(PI_1_5_0_INTERNALS)) {
			const dir = join(scope, name);
			mkdirSync(dir, { recursive: true });
			const entries = reexports[name] ?? { ".": "" };
			const exports: Record<string, string> = {};
			for (const [subpath, real] of Object.entries(entries)) {
				const file = `./${subpath === "." ? "index" : subpath.slice(2)}.js`;
				exports[subpath] = file;
				writeFileSync(join(dir, file), real ? `export * from ${JSON.stringify(real)};\n` : "export {};\n");
			}
			const manifest = {
				name: `@earendil-works/${name}`,
				version: installed[name] ?? version,
				type: "module",
				exports,
				dependencies: pin(dependencies),
			};
			writeFileSync(join(dir, "package.json"), JSON.stringify(manifest));
		}
		const piDir = join(scope, "pi-coding-agent");
		mkdirSync(join(piDir, "dist"), { recursive: true });
		const manifest = {
			name: "@earendil-works/pi-coding-agent",
			version,
			type: "module",
			exports: { ".": { import: "./dist/index.js" } },
			dependencies: pin(PI_1_5_0_DIRECT),
		};
		writeFileSync(join(piDir, "package.json"), JSON.stringify(manifest));
		// A local export takes precedence over the star re-export, so VERSION is the fake's own.
		const realIndex = pathToFileURL(join(realPiDir(), "dist", "index.js")).href;
		writeFileSync(
			join(piDir, "dist", "index.js"),
			`export * from ${JSON.stringify(realIndex)};\nexport const VERSION = ${JSON.stringify(version)};\n`,
		);
		return root;
	}

	/** A SoL-Pi checkout with only the compat script, the given src/ files, and the real node_modules. */
	function fakeCheckout(sources: Record<string, string>): string {
		const root = tempRoot();
		mkdirSync(join(root, "scripts"));
		mkdirSync(join(root, "src"));
		copyFileSync("scripts/check-pi-compat.mjs", join(root, "scripts", "check-pi-compat.mjs"));
		for (const [name, source] of Object.entries(sources)) writeFileSync(join(root, "src", name), source);
		symlinkSync(dirname(dirname(realPiDir())), join(root, "node_modules"), "dir");
		return join(root, "scripts", "check-pi-compat.mjs");
	}

	it("passes on the installed Pi and reports its version, bash exit mode, and codemode availability", async () => {
		expect(baseline.status, baseline.output).toBe(0);
		const [, version, realDir] = detected ?? [];
		expect(version).toBeDefined();
		const pi = (await import("@earendil-works/pi-coding-agent")) as Record<string, unknown>;
		expect(pi.VERSION).toBe(version);
		expect(baseline.output).toContain("Pi compatibility: OK");
		expect(baseline.output).not.toContain("WARN:");
		const bash = (pi.createBashToolDefinition as (cwd: string) => { outputSchema?: unknown })(process.cwd());
		// Pi >= 0.99 returns isError with structuredContent for non-zero exits; older Pi throws.
		expect(baseline.output).toMatch(
			bash.outputSchema === undefined
				? /^bash non-zero exit: throws \(Pi <= 0\.98 behaviour\): Command exited with code 3$/m
				: /^bash non-zero exit: returns isError result/m,
		);
		expect(baseline.output).toContain(
			typeof pi.createCodemodeExtension === "function" ? "codemode: available" : "codemode: not available",
		);
		const explicit = checkPiCompat("--pi-root", realDir ?? "", "--strict");
		expect(explicit.status, explicit.output).toBe(0);
	}, 30_000);

	it("fails below the supported Pi floor", () => {
		const result = checkPiCompat("--pi-root", fakePi("0.80.0", "*"));
		expect(result.status, result.output).toBe(1);
		expect(result.output).toContain("Pi 0.80.0 is below the supported floor 0.84.2");
	}, 30_000);

	it("warns on untested Pi versions and fails them only under --strict", () => {
		const root = fakePi("9.0.0", "*");
		const relaxed = checkPiCompat("--pi-root", root);
		expect(relaxed.status, relaxed.output).toBe(0);
		expect(relaxed.output).toContain("WARN: Pi 9.0.0 is not in the tested set");
		const strict = checkPiCompat(`--pi-root=${root}`, "--strict");
		expect(strict.status, strict.output).toBe(1);
	}, 30_000);

	it("warns when Pi's internal packages come from another release", () => {
		// Pi before 1.3.0 depends on its internal packages with caret ranges, so a fresh install of
		// Pi 1.0.4 now gets pi-codemode 1.3.0 and fails to load.
		const version = realVersion();
		const root = fakePi(version, "*");
		const scope = join(root, "node_modules", "@earendil-works");
		const manifestPath = join(scope, "pi-coding-agent", "package.json");
		const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, unknown>;
		writeFileSync(manifestPath, JSON.stringify({ ...manifest, dependencies: { "@earendil-works/pi-codemode": `^${version}` } }));
		mkdirSync(join(scope, "pi-codemode"));
		writeFileSync(join(scope, "pi-codemode", "package.json"), JSON.stringify({ name: "@earendil-works/pi-codemode", version: "99.0.0" }));
		const relaxed = checkPiCompat("--pi-root", root);
		expect(relaxed.status, relaxed.output).toBe(0);
		expect(relaxed.output).toContain(`WARN: Pi ${version} is installed with internal packages from other releases (pi-codemode 99.0.0)`);
		// The warning advises the latest tested release, Pi 1.5.0 (CR-SLP-002 §S2).
		expect(relaxed.output).toContain("install Pi 1.5.0");
		expect(relaxed.output).not.toContain("install Pi 1.3.0");
		const strict = checkPiCompat("--pi-root", root, "--strict");
		expect(strict.status, strict.output).toBe(1);
	}, 30_000);

	it("passes a Pi 1.5.0 install with its own VERSION and 1.5.0 internals under --strict without a warning", () => {
		const root = fakePiRelease("1.5.0");
		const result = checkPiCompat("--pi-root", root, "--strict");
		expect(result.output).toMatch(/^Pi: @earendil-works\/pi-coding-agent@1\.5\.0 \(.+sol-pi-compat-.+\)$/mu);
		expect(result.output).not.toContain("WARN:");
		expect(result.output).not.toContain("ERROR:");
		expect(result.output).toMatch(/^Pi compatibility: OK$/mu);
		expect(result.status, result.output).toBe(0);
	}, 30_000);

	it("warns when an internal package Pi reaches only indirectly comes from another release", () => {
		// pi-schema is not a direct dependency of pi-coding-agent 1.5.0; it arrives through pi-ai and
		// pi-agent-core, so a check of the direct dependencies alone misses it.
		const root = fakePiRelease("1.5.0", { "pi-schema": "1.4.0" });
		const relaxed = checkPiCompat("--pi-root", root);
		expect(relaxed.status, relaxed.output).toBe(0);
		// Listed once, though two internal packages reach it, and no direct package is listed.
		expect(relaxed.output).toContain("WARN: Pi 1.5.0 is installed with internal packages from other releases (pi-schema 1.4.0)");
		expect(relaxed.output.match(/^WARN:/gmu)).toHaveLength(1);
		const strict = checkPiCompat("--pi-root", root, "--strict");
		expect(strict.status, strict.output).toBe(1);
		expect(strict.output).toContain("Pi compatibility: FAIL");
	}, 30_000);

	it("warns on a nested copy of an internal package from another release beside a top-level copy of this release", () => {
		// pi-agent-core resolves the top-level pi-schema 1.5.0, but pi-ai resolves its own nested
		// pi-schema 1.4.0 first: both copies are installed, so the nested one is still checked.
		const root = fakePiRelease("1.5.0");
		const nested = join(root, "node_modules", "@earendil-works", "pi-ai", "node_modules", "@earendil-works", "pi-schema");
		mkdirSync(nested, { recursive: true });
		writeFileSync(join(nested, "index.js"), "export {};\n");
		writeFileSync(
			join(nested, "package.json"),
			JSON.stringify({ name: "@earendil-works/pi-schema", version: "1.4.0", type: "module", exports: { ".": "./index.js" } }),
		);
		const relaxed = checkPiCompat("--pi-root", root);
		expect(relaxed.status, relaxed.output).toBe(0);
		expect(relaxed.output).toContain("WARN: Pi 1.5.0 is installed with internal packages from other releases (pi-schema 1.4.0)");
		expect(relaxed.output.match(/^WARN:/gmu)).toHaveLength(1);
		const strict = checkPiCompat("--pi-root", root, "--strict");
		expect(strict.status, strict.output).toBe(1);
	}, 30_000);

	it("follows a dependency cycle between Pi's internal packages to an end and lists each package once", () => {
		// pi-ai and pi-schema depend on each other.
		const root = fakePiRelease("1.5.0", { "pi-schema": "1.4.0" });
		const manifestPath = join(root, "node_modules", "@earendil-works", "pi-schema", "package.json");
		const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, unknown>;
		writeFileSync(manifestPath, JSON.stringify({ ...manifest, dependencies: { "@earendil-works/pi-ai": "1.5.0" } }));
		const relaxed = checkPiCompat("--pi-root", root);
		expect(relaxed.status, relaxed.output).toBe(0);
		expect(relaxed.output).toContain("WARN: Pi 1.5.0 is installed with internal packages from other releases (pi-schema 1.4.0)");
		expect(relaxed.output.match(/^WARN:/gmu)).toHaveLength(1);
		expect(relaxed.output).toMatch(/^Pi compatibility: OK \(with warnings\)$/mu);
	}, 30_000);

	it("fails when a Pi export SoL-Pi imports is missing", () => {
		const result = checkPiCompat("--pi-root", fakePi("1.0.4", "{ VERSION, CONFIG_DIR_NAME }"));
		expect(result.status, result.output).toBe(1);
		expect(result.output).toContain("Missing public Pi API: @earendil-works/pi-coding-agent getAgentDir");
		expect(result.output).toContain("Missing public Pi API: createBashToolDefinition");
	}, 30_000);

	it("checks only the Pi imports that survive TypeScript import elision", () => {
		const typeOnly = [
			'import { ExtensionAPI, getAgentDir, NotAPiType } from "@earendil-works/pi-coding-agent";',
			"export type Missing = NotAPiType;",
			"export const dir = (_pi: ExtensionAPI): string => getAgentDir();",
		].join("\n");
		const passing = runScript(fakeCheckout({ "type-only.ts": typeOnly }), ["--strict"]);
		expect(passing.status, passing.output).toBe(0);
		expect(passing.output).not.toContain("ExtensionAPI");
		expect(passing.output).not.toContain("NotAPiType");

		const valueUse = 'import { notAPiExport } from "@earendil-works/pi-coding-agent";\nexport const value = notAPiExport;';
		const failing = runScript(fakeCheckout({ "type-only.ts": typeOnly, "value.ts": valueUse }), []);
		expect(failing.status, failing.output).toBe(1);
		expect(failing.output).toContain("Missing public Pi API: @earendil-works/pi-coding-agent notAPiExport");
		expect(failing.output).not.toContain("ExtensionAPI");
	}, 30_000);

	it("reports the bash exit status line when bash throws on a non-zero exit", () => {
		const legacyBash = [
			"export function createBashToolDefinition() {",
			'\treturn { execute: async () => { throw new Error("out\\n\\nCommand exited with code 3"); } };',
			"}",
		].join("\n");
		const result = checkPiCompat("--pi-root", fakePi(realVersion(), "*", legacyBash), "--strict");
		expect(result.status, result.output).toBe(0);
		expect(result.output).toContain("bash non-zero exit: throws (Pi <= 0.98 behaviour): Command exited with code 3");
	}, 30_000);

	it("warns when the bash probe throws for a reason other than a non-zero exit", () => {
		const brokenBash = [
			"export function createBashToolDefinition() {",
			'\treturn { execute: async () => { throw new Error("spawn /bin/bash ENOENT"); } };',
			"}",
		].join("\n");
		const root = fakePi(realVersion(), "*", brokenBash);
		const relaxed = checkPiCompat("--pi-root", root);
		expect(relaxed.status, relaxed.output).toBe(0);
		expect(relaxed.output).toContain("bash non-zero exit: throws an unexpected error: spawn /bin/bash ENOENT");
		expect(relaxed.output).not.toContain("Pi <= 0.98 behaviour");
		expect(relaxed.output).toContain("WARN: bash probe threw for a reason other than a non-zero exit");
		const strict = checkPiCompat("--pi-root", root, "--strict");
		expect(strict.status, strict.output).toBe(1);
	}, 30_000);

	it("reports a Pi install that cannot be imported as a structured failure", () => {
		const result = checkPiCompat("--pi-root", fakePi(realVersion(), "", 'throw new Error("broken install");'));
		expect(result.status, result.output).toBe(1);
		expect(result.output).toContain("ERROR: Cannot load @earendil-works/pi-coding-agent: broken install");
		expect(result.output).toContain("Pi compatibility: FAIL");
		expect(result.output).not.toMatch(/^\s+at /m);
	}, 30_000);
});

describe("declared Pi compatibility", () => {
	function manifest(): PackageManifest {
		return JSON.parse(readFileSync("package.json", "utf8")) as PackageManifest;
	}

	function piPeerRanges(): string[] {
		const peers = manifest().peerDependencies;
		return piPackages.map((name) => {
			const range = peers[name];
			if (range === undefined) throw new Error(`Missing Pi peer dependency: ${name}`);
			return range;
		});
	}

	it("requires the documented Pi floor from every shared-release Pi package", () => {
		const ranges = piPeerRanges();
		const floor = documentedFloor();

		expect(new Set(ranges).size).toBe(1);
		for (const range of ranges) {
			expect(range).not.toBe("*");
			expect(declaredFloor(range), range).toBe(floor);
		}
	});

	it("keeps the lockfile root peers in step with the manifest", () => {
		// bun.lock is JSONC: it ends objects and arrays with trailing commas.
		const lockfile = Bun.JSONC.parse(readFileSync("bun.lock", "utf8")) as {
			workspaces: Record<string, Partial<PackageManifest>>;
		};
		const locked = piPackages.map((name) => lockfile.workspaces[""]?.peerDependencies?.[name]);

		expect(locked).toEqual(piPeerRanges());
	});

	it("excludes the Pi release that satisfies the range but cannot load SoL-Pi", () => {
		const incompatible = "0.79.10";
		for (const range of piPeerRanges()) {
			expect(compareVersions(declaredFloor(range), incompatible), range).toBeGreaterThan(0);
		}
	});
});

// --- The npm package `@anthill-tec/sol-pi` (CR-SLP-007 §S1) ------------------------------------------

/** The release version both packages carry. */
const RELEASE_VERSION = "0.1.0";

/** `package.json` values §S1 leaves unchanged, as on the base branch (develop at CR-SLP-004's merge). */
const BASE_FILES = [
	"src/sol-pi",
	"assets",
	"docs/compatibility.md",
	"docs/configuration.md",
	"scripts/check-sol-pi-config.mjs",
	"agents-install.md",
	"README.md",
	"LICENSE",
	"CONTRIBUTING.md",
	"SECURITY.md",
	"THIRD_PARTY_NOTICES.md",
	"sol-pi.example.json",
];
const BASE_PI = { extensions: ["./src/sol-pi/index.ts"] };
const BASE_PEER_DEPENDENCIES = {
	"@earendil-works/pi-agent-core": ">=0.84.2",
	"@earendil-works/pi-ai": ">=0.84.2",
	"@earendil-works/pi-coding-agent": ">=0.84.2",
	"@earendil-works/pi-tui": ">=0.84.2",
	typebox: "*",
};

/** The files `bun pm pack --dry-run` lists on the base branch, sorted. */
const BASE_PACKED_FILES = [
	"CONTRIBUTING.md",
	"LICENSE",
	"README.md",
	"SECURITY.md",
	"THIRD_PARTY_NOTICES.md",
	"agents-install.md",
	"assets/sol-pi-hero.png",
	"docs/compatibility.md",
	"docs/configuration.md",
	"package.json",
	"scripts/check-sol-pi-config.mjs",
	"sol-pi.example.json",
	"src/sol-pi/config.ts",
	"src/sol-pi/extensions/action-fusion/file-queue.ts",
	"src/sol-pi/extensions/action-fusion/index.ts",
	"src/sol-pi/extensions/action-fusion/then-run.ts",
	"src/sol-pi/extensions/evidence-preserving-reducer/archive.ts",
	"src/sol-pi/extensions/evidence-preserving-reducer/candidate.ts",
	"src/sol-pi/extensions/evidence-preserving-reducer/config.ts",
	"src/sol-pi/extensions/evidence-preserving-reducer/index.ts",
	"src/sol-pi/extensions/evidence-preserving-reducer/journal.ts",
	"src/sol-pi/extensions/evidence-preserving-reducer/provider.ts",
	"src/sol-pi/extensions/evidence-preserving-reducer/receipt.ts",
	"src/sol-pi/extensions/observation-pack/index.ts",
	"src/sol-pi/extensions/observation-pack/ledger.ts",
	"src/sol-pi/extensions/observation-pack/observation.ts",
	"src/sol-pi/extensions/online-context-compact/economics.ts",
	"src/sol-pi/extensions/online-context-compact/extension.ts",
	"src/sol-pi/extensions/online-context-compact/index.ts",
	"src/sol-pi/extensions/online-context-compact/plan.ts",
	"src/sol-pi/extensions/online-context-compact/projection.ts",
	"src/sol-pi/extensions/online-context-compact/state.ts",
	"src/sol-pi/extensions/online-context-compact/subagents.ts",
	"src/sol-pi/extensions/online-context-compact/tools.ts",
	"src/sol-pi/index.ts",
	"src/sol-pi/runtime-paths.ts",
	"src/sol-pi/shell-options.ts",
	"src/sol-pi/tui.ts",
];

/** The tools SoL-Pi registers with every mechanism enabled. */
const SOL_PI_TOOLS = ["edit", "obs_recall", "update_plan", "write"];

describe("npm package @anthill-tec/sol-pi", () => {
	const text = readFileSync("package.json", "utf8");
	const manifest = JSON.parse(text) as Record<string, unknown>;

	it("is named @anthill-tec/sol-pi, public, with the repository and the pi-package keyword", () => {
		expect(manifest.name).toBe("@anthill-tec/sol-pi");
		expect("private" in manifest).toBe(false);
		expect(manifest.publishConfig).toEqual({ access: "public" });
		// npm's normalised form, so `npm publish` corrects nothing.
		expect(manifest.repository).toEqual({ type: "git", url: "git+https://github.com/anthill-tec/SoL-Pi.git" });
		expect(manifest.keywords).toContain("pi-package");
	});

	it("is indented with two spaces", () => {
		expect(text).toBe(`${JSON.stringify(manifest, null, 2)}\n`);
		expect(text).not.toContain("\t");
	});

	it(`carries version ${RELEASE_VERSION} in package.json and sol_pi_axi/_version.py`, () => {
		expect(manifest.version).toBe(RELEASE_VERSION);
		expect(readFileSync("sol_pi_axi/_version.py", "utf8")).toBe(`__version__ = "${RELEASE_VERSION}"\n`);
	});

	it("keeps files, pi.extensions, peerDependencies and dependencies unchanged", () => {
		expect(manifest.files).toEqual(BASE_FILES);
		expect(manifest.pi).toEqual(BASE_PI);
		expect(manifest.peerDependencies).toEqual(BASE_PEER_DEPENDENCIES);
		expect("dependencies" in manifest).toBe(false);
	});

	it(`passes stamp_version.py check ${RELEASE_VERSION} pypi:. npm:.`, () => {
		const result = spawnSync("python3", [".github/scripts/stamp_version.py", "check", RELEASE_VERSION, "pypi:.", "npm:."], {
			cwd: process.cwd(),
			encoding: "utf8",
			timeout: 25_000,
		});
		expect({ status: result.status, stderr: result.stderr }).toEqual({ status: 0, stderr: "" });
	}, 30_000);

	it("packs the same files as the base branch", () => {
		expect([...packedFiles()].sort()).toEqual(BASE_PACKED_FILES);
	}, 30_000);

	it("packs a tarball that the development dependency's Pi loads with its path as the extension, registering SoL-Pi's tools", async () => {
		const root = mkdtempSync(join(tmpdir(), "sol-pi-tarball-"));
		let session: AgentSession | undefined;
		try {
			const packed = spawnSync("bun", ["pm", "pack", "--destination", root], {
				cwd: process.cwd(),
				encoding: "utf8",
				timeout: 25_000,
			});
			expect(packed.status, packed.stderr).toBe(0);
			const tarballs = readdirSync(root).filter((name) => name.endsWith(".tgz"));
			expect(tarballs).toHaveLength(1);
			const unpacked = join(root, "unpacked");
			mkdirSync(unpacked);
			const untar = spawnSync("tar", ["-xzf", join(root, tarballs[0] ?? ""), "-C", unpacked], { encoding: "utf8" });
			expect(untar.status, untar.stderr).toBe(0);
			const packageDir = join(unpacked, "package");
			const packedManifest = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8")) as Record<string, unknown>;
			expect({ name: packedManifest.name, version: packedManifest.version })
				.toEqual({ name: "@anthill-tec/sol-pi", version: RELEASE_VERSION });

			const cwd = join(root, "project");
			const agentDir = join(root, "agent");
			mkdirSync(join(cwd, CONFIG_DIR_NAME), { recursive: true });
			mkdirSync(agentDir);
			writeFileSync(join(cwd, CONFIG_DIR_NAME, "sol-pi.json"), JSON.stringify({
				version: 1,
				actionFusion: true,
				observationPack: true,
				evidencePreservingReducer: true,
				onlineContextCompact: true,
			}));
			const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } }, { projectTrusted: true });
			const resourceLoader = new DefaultResourceLoader({
				cwd,
				agentDir,
				settingsManager,
				additionalExtensionPaths: [packageDir],
				noExtensions: true,
				noSkills: true,
				noPromptTemplates: true,
				noThemes: true,
				noContextFiles: true,
			});
			await resourceLoader.reload();
			const loaded = resourceLoader.getExtensions();
			expect(loaded.errors).toEqual([]);
			const faux = fauxProvider({ provider: "sol-pi-tarball-test", api: "sol-pi-tarball-test-api" });
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
			const solPi = loaded.extensions.filter((extension) => extension.resolvedPath.startsWith(`${packageDir}${sep}`));
			expect(solPi).toHaveLength(1);
			expect([...(solPi[0]?.tools.keys() ?? [])].sort()).toEqual(SOL_PI_TOOLS);
			expect(session.getActiveToolNames()).toEqual(expect.arrayContaining(SOL_PI_TOOLS));
		} finally {
			session?.dispose();
			rmSync(root, { recursive: true, force: true });
		}
	}, 60_000);
});
