/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */
/*
 * Shared support for the Action Fusion suites only. It imports production code, so it lives apart
 * from `tests/helpers.ts`: a broken Action Fusion export then fails these suites alone.
 */
import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";
import {
	createActionFusionExtension,
	type ActionFusionOptions,
} from "../src/sol-pi/extensions/action-fusion/index.ts";

/** The fused `edit` and `write` tools Action Fusion registers with `options`. */
export function loadFusedTools(options?: ActionFusionOptions): { edit: ToolDefinition; write: ToolDefinition } {
	const registered = new Map<string, ToolDefinition>();
	const pi = {
		registerTool: (tool: ToolDefinition) => registered.set(tool.name, tool),
	} as unknown as ExtensionAPI;
	createActionFusionExtension(options)(pi);
	const edit = registered.get("edit");
	const write = registered.get("write");
	if (!edit || !write) throw new Error("action fusion did not register edit and write");
	return { edit, write };
}
