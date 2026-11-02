/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";
import readline from "readline/promises";

/**
 * Queries available providers and models from the installed Pi instance.
 * Returns structured data suitable for interactive selection.
 */
export function queryPiModels() {
	const piConfig = join(homedir(), ".pi", "agent", "settings.json");

	if (!existsSync(piConfig)) {
		throw new Error("No Pi configuration found at ~/.pi/agent/settings.json");
	}

	try {
		const settings = JSON.parse(readFileSync(piConfig, "utf-8"));
		const providers = {};

		for (const modelId of settings.enabledModels || []) {
			const [provider, ...rest] = modelId.split("/");
			const modelName = rest.join("/");
			if (!providers[provider]) providers[provider] = [];
			providers[provider].push(modelName);
		}

		return {
			defaultProvider: settings.defaultProvider || null,
			defaultModel: settings.defaultModel || null,
			providers: Object.entries(providers).map(([id, models]) => ({
				id,
				name: id.split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" "),
				models: models.map((m) => ({ id: m })),
			})),
			totalModels: settings.enabledModels?.length || 0,
		};
	} catch (err) {
		throw new Error(`Failed to parse Pi settings: ${err.message}`);
	}
}

/**
 * Performs interactive provider/model selection.
 * Returns an object like: { providerId: "anthropic", modelId: "claude-opus-5-5" }
 */
export async function selectProviderAndModel() {
	const data = queryPiModels();

	if (!data.providers || data.providers.length === 0) {
		throw new Error("No providers found in Pi configuration");
	}

	const rl = readline.createInterface({
		input: process.stdin,
		output: process.stdout,
		prompt: "\n",
	});

	let selectedProvider = null;
	let selectedModel = null;

	try {
		// Show available providers
		console.log("\n══════════════════════════════════════════");
		console.log("  Available Pi Providers & Models");
		console.log("══════════════════════════════════════════\n");

		for (const [idx, provider] of data.providers.entries()) {
			const marker = (data.defaultProvider === provider.id && idx === 0) ? " ◀" : "";
			console.log(`  ${String(idx + 1).padEnd(2)}. ${provider.name} (${provider.models.length})${marker}`);
		}

		console.log();
		if (data.defaultProvider && data.defaultModel) {
			console.log(`  Default: ${data.defaultProvider}/${data.defaultModel}`);
		}
		console.log("\n──────────────────────────────────────────");
		console.log("  Select a provider (1-" + data.providers.length + ", or Enter for default):");
		console.log("──────────────────────────────────────────\n");

		const choice = (await rl.question("> ")).trim();
		
		if (!choice) {
			// Use first provider as default if available
			selectedProvider = data.providers[0]?.id;
		} else {
			const idx = parseInt(choice, 10);
			if (idx < 1 || idx > data.providers.length) {
				throw new Error(`Invalid selection: ${choice}. Enter a number between 1 and ${data.providers.length}`);
			}
			selectedProvider = data.providers[idx - 1].id;
		}

		const providerData = data.providers.find(p => p.id === selectedProvider);
		if (!providerData) {
			throw new Error(`No provider found with ID: ${selectedProvider}`);
		}

		console.log(`\n─── Selecting model for ${providerData.name} (or Enter for default: ${data.defaultModel}) ───`);
		console.log();
		
		for (const [idx, model] of providerData.models.entries()) {
			const marker = (model.id === data.defaultModel) ? " ◀" : "";
			console.log(`  ${String(idx + 1).padEnd(2)}. ${model.id}${marker}`);
		}

		console.log("\n──────────────────────────────────────────");
		console.log("  Model selection: ");
		console.log("──────────────────────────────────────────\n");

		const modelChoice = (await rl.question("> ")).trim();
		
		if (!modelChoice) {
			// Default to first model in selected provider or the global default
			selectedModel = data.defaultModel || providerData.models[0]?.id;
		} else {
			const idx = parseInt(modelChoice, 10);
			if (idx < 1 || idx > providerData.models.length) {
				throw new Error(`Invalid model selection: ${modelChoice}`);
			}
			selectedModel = providerData.models[idx - 1].id;
		}

		console.log("\n══════════════════════════════════════════");
		console.log("  Selection complete!");
		console.log("══════════════════════════════════════════");
		console.log(`\n  Provider : ${selectedProvider}`);
		console.log(`  Model    : ${selectedModel}`);
		console.log("\n");
	} finally {
		rl.close();
	}

	return { providerId: selectedProvider, modelId: selectedModel };
}

if (import.meta.main) {
	try {
		const selection = await selectProviderAndModel();
		console.log(`\n[selection]${JSON.stringify(selection)}`);
	} catch (err) {
		console.error(`Selection failed: ${err.message}`);
		process.exit(1);
	}
}
