/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { AssistantMessage, Context, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { describe, expect, it, vi } from "bun:test";
import { DEFAULT_CONFIG } from "../src/sol-pi/config.ts";
import { REDUCER_RECEIPT_SCHEMA } from "../src/sol-pi/extensions/evidence-preserving-reducer/index.ts";
import { createSolPiExtension, registerConfiguredFeatures } from "../src/sol-pi/index.ts";
import { bashEvent, contextInput, FakePi, fakeContext, sourceHash } from "./helpers.ts";

const CUSTOM_REDUCER = {
	id: "configured-reducer-model",
	name: "configured reducer model",
	api: "openai-responses",
	provider: "configured-provider",
	baseUrl: "https://example.invalid/v1",
	reasoning: true,
	input: ["text"],
	cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
	contextWindow: 32_768,
	maxTokens: 4_096,
} satisfies Model<"openai-responses">;

/** Where `@gotgenes/pi-subagents` 25.0.5 publishes its service; Online Context Compact's probe reads it. */
const SUBAGENTS_SERVICE_SLOT = Symbol.for("@gotgenes/pi-subagents:service");

/**
 * Puts a getter on the slot that counts every read and answers with a running service, runs `body`,
 * then removes the getter so no other test sees it.
 */
async function withObservedSlot(body: (slotReads: ReturnType<typeof vi.fn>) => void | Promise<void>): Promise<void> {
	const service = { hasRunning: () => true, abortAll: () => 0 };
	const slotReads = vi.fn(() => service);
	Object.defineProperty(globalThis, SUBAGENTS_SERVICE_SLOT, { configurable: true, get: slotReads });
	try {
		await body(slotReads);
	} finally {
		delete (globalThis as Record<symbol, unknown>)[SUBAGENTS_SERVICE_SLOT];
	}
}

describe("SoL-Pi entrypoint", () => {
	it("registers no tools or events when every feature is disabled", () => {
		const pi = new FakePi();
		registerConfiguredFeatures(pi.asExtensionApi(), DEFAULT_CONFIG);
		expect(pi.registeredTools).toEqual([]);
		expect(pi.handlers.size).toBe(0);
	});

	it("registers all four standalone mechanisms from one config", () => {
		const pi = new FakePi();
		registerConfiguredFeatures(pi.asExtensionApi(), {
			...DEFAULT_CONFIG,
			actionFusion: true,
			observationPack: true,
			evidencePreservingReducer: true,
			onlineContextCompact: true,
		});

		expect(pi.registeredTools.map((tool) => tool.name)).toEqual(["edit", "write", "obs_recall", "update_plan"]);
		expect([...pi.handlers.keys()].sort()).toEqual([
			"agent_settled",
			"before_provider_request",
			"context",
			"input",
			"message_end",
			"session_before_compact",
			"session_before_tree",
			"session_compact",
			"session_shutdown",
			"session_start",
			"session_tree",
			"tool_result",
			"turn_end",
		]);
	});

	const withoutOnlineContextCompact = [
		["every feature is disabled", DEFAULT_CONFIG, []],
		[
			"Online Context Compact is disabled and every other feature is enabled",
			{ ...DEFAULT_CONFIG, actionFusion: true, observationPack: true, evidencePreservingReducer: true },
			["edit", "write", "obs_recall"],
		],
	] as const;
	for (const [label, config, tools] of withoutOnlineContextCompact) {
		it(`does not read the pi-subagents service slot when ${label}`, async () => {
			await withObservedSlot((slotReads) => {
				const pi = new FakePi();
				registerConfiguredFeatures(pi.asExtensionApi(), config);

				expect(pi.registeredTools.map((tool) => tool.name)).toEqual([...tools]);
				expect(slotReads).not.toHaveBeenCalled();
			});
			expect(Object.getOwnPropertyDescriptor(globalThis, SUBAGENTS_SERVICE_SLOT)).toBeUndefined();
		});
	}

	it("reads the pi-subagents service slot exactly once while registering an enabled Online Context Compact, and not again at session_start", async () => {
		await withObservedSlot(async (slotReads) => {
			const pi = new FakePi();
			registerConfiguredFeatures(pi.asExtensionApi(), { ...DEFAULT_CONFIG, onlineContextCompact: true });

			expect(pi.registeredTools.map((tool) => tool.name)).toEqual(["update_plan"]);
			// Captured while the features are registered, which the entry point does inside session_start.
			expect(slotReads).toHaveBeenCalledTimes(1);

			const ctx = fakeContext(pi.sessionManager);
			await pi.emit("session_start", { type: "session_start" }, ctx);
			await pi.emit("session_start", { type: "session_start" }, ctx);
			// Online Context Compact keeps the probe it was given: a later session_start reads nothing.
			expect(slotReads).toHaveBeenCalledTimes(1);
		});
		expect(Object.getOwnPropertyDescriptor(globalThis, SUBAGENTS_SERVICE_SLOT)).toBeUndefined();
	});

	it("waits for a trusted session context and initializes once", async () => {
		const pi = new FakePi();
		const loader = vi.fn(() => ({ ...DEFAULT_CONFIG, observationPack: true }));
		createSolPiExtension(loader)(pi.asExtensionApi());
		expect([...pi.handlers.keys()]).toEqual(["session_start", "session_shutdown"]);

		const ctx = fakeContext(pi.sessionManager);
		await pi.emit("session_start", { type: "session_start" }, ctx);
		await pi.emit("session_start", { type: "session_start" }, ctx);

		expect(loader).toHaveBeenCalledOnce();
		expect(pi.registeredTools.map((tool) => tool.name)).toEqual(["obs_recall"]);
		expect([...pi.handlers.keys()].sort()).toEqual(["context", "session_shutdown", "session_start"]);
	});

	it("passes the configured reducer provider/model route into EPR", async () => {
		const root = mkdtempSync(join(tmpdir(), "sol-pi-configured-epr-"));
		try {
			const pi = new FakePi();
			registerConfiguredFeatures(pi.asExtensionApi(), {
				...DEFAULT_CONFIG,
				evidencePreservingReducer: true,
				evidencePreservingReducerProvider: CUSTOM_REDUCER.provider,
				evidencePreservingReducerModel: CUSTOM_REDUCER.id,
			});
			const body = `ERROR configured reducer failure\n${"diagnostic line\n".repeat(360)}`;
			let calledModel: Model<string> | undefined;
			const context = fakeContext(root, {
				modelRegistry: {
					find: (provider: string, modelId: string) =>
						provider === CUSTOM_REDUCER.provider && modelId === CUSTOM_REDUCER.id ? CUSTOM_REDUCER : undefined,
					complete: async (model: Model<string>, request: Context): Promise<AssistantMessage> => {
						calledModel = model;
						const input = contextInput(request);
						return {
							role: "assistant",
							content: [
								{
									type: "text",
									text: JSON.stringify({
										schema: REDUCER_RECEIPT_SCHEMA,
										source_sha256: sourceHash(input),
										status: "failure",
										uncertain: false,
										evidence: [{ kind: "failure", quote: "ERROR configured reducer failure" }],
									}),
								},
							],
							api: model.api,
							provider: model.provider,
							model: model.id,
							usage: {
								input: 10,
								output: 10,
								cacheRead: 0,
								cacheWrite: 0,
								totalTokens: 20,
								cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
							},
							stopReason: "stop",
							timestamp: Date.now(),
						};
					},
				} as unknown as ExtensionContext["modelRegistry"],
			});

			const result = (await pi.emit("tool_result", bashEvent(body, { toolCallId: "call-configured-reducer" }), context)) as {
				content: { type: string; text: string }[];
			};

			expect(calledModel).toBe(CUSTOM_REDUCER);
			expect(result.content[0]?.text ?? "").toContain(`reducer_model=${CUSTOM_REDUCER.id}`);
			expect(result.content[0]?.text ?? "").toContain(`reducer_provider=${CUSTOM_REDUCER.provider}`);
		} finally {
			rmSync(root, { recursive: true, force: true });
		}
	});
});
