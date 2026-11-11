/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
	createAgentSession,
	DefaultResourceLoader,
	SessionManager,
	SettingsManager,
	type AgentSession,
	type ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import {
	fauxAssistantMessage,
	fauxProvider,
	type FauxResponseStep,
} from "@earendil-works/pi-ai/providers/faux";
import { afterEach, beforeEach, describe, expect, it, vi } from "bun:test";
import {
	BOUNDARY_COMPACTION_INSTRUCTIONS,
	createOnlineContextCompactExtension,
	POST_COMPACTION_PLAN_REMINDER,
} from "../src/sol-pi/extensions/online-context-compact/extension.ts";
import { DEFAULT_CONFIG } from "../src/sol-pi/config.ts";
import { createSolPiExtension } from "../src/sol-pi/index.ts";
import { boundaryResponses, compactions, recordingUi, reminders, waitFor, type Notification } from "./helpers.ts";

/** Where `@gotgenes/pi-subagents` 25.0.5 publishes its service (`publishSubagentsService`). */
const SUBAGENTS_SERVICE_SLOT = Symbol.for("@gotgenes/pi-subagents:service");
const DEFERRED_ENTRY = "sol-pi-online-context-compact-deferred";
const DEFERRED_NOTICE = "Online compaction deferred: sub-agents are running";

const COMPACTION = { enabled: false, keepRecentTokens: 150, reserveTokens: 1_024 };

/** One way Online Context Compact reaches a session. Every scenario runs under each. */
type Registration = {
	/** The factory's name, shown in every test's name. */
	readonly name: string;
	/** Keeps the faux provider's names apart between registrations. */
	readonly id: string;
	readonly register: ExtensionFactory;
};
const REGISTRATIONS: readonly Registration[] = [
	{
		name: "createOnlineContextCompactExtension",
		id: "occ",
		register: (pi) =>
			createOnlineContextCompactExtension({ cacheWriteReadRatio: 0, keepRecentTokens: COMPACTION.keepRecentTokens })(pi),
	},
	{
		// The packaged entry point: it registers the features inside its first session_start, and
		// keepRecentTokens comes from the session's compaction settings.
		name: "createSolPiExtension",
		id: "solpi",
		register: (pi) =>
			createSolPiExtension(() => ({ ...DEFAULT_CONFIG, onlineContextCompact: true, cacheWriteReadRatio: 0 }))(pi),
	},
];

/** Pi's run mode as `bindExtensions` takes it (the package does not export `ExtensionMode`). */
type ExtensionMode = NonNullable<Parameters<AgentSession["bindExtensions"]>[0]["mode"]>;
type Slot = Record<symbol, unknown>;
const slot = globalThis as unknown as Slot;

function publishService(service: unknown): void {
	slot[SUBAGENTS_SERVICE_SLOT] = service;
}

function clearServiceSlot(): void {
	delete slot[SUBAGENTS_SERVICE_SLOT];
}

/** A stand-in for pi-subagents' published service: only the surface SoL-Pi may probe, plus abortAll. */
function fakeService(hasRunning: () => unknown) {
	return { hasRunning: vi.fn(hasRunning), abortAll: vi.fn(() => 0) };
}

/**
 * pi-subagents' `InterruptHandler`: latches the run's abort signal at every `turn_start` (deduped by
 * reference, re-wired for a new run's signal) and counts how often it fires.
 */
function interruptListener() {
	const probe = { fired: 0, latched: 0 };
	const factory: ExtensionFactory = (pi) => {
		let latched: AbortSignal | undefined;
		let detach: (() => void) | undefined;
		pi.on("turn_start", (_event, context) => {
			const signal = context.signal;
			if (signal === latched) return;
			detach?.();
			detach = undefined;
			latched = signal;
			if (!signal) return;
			probe.latched++;
			const onAbort = (): void => {
				probe.fired++;
			};
			signal.addEventListener("abort", onAbort, { once: true });
			detach = () => signal.removeEventListener("abort", onAbort);
		});
	};
	return { probe, factory };
}

