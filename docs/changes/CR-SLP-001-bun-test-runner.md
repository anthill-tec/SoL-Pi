# CR-SLP-001 — Run the test suite on `bun test`; remove Vitest

**Status:** PENDING · Pre-review: due — the gap analysis needed a ruling from the user (the test runner)
**Type:** maintenance
**Priority:** P0 — every later CR's RED/GREEN/VERIFY runs, the pre-merge gate and CI run `bun test`
**Depends on:** none
**Labels:** tests, tooling, ci
**Phase:** 0.1.0 · wave 1
**Design reference:** none (no PRD covers the test tooling); the runner contract is the bun Crucible client's `--help`

## Context

The suite is written for Vitest (`vitest run`; tests import from `"vitest"`; `tsconfig.json`
loads `vitest/globals`). The project's Crucible client runs `bun test` for `test`, `regression`
and `pre-merge-gate`, with no setting to change the runner, and the release workflow's `test-bun`
job runs `bun test` too. A declared `test:<tier>` script cannot replace it: the pre-merge gate is
additive and always runs the whole suite under `bun test`.

Under `bun test` today (measured through the client, 2026-11-04): **274 tests across 25 files,
259 pass, 15 fail.** Bun resolves the `"vitest"` imports, so most of the suite runs unchanged. The
15 failures:

- 8 use Vitest-only API that Bun does not provide — `vi.waitFor` (7, in
  `tests/online-context-compact.test.ts`) and `expect.soft` (in
  `tests/online-context-compact-cli.test.ts`).
- 7 fail for reasons not yet diagnosed:
  - `action fusion then_run > drops the savings banner once a fused call settles as an error`
    (`tests/action-fusion.test.ts`): the failed render still contains `SoL-Pi`;
  - `SoL-Pi with Pi codemode (all mechanisms) > runs all four mechanisms together in codemode "on" mode`
    (`tests/all-mechanisms.test.ts`): `no JSON in script result: Script failed`;
  - `observation pack > fails recall closed when an object path is replaced by a symlink` and
    `… fails storage closed when the observation directory is a symlink`
    (`tests/observation-pack.test.ts`): `extension ctx is stale after session replacement or reload`;
  - `finishes the OCC continuation in the real Pi print CLI before exiting`
    (`tests/online-context-compact-cli.test.ts`);
  - `ObservationPack and OCC savings > does not compact a projected prefix that is smaller than the replacement summary`
    (`tests/online-context-compact-projection.test.ts`): a token estimate is `NaN`;
  - `published package > contains the standalone entrypoint …` and `… ships Online Context Compact …`
    (`tests/package.test.ts`): `packedFiles()` returns an empty list.

## Scope

### §S1 — Port the Vitest-only API

**Surfaces (verified 2026-11-04):** `tests/online-context-compact.test.ts`,
`tests/online-context-compact-cli.test.ts`.

- Replace every `vi.waitFor(...)` with an equivalent `bun:test`-compatible wait: a small polling
  helper in `tests/helpers.ts` that retries an assertion until it passes or a timeout elapses,
  and rethrows the last assertion error on timeout.
- Replace every `expect.soft(...)` with plain `expect(...)`, keeping each assertion.

### §S2 — Move every test file to `bun:test`

**Surfaces:** the 24 files under `tests/` importing from `"vitest"`, `tests/helpers.ts`.

- Import the test API from `"bun:test"` in every test file and helper. `vi.fn`, `vi.spyOn`,
  `vi.useFakeTimers`, `vi.useRealTimers`, `vi.advanceTimersByTime` and `vi.restoreAllMocks` become
  their `bun:test` equivalents (`mock`/`spyOn`/`jest.*`, or `vi` from `"bun:test"`).
