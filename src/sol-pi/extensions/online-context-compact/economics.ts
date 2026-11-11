/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */

export type CompactionEconomics = {
	readonly remainingRequestScale: number;
	readonly remainingRequestStddevK: number;
	readonly windowReserveTokens: number;
	readonly firstCompactionRequestScale: number;
	readonly subsequentCompactionMargin: number;
	/** Minimum provider requests since the last compaction before economics may compact again. */
	readonly minimumRequestsSinceCompaction: number;
};

export const DEFAULT_COMPACTION_ECONOMICS: CompactionEconomics = Object.freeze({
	remainingRequestScale: 1,
	remainingRequestStddevK: 0,
	windowReserveTokens: 16_384,
	firstCompactionRequestScale: 2,
	subsequentCompactionMargin: 1.5,
	minimumRequestsSinceCompaction: 2,
});

export type CompactionReason =
	| "economic"
	| "window_protection"
	| "deferred_economic"
	| "deferred_subsequent_margin"
	| "deferred_carried_debt"
	| "deferred_post_compaction_cooldown"
	| "horizon_unavailable"
	| "cache_ratio_unavailable"
	| "native_not_compactable"
	| "non_positive_saving";

export type RequestHorizonEstimate = {
	readonly completedBoundaryRequestCounts: readonly number[];
	readonly requestsPerBoundaryMean: number;
	readonly requestsPerBoundaryLowerBound: number;
	readonly unboundedExpectedRemainingRequests: number;
	readonly averageContextTokenIncrement: number | null;
	readonly windowRequestUpperBound: number | null;
	readonly expectedRemainingRequests: number;
};

export type CompactionDecision = {
	readonly writeTokens: number;
	readonly archiveTokens: number;
	readonly memoTokens: number;
	/** Estimated context written after compaction, including the replacement memo. */
	readonly postCompactionTokens: number;
	readonly contextTokens: number;
	readonly completedBoundaryRequestCounts: readonly number[] | null;
	readonly requestsPerBoundaryMean: number | null;
	readonly requestsPerBoundaryLowerBound: number | null;
	readonly unboundedExpectedRemainingRequests: number | null;
	readonly averageContextTokenIncrement: number | null;
	readonly windowRequestUpperBound: number | null;
	readonly expectedRemainingRequests: number | null;
	readonly breakevenRequests: number | null;
	readonly combinedBreakevenRequests: number | null;
	readonly effectiveHorizonRequests: number | null;
	readonly cacheWriteReadRatio: number | null;
	readonly incrementalCacheCostRatio: number | null;
	readonly priorCompactionCount: number;
	readonly requestsSinceLastCompaction: number | null;
	readonly carriedDebtTokens: number;
	readonly cacheDebtRepaymentTokens: number;
	readonly compact: boolean;
	readonly reason: CompactionReason;
};

const MINIMUM_VARIANCE_SAMPLES = 3;
const SMALL_SAMPLE_SCALE = 0.5;

export function estimateRemainingRequests(input: {
	readonly completedBoundaryRequestCounts: readonly number[];
	readonly remainingBoundaries: number;
	readonly scale: number;
	readonly standardDeviationK: number;
	readonly contextTokens: number;
	readonly contextWindowTokens: number | null;
	readonly averageContextTokenIncrement: number | null;
}): RequestHorizonEstimate {
	const mean =
		input.completedBoundaryRequestCounts.reduce((total, count) => total + count, 0) /
		Math.max(1, input.completedBoundaryRequestCounts.length);
	let lowerBound = mean;
	if (input.standardDeviationK !== 0) {
		if (input.completedBoundaryRequestCounts.length < MINIMUM_VARIANCE_SAMPLES) {
			lowerBound *= SMALL_SAMPLE_SCALE;
		} else {
			const variance = input.completedBoundaryRequestCounts.reduce(
				(total, count) => total + (count - mean) ** 2,
				0,
			);
			const deviation = Math.sqrt(variance / (input.completedBoundaryRequestCounts.length - 1));
			lowerBound = Math.max(0, mean - input.standardDeviationK * deviation);
		}
	}

	const unboundedExpectedRemainingRequests =
		1 + Math.floor(lowerBound * Math.max(0, input.remainingBoundaries) * input.scale);
	const windowRequestUpperBound =
		input.contextWindowTokens === null ||
		input.averageContextTokenIncrement === null ||
		input.averageContextTokenIncrement <= 0
			? null
			: Math.max(
					0,
					Math.floor((input.contextWindowTokens - input.contextTokens) / input.averageContextTokenIncrement),
				);

	return {
		completedBoundaryRequestCounts: [...input.completedBoundaryRequestCounts],
		requestsPerBoundaryMean: mean,
		requestsPerBoundaryLowerBound: lowerBound,
		unboundedExpectedRemainingRequests,
		averageContextTokenIncrement: input.averageContextTokenIncrement,
		windowRequestUpperBound,
		expectedRemainingRequests:
			windowRequestUpperBound === null
				? unboundedExpectedRemainingRequests
				: Math.min(unboundedExpectedRemainingRequests, windowRequestUpperBound),
	};
}

