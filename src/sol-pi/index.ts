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
import { clearSolPiSavingsTimer } from "./tui.ts";

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
	if (config.onlineContextCompact) registerOnlineContextCompact(pi, config.cacheWriteReadRatio);
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
