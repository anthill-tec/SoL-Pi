/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

/**
 * The `globalThis` slot `@gotgenes/pi-subagents` (25.0.5) publishes its service under. SoL-Pi reads
 * the slot without importing or depending on pi-subagents.
 */
const SUBAGENTS_SERVICE_SLOT = Symbol.for("@gotgenes/pi-subagents:service");

/** Answers whether any sub-agent is running or queued. */
export type SubagentsProbe = () => boolean;

/**
 * Reads the service in the slot now and returns a probe bound to that service. Child sessions
 * overwrite and later delete the slot, so the caller captures once and never reads the slot again.
 * There are two capture points: the packaged entry point calls this while it registers the features
 * during `session_start` (`registerConfiguredFeatures`), and Online Context Compact registered alone
 * calls it at its own first `session_start`.
 * With no service, or no `hasRunning` function, the probe reports no sub-agents. A `hasRunning()`
 * that throws or returns a non-boolean is treated as running, failing safe for the agents.
 */
export function captureSubagentsProbe(): SubagentsProbe {
	const service: unknown = (globalThis as Record<symbol, unknown>)[SUBAGENTS_SERVICE_SLOT];
	if (service === null || (typeof service !== "object" && typeof service !== "function")) return () => false;
	const hasRunning: unknown = (service as { readonly hasRunning?: unknown }).hasRunning;
	if (typeof hasRunning !== "function") return () => false;
	return () => {
		try {
			const running: unknown = hasRunning.call(service);
			return typeof running === "boolean" ? running : true;
		} catch {
			return true;
		}
	};
}