export function decideCompaction(input: {
	readonly writeTokens: number;
	readonly archiveTokens: number;
	readonly memoTokens: number;
	readonly contextTokens: number;
	readonly completedBoundaryRequestCounts: readonly number[] | null;
	readonly remainingBoundaries: number;
	readonly averageContextTokenIncrement: number | null;
	readonly contextWindowTokens: number | null;
	readonly priorCompactionCount: number;
	/** Provider requests since the last compaction; null when never compacted. */
	readonly requestsSinceLastCompaction?: number | null;
	readonly carriedDebtTokens: number;
	readonly cacheDebtRepaymentTokens: number;
	readonly cacheWriteReadRatio: number | null;
	readonly economics: CompactionEconomics;
}): CompactionDecision {
	const horizon =
		input.completedBoundaryRequestCounts === null
			? null
			: estimateRemainingRequests({
					completedBoundaryRequestCounts: input.completedBoundaryRequestCounts,
					remainingBoundaries: input.remainingBoundaries,
					scale: input.economics.remainingRequestScale,
					standardDeviationK: input.economics.remainingRequestStddevK,
					contextTokens: input.contextTokens,
					contextWindowTokens: input.contextWindowTokens,
					averageContextTokenIncrement: input.averageContextTokenIncrement,
				});
	const savingTokens = input.archiveTokens - input.memoTokens;
	const postCompactionTokens = Math.max(0, input.writeTokens - savingTokens);
	const incrementalCacheCostRatio =
		input.cacheWriteReadRatio === null ? null : Math.max(0, input.cacheWriteReadRatio - 1);
	const newDebtTokens = postCompactionTokens * (incrementalCacheCostRatio ?? 0);
	const breakevenRequests =
		savingTokens > 0 && incrementalCacheCostRatio !== null ? newDebtTokens / savingTokens : null;
	const combinedRepaymentTokens = input.cacheDebtRepaymentTokens + savingTokens;
	const combinedBreakevenRequests =
		savingTokens > 0 && incrementalCacheCostRatio !== null && combinedRepaymentTokens > 0
			? (input.carriedDebtTokens + newDebtTokens) / combinedRepaymentTokens
			: null;
	const firstCompaction = input.priorCompactionCount === 0;
	const effectiveHorizonRequests = effectiveHorizon(
		horizon,
		firstCompaction,
		input.economics.firstCompactionRequestScale,
	);
	const windowProtection =
		input.contextWindowTokens !== null &&
		input.contextTokens >= input.contextWindowTokens - input.economics.windowReserveTokens;
	const baseEconomic =
		horizon !== null &&
		horizon.expectedRemainingRequests > 0 &&
		breakevenRequests !== null &&
		breakevenRequests <= horizon.expectedRemainingRequests;
	const firstEconomic =
		firstCompaction &&
		effectiveHorizonRequests !== null &&
		effectiveHorizonRequests > 0 &&
		breakevenRequests !== null &&
		breakevenRequests <= effectiveHorizonRequests;
	const subsequentMarginOpen =
		!firstCompaction &&
		horizon !== null &&
		breakevenRequests !== null &&
		breakevenRequests * input.economics.subsequentCompactionMargin <= horizon.expectedRemainingRequests;
	const carriedDebtGateOpen =
		!firstCompaction &&
		horizon !== null &&
		combinedBreakevenRequests !== null &&
		combinedBreakevenRequests <= horizon.expectedRemainingRequests;
	const economic = firstCompaction ? firstEconomic : baseEconomic && subsequentMarginOpen && carriedDebtGateOpen;
	const compressible = savingTokens > 0;
	const cooldownActive =
		input.requestsSinceLastCompaction !== null &&
		input.requestsSinceLastCompaction !== undefined &&
		input.requestsSinceLastCompaction < input.economics.minimumRequestsSinceCompaction;
	// Window protection stays absolute: near the context limit, compact even in cooldown.
	const economicAllowed = economic && !cooldownActive;
	const compact = compressible && (windowProtection || economicAllowed);

	return {
		writeTokens: input.writeTokens,
		archiveTokens: input.archiveTokens,
		memoTokens: input.memoTokens,
		postCompactionTokens,
		contextTokens: input.contextTokens,
		...(horizon ?? {
			completedBoundaryRequestCounts: null,
			requestsPerBoundaryMean: null,
			requestsPerBoundaryLowerBound: null,
			unboundedExpectedRemainingRequests: null,
			averageContextTokenIncrement: input.averageContextTokenIncrement,
			windowRequestUpperBound: null,
			expectedRemainingRequests: null,
		}),
		breakevenRequests,
		combinedBreakevenRequests,
		effectiveHorizonRequests,
		cacheWriteReadRatio: input.cacheWriteReadRatio,
		incrementalCacheCostRatio,
		priorCompactionCount: input.priorCompactionCount,
		requestsSinceLastCompaction: input.requestsSinceLastCompaction ?? null,
		carriedDebtTokens: input.carriedDebtTokens,
		cacheDebtRepaymentTokens: input.cacheDebtRepaymentTokens,
		compact,
		reason: compactionReason({
			compressible,
			windowProtection,
			economic,
			cooldownActive,
			horizonAvailable: horizon !== null,
			breakevenAvailable: breakevenRequests !== null,
			firstCompaction,
			baseEconomic,
			subsequentMarginOpen,
			carriedDebtGateOpen,
		}),
	};
}