- Per-suite timeouts keep their values (for example the Pi compatibility check's 30 s), expressed
  in the form `bun:test` honours.

### §S3 — Make the 7 remaining failures pass under `bun test`

For each failure in Context, find the cause and fix it at the cause. A cause in a test (runner
behaviour, isolation between files, the working directory, process spawning) is fixed in the
test. A cause in production code is fixed there, with a test that fails before the fix. No test
is deleted, skipped, or loosened to pass.

### §S4 — Remove Vitest from the project

**Surfaces:** `package.json`, `package-lock.json`, `bun.lock`, `tsconfig.json`.

- `package.json`: `scripts.test` is `bun test`; `vitest` is removed from `devDependencies`;
  `@types/bun` is added at an exact version. `check` keeps its shape
  (`npm run typecheck && npm test && npm pack --dry-run`).
- `tsconfig.json` `compilerOptions.types` is `["node", "bun"]`.
- `package-lock.json` and `bun.lock` are regenerated from the manifest; neither contains a
  `vitest` or `@vitest/*` package. npm stays the installer the install guide uses; both lockfiles
  are kept.

### §S5 — Replace every Vitest invocation in scripts and docs

**Surfaces:** `setup-sol-pi.fish` (the two all-mechanisms runs and the full-suite run),
`agents-install.md` (verification commands and its recovery step), `docs/star-history.md`,
`examples/sol-pi-skill/bin/sol-pi-run`, `THIRD_PARTY_NOTICES.md`, the comment in
`tests/package.test.ts` that names Vitest's timeout.

- Each `npx vitest run <paths>` becomes `bun test <paths>`; the setup script's full-suite run
  keeps excluding `tests/package.test.ts`.
- `agents-install.md` lists Bun as a prerequisite for the verification step.
- `THIRD_PARTY_NOTICES.md` names the development tools actually used (`@types/bun`, not Vitest).

### §S6 — CI runs the suite on the client's timeout

**Surfaces:** `.github/workflows/release.yml` (`test-bun` job).

- The `Run the tests` step runs `bun test --timeout 30000`, the per-test budget the bun Crucible
  client applies to every run it makes.

## Acceptance criteria

- [ ] **§S1** `git grep -n -E 'vi\.waitFor|expect\.soft' -- tests` returns nothing.
- [ ] **§S1** The polling helper has a unit test: it resolves once the assertion passes, and on
      timeout rejects with the assertion's own last error.
- [ ] **§S2** `git grep -n 'from "vitest"' -- tests` returns nothing; every test file that uses the
      test API imports it from `"bun:test"`.
- [ ] **§S3** Each of the 7 tests named in Context passes under `bun test`, with its name and
      assertions unchanged (a production-code cause additionally has a new failing-first test).
- [ ] **§S3** No test is added to a skip, `todo` or `only` list: `git grep -n -E '\.(skip|todo|only)\(' -- tests`
      returns no line this CR added.
- [ ] **§S4** `package.json` `scripts.test` is exactly `bun test`; `devDependencies` has no
      `vitest` key and has `@types/bun` at an exact version.
- [ ] **§S4** `tsconfig.json` `compilerOptions.types` is exactly `["node", "bun"]`, and
      `npm run typecheck` exits 0.
- [ ] **§S4** `grep -c vitest package-lock.json bun.lock` is 0 for both files, and
      `bun install --frozen-lockfile` and `npm ci --ignore-scripts` both succeed on a clean checkout.
- [ ] **§S5** `git grep -n -i vitest -- . ':!docs/changes'` returns nothing.
- [ ] **§S5** `tests/install-guide.test.ts` passes against the updated `agents-install.md`.
- [ ] **§S6** The `test-bun` step's command is exactly `bun test --timeout 30000`.
- [ ] **Whole suite:** the bun client's `regression` reports **274 passed, 0 failed** (or more
      passed, where §S1/§S3 add tests), and `pre-merge-gate` passes.

## Estimated size

5 points. §S1, §S2, §S4–§S6 are mechanical; the uncertainty is §S3's seven diagnoses.

## Risks

- A §S3 cause may be a real production defect hidden by Vitest's isolation (for example the stale
  extension `ctx` after a reload). It is fixed here only while it stays within one failure's
  cause; a fix that needs a design change becomes its own CR.
- Bun runs all test files in one process by default; isolation problems may surface beyond the
  seven failures once the imports change.

## Non-goals

- Changing the package manager or the install guide's npm steps (beyond the test command).
- Pi 1.5.0 support (its own CR).
- Reworking `setup-sol-pi.fish` beyond its test invocations.