type ScenarioOptions = {
	readonly name: string;
	readonly responses: FauxResponseStep[];
	readonly mode?: ExtensionMode;
	/** Large history makes the completed step's economics favour a boundary compaction. */
	readonly history?: boolean;
	readonly extensions?: ExtensionFactory[];
	/** Runs after the session is created and before its session_start. */
	readonly beforeSessionStart?: () => void;
	/** Runs after session_start and before the prompt. */
	readonly afterSessionStart?: (session: AgentSession) => void | Promise<void>;
};
type ScenarioRun = {
	readonly session: AgentSession;
	readonly sessionManager: SessionManager;
	readonly faux: ReturnType<typeof fauxProvider>;
	readonly extensionErrors: string[];
	readonly compactionRequests: { customInstructions?: string; reason: string }[];
	readonly stopReasons: string[];
	readonly notifications: Notification[];
	readonly settledCount: () => number;
};

/**
 * Runs Online Context Compact, registered by `registration`, in a real AgentSession (faux model)
 * bound in `mode`, then prompts once.
 */
async function runScenario(
	registration: Registration,
	options: ScenarioOptions,
	body: (run: ScenarioRun) => Promise<void>,
): Promise<void> {
	const scenario = `${registration.id}-${options.name}`;
	const cwd = await mkdtemp(join(tmpdir(), "sol-pi-occ-subagents-"));
	const agentDir = join(cwd, "agent");
	await mkdir(agentDir);

	let session: AgentSession | undefined;
	try {
		const faux = fauxProvider({
			provider: `sol-pi-occ-subagents-${scenario}`,
			api: `sol-pi-occ-subagents-api-${scenario}`,
			models: [{ id: `sol-pi-occ-subagents-model-${scenario}`, contextWindow: 4_096, maxTokens: 1_024 }],
		});
		faux.setResponses(options.responses);

		const compactionRequests: { customInstructions?: string; reason: string }[] = [];
		const recorder: ExtensionFactory = (pi) => {
			pi.on("session_before_compact", (event) => {
				compactionRequests.push({ customInstructions: event.customInstructions, reason: event.reason });
			});
		};
		const extension: ExtensionFactory = (pi) => {
			pi.registerProvider(faux.provider);
			registration.register(pi);
			pi.on("session_before_compact", (event) => ({
				compaction: {
					summary: `deterministic compacted history ${"s".repeat(6_000)}`,
					firstKeptEntryId: event.preparation.firstKeptEntryId,
					tokensBefore: event.preparation.tokensBefore,
				},
			}));
		};

		const settingsManager = SettingsManager.inMemory({ compaction: COMPACTION, retry: { enabled: false } });
		const sessionManager = SessionManager.inMemory(cwd);
		if (options.history ?? true) {
			sessionManager.appendMessage({
				role: "user",
				content: [{ type: "text", text: `historical request ${"x".repeat(6_000)}` }],
				timestamp: Date.now() - 2,
			});
			sessionManager.appendMessage(fauxAssistantMessage(`historical response ${"y".repeat(6_000)}`));
		}
		const resourceLoader = new DefaultResourceLoader({
			cwd,
			agentDir,
			settingsManager,
			extensionFactories: [
				{ name: `occ-subagents-recorder-${scenario}`, factory: recorder },
				{ name: `occ-subagents-session-test-${scenario}`, factory: extension },
				...(options.extensions ?? []).map((factory, index) => ({ name: `occ-subagents-extra-${scenario}-${index}`, factory })),
			],
			noExtensions: true,
			noSkills: true,
			noPromptTemplates: true,
			noThemes: true,
			noContextFiles: true,
			systemPrompt: "You are a deterministic lifecycle test assistant.",
		});
		await resourceLoader.reload();
		expect(resourceLoader.getExtensions().errors).toEqual([]);

		const created = await createAgentSession({
			cwd,
			agentDir,
			model: faux.getModel(),
			thinkingLevel: "off",
			tools: ["update_plan"],
			resourceLoader,
			sessionManager,
			settingsManager,
		});
		session = created.session;
		const extensionErrors: string[] = [];
		const notifications: Notification[] = [];
		options.beforeSessionStart?.();
		// Binding emits session_start, as Pi's interactive, print and RPC modes do.
		await session.bindExtensions({
			mode: options.mode ?? "print",
			uiContext: recordingUi(notifications) as never,
			onError: (error) => extensionErrors.push(`${error.event}: ${error.error}`),
		});
		await options.afterSessionStart?.(session);

		let settledCount = 0;
		const stopReasons: string[] = [];
		session.subscribe((event) => {
			if (event.type === "agent_settled") settledCount++;
			if (event.type === "message_end" && event.message.role === "assistant") {
				stopReasons.push(event.message.stopReason);
			}
		});

		await session.prompt("finish the current plan step", { expandPromptTemplates: false, source: "interactive" });

		await body({
			session,
			sessionManager,
			faux,
			extensionErrors,
			compactionRequests,
			stopReasons,
			notifications,
			settledCount: () => settledCount,
		});
		expect(session.isStreaming).toBe(false);
		expect(session.isIdle).toBe(true);
	} finally {
		session?.dispose();
		await rm(cwd, { recursive: true, force: true });
	}
}

