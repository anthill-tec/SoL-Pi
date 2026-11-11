/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

import { getAgentDir, type BashToolOptions, type ExtensionAPI, type ExtensionContext, type ExtensionFactory } from "@earendil-works/pi-coding-agent";
import { loadSolPiConfig, type SolPiConfig } from "./config.ts";
import { createActionFusionExtension } from "./extensions/action-fusion/index.ts";
import { loadActionFusionBashOptions } from "./shell-options.ts";
import { registerEvidencePreservingReducer } from "./extensions/evidence-preserving-reducer/index.ts";
import { registerObservationPack } from "./extensions/observation-pack/index.ts";
import { registerOnlineContextCompact } from "./extensions/online-context-compact/index.ts";
import { captureSubagentsProbe } from "./extensions/online-context-compact/subagents.ts";
import { clearSolPiSavingsTimer } from "./tui.ts";

/**
 * Registers the features the configuration enables. The packaged entry point calls this inside its
 * first session_start handler, because the configuration needs that event's context. Pi delivers an
 * event to the handlers registered when the delivery began, so a session_start handler a feature
 * registers here misses the first session_start. Whatever a feature must do at that event is done
 * here and handed to the feature.
 */
export function registerConfiguredFeatures(
	pi: ExtensionAPI,
	config: SolPiConfig,
	bashOptions?: BashToolOptions,
): void {
	if (config.actionFusion) createActionFusionExtension({ bashOptions })(pi);
	if (config.observationPack) registerObservationPack(pi);
	if (config.evidencePreservingReducer) {
		registerEvidencePreservingReducer(pi, {
			reducerModel: config.evidencePreservingReducerModel,
			reducerProvider: config.evidencePreservingReducerProvider,
		});
	}
	// Online Context Compact binds the pi-subagents service at session_start. Its own handler misses
	// the first one (see above), so the service is captured here, and only when the feature is enabled.
	if (config.onlineContextCompact) {
		registerOnlineContextCompact(pi, config.cacheWriteReadRatio, captureSubagentsProbe());
	}
}

export type SolPiConfigLoader = (ctx: ExtensionContext) => SolPiConfig;

export function createSolPiExtension(
	loadConfig: SolPiConfigLoader = (ctx) => loadSolPiConfig(ctx.cwd, getAgentDir(), ctx.isProjectTrusted()),
): ExtensionFactory {
	return (pi) => {
		let initialized = false;
		pi.on("session_start", (_event, ctx) => {
			if (initialized) return;
			initialized = true;
			// The load signal sol-pi-axi verify waits for: sent first, so it reaches the check even when
			// the configuration below is invalid.
			const verifyValue = process.env.SOL_PI_AXI_VERIFY;
			if (verifyValue) ctx.ui.notify(`sol-pi-axi verify ${verifyValue}`, "info");
			const config = loadConfig(ctx);
			const bashOptions = config.actionFusion
				? loadActionFusionBashOptions(ctx.cwd, ctx.isProjectTrusted())
				: undefined;
			registerConfiguredFeatures(pi, config, bashOptions);
		});
		// Whatever features are enabled, a savings status timer never outlives its session.
		pi.on("session_shutdown", (_event, ctx) => {
			clearSolPiSavingsTimer(ctx);
		});
	};
}

export default function solPiExtension(pi: ExtensionAPI): void {
	createSolPiExtension()(pi);
}
