/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";
import { createRequire } from "node:module";

/*
 * Query the installed Pi instance for available providers and models.
 * Reads ~/.pi/agent/settings.json directly (the source of truth for enabled configs).
 * Outputs JSON suitable for parsing in shell scripts or other tools.
 *
 * Output format:
 * {
 *   "defaultProvider": "...",
 *   "defaultModel": "...",
 *   "providers": [
 *     { "id": "...", "name": "...", "models": [{ "id": "..." }, ...] }
 *   ],
 *   "totalModels": N
 * }
 */

function queryPiModels() {
	const piConfig = join(homedir(), ".pi", "agent", "settings.json");

	if (!existsSync(piConfig)) {
		console.error("Error: No Pi configuration found at ~/.pi/agent/settings.json");
		process.exit(1);
	}

	try {
		const settings = JSON.parse(readFileSync(piConfig, "utf-8"));
		const providers = {};

		for (const modelId of settings.enabledModels || []) {
			const [provider, ...rest] = modelId.split("/");
			const modelName = rest.join("/"); // handles nested like openrouter/openai/gpt-6-astra
			if (!providers[provider]) providers[provider] = [];
			providers[provider].push(modelName);
		}

		return {
			defaultProvider: settings.defaultProvider,
			defaultModel: settings.defaultModel || null,
			providers: Object.entries(providers)
				.map(([provider, models]) => ({
					id: provider,
					name:
						provider.split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ") ?? provider,
					models: models.map((m) => ({ id: m })),
				})),
			totalModels: settings.enabledModels?.length || 0,
		};
	} catch (err) {
		console.error(`Error parsing Pi settings: ${err.message}`);
		process.exit(1);
	}
}

export { queryPiModels };

// Export for use as CLI tool
if (import.meta.main) {
	// Interactive mode: only when run directly with TTY
	const isInteractive = process.stdin.isTTY && !process.argv.includes("--help");
	
	if (isInteractive) {
		console.error("ℹ Use --interactive flag for guided provider/model selection");
		console.error("ℹ Or pipe output to your own handler:");
		console.error("ℹ   node scripts/query-pi-models.mjs | jq '.providers[0].id'");
	} else {
		const result = queryPiModels();
		console.log(JSON.stringify(result, null, 2));
	}
}
