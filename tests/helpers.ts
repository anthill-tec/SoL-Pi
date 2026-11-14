/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { Context } from "@earendil-works/pi-ai";
import {
	fauxAssistantMessage,
	fauxProvider,
	fauxText,
	fauxToolCall,
	type FauxResponseStep,
} from "@earendil-works/pi-ai/providers/faux";
import * as piCodingAgent from "@earendil-works/pi-coding-agent";
import {
	createAgentSession,
	createBashToolDefinition,
	DefaultResourceLoader,
	InteractiveMode,
	SessionManager as PiSessionManager,
	SettingsManager,
	type ExtensionAPI,
	type ExtensionContext,
	type ExtensionFactory,
	type SessionEntry,
	type SessionManager,
	type Theme,
	type ToolDefinition,
	type ToolResultEvent,
} from "@earendil-works/pi-coding-agent";
import type { Component } from "@earendil-works/pi-tui";
import { readFileSync } from "node:fs";
import { mkdir, mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Worker } from "node:worker_threads";

type Handler = (event: unknown, context: ExtensionContext) => unknown | Promise<unknown>;

export const plainTheme = {
	fg: (_color: string, text: string) => text,
	bg: (_color: string, text: string) => text,
	bold: (text: string) => text,
} as unknown as Theme;

export function componentText(component: Component, width = 120): string {
	return component
		.render(width)
		.map((line) => line.trimEnd())
		.join("\n");
}

/**
 * Minimal session manager stand-in: enough for extensions that only need a
 * session directory and an append-only custom-entry log.
 */
export class FakeSessionManager {
	readonly entries: SessionEntry[];
	readonly sessionDir: string;
	sessionId: string;
	sessionFile: string | undefined;
	leafId: string | null;
	private nextId = 1;

	constructor(entries: SessionEntry[] = [], sessionId = "session-a", sessionDir = tmpdir()) {
		this.entries = entries;
		this.sessionId = sessionId;
		this.sessionFile = join(sessionDir, `${sessionId}.jsonl`);
		this.sessionDir = sessionDir;
		this.leafId = entries.at(-1)?.id ?? null;
	}

	getSessionId(): string {
		return this.sessionId;
	}

	getSessionFile(): string | undefined {
		return this.sessionFile;
	}

	getSessionDir(): string {
		return this.sessionDir;
	}

	getLeafId(): string | null {
		return this.leafId;
	}

	getEntries(): SessionEntry[] {
		return this.entries;
	}

	getBranch(): SessionEntry[] {
		return this.entries;
	}

	appendCustomEntry(customType: string, data: unknown): string {
		const id = `custom-${this.nextId++}`;
		this.entries.push({
			type: "custom",
			id,
			parentId: this.leafId,
			timestamp: new Date().toISOString(),
			customType,
			data,
		});
		this.leafId = id;
		return id;
	}

	appendMessage(message: AgentMessage): string {
		const id = `message-${this.nextId++}`;
		this.entries.push({
			type: "message",
			id,
			parentId: this.leafId,
			timestamp: new Date().toISOString(),
			message,
		});
		this.leafId = id;
		return id;
	}

	/** Custom-entry payloads appended so far, in order. */
	customEntryData(): Record<string, unknown>[] {
		return this.entries.flatMap((entry) =>
			entry.type === "custom" && typeof entry.data === "object" && entry.data !== null
				? [entry.data as Record<string, unknown>]
				: [],
		);
	}
}

function isSystemMessage(message: AgentMessage): boolean {
	return (message as { role: string }).role === "system";
}

function sameMessages(left: readonly AgentMessage[], right: readonly AgentMessage[]): boolean {
	return left.length === right.length && left.every((message, index) => message === right[index]);
}