/** One completed step whose economics favour compaction, then the model's final reply. */
function singleBoundary(finalReply: string): FauxResponseStep[] {
	return [...boundaryResponses(1), fauxAssistantMessage(finalReply)];
}

function deferredEntries(sessionManager: SessionManager): Record<string, unknown>[] {
	return sessionManager
		.getEntries()
		.flatMap((entry) =>
			entry.type === "custom" && entry.customType === DEFERRED_ENTRY ? [entry.data as Record<string, unknown>] : [],
		);
}

/** The step completion ran in-turn: no stop, no compaction, one deferred entry for step "build". */
function expectDeferredStep(run: ScenarioRun, finalReply: string): void {
	expect(run.extensionErrors).toEqual([]);
	expect(run.stopReasons).not.toContain("aborted");
	expect(run.stopReasons).toEqual(["toolUse", "toolUse", "stop"]);
	expect(run.compactionRequests).toEqual([]);
	expect(compactions(run.sessionManager)).toBe(0);
	expect(reminders(run.sessionManager, POST_COMPACTION_PLAN_REMINDER)).toBe(0);
	const deferred = deferredEntries(run.sessionManager);
	expect(deferred).toHaveLength(1);
	// Exactly the completed plan step's id (not the update_plan tool call id) and the reason.
	expect(deferred[0]).toEqual({ stepId: "build", reason: "subagents-running" });
	expect(run.faux.state.callCount).toBe(3);
	expect(run.session.getLastAssistantText()).toBe(finalReply);
	expect(run.settledCount()).toBe(1);
}

/** The step completion compacted exactly as Online Context Compact does without sub-agents. */
function expectCompactedStep(run: ScenarioRun, finalReply: string): void {
	expect(run.extensionErrors).toEqual([]);
	expect(run.compactionRequests).toEqual([{ customInstructions: BOUNDARY_COMPACTION_INSTRUCTIONS, reason: "manual" }]);
	expect(compactions(run.sessionManager)).toBe(1);
	expect(reminders(run.sessionManager, POST_COMPACTION_PLAN_REMINDER)).toBe(1);
	expect(deferredEntries(run.sessionManager)).toEqual([]);
	expect(run.faux.state.callCount).toBe(3);
	expect(run.session.getLastAssistantText()).toBe(finalReply);
	expect(run.settledCount()).toBe(2);
}

