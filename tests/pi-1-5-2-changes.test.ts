/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */
/**
 * How SoL-Pi behaves on the Pi 1.5.1 and 1.5.2 changes reviewed in docs/compatibility.md (CR-SLP-012
 * §S3), through Pi on the development dependency:
 *
 * - Anthropic message threads: a real Pi session with SoL-Pi's packaged entry point loaded and every
 *   feature on, talking `anthropic-messages` with `compat.supportsMessageThreads` to a loopback
 *   recorder that answers Anthropic's streaming Messages API. The recorded request bodies show when Pi
 *   continues a thread and when SoL-Pi's changes to messages already sent (an Observation Pack
 *   replacement, a compaction) make Pi send the full request as a new thread.
 * - Package identity: Pi's DefaultPackageManager on a fabricated project and agent directory, with a
 *   local SoL-Pi checkout beside a user-level npm install, and the project entry that turns the npm
 *   copy off.
 */
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Api, Model } from "@earendil-works/pi-ai";
import {
	CONFIG_DIR_NAME,
	createAgentSession,
	DefaultPackageManager,
	DefaultResourceLoader,
	SessionManager,
	SettingsManager,
	type AgentSession,
	type ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import { afterEach, describe, expect, it } from "bun:test";
import { DEFAULT_CONFIG } from "../src/sol-pi/config.ts";
import { createObservation, FULL_SENDS, placeholderFor, THRESHOLD_BYTES } from "../src/sol-pi/extensions/observation-pack/index.ts";

const tempDirs: string[] = [];

async function tempDir(prefix: string): Promise<string> {
	const dir = await mkdtemp(join(tmpdir(), prefix));
	tempDirs.push(dir);
	return dir;
}

afterEach(async () => {
	await Promise.all(tempDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

// ---------------------------------------------------------------------------------------------------
// Message threads
// ---------------------------------------------------------------------------------------------------

const PROVIDER = "sol-pi-threads";
const MODEL_ID = "sol-pi-threads-model";

/** A reply the recorder streams back: assistant text, or one tool call. */
type Reply = { text: string } | { tool: { id: string; name: string; input: Record<string, unknown> } };

type AnthropicMessage = { role: string; content: unknown };

/** An Anthropic Messages request body as the recorder received it. */
interface RequestBody {
	model: string;
	system?: unknown;
	tools?: unknown[];
	messages: AnthropicMessage[];
	thread?: { type: string; previous_message_id?: string };
	[key: string]: unknown;
}

/**
 * A loopback HTTP server that answers Anthropic Messages streaming requests. It records every request
 * body and streams the next scripted reply; each reply's `message_start.message` carries the id
 * `msg_<n>` (n counts from 1) unless `replyIds` is off.
 */
class AnthropicRecorder {
	readonly bodies: RequestBody[] = [];
	private readonly replies: Reply[] = [];
	private server: Server | undefined;
	replyIds = true;

	script(...replies: Reply[]): void {
		this.replies.push(...replies);
	}

	async start(): Promise<string> {
		this.server = createServer((request, response) => {
			void this.answer(request, response);
		});
		await new Promise<void>((resolve) => this.server?.listen(0, "127.0.0.1", resolve));
		const { port } = this.server.address() as AddressInfo;
		return `http://127.0.0.1:${port}`;
	}

	async stop(): Promise<void> {
		const server = this.server;
		if (!server) return;
		server.closeAllConnections();
		await new Promise<void>((resolve) => server.close(() => resolve()));
	}

	private async answer(request: IncomingMessage, response: ServerResponse): Promise<void> {
		const chunks: Buffer[] = [];
		for await (const chunk of request) chunks.push(chunk as Buffer);
		let body: RequestBody;
		try {
			body = JSON.parse(Buffer.concat(chunks).toString("utf8")) as RequestBody;
		} catch (error) {
			// A request Pi sent that is not JSON fails the test through Pi's error, not a hung stream.
			response.writeHead(400, { "content-type": "application/json" });
			response.end(JSON.stringify({ type: "error", error: { type: "invalid_request_error", message: String(error) } }));
			return;
		}
		this.bodies.push(body);
		const ordinal = this.bodies.length;
		const reply = this.replies.shift() ?? { text: `unscripted reply ${ordinal}` };
		response.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
		for (const [event, data] of sseEvents(reply, body.model, this.replyIds ? `msg_${ordinal}` : undefined)) {
			response.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
		}
		response.end();
	}
}

/** The Anthropic streaming events of one reply. */
function sseEvents(reply: Reply, model: string, id: string | undefined): [string, unknown][] {
	const message: Record<string, unknown> = {
		type: "message",
		role: "assistant",
		model,
		content: [],
		stop_reason: null,
		stop_sequence: null,
		usage: { input_tokens: 10, output_tokens: 1 },
	};
	if (id !== undefined) message.id = id;
	const events: [string, unknown][] = [["message_start", { type: "message_start", message }]];
	if ("text" in reply) {
		events.push(
			["content_block_start", { type: "content_block_start", index: 0, content_block: { type: "text", text: "" } }],
			["content_block_delta", { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: reply.text } }],
			["content_block_stop", { type: "content_block_stop", index: 0 }],
		);
	} else {
		events.push(
			[
				"content_block_start",
				{ type: "content_block_start", index: 0, content_block: { type: "tool_use", id: reply.tool.id, name: reply.tool.name, input: {} } },
			],
			[
				"content_block_delta",
				{ type: "content_block_delta", index: 0, delta: { type: "input_json_delta", partial_json: JSON.stringify(reply.tool.input) } },
			],
			["content_block_stop", { type: "content_block_stop", index: 0 }],
		);
	}
	events.push(
		[
			"message_delta",
			{
				type: "message_delta",
				delta: { stop_reason: "text" in reply ? "end_turn" : "tool_use", stop_sequence: null },
				usage: { output_tokens: 5 },
			},
		],
		["message_stop", { type: "message_stop" }],
	);
	return events;
}

/** Every string inside a JSON value, depth first. */
function stringsIn(value: unknown): string[] {
	if (typeof value === "string") return [value];
	if (Array.isArray(value)) return value.flatMap(stringsIn);
	if (value !== null && typeof value === "object") return Object.values(value).flatMap(stringsIn);
	return [];
}

/** The tool_result blocks of a request's messages, by tool_use_id. */
function toolResultBlocks(messages: readonly AnthropicMessage[]): Map<string, unknown> {
	const blocks = new Map<string, unknown>();
	for (const message of messages) {
		if (!Array.isArray(message.content)) continue;
		for (const block of message.content as { type?: string; tool_use_id?: string; content?: unknown }[]) {
			if (block.type === "tool_result" && block.tool_use_id) blocks.set(block.tool_use_id, block.content);
		}
	}
	return blocks;
}

/** The text a recorded tool_result block carries. */
function toolResultText(content: unknown): string {
	return stringsIn(content).join("\n");
}

interface ThreadSession {
	session: AgentSession;
	recorder: AnthropicRecorder;
	/** The payloads a test extension's `before_provider_request` handler received, deep-copied, in order. */
	payloads: RequestBody[];
	cwd: string;
	errors: unknown[];
}

interface ThreadSessionOptions {
	supportsMessageThreads?: boolean;
	observationPack?: boolean;
}

/**
 * A real Pi session with SoL-Pi's packaged entry point loaded from this checkout and every feature on
 * (a trusted project sol-pi.json), on a provider registered with `api: "anthropic-messages"`,
 * `compat.supportsMessageThreads` and `baseUrl` at a loopback recorder. The in-memory session has an
 * id, and cache retention stays at Pi's default ("short").
 */
async function threadSession(recorder: AnthropicRecorder, options: ThreadSessionOptions = {}): Promise<ThreadSession> {
	const baseUrl = await recorder.start();
	const cwd = await tempDir("sol-pi-threads-");
	const agentDir = join(cwd, "agent");
	await mkdir(agentDir);
	await mkdir(join(cwd, CONFIG_DIR_NAME));
	await writeFile(
		join(cwd, CONFIG_DIR_NAME, "sol-pi.json"),
		JSON.stringify({
			...DEFAULT_CONFIG,
			actionFusion: true,
			observationPack: options.observationPack ?? true,
			evidencePreservingReducer: true,
			onlineContextCompact: true,
		}),
	);
	const compat = { supportsMessageThreads: options.supportsMessageThreads ?? true };
	const cost = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
	const model = {
		id: MODEL_ID,
		name: "SoL-Pi message threads recorder",
		api: "anthropic-messages",
		provider: PROVIDER,
		baseUrl,
		reasoning: false,
		input: ["text"],
		cost,
		contextWindow: 200_000,
		maxTokens: 4_096,
		compat,
	} as unknown as Model<Api>;
	const payloads: RequestBody[] = [];
	const providerFactory: ExtensionFactory = (pi) => {
		pi.registerProvider(PROVIDER, {
			baseUrl,
			apiKey: "sol-pi-threads-test-key",
			api: "anthropic-messages",
			models: [
				{
					id: MODEL_ID,
					name: "SoL-Pi message threads recorder",
					reasoning: false,
					input: ["text"],
					cost,
					contextWindow: 200_000,
					maxTokens: 4_096,
					compat: compat as never,
				},
			],
		});
	};
	const payloadFactory: ExtensionFactory = (pi) => {
		pi.on("before_provider_request", (event) => {
			payloads.push(structuredClone(event.payload) as RequestBody);
			return undefined;
		});
	};
	const settingsManager = SettingsManager.inMemory(
		{ compaction: { enabled: false, keepRecentTokens: 1 }, retry: { enabled: false } },
		{ projectTrusted: true },
	);
	const resourceLoader = new DefaultResourceLoader({
		cwd,
		agentDir,
		settingsManager,
		additionalExtensionPaths: [join(process.cwd(), "src/sol-pi/index.ts")],
		extensionFactories: [
			{ name: "message-threads-test-provider", factory: providerFactory },
			{ name: "message-threads-test-payloads", factory: payloadFactory },
		],
		noExtensions: true,
		noSkills: true,
		noPromptTemplates: true,
		noThemes: true,
		noContextFiles: true,
		systemPrompt: "You are a deterministic message-thread test assistant.",
	});
	await resourceLoader.reload();
	expect(resourceLoader.getExtensions().errors).toEqual([]);
	const sessionManager = SessionManager.inMemory(cwd);
	expect(sessionManager.getSessionId()).toMatch(/\S/u);
	const { session } = await createAgentSession({
		cwd,
		agentDir,
		model,
		thinkingLevel: "off",
		resourceLoader,
		sessionManager,
		settingsManager,
	});
	const errors: unknown[] = [];
	await session.bindExtensions({ onError: (error) => errors.push(error) });
	return { session, recorder, payloads, cwd, errors };
}

/** The tool results the session stored, by tool call id, as the text Observation Pack measures. */
function storedToolResults(session: AgentSession) {
	const results = new Map<string, { toolCallId: string; toolName: string; content: { type: string; text?: string }[]; isError: boolean }>();
	for (const entry of session.sessionManager.getBranch()) {
		if (entry.type === "message" && entry.message.role === "toolResult") {
			const message = entry.message as unknown as { toolCallId: string; toolName: string; content: { type: string; text?: string }[]; isError: boolean };
			results.set(message.toolCallId, message);
		}
	}
	return results;
}

describe("Pi 1.5.1 Anthropic message threads with SoL-Pi loaded", () => {
	const sessions: AgentSession[] = [];
	const recorders: AnthropicRecorder[] = [];

	afterEach(async () => {
		for (const session of sessions.splice(0)) session.dispose();
		await Promise.all(recorders.splice(0).map((recorder) => recorder.stop()));
	});

	async function open(options: ThreadSessionOptions = {}): Promise<ThreadSession> {
		const recorder = new AnthropicRecorder();
		recorders.push(recorder);
		const opened = await threadSession(recorder, options);
		sessions.push(opened.session);
		return opened;
	}

	it("continues the thread with only the messages added after the first reply when earlier messages are unchanged", async () => {
		const { session, recorder, cwd, errors } = await open();
		await writeFile(join(cwd, "small.txt"), "a small file\n");
		recorder.script({ tool: { id: "toolu_small", name: "read", input: { path: "small.txt" } } }, { text: "read it" });

		await session.prompt("read small.txt", { expandPromptTemplates: false });

		expect(errors).toEqual([]);
		expect(session.getLastAssistantText()).toBe("read it");
		expect(recorder.bodies).toHaveLength(2);
		const [first, second] = recorder.bodies as [RequestBody, RequestBody];
		expect(first.thread).toEqual({ type: "create" });
		expect(first.messages).toHaveLength(1);
		// The second request continues the first reply's thread, without system and tools, and carries
		// only the tool result that followed the reply.
		expect(second.thread).toEqual({ type: "continue", previous_message_id: "msg_1" });
		expect(second.system).toBeUndefined();
		expect(second.tools).toBeUndefined();
		expect(second.messages).toHaveLength(1);
		expect(second.messages[0]?.role).toBe("user");
		expect([...toolResultBlocks(second.messages).keys()]).toEqual(["toolu_small"]);
		expect(toolResultText(toolResultBlocks(second.messages).get("toolu_small"))).toContain("a small file");
	}, 60_000);

	it("sends a large tool result in full as often as Observation Pack does, then starts a new thread that carries only its replacement", async () => {
		const { session, recorder, payloads, cwd, errors } = await open();
		expect(FULL_SENDS).toBe(2);
		const lines = Array.from({ length: 240 }, (_, index) => `line ${String(index).padStart(3, "0")} ${"x".repeat(80)}`);
		lines[120] = "MIDDLE-OF-THE-LARGE-RESULT-7f3a";
		await writeFile(join(cwd, "large.txt"), `${lines.join("\n")}\n`);
		await writeFile(join(cwd, "one.txt"), "first small file\n");
		await writeFile(join(cwd, "two.txt"), "second small file\n");
		recorder.script(
			{ tool: { id: "toolu_large", name: "read", input: { path: "large.txt" } } },
			{ tool: { id: "toolu_one", name: "read", input: { path: "one.txt" } } },
			{ tool: { id: "toolu_two", name: "read", input: { path: "two.txt" } } },
			{ text: "all read" },
		);

		await session.prompt("read the files", { expandPromptTemplates: false });

		expect(errors).toEqual([]);
		expect(session.getLastAssistantText()).toBe("all read");
		expect(recorder.bodies).toHaveLength(4);
		expect(payloads).toHaveLength(4);
		const stored = storedToolResults(session).get("toolu_large");
		expect(stored).toBeDefined();
		const original = (stored?.content ?? []).map((block) => block.text ?? "").join("\n");
		expect(Buffer.byteLength(original, "utf8")).toBeGreaterThan(THRESHOLD_BYTES);
		const observation = createObservation(stored as never, cwd);
		expect(observation).toBeDefined();
		const replacement = placeholderFor(observation as NonNullable<typeof observation>);

		// Observation Pack sends the result in full on its first FULL_SENDS requests (2 and 3), and the
		// replacement from the request after them (4).
		const largeIn = (body: RequestBody) => toolResultText(toolResultBlocks(body.messages).get("toolu_large"));
		expect(largeIn(payloads[1] as RequestBody)).toBe(original);
		expect(largeIn(payloads[2] as RequestBody)).toBe(original);
		expect(largeIn(payloads[3] as RequestBody)).toBe(replacement);

		const [first, second, third, fourth] = recorder.bodies as [RequestBody, RequestBody, RequestBody, RequestBody];
		expect(first.thread).toEqual({ type: "create" });
		// Until the replacement every request continues the thread; the full result crosses the wire once.
		expect(second.thread).toEqual({ type: "continue", previous_message_id: "msg_1" });
		expect(largeIn(second)).toBe(original);
		expect(third.thread).toEqual({ type: "continue", previous_message_id: "msg_2" });
		expect(toolResultBlocks(third.messages).has("toolu_large")).toBe(false);
		// The replacement changes a message already sent: a new thread with every message.
		expect(fourth.thread).toEqual({ type: "create" });
		expect(fourth.system).toEqual(first.system);
		expect(fourth.tools).toEqual(first.tools);
		expect(fourth.messages.map((message) => message.role)).toEqual(["user", "assistant", "user", "assistant", "user", "assistant", "user"]);
		expect([...toolResultBlocks(fourth.messages).keys()]).toEqual(["toolu_large", "toolu_one", "toolu_two"]);
		expect(largeIn(fourth)).toBe(replacement);
		const fourthText = stringsIn(fourth.messages).join("\n");
		expect(fourthText).not.toContain(original);
		expect(fourthText).not.toContain("MIDDLE-OF-THE-LARGE-RESULT-7f3a");
	}, 60_000);

	it("starts a new thread on the first request after a compaction of the session", async () => {
		const { session, recorder, errors } = await open();
		recorder.script({ text: "first answer" }, { text: "second answer" });
		await session.prompt("first question", { expandPromptTemplates: false });
		await session.prompt("second question", { expandPromptTemplates: false });
		expect(recorder.bodies).toHaveLength(2);
		// Before the compaction the conversation continues its thread.
		expect(recorder.bodies[1]?.thread).toEqual({ type: "continue", previous_message_id: "msg_1" });

		recorder.script({ text: "## Goal\nCompacted summary of the earlier questions." });
		await session.compact();
		const afterCompaction = recorder.bodies.length;
		recorder.script({ text: "third answer" });
		await session.prompt("third question", { expandPromptTemplates: false });

		expect(errors).toEqual([]);
		expect(session.getLastAssistantText()).toBe("third answer");
		expect(recorder.bodies).toHaveLength(afterCompaction + 1);
		const next = recorder.bodies.at(-1) as RequestBody;
		expect(stringsIn(next.messages).join("\n")).toContain("third question");
		expect(next.thread).toEqual({ type: "create" });
		expect(next.system).toBeDefined();
		expect(next.tools).toBeDefined();
	}, 60_000);

	it("gives a before_provider_request handler system, tools and every message on a request sent as a continue", async () => {
		const { session, recorder, payloads, cwd, errors } = await open();
		await writeFile(join(cwd, "small.txt"), "a small file\n");
		recorder.script({ tool: { id: "toolu_small", name: "read", input: { path: "small.txt" } } }, { text: "read it" });

		await session.prompt("read small.txt", { expandPromptTemplates: false });

		expect(errors).toEqual([]);
		expect(recorder.bodies).toHaveLength(2);
		expect(payloads).toHaveLength(2);
		const [first, second] = recorder.bodies as [RequestBody, RequestBody];
		expect(second.thread?.type).toBe("continue");
		const payload = payloads[1] as RequestBody;
		// The handler saw the full request Pi built, not the continuation it sent.
		expect(payload.thread).toBeUndefined();
		expect(payload.system).toEqual(first.system);
		expect(payload.system).toBeDefined();
		expect(Array.isArray(payload.tools) && payload.tools.length > 0).toBe(true);
		expect(payload.tools).toEqual(first.tools);
		expect(payload.messages.map((message) => message.role)).toEqual(["user", "assistant", "user"]);
		expect(stringsIn(payload.messages[0]).join("\n")).toContain("read small.txt");
		expect([...toolResultBlocks(payload.messages).keys()]).toEqual(["toolu_small"]);
		// The continuation is the tail of what the handler received.
		expect(payload.messages.slice(-second.messages.length)).toEqual(second.messages);
	}, 60_000);
});

// ---------------------------------------------------------------------------------------------------
// Package identity
// ---------------------------------------------------------------------------------------------------

const NPM_SOURCE = "npm:@anthill-tec/sol-pi";
const ENTRY_POINT = join("src", "sol-pi", "index.ts");
/** The project entry from docs/compatibility.md that turns a user-level npm SoL-Pi off. */
const PROJECT_ENTRY = { source: NPM_SOURCE, autoload: false, extensions: ["-src/sol-pi/index.ts"] };

/** A copy of this checkout's SoL-Pi package (manifest and src/) at `dir`. */
async function solPiCopy(dir: string): Promise<string> {
	await mkdir(dir, { recursive: true });
	await cp(join(process.cwd(), "src"), join(dir, "src"), { recursive: true });
	await writeFile(join(dir, "package.json"), await readFile(join(process.cwd(), "package.json"), "utf8"));
	return dir;
}

interface IdentityLayout {
	cwd: string;
	agentDir: string;
	checkout: string;
	npmInstall: string;
}

/**
 * A fabricated project at `<root>/project` whose `.pi/settings.json` names a SoL-Pi checkout at
 * `<root>/SoL-Pi` by a `..` path (plus `projectEntry` when given), and an agent dir at `<root>/agent`
 * whose settings name the npm SoL-Pi and hold its install at `npm/node_modules/@anthill-tec/sol-pi`
 * when `userNpm` is on.
 */
async function identityLayout(projectEntry: boolean, userNpm: boolean): Promise<IdentityLayout> {
	const root = await tempDir("sol-pi-identity-");
	const cwd = join(root, "project");
	const agentDir = join(root, "agent");
	const checkout = await solPiCopy(join(root, "SoL-Pi"));
	const npmInstall = join(agentDir, "npm", "node_modules", "@anthill-tec", "sol-pi");
	await mkdir(join(cwd, CONFIG_DIR_NAME), { recursive: true });
	await mkdir(agentDir, { recursive: true });
	const projectPackages: unknown[] = ["../../SoL-Pi"];
	if (projectEntry) projectPackages.push(PROJECT_ENTRY);
	await writeFile(join(cwd, CONFIG_DIR_NAME, "settings.json"), JSON.stringify({ packages: projectPackages }, null, 2));
	if (userNpm) {
		await solPiCopy(npmInstall);
		await writeFile(join(agentDir, "settings.json"), JSON.stringify({ packages: [NPM_SOURCE] }, null, 2));
	}
	return { cwd, agentDir, checkout, npmInstall };
}

/** The SoL-Pi entry points Pi's package manager resolves for the layout, and the sources it asked to install. */
async function resolveSolPi(layout: IdentityLayout) {
	const settingsManager = SettingsManager.create(layout.cwd, layout.agentDir, { projectTrusted: true });
	const packageManager = new DefaultPackageManager({ cwd: layout.cwd, agentDir: layout.agentDir, settingsManager });
	const missing: string[] = [];
	const offline = process.env.PI_OFFLINE;
	// PI_OFFLINE in the environment would skip the missing-package callback; "0" is Pi's "not offline".
	if (offline !== undefined) process.env.PI_OFFLINE = "0";
	try {
		const resolved = await packageManager.resolve(async (source) => {
			missing.push(source);
			return "skip";
		});
		const entries = resolved.extensions
			.filter((resource) => resource.path.endsWith(ENTRY_POINT))
			.map((resource) => ({ path: resource.path, enabled: resource.enabled }));
		return { entries, missing };
	} finally {
		if (offline !== undefined) process.env.PI_OFFLINE = offline;
	}
}

describe("Pi package identity: a local SoL-Pi checkout beside a user-level npm install", () => {
	it("enables both SoL-Pi entry points when the project has no entry for the npm package", async () => {
		const layout = await identityLayout(false, true);
		const { entries, missing } = await resolveSolPi(layout);

		expect(missing).toEqual([]);
		expect(entries).toHaveLength(2);
		expect(entries).toContainEqual({ path: join(layout.checkout, ENTRY_POINT), enabled: true });
		expect(entries).toContainEqual({ path: join(layout.npmInstall, ENTRY_POINT), enabled: true });
	});

	it("enables only the local checkout's entry point and disables the npm one with the project entry", async () => {
		const layout = await identityLayout(true, true);
		const { entries, missing } = await resolveSolPi(layout);

		expect(missing).toEqual([]);
		expect(entries).toHaveLength(2);
		expect(entries).toContainEqual({ path: join(layout.checkout, ENTRY_POINT), enabled: true });
		expect(entries).toContainEqual({ path: join(layout.npmInstall, ENTRY_POINT), enabled: false });
		expect(entries.filter((entry) => entry.enabled)).toEqual([{ path: join(layout.checkout, ENTRY_POINT), enabled: true }]);
	});

	it("asks to install npm:@anthill-tec/sol-pi when the project entry has no user-level npm SoL-Pi to turn off", async () => {
		const layout = await identityLayout(true, false);
		const { entries, missing } = await resolveSolPi(layout);

		expect(missing).toEqual([NPM_SOURCE]);
		// The skipped install leaves only the local checkout.
		expect(entries).toEqual([{ path: join(layout.checkout, ENTRY_POINT), enabled: true }]);
	});
});