/**
 * The request horizon a compaction is priced against: the first compaction's
 * horizon is scaled and capped by the context window; later ones use it as is.
 */
function effectiveHorizon(
	horizon: RequestHorizonEstimate | null,
	firstCompaction: boolean,
	firstCompactionRequestScale: number,
): number | null {
	if (horizon === null) return null;
	if (!firstCompaction) return horizon.expectedRemainingRequests;
	return Math.min(
		horizon.expectedRemainingRequests * firstCompactionRequestScale,
		horizon.windowRequestUpperBound ?? Number.POSITIVE_INFINITY,
	);
}

/** The first gate, in precedence order, that decided a compaction. */
function compactionReason(gates: {
	readonly compressible: boolean;
	readonly windowProtection: boolean;
	readonly economic: boolean;
	readonly cooldownActive: boolean;
	readonly horizonAvailable: boolean;
	readonly breakevenAvailable: boolean;
	readonly firstCompaction: boolean;
	readonly baseEconomic: boolean;
	readonly subsequentMarginOpen: boolean;
	readonly carriedDebtGateOpen: boolean;
}): CompactionReason {
	if (!gates.compressible) return "non_positive_saving";
	if (gates.windowProtection) return "window_protection";
	if (gates.economic) return gates.cooldownActive ? "deferred_post_compaction_cooldown" : "economic";
	if (!gates.horizonAvailable) return "horizon_unavailable";
	if (!gates.breakevenAvailable) return "cache_ratio_unavailable";
	const laterBaseEconomic = !gates.firstCompaction && gates.baseEconomic;
	if (laterBaseEconomic && !gates.subsequentMarginOpen) return "deferred_subsequent_margin";
	if (laterBaseEconomic && !gates.carriedDebtGateOpen) return "deferred_carried_debt";
	return "deferred_economic";
}