for (const registration of REGISTRATIONS) describe(`Online Context Compact with running pi-subagents agents, registered by ${registration.name}`, () => {
	beforeEach(clearServiceSlot);
	afterEach(clearServiceSlot);

	/** Names the registration in the test's own name, so a failure says which registration broke. */
	const under = (behaviour: string): string => `${behaviour} (registered by ${registration.name})`;
	const withScenario = (options: ScenarioOptions, body: (run: ScenarioRun) => Promise<void>): Promise<void> =>
		runScenario(registration, options, body);

	it(under("defers a favourable boundary compaction without stopping the turn while hasRunning() is true"), async () => {
		const service = fakeService(() => true);
		await withScenario(
			{
				name: "defer-running",
				responses: singleBoundary("final while agents run"),
				beforeSessionStart: () => publishService(service),
			},
			async (run) => {
				expectDeferredStep(run, "final while agents run");
				expect(service.hasRunning).toHaveBeenCalledTimes(1);
				expect(service.abortAll).not.toHaveBeenCalled();
			},
		);
	}, 10_000);

	it(under("does not fire a turn_start abort-signal listener at a deferred step, while a later session.abort() still fires it"), async () => {
		const service = fakeService(() => true);
		const { probe, factory } = interruptListener();
		const waitForAbort: FauxResponseStep = async (_context, options) => {
			await new Promise<void>((resolve) => {
				const signal = options?.signal;
				if (!signal || signal.aborted) return resolve();
				signal.addEventListener("abort", () => resolve(), { once: true });
				setTimeout(resolve, 5_000);
			});
			return fauxAssistantMessage("later run was not interrupted");
		};
		await withScenario(
			{
				name: "listener",
				responses: [...singleBoundary("final before the later run"), waitForAbort],
				extensions: [factory],
				beforeSessionStart: () => publishService(service),
			},
			async (run) => {
				expect(run.extensionErrors).toEqual([]);
				// pi-subagents would have called abortAll() had the signal fired.
				expect(probe.fired).toBe(0);
				expect(probe.latched).toBe(1);
				expect(deferredEntries(run.sessionManager)).toHaveLength(1);

				const later = run.session.prompt("keep going", { expandPromptTemplates: false, source: "interactive" });
				await waitFor(() => {
					expect(probe.latched).toBe(2);
					expect(run.faux.state.callCount).toBe(4);
				}, { timeout: 3_000 });
				await run.session.abort();
				await later;
				// The user's abort reaches the listener latched for the later run.
				expect(probe.fired).toBe(1);
				expect(run.faux.state.callCount).toBe(4);
			},
		);
	}, 10_000);

	for (const after of ["replaced by a service that is not running", "deleted"] as const) {
		it(under(`keeps the service captured at session_start when the slot is ${after} afterwards`), async () => {
			const captured = fakeService(() => true);
			const replacement = fakeService(() => false);
			await withScenario(
				{
					name: `capture-${after === "deleted" ? "deleted" : "replaced"}`,
					responses: singleBoundary("final with the captured service"),
					beforeSessionStart: () => publishService(captured),
					afterSessionStart: () => {
						if (after === "deleted") clearServiceSlot();
						else publishService(replacement);
					},
				},
				async (run) => {
					expectDeferredStep(run, "final with the captured service");
					expect(captured.hasRunning).toHaveBeenCalledTimes(1);
					expect(replacement.hasRunning).not.toHaveBeenCalled();
				},
			);
		}, 10_000);
	}

	it(under("keeps service A and never probes service B when a second session_start reaches the same extension instance"), async () => {
		const first = fakeService(() => true);
		const second = fakeService(() => false);
		const sessionStarts: string[] = [];
		await withScenario(
			{
				name: "second-session-start",
				responses: singleBoundary("final after a second session_start"),
				extensions: [
					(pi) => {
						pi.on("session_start", (event) => {
							sessionStarts.push(event.reason);
						});
					},
				],
				beforeSessionStart: () => publishService(first),
				afterSessionStart: async (session) => {
					publishService(second);
					// The session's own runner: the same extension instances that saw the first session_start.
					await session.extensionRunner.emit({ type: "session_start", reason: "resume" });
				},
			},
			async (run) => {
				expect(sessionStarts).toEqual(["startup", "resume"]);
				expectDeferredStep(run, "final after a second session_start");
				expect(first.hasRunning).toHaveBeenCalledTimes(1);
				expect(second.hasRunning).not.toHaveBeenCalled();
				expect(second.abortAll).not.toHaveBeenCalled();
			},
		);
	}, 10_000);

	it(under("compacts and never probes a running service published after session_start when the slot was empty at session_start"), async () => {
		const late = fakeService(() => true);
		await withScenario(
			{
				name: "late-service",
				responses: singleBoundary("final with a late service"),
				afterSessionStart: () => publishService(late),
			},
			async (run) => {
				// The slot still holds the late service at the decision: nothing reads it there.
				expect(slot[SUBAGENTS_SERVICE_SLOT]).toBe(late);
				expectCompactedStep(run, "final with a late service");
				expect(late.hasRunning).not.toHaveBeenCalled();
				expect(late.abortAll).not.toHaveBeenCalled();
			},
		);
	}, 10_000);

	it(under("records no deferral and shows no notice when the step's economics do not compact"), async () => {
		const service = fakeService(() => true);
		await withScenario(
			{
				name: "uneconomic",
				mode: "tui",
				history: false,
				responses: singleBoundary("final without compaction"),
				beforeSessionStart: () => publishService(service),
			},
			async (run) => {
				expect(run.extensionErrors).toEqual([]);
				expect(run.compactionRequests).toEqual([]);
				expect(compactions(run.sessionManager)).toBe(0);
				expect(deferredEntries(run.sessionManager)).toEqual([]);
				expect(run.notifications).toEqual([]);
				expect(service.hasRunning).not.toHaveBeenCalled();
				expect(run.stopReasons).toEqual(["toolUse", "toolUse", "stop"]);
				expect(run.session.getLastAssistantText()).toBe("final without compaction");
			},
		);
	}, 10_000);

	it(under("compacts the step completion unchanged when no service is in the slot at session_start"), async () => {
		await withScenario({ name: "no-service", responses: singleBoundary("final without a service") }, async (run) => {
			expectCompactedStep(run, "final without a service");
		});
	}, 10_000);

	it(under("compacts the step completion unchanged when the captured service has no hasRunning function"), async () => {
		await withScenario(
			{
				name: "no-probe",
				responses: singleBoundary("final without a probe"),
				beforeSessionStart: () => publishService({ hasRunning: true, abortAll: () => 0 }),
			},
			async (run) => {
				expectCompactedStep(run, "final without a probe");
			},
		);
	}, 10_000);

	it(under("compacts the step completion unchanged when hasRunning() is false"), async () => {
		const service = fakeService(() => false);
		await withScenario(
			{
				name: "idle-service",
				responses: singleBoundary("final with idle agents"),
				beforeSessionStart: () => publishService(service),
			},
			async (run) => {
				expectCompactedStep(run, "final with idle agents");
				// Probed once, after the economic decision to compact.
				expect(service.hasRunning).toHaveBeenCalledTimes(1);
				expect(service.abortAll).not.toHaveBeenCalled();
			},
		);
	}, 10_000);

	const unsafeProbes: readonly (readonly [label: string, hasRunning: () => unknown])[] = [
		["throws", () => {
			throw new Error("sub-agent registry unavailable");
		}],
		["returns the number 1", () => 1],
		["returns the string \"false\"", () => "false"],
		["returns undefined", () => undefined],
		["returns null", () => null],
	];
	for (const [label, hasRunning] of unsafeProbes) {
		it(under(`defers the compaction when hasRunning() ${label}`), async () => {
			const service = fakeService(hasRunning);
			await withScenario(
				{
					name: `unsafe-${label.replace(/\W+/gu, "-")}`,
					responses: singleBoundary(`final when hasRunning ${label}`),
					beforeSessionStart: () => publishService(service),
				},
				async (run) => {
					expectDeferredStep(run, `final when hasRunning ${label}`);
					expect(service.hasRunning).toHaveBeenCalledTimes(1);
				},
			);
		}, 10_000);
	}

	it(under("compacts at the next step completion once hasRunning() is false after a deferral"), async () => {
		let running = true;
		const service = fakeService(() => running);
		const [open2, done2] = boundaryResponses(2, `second phase work ${"z".repeat(6_000)}`);
		const agentsFinished: FauxResponseStep = async (context, options, state, model) => {
			running = false;
			return typeof open2 === "function" ? await open2(context, options, state, model) : open2!;
		};
		await withScenario(
			{
				name: "next-safe-point",
				responses: [...boundaryResponses(1), agentsFinished, done2!, fauxAssistantMessage("final after the later compaction")],
				beforeSessionStart: () => publishService(service),
			},
			async (run) => {
				expect(run.extensionErrors).toEqual([]);
				expect(deferredEntries(run.sessionManager)).toHaveLength(1);
				expect(run.compactionRequests).toEqual([{ customInstructions: BOUNDARY_COMPACTION_INSTRUCTIONS, reason: "manual" }]);
				expect(compactions(run.sessionManager)).toBe(1);
				expect(reminders(run.sessionManager, POST_COMPACTION_PLAN_REMINDER)).toBe(1);
				expect(service.hasRunning).toHaveBeenCalledTimes(2);
				expect(run.faux.state.callCount).toBe(5);
				expect(run.session.getLastAssistantText()).toBe("final after the later compaction");
				expect(run.settledCount()).toBe(2);
			},
		);
	}, 10_000);

	it(under("notifies once in tui mode with the deferral notice at level info"), async () => {
		await withScenario(
			{
				name: "notice-tui",
				mode: "tui",
				responses: singleBoundary("final with a tui notice"),
				beforeSessionStart: () => publishService(fakeService(() => true)),
			},
			async (run) => {
				expectDeferredStep(run, "final with a tui notice");
				expect(run.notifications).toEqual([[DEFERRED_NOTICE, "info"]]);
			},
		);
	}, 10_000);

	for (const mode of ["print", "json", "rpc"] as const) {
		it(under(`shows no deferral notice in ${mode} mode`), async () => {
			await withScenario(
				{
					name: `notice-${mode}`,
					mode,
					responses: singleBoundary(`final in ${mode} mode`),
					beforeSessionStart: () => publishService(fakeService(() => true)),
				},
				async (run) => {
					expectDeferredStep(run, `final in ${mode} mode`);
					expect(run.notifications).toEqual([]);
				},
			);
		}, 10_000);
	}
});