/** Simplified `getCurrentSystemMessage`: every system message folded into one. */
function collapseSystemMessages(messages: readonly AgentMessage[]): AgentMessage | undefined {
	const system = messages.filter(isSystemMessage) as unknown as Array<{ content: unknown; timestamp: number }>;
	if (system.length === 0) return undefined;
	return {
		role: "system",
		content: system.map((message) => (typeof message.content === "string" ? message.content : "")).join("\n\n"),
		timestamp: system[0]!.timestamp,
		collapsedFrom: system.length,
	} as unknown as AgentMessage;
}

/**
 * ExtensionAPI stand-in that records handlers and tools, so an extension can be
 * driven directly without a session, a provider, or the extension runner.
 */
export class FakePi {
	readonly handlers = new Map<string, Handler[]>();
	readonly registeredTools: ToolDefinition[] = [];
	readonly sentMessages: Array<{
		message: { customType: string; content: string; display: boolean; details?: unknown };
		options: { triggerTurn?: boolean; deliverAs?: "steer" | "followUp" | "nextTurn" } | undefined;
	}> = [];
	readonly sessionManager: FakeSessionManager;

	constructor(sessionManager: FakeSessionManager = new FakeSessionManager()) {
		this.sessionManager = sessionManager;
	}

	on(event: string, handler: unknown): void {
		const handlers = this.handlers.get(event) ?? [];
		handlers.push(handler as Handler);
		this.handlers.set(event, handlers);
	}

	registerTool(tool: ToolDefinition): void {
		this.registeredTools.push(tool);
	}

	appendEntry(customType: string, data?: unknown): void {
		this.sessionManager.appendCustomEntry(customType, data);
	}

	sendMessage(
		message: { customType: string; content: string; display: boolean; details?: unknown },
		options?: { triggerTurn?: boolean; deliverAs?: "steer" | "followUp" | "nextTurn" },
	): void {
		this.sentMessages.push({ message, options });
	}

	asExtensionApi(): ExtensionAPI {
		return this as unknown as ExtensionAPI;
	}

	tool(name: string): ToolDefinition {
		const tool = this.registeredTools.find((candidate) => candidate.name === name);
		if (!tool) throw new Error(`tool not registered: ${name}`);
		return tool;
	}

	/** Run every handler for one event and return the last defined result. */
	async emit(eventName: string, event: unknown, context: ExtensionContext): Promise<unknown> {
		let result: unknown;
		for (const handler of this.handlers.get(eventName) ?? []) {
			const current = await handler(event, context);
			if (current !== undefined) result = current;
		}
		return result;
	}

	/**
	 * Run the `context` handlers the way Pi 1.0's runner does: each handler sees
	 * a structured clone without system messages, may edit it in place or return
	 * a new list, and system messages stay at their indices only while the
	 * handler keeps every message object. Otherwise they collapse into one
	 * leading system message, as `restoreSystemMessages` does.
	 */
	async emitContext(messages: readonly AgentMessage[], context: ExtensionContext): Promise<AgentMessage[]> {
		let current = structuredClone(messages) as AgentMessage[];
		for (const handler of this.handlers.get("context") ?? []) {
			const visible = current.filter((message) => !isSystemMessage(message));
			const snapshot = visible.slice();
			const result = (await handler({ type: "context", messages: visible }, context)) as
				| { messages?: AgentMessage[] }
				| undefined;
			const returned = result?.messages ?? (sameMessages(visible, snapshot) ? undefined : visible);
			if (!returned || sameMessages(returned, snapshot)) continue;
			const head = collapseSystemMessages(current);
			current = head ? [head, ...returned] : returned;
		}
		return current;
	}
}

/**
 * The context Pi passes to tool `execute()`: `ExtensionContext` before Pi 0.99,
 * `ExtensionToolContext` (adds `tools` and `executeTool`) since then.
 */
export type ToolExecuteContext = Parameters<ToolDefinition["execute"]>[4];

/**
 * Tool-execution context over {@link fakeContext}. No other tools are callable:
 * `executeTool` reports every call as an unknown-tool error, as Pi does.
 */
