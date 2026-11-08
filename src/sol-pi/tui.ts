/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

import type { ExtensionContext, Theme } from "@earendil-works/pi-coding-agent";
import { type Component, Container, Text } from "@earendil-works/pi-tui";

export type SolPiTuiMechanism =
	| "Action Fusion"
	| "Observation Pack"
	| "Luna Delegating"
	| "Online Context Compact";

const STATUS_KEY = "sol-pi-savings";
const STATUS_DURATION_MS = 4_000;
const INTEGER_FORMAT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const statusTimers = new WeakMap<ExtensionContext["ui"], ReturnType<typeof setTimeout>>();

export function formatSavingsCount(value: number, unit: string): string {
	const count = Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
	return `${INTEGER_FORMAT.format(count)} ${unit}`;
}

function compactDecimal(value: number): string {
	return value.toFixed(1).replace(/\.0$/u, "");
}

export function formatSavingsBytes(value: number): string {
	const bytes = Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
	if (bytes >= 1024 * 1024) {
		return `${compactDecimal(bytes / (1024 * 1024))} MiB removed from future prompts`;
	}
	if (bytes >= 1024) return `${compactDecimal(bytes / 1024)} KiB removed from future prompts`;
	return `${INTEGER_FORMAT.format(bytes)} B removed from future prompts`;
}

export function renderSolPiTool(
	theme: Theme,
	mechanism: SolPiTuiMechanism,
	saving: string,
	base?: Component,
): Component {
	const container = new Container();
	const title = `${theme.fg("warning", "⚡")} ${theme.fg("accent", theme.bold(`SoL-Pi · ${mechanism}`))}`;
	container.addChild(new Text(title, 0, 0));
	container.addChild(new Text(theme.fg("success", `Money saved · ${saving}`), 0, 0));
	if (base) container.addChild(base);
	return container;
}

/**
 * Whether a tool call was made by another tool through `ctx.executeTool()`,
 * such as a codemode script, rather than by the model. Pi 0.99+ gives such
 * calls the id `<calling id>/<n>` (documented on `ExtensionToolContext`) and
 * passes no other marker to `execute()`. Provider-issued ids do not end in
 * `/<digits>`; a false match would only suppress a savings notice.
 */
export function isNestedToolCallId(toolCallId: string): boolean {
	return /\/\d+$/u.test(toolCallId);
}

export function showSolPiSavings(
	context: ExtensionContext,
	mechanism: SolPiTuiMechanism,
	saving: string,
): void {
	if (context.mode !== "tui") return;
	const ui = context.ui;
	const message = `⚡ SoL-Pi · ${mechanism}\nMoney saved · ${saving}`;
	ui.notify(message, "info");
	ui.setStatus(STATUS_KEY, `⚡ ${mechanism} · ${saving}`);

	const previous = statusTimers.get(ui);
	if (previous) clearTimeout(previous);
	const timer = setTimeout(() => {
		if (statusTimers.get(ui) !== timer) return;
		statusTimers.delete(ui);
		// Pi throws from `context.ui` itself, as well as from its methods, once the context is stale.
		ignoreStaleContext(() => context.ui.setStatus(STATUS_KEY, undefined));
	}, STATUS_DURATION_MS);
	if (typeof timer === "object" && "unref" in timer) timer.unref();
	statusTimers.set(ui, timer);
}

/**
 * Cancels the pending status clear `showSolPiSavings` armed for this context's UI. SoL-Pi calls it
 * at `session_shutdown`, so the timer never fires on a session that is gone.
 */
export function clearSolPiSavingsTimer(context: ExtensionContext): void {
	ignoreStaleContext(() => {
		const ui = context.ui;
		const timer = statusTimers.get(ui);
		if (!timer) return;
		clearTimeout(timer);
		statusTimers.delete(ui);
	});
}

/** The start of the error Pi throws from a context used after its session was replaced, reloaded or shut down. */
const STALE_CONTEXT_MESSAGE = "This extension ctx is stale";

/** Runs `action`; a stale-context error means the session is gone, so there is nothing to do. */
function ignoreStaleContext(action: () => void): void {
	try {
		action();
	} catch (error) {
		if (error instanceof Error && error.message.startsWith(STALE_CONTEXT_MESSAGE)) return;
		throw error;
	}
}
