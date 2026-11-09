/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */
/**
 * The load signal `sol-pi-axi verify` waits for (DN-sol-pi-axi §D6), through a real Pi AgentSession
 * on the development dependency with a faux model: when `SOL_PI_AXI_VERIFY` holds a non-empty value,
 * SoL-Pi's `session_start` first calls `ui.notify("sol-pi-axi verify <value>", "info")`, before it
 * reads its configuration, so a loaded SoL-Pi signals even when its configuration is invalid; with
 * the variable unset or empty it calls nothing extra.
 */
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fauxProvider } from "@earendil-works/pi-ai/providers/faux";
import {
	createAgentSession,
	DefaultResourceLoader,
	SessionManager,
	SettingsManager,
	type AgentSession,
	type ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { DEFAULT_CONFIG, type SolPiConfig } from "../src/sol-pi/config.ts";
import { createSolPiExtension } from "../src/sol-pi/index.ts";

const VERIFY_ENV = "SOL_PI_AXI_VERIFY";
const AGENT_DIR_ENV = "PI_CODING_AGENT_DIR";
const SIGNAL_PREFIX = "sol-pi-axi verify";

/** Every mechanism off, so SoL-Pi itself notifies nothing at `session_start` but the signal. */
const ALL_OFF: SolPiConfig = {
	...DEFAULT_CONFIG,
	actionFusion: false,
	observationPack: false,
	evidencePreservingReducer: false,
	onlineContextCompact: false,
};

type Notification = readonly [message: string, level: string | undefined];

function recordingUi(notifications: Notification[]) {
	const noop = () => undefined;
	return {
		notify: (message: string, level?: string) => void notifications.push([message, level]),
		setStatus: noop,
		setWorkingMessage: noop,
		setWorkingVisible: noop,
		setWorkingIndicator: noop,
		setHiddenThinkingLabel: noop,
		setWidget: noop,
		setFooter: noop,
		setHeader: noop,
		setTitle: noop,
		onTerminalInput: () => noop,
		select: async () => undefined,
		confirm: async () => false,
		input: async () => undefined,
		editor: async () => undefined,
		custom: async () => undefined,
		pasteToEditor: noop,
		setEditorText: noop,
		getEditorText: () => "",
		getToolsExpanded: () => false,
		setToolsExpanded: noop,
	};
}

const savedEnv: Record<string, string | undefined> = {};
const tempDirs: string[] = [];

beforeEach(() => {
	for (const name of [VERIFY_ENV, AGENT_DIR_ENV]) savedEnv[name] = process.env[name];
	delete process.env[VERIFY_ENV];
});

afterEach(async () => {
	for (const [name, value] of Object.entries(savedEnv)) {
		if (value === undefined) delete process.env[name];
		else process.env[name] = value;
	}
	await Promise.all(tempDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

interface StartedSession {
	notifications: Notification[];
	errors: { event: string; error: string; extensionPath: string }[];
}

/**
 * Starts a real Pi AgentSession (faux model) with SoL-Pi loaded — from `extension` when given, else
 * from this checkout's `src/sol-pi/index.ts` through Pi's own extension loader — binds its extensions
 * in RPC mode (which emits `session_start`, as Pi's RPC mode does) and returns what SoL-Pi notified
 * and every extension error Pi reported.
 */
async function startSession(
	agentDir: string,
	cwd: string,
	options: { extension?: ExtensionFactory; notifications?: Notification[] } = {},
): Promise<StartedSession> {
	const faux = fauxProvider({ provider: "sol-pi-verify-signal", api: "sol-pi-verify-signal-api" });
	const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
	const resourceLoader = new DefaultResourceLoader({
		cwd,
		agentDir,
		settingsManager,
		additionalExtensionPaths: options.extension ? [] : [join(process.cwd(), "src/sol-pi/index.ts")],
		extensionFactories: [
			{ name: "verify-signal-faux-provider", factory: (pi) => pi.registerProvider(faux.provider) },
			...(options.extension ? [{ name: "verify-signal-sol-pi", factory: options.extension }] : []),
		],
		noExtensions: true,
		noSkills: true,
		noPromptTemplates: true,
		noThemes: true,
		noContextFiles: true,
		systemPrompt: "You are a deterministic load-signal test assistant.",
	});
	await resourceLoader.reload();
	expect(resourceLoader.getExtensions().errors).toEqual([]);
	const notifications = options.notifications ?? [];
	const errors: StartedSession["errors"] = [];
	let session: AgentSession | undefined;
	try {
		({ session } = await createAgentSession({
			cwd,
			agentDir,
			model: faux.getModel(),
			thinkingLevel: "off",
			resourceLoader,
			sessionManager: SessionManager.inMemory(cwd),
			settingsManager,
		}));
		await session.bindExtensions({
			mode: "rpc",
			uiContext: recordingUi(notifications) as never,
			onError: (error) => errors.push({ event: error.event, error: error.error, extensionPath: error.extensionPath }),
		});
		return { notifications, errors };
	} finally {
		session?.dispose();
	}
}

async function tempTree(): Promise<{ agentDir: string; cwd: string }> {
	const root = await mkdtemp(join(tmpdir(), "sol-pi-verify-signal-"));
	tempDirs.push(root);
	const agentDir = join(root, "agent");
	const cwd = join(root, "project");
	await mkdir(agentDir);
	await mkdir(cwd);
	return { agentDir, cwd };
}

/** SoL-Pi built with a configuration loader that records what had been notified when it ran. */
function recordingSolPi(notifications: Notification[], seenAtLoad: Notification[][]): ExtensionFactory {
	return createSolPiExtension(() => {
		seenAtLoad.push([...notifications]);
		return ALL_OFF;
	});
}

function signals(notifications: Notification[]): Notification[] {
	return notifications.filter(([message]) => message.startsWith(SIGNAL_PREFIX));
}

describe("SoL-Pi's load signal for sol-pi-axi verify", () => {
	it("notifies exactly 'sol-pi-axi verify n1' at info once when SOL_PI_AXI_VERIFY is n1", async () => {
		process.env[VERIFY_ENV] = "n1";
		const { agentDir, cwd } = await tempTree();
		const notifications: Notification[] = [];
		const seenAtLoad: Notification[][] = [];
		const { errors } = await startSession(agentDir, cwd, {
			extension: recordingSolPi(notifications, seenAtLoad),
			notifications,
		});
		expect(errors).toEqual([]);
		expect(signals(notifications)).toEqual([["sol-pi-axi verify n1", "info"]]);
		expect(notifications).toEqual([["sol-pi-axi verify n1", "info"]]);
	}, 30_000);

	it("notifies before it reads its configuration", async () => {
		process.env[VERIFY_ENV] = "n1";
		const { agentDir, cwd } = await tempTree();
		const notifications: Notification[] = [];
		const seenAtLoad: Notification[][] = [];
		await startSession(agentDir, cwd, { extension: recordingSolPi(notifications, seenAtLoad), notifications });
		// The configuration was read exactly once, and the signal had already been sent by then.
		expect(seenAtLoad).toEqual([[["sol-pi-axi verify n1", "info"]]]);
	}, 30_000);

	it("still notifies when the agent directory's sol-pi.json is invalid, and the configuration error follows", async () => {
		process.env[VERIFY_ENV] = "n1";
		const { agentDir, cwd } = await tempTree();
		await writeFile(join(agentDir, "sol-pi.json"), '{"version":2}\n');
		process.env[AGENT_DIR_ENV] = agentDir;
		const { notifications, errors } = await startSession(agentDir, cwd);
		expect(signals(notifications)).toEqual([["sol-pi-axi verify n1", "info"]]);
		// The invalid file still fails SoL-Pi's session_start, after the signal.
		expect(errors).toHaveLength(1);
		expect(errors[0]!.event).toBe("session_start");
		expect(errors[0]!.error).toContain("SoL-Pi config version must be 1");
		expect(errors[0]!.extensionPath).toEndWith(join("src", "sol-pi", "index.ts"));
	}, 30_000);

	it("carries the variable's value verbatim", async () => {
		process.env[VERIFY_ENV] = "run-7f3a 9";
		const { agentDir, cwd } = await tempTree();
		const notifications: Notification[] = [];
		await startSession(agentDir, cwd, { extension: recordingSolPi(notifications, []), notifications });
		expect(signals(notifications)).toEqual([["sol-pi-axi verify run-7f3a 9", "info"]]);
	}, 30_000);

	it("makes no such call when SOL_PI_AXI_VERIFY is unset", async () => {
		delete process.env[VERIFY_ENV];
		const { agentDir, cwd } = await tempTree();
		const notifications: Notification[] = [];
		const seenAtLoad: Notification[][] = [];
		await startSession(agentDir, cwd, { extension: recordingSolPi(notifications, seenAtLoad), notifications });
		// SoL-Pi was loaded and read its configuration, and called nothing extra.
		expect(seenAtLoad).toEqual([[]]);
		expect(notifications).toEqual([]);
	}, 30_000);

	it("makes no such call when SOL_PI_AXI_VERIFY is empty", async () => {
		process.env[VERIFY_ENV] = "";
		const { agentDir, cwd } = await tempTree();
		const notifications: Notification[] = [];
		const seenAtLoad: Notification[][] = [];
		await startSession(agentDir, cwd, { extension: recordingSolPi(notifications, seenAtLoad), notifications });
		expect(seenAtLoad).toEqual([[]]);
		expect(notifications).toEqual([]);
	}, 30_000);
});