export function fakeToolContext(
	sessionManager: FakeSessionManager | string,
	overrides: Record<string, unknown> = {},
): ToolExecuteContext {
	return {
		...(fakeContext(sessionManager) as unknown as Record<string, unknown>),
		tools: [],
		executeTool: async (name: string, args: unknown) => ({
			toolCall: { type: "toolCall", id: "fake/1", name, arguments: args ?? {} },
			result: { content: [{ type: "text", text: `Tool "${name}" is not available` }], details: undefined },
			isError: true,
		}),
		...overrides,
	} as unknown as ToolExecuteContext;
}

/*
 * Capability probes of the installed Pi. The suite's capability guards skip on what these report
 * missing, so it still runs against the older Pi the peer range admits; `pi-capabilities.test.ts`
 * asserts that the development dependency's Pi has every one of them.
 */

/** Pi 1.0 codemode; Pi 0.84.2 does not ship it. */
export const createCodemodeExtension = (piCodingAgent as unknown as Record<string, unknown>).createCodemodeExtension as
	| ((options: { mode: "on" | "only" }) => ExtensionFactory)
	| undefined;

/** Pi's session projection, edits applied; Pi 0.84.2 does not ship it. */
export const buildSessionProjection = (piCodingAgent as unknown as {
	buildSessionProjection?: (entries: SessionEntry[]) => { messages: AgentMessage[] };
}).buildSessionProjection;

/**
 * Pi 0.99 changed bash to return a non-zero exit as an `isError` result; 0.84
 * throws. Detected from the installed bash, not from a version string.
 */
export async function bashReturnsNonZeroExit(): Promise<boolean> {
	const bash = createBashToolDefinition(tmpdir(), { operations: { exec: async () => ({ exitCode: 7 }) } });
	try {
		await bash.execute("probe", { command: "exit 7" }, undefined, undefined, fakeToolContext(tmpdir(), { cwd: tmpdir() }));
		return true;
	} catch {
		return false;
	}
}

export function fakeContext(
	sessionManager: FakeSessionManager | string,
	overrides: Partial<ExtensionContext> = {},
): ExtensionContext {
	const manager =
		typeof sessionManager === "string" ? new FakeSessionManager([], "session-a", sessionManager) : sessionManager;
	return {
		mode: "json",
		hasUI: false,
		cwd: process.cwd(),
		sessionManager: manager,
		modelRegistry: {},
		model: undefined,
		scopedModels: [],
		ui: {},
		isIdle: () => false,
		isProjectTrusted: () => true,
		signal: undefined,
		abort: () => undefined,
		hasPendingMessages: () => false,
		shutdown: () => undefined,
		getContextUsage: () => undefined,
		compact: () => undefined,
		getSystemPrompt: () => "",
		...overrides,
	} as unknown as ExtensionContext;
}

/**
 * The installed Pi CLI entrypoint, read from the package's `pi` bin: `dist/bundle/cli.js` on Pi 1.x,
 * `dist/cli.js` on Pi 0.84.2.
 */
