/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 */
import { afterEach, describe, expect, it, vi } from "bun:test";
import { waitFor } from "./helpers.ts";

/** A callback that throws a numbered error on each of its first `failures` calls, then returns `value`. */
function flaky<T>(failures: number, value: T) {
	const errors: Error[] = [];
	const times: number[] = [];
	const callback = (): T => {
		times.push(performance.now());
		if (errors.length < failures) {
			const error = new Error(`attempt ${errors.length + 1}`);
			errors.push(error);
			throw error;
		}
		return value;
	};
	return { callback, errors, times, calls: () => times.length };
}

function medianGap(times: number[]): number {
	const gaps = times.slice(1).map((time, index) => time - (times[index] ?? time));
	gaps.sort((left, right) => left - right);
	return gaps[Math.floor(gaps.length / 2)] ?? Number.NaN;
}

describe("waitFor", () => {
	afterEach(() => {
		vi.useRealTimers();
	});

	it("resolves with the callback's value once the callback stops throwing", async () => {
		const probe = flaky(2, { ready: true });

		await expect(waitFor(probe.callback)).resolves.toEqual({ ready: true });
		expect(probe.calls()).toBe(3);
		expect(probe.errors.map((error) => error.message)).toEqual(["attempt 1", "attempt 2"]);
	});

	it("stops calling the callback once it has resolved", async () => {
		const probe = flaky(1, "done");

		expect(await waitFor(probe.callback)).toBe("done");
		await new Promise((resolve) => setTimeout(resolve, 200));
		expect(probe.calls()).toBe(2);
	});

	it("gives up after 1000 ms by default and rejects with the callback's last error", async () => {
		const probe = flaky(Number.POSITIVE_INFINITY, "never");
		const started = performance.now();

		const failure = await waitFor(probe.callback).then(
			() => undefined,
			(error: unknown) => error,
		);
		const elapsed = performance.now() - started;

		expect(probe.errors.length).toBeGreaterThan(1);
		expect(failure).toBe(probe.errors.at(-1));
		expect(failure).not.toBe(probe.errors[0]);
		expect((failure as Error).message).toBe(`attempt ${probe.calls()}`);
		expect(elapsed).toBeGreaterThanOrEqual(950);
		expect(elapsed).toBeLessThan(1_500);
	});

	it("polls every 50 ms by default", async () => {
		const probe = flaky(Number.POSITIVE_INFINITY, "never");

		await expect(waitFor(probe.callback)).rejects.toThrow(/^attempt \d+$/u);

		expect(medianGap(probe.times)).toBeGreaterThanOrEqual(40);
		expect(medianGap(probe.times)).toBeLessThan(90);
		expect(probe.calls()).toBeGreaterThanOrEqual(10);
		expect(probe.calls()).toBeLessThanOrEqual(22);
	});

	it("takes the timeout and the interval from { timeout, interval }", async () => {
		const probe = flaky(Number.POSITIVE_INFINITY, "never");
		const started = performance.now();

		const failure = await waitFor(probe.callback, { timeout: 300, interval: 100 }).then(
			() => undefined,
			(error: unknown) => error,
		);
		const elapsed = performance.now() - started;

		expect(failure).toBe(probe.errors.at(-1));
		expect(elapsed).toBeGreaterThanOrEqual(280);
		expect(elapsed).toBeLessThan(800);
		expect(medianGap(probe.times)).toBeGreaterThanOrEqual(90);
		expect(medianGap(probe.times)).toBeLessThan(180);
		expect(probe.calls()).toBeGreaterThanOrEqual(2);
		expect(probe.calls()).toBeLessThanOrEqual(4);

		// A callback whose promise never settles is called once, and waitFor still rejects at the timeout.
		let pendingCalls = 0;
		const pendingStarted = performance.now();
		const hung = await waitFor(
			() => {
				pendingCalls += 1;
				return new Promise<never>(() => undefined);
			},
			{ timeout: 300, interval: 100 },
		).then(
			() => undefined,
			(error: unknown) => error,
		);

		expect(hung).toBeInstanceOf(Error);
		expect((hung as Error).message).toBe("Timed out in waitFor!");
		expect(pendingCalls).toBe(1);
		expect(performance.now() - pendingStarted).toBeGreaterThanOrEqual(280);
	});

	it("waits past the default timeout when { timeout } is longer", async () => {
		let calls = 0;
		const started = performance.now();
		const callback = (): number => {
			calls += 1;
			if (performance.now() - started < 1_200) throw new Error("not yet");
			return calls;
		};

		const value = await waitFor(callback, { timeout: 2_000, interval: 100 });

		expect(value).toBe(calls);
		expect(performance.now() - started).toBeGreaterThanOrEqual(1_200);
	});

	it("keeps polling on real timers while fake timers are installed", async () => {
		vi.useFakeTimers();
		const probe = flaky(2, "real");

		await expect(waitFor(probe.callback)).resolves.toBe("real");
		expect(probe.calls()).toBe(3);
	});

	it("gives up on real time while fake timers are installed", async () => {
		vi.useFakeTimers();
		const probe = flaky(Number.POSITIVE_INFINITY, "never");

		const failure = await waitFor(probe.callback, { timeout: 200, interval: 50 }).then(
			() => undefined,
			(error: unknown) => error,
		);

		expect(failure).toBe(probe.errors.at(-1));
		expect(probe.calls()).toBeGreaterThanOrEqual(2);
		expect(probe.calls()).toBeLessThanOrEqual(10);
	});
});