export function piCliPath(): string {
	const root = dirname(dirname(fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"))));
	const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as { bin?: string | Record<string, string> };
	const bin = typeof manifest.bin === "string" ? manifest.bin : manifest.bin?.pi;
	if (!bin) throw new Error("@earendil-works/pi-coding-agent declares no pi bin");
	return join(root, bin);
}

/** `Atomics.waitAsync` (ES2024, newer than the project's `lib`) as far as `realSleep` uses it. */
type WaitAsync = (
	typedArray: Int32Array,
	index: number,
	value: number,
	timeout: number,
) => { async: boolean; value: Promise<string> | string };

/**
 * Sleeps on real time until `milliseconds` pass or `cell` is notified. Bun's fake timers capture
 * every timer created while they are installed (even through a `setTimeout` captured earlier) and
 * freeze its clocks; an `Atomics.waitAsync` timeout is not a timer, so it elapses on real time.
 */
async function realSleep(cell: Int32Array, milliseconds: number): Promise<void> {
	const waitAsync = (Atomics as unknown as { waitAsync: WaitAsync }).waitAsync;
	const result = waitAsync(cell, 0, 0, milliseconds);
	if (result.async) await result.value;
}

export interface WaitForOptions {
	/** How long to keep calling the callback, in milliseconds (default 1000). */
	timeout?: number;
	/** How long to wait between calls, in milliseconds (default 50). */
	interval?: number;
}

/**
 * Vitest's waitFor contract: calls `callback` until it returns (or resolves) without
 * throwing, every `interval` ms for at most `timeout` ms, and resolves to its value; on timeout it
 * rejects with the callback's last error. A callback whose promise has not settled by the timeout
 * is not called again, and `waitFor` rejects at the timeout with its last error, else with
 * "Timed out in waitFor!". It polls on real time even while fake timers are installed.
 */
const TIMED_OUT: unique symbol = Symbol("waitFor timed out");

export async function waitFor<T>(
	callback: () => T | Promise<T>,
	options: WaitForOptions = {},
): Promise<T> {
	const timeout = options.timeout ?? 1_000;
	const interval = options.interval ?? 50;
	// The deadline is a real-time sleep of its own, since the clocks may be faked.
	const cell = new Int32Array(new SharedArrayBuffer(4));
	let timedOut = false;
	const deadline = realSleep(cell, timeout).then(() => {
		timedOut = true;
	});
	const deadlineReached = deadline.then((): typeof TIMED_OUT => TIMED_OUT);
	try {
		let lastError: unknown;
		for (;;) {
			try {
				// The deadline also ends a call whose promise never settles.
				const outcome: T | typeof TIMED_OUT = await Promise.race([callback(), deadlineReached]);
				if (outcome !== TIMED_OUT) return outcome;
			} catch (error) {
				lastError = error;
			}
			if (timedOut) throw lastError || new Error("Timed out in waitFor!");
			await Promise.race([realSleep(cell, interval), deadline]);
			if (timedOut) throw lastError;
		}
	} finally {
		// Release the deadline and any pending sleep on this call's cell.
		Atomics.notify(cell, 0);
	}
}

const workerExits: Promise<unknown>[] = [];
let originalTerminate: Worker["terminate"] | undefined;

/**
 * Records the exit of every worker thread terminated from now on. Pi counts each codemode worker
 * against a process-wide limit until the worker exits, which on Bun can come after the script's
 * result. `bun test` runs every file in one process, so a worker still exiting when a codemode test
 * ends would count against the next codemode test.
 */
export function trackWorkerExits(): void {
	if (originalTerminate) return;
	const terminate = Worker.prototype.terminate;
	originalTerminate = terminate;
	Worker.prototype.terminate = function (this: Worker) {
		const exited = terminate.call(this);
		workerExits.push(exited.catch(() => undefined));
		return exited;
	};
}

/** Waits until every worker terminated since `trackWorkerExits` has exited, then stops recording. */
export async function settleWorkerExits(): Promise<void> {
	while (workerExits.length > 0) await Promise.all(workerExits.splice(0));
	if (originalTerminate) Worker.prototype.terminate = originalTerminate;
	originalTerminate = undefined;
}

/** A file at the repository root (the test run's working directory), as text. */
export function rootFile(name: string): string {
	return readFileSync(join(process.cwd(), name), "utf8");
}

/** The text of a reducer request's user message. */
export function contextInput(context: Context): string {
	const message = context.messages[0];
	if (message?.role !== "user") throw new Error("reducer request omitted its user message");
	if (typeof message.content === "string") return message.content;
	return message.content.flatMap((item) => (item.type === "text" ? [item.text] : [])).join("\n");
}

/** The `source_sha256` a reducer request carries. */
export function sourceHash(input: string): string {
	const match = input.match(/source_sha256=([a-f0-9]{64})/u);
	if (!match?.[1]) throw new Error("request omitted source hash");
	return match[1];
}

/** One open plan step, the same step completed, and the progress reported with it. */
export const OPEN = [{ id: "build", goal: "build it", status: "in_progress" }] as const;
export const DONE = [{ id: "build", goal: "build it", status: "completed" }] as const;
export const PROGRESS = {
	files_changed: ["src/a.ts"],
	verification: ["tests passed"],
	decisions: ["kept the implementation small"],
};

/** Faux model turns that open the plan step and then complete it: one Online Context Compact boundary. */
export function boundaryResponses(ordinal: number, workText?: string): FauxResponseStep[] {
	const openPlan = fauxToolCall("update_plan", { steps: OPEN }, { id: `plan-open-${ordinal}` });
	return [
		fauxAssistantMessage(workText === undefined ? openPlan : [fauxText(workText), openPlan], { stopReason: "toolUse" }),
		fauxAssistantMessage(
			fauxToolCall("update_plan", { steps: DONE, progress: PROGRESS }, { id: `plan-done-${ordinal}` }),
			{ stopReason: "toolUse" },
		),
	];
}

/** The compaction entries on the session's current branch. */
export function compactions(sessionManager: SessionManager): number {
	return sessionManager.getBranch().filter((entry) => entry.type === "compaction").length;
}

export type Notification = readonly [message: string, level: string | undefined];

/** An extension UI that records every `notify` call and does nothing else. */
export function recordingUi(notifications: Notification[]) {
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

/** A failed `pytest -q` bash result carrying `body`, with any field replaced by `overrides`. */
export function bashEvent(body: string, overrides: Partial<ToolResultEvent> = {}): ToolResultEvent {
	return {
		type: "tool_result",
		toolName: "bash",
		toolCallId: "call-1",
		input: { command: "pytest -q" },
		content: [{ type: "text", text: body }],
		details: undefined,
		isError: true,
		...overrides,
	} as ToolResultEvent;
}

/** A new temporary directory named with `prefix`, recorded in `tracked` for the caller to remove. */
export async function createTempDir(prefix: string, tracked: string[]): Promise<string> {
	const dir = await mkdtemp(join(tmpdir(), prefix));
	tracked.push(dir);
	return dir;
}

/** One package's notes in Pi's "Extension Updates" startup view. */
export interface ExtensionChangelogUpdate {
	name: string;
	version: string;
	markdown: string;
}

/** What Pi's changelog step saw and did for an installed package on a fresh interactive launch. */
export interface ExtensionChangelogRun {
	/** The updates Pi's interactive mode shows under "Extension Updates". */
	updates: ExtensionChangelogUpdate[];
	/** The version Pi recorded as last seen for the package afterwards. */
	recorded: string | undefined;
	/** The extension load errors of the session's resource loader. */
	loadErrors: unknown[];
	/** Where Pi found the package's changelog; undefined when it found none. */
	changelogPath: string | undefined;
}

/**
 * Runs Pi's own extension changelog step (`InteractiveMode.getExtensionChangelogUpdates`, Pi 1.5.0+)
 * on a real session that has the package at `packageDir` installed as a user package, with
 * `lastSeen` as the version Pi last saw for it (undefined: Pi has never seen it). `workDir` is an
 * existing, caller-owned directory used as the session's working directory and agent directory root.
 */
export async function extensionChangelogUpdates(packageDir: string, lastSeen: string | undefined, workDir: string): Promise<ExtensionChangelogRun> {
	const cwd = workDir;
	const agentDir = join(workDir, "agent");
	await mkdir(agentDir, { recursive: true });
	const faux = fauxProvider({ provider: "sol-pi-changelog", api: "sol-pi-changelog-api" });
	const settingsManager = SettingsManager.inMemory(
		{ packages: [packageDir], compaction: { enabled: false }, retry: { enabled: false } },
		{ projectTrusted: true },
	);
	const key = JSON.stringify({ source: packageDir, scope: "user" });
	if (lastSeen) settingsManager.setExtensionChangelogVersion(key, lastSeen);
	const resourceLoader = new DefaultResourceLoader({
		cwd,
		agentDir,
		settingsManager,
		extensionFactories: [{ name: "changelog-test-provider", factory: (pi) => pi.registerProvider(faux.provider) }],
		noSkills: true,
		noPromptTemplates: true,
		noThemes: true,
		noContextFiles: true,
	});
	await resourceLoader.reload();
	const loaded = resourceLoader.getExtensions();
	const installed = loaded.extensions.find((extension) => extension.sourceInfo.origin === "package");
	const { session } = await createAgentSession({
		cwd,
		agentDir,
		model: faux.getModel(),
		thinkingLevel: "off",
		resourceLoader,
		sessionManager: PiSessionManager.inMemory(cwd),
		settingsManager,
	});
	try {
		// Pi's own startup step, run on this session as InteractiveMode runs it on a fresh launch. It is a
		// private step of InteractiveMode.init, whose only public path needs a TUI; docs/compatibility.md
		// records the coupling, and a Pi that renames or drops it fails here.
		const mode = InteractiveMode.prototype as unknown as {
			getExtensionChangelogUpdates?(this: unknown): ExtensionChangelogUpdate[];
			readPackageJson?: unknown;
		};
		if (typeof mode.getExtensionChangelogUpdates !== "function") throw new Error("Pi's InteractiveMode.init step getExtensionChangelogUpdates is missing");
		if (typeof mode.readPackageJson !== "function") throw new Error("Pi's InteractiveMode readPackageJson is missing");
		const updates = mode.getExtensionChangelogUpdates.call({ session, settingsManager, readPackageJson: mode.readPackageJson });
		return {
			updates,
			recorded: settingsManager.getExtensionChangelogVersion(key),
			loadErrors: loaded.errors,
			changelogPath: installed?.sourceInfo.changelogPath,
		};
	} finally {
		session.dispose();
	}
}

/** The text blocks of a provider-request message, joined; a string content as it is. */
export function wireText(message: { content?: unknown } | undefined): string {
	if (!message || !Array.isArray(message.content)) return typeof message?.content === "string" ? message.content : "";
	return (message.content as { type: string; text?: string }[])
		.flatMap((block) => (block.type === "text" && block.text !== undefined ? [block.text] : []))
		.join("\n");
}

export type DeclaredTool = { name: string; description?: string; parameters?: { properties?: Record<string, unknown> } };

/**
 * Tools declared to the model by Pi 1.0 tool-declaration system messages, after any loadout hook
 * hid some; with `contextTools`, `context.tools` first.
 */
export function declaredTools(context: unknown, { contextTools = false }: { contextTools?: boolean } = {}): DeclaredTool[] {
	const { messages = [], tools = [] } = context as { messages?: readonly unknown[]; tools?: readonly unknown[] };
	const declared = new Map<string, DeclaredTool>();
	if (contextTools) for (const tool of tools as readonly DeclaredTool[]) declared.set(tool.name, tool);
	for (const message of messages) {
		const system = message as {
			role?: string;
			toolsAdded?: readonly DeclaredTool[];
			toolsRemoved?: readonly (string | { name: string })[];
		};
		if (system.role !== "system") continue;
		for (const tool of system.toolsRemoved ?? []) declared.delete(typeof tool === "string" ? tool : tool.name);
		for (const tool of system.toolsAdded ?? []) declared.set(tool.name, tool);
	}
	return [...declared.values()];
}

/**
 * The Online Context Compact reminders on the session's current branch whose content is `content`;
 * with `display` given, only those with that display flag.
 */
export function reminders(sessionManager: SessionManager, content: string, display?: boolean): number {
	return sessionManager
		.getBranch()
		.filter(
			(entry) =>
				entry.type === "custom_message" &&
				entry.customType === "sol-pi-online-context-compact" &&
				entry.content === content &&
				(display === undefined || entry.display === display),
		).length;
}
