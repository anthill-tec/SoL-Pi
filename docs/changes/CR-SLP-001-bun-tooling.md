# CR-SLP-001 — Move the project's tooling to Bun; remove Vitest

**Status:** PENDING · Pre-review: ran — the gap analysis needed rulings from the user (the test runner, Bun tooling everywhere)
**Type:** maintenance
**Priority:** P0 — every later CR's RED/GREEN/VERIFY runs, the pre-merge gate and CI run `bun test`
**Depends on:** none
**Labels:** tests, tooling, ci, docs
**Phase:** 0.1.0 · wave 1
**Design reference:** none (no PRD covers the tooling); the runner contract is the bun Crucible client's `--help`

## Context

The project's development tooling is npm and Vitest: `npm ci`, `npm run check`, `npm audit`,
`npm pack`, `vitest run`, tests importing from `"vitest"`, `tsconfig.json` loading
`vitest/globals`. The bun Crucible client runs `bun test` for `test`, `regression` and
`pre-merge-gate`, with no setting to change the runner, and the release workflow's `test-bun` job
installs with `bun install --frozen-lockfile` and runs `bun test`. This CR moves every development
tool in the repository to Bun and removes Vitest.

**Reference (2026-11-04, this machine, Pi 1.3.0 dev dependency).** Vitest 4.1.11: 274 tests in
25 files, 271 pass, 3 fail, 0 skipped. `bun test` on Bun 1.4.4 through the client: the same 274
tests in the same 25 files, 260 pass, 14 fail, 0 skipped, 3163 `expect()` calls. Per file:

| File | Tests |
|---|---|
| `tests/action-fusion-paths.test.ts` | 26 |
| `tests/action-fusion.test.ts` | 23 |
| `tests/all-mechanisms.test.ts` | 4 |
| `tests/codemode-compat.test.ts` | 2 |
| `tests/config.test.ts` | 18 |
| `tests/evidence-preserving-reducer.test.ts` | 27 |
| `tests/install-guide.test.ts` | 7 |
| `tests/observation-pack.test.ts` | 20 |
| `tests/online-context-compact-agent-session.test.ts` | 11 |
| `tests/online-context-compact-cli.test.ts` | 1 |
| `tests/online-context-compact-economics.test.ts` | 12 |
| `tests/online-context-compact-plan.test.ts` | 5 |
| `tests/online-context-compact-projection.test.ts` | 6 |
| `tests/online-context-compact-recovery.test.ts` | 8 |
| `tests/online-context-compact-state.test.ts` | 11 |
| `tests/online-context-compact.test.ts` | 23 |
| `tests/package.test.ts` | 15 |
| `tests/pi-package-integration.test.ts` | 7 |
| `tests/runtime-paths.test.ts` | 9 |
| `tests/setup-prompt-flow.test.ts` | 6 |
| `tests/shell-options.test.ts` | 5 |
| `tests/sol-pi-config-preflight.test.ts` | 14 |
| `tests/sol-pi-regression-stress.test.ts` | 2 |
| `tests/star-history.test.js` | 5 |
| `tests/tui.test.ts` | 7 |

The failures, by cause:

- **Bun 1.4.4 lacks Vitest API (10 tests).** `vi.waitFor` (7 tests in
  `tests/online-context-compact.test.ts`); `expect.soft` (`finishes the OCC continuation in the
  real Pi print CLI before exiting`, `tests/online-context-compact-cli.test.ts`); a test callback's
  context parameter, which Bun treats as a `done` callback, so `ctx.skip()` is never reached and the
  test times out (`observation pack > fails recall closed when an object path is replaced by a
  symlink` and `… fails storage closed when the observation directory is a symlink`,
  `tests/observation-pack.test.ts`).
- **A Bun defect (1 test).** In Bun 1.4.4, `toMatchObject` with an asymmetric matcher in the
  expected value writes the matcher into the received object. `ObservationPack and OCC savings >
  does not compact a projected prefix that is smaller than the replacement summary`
  (`tests/online-context-compact-projection.test.ts`) then reads a corrupted message and gets
  `NaN`. The suite's only other such assertion is the last statement of its test.
- **Shared process state (intermittent, 1 test per run).** Pi limits codemode to 2 concurrent
  workers with a process-wide counter. Vitest gives each file its own module registry; `bun test`
  shares one process, so codemode workers an earlier test left running or shutting down count
  against a later test (`Codemode worker limit reached`).
- **Defects on this machine under both runners (3 tests).** `action fusion then_run > drops the
  savings banner once a fused call settles as an error` (`tests/action-fusion.test.ts`) fails when
  the checkout directory is named `SoL-Pi`, because the rendered file link contains the absolute
  path. `published package > contains the standalone entrypoint and no Pi monorepo source` and
  `… ships Online Context Compact from the standalone source tree` (`tests/package.test.ts`) read
  `npm pack --json` as an array; npm 12 emits an object keyed by package name.

Bun also reports four `it.each` rows under one shared name each, because it leaves `%s`
unformatted for primitive rows: `reduces fused command output while preserving the mutation
confirmation (failed=%s)`, `records real progress on the first plan update after compaction,
following %s work requests`, `preserves existing debt during unrelated native compaction
(fromExtension=%s)` and `starts and shuts down the offline RPC CLI without a prompt (all
enabled: %s)`.

## Scope

### §S1 — Tests import from `bun:test`

**Surfaces (verified 2026-11-04):** the 24 files under `tests/` importing from `"vitest"`.

- Every test file imports its test API from `"bun:test"`. `vi.fn`, `vi.spyOn`, `vi.useFakeTimers`,
  `vi.useRealTimers`, `vi.advanceTimersByTime` and `vi.restoreAllMocks` keep their call sites, using
  the `vi` that `"bun:test"` exports. Test bodies change only where §S2–§S4 require.

### §S2 — Replace the Vitest API that Bun lacks

**Surfaces:** `tests/helpers.ts`, a new `tests/helpers.test.ts`, `tests/online-context-compact.test.ts`,
`tests/online-context-compact-cli.test.ts`, `tests/observation-pack.test.ts`.

- `waitFor` in `tests/helpers.ts` keeps Vitest's `vi.waitFor` contract: it calls the callback
  until it returns without throwing, every 50 ms for at most 1000 ms by default (both
  overridable), resolves to the callback's value, and on timeout rejects with the callback's last
  error. Like `vi.waitFor`, it polls on real timers even while fake timers are installed. Each
  `vi.waitFor(...)` call becomes `waitFor(...)` with the same arguments. Its own tests live in a
  new `tests/helpers.test.ts`.
- Each `expect.soft(...)` becomes `expect(...)` with the same matcher and expected value.
- The two symlink tests decide their skip when they are registered: `it.skipIf(!symlinksSupported)`
  with `symlinksSupported` resolved once at the top of the file from the existing
  `canCreateSymlinks` probe, in place of the context parameter and `ctx.skip()`.

### §S3 — Fix the Bun-specific causes

**Surfaces:** `tests/online-context-compact-projection.test.ts`, the codemode tests in
`tests/codemode-compat.test.ts`, `tests/observation-pack.test.ts`,
`tests/online-context-compact-agent-session.test.ts`, `tests/package.test.ts`, the tests that start Pi in a child process, and the four `it.each` tables named in
Context.

- The projection test computes every value it derives from `projected` before its
  `toMatchObject` assertion, so the assertion sees and checks the same data as today.
- Every test that starts codemode leaves no codemode worker running or shutting down when it
  ends, so the next codemode test starts with Pi's full worker allowance, whichever codemode test
  ran before it.
- **Type fixes for `@types/bun`.** `describe`'s options argument (`{ timeout: 30_000 }` in
  `tests/package.test.ts`), which Bun's types do not accept, becomes a per-test timeout with the
  same value on each test of that block. The two `toEqual` calls whose expected value is an
  indexed `T | undefined` (`tests/codemode-compat.test.ts`, `tests/observation-pack.test.ts`)
  narrow it first, keeping the comparison.
- **Pi runs on Node, as under Vitest.** The tests that start Pi's CLI or the compatibility script
  in a child process (`tests/online-context-compact-cli.test.ts`,
  `tests/pi-package-integration.test.ts`, `tests/sol-pi-config-preflight.test.ts`,
  `tests/package.test.ts`) start it with `node`, Pi's own runtime, in place of
  `process.execPath`, which is Bun under `bun test`.
- Each of the four `it.each` tables passes its rows so that Bun formats `%s`, giving each test the
  title Vitest gives it (for example `… (failed=false)` and `… (failed=true)`).

### §S4 — Fix the machine-dependent tests

**Surfaces:** `tests/action-fusion.test.ts`, `tests/package.test.ts`.

- The savings-banner test asserts the absence of the banner itself, so the test no longer depends
  on the checkout directory's name.
- `packedFiles()` lists the package with `bun pm pack --dry-run` and reads the file paths it
  prints. The published-package tests keep every assertion.
- The lockfile-peers test reads `bun.lock` in place of `package-lock.json`, with the same
  assertion.

### §S5 — Bun as the package manager and script runner

**Surfaces:** `package.json`, `package-lock.json`, `bun.lock`, `tsconfig.json`, a new
`bunfig.toml`.

- `package.json`:
  - `scripts.test` is `bun test --timeout 30000`, the client's per-test budget (Bun's default is
    5 s, and `bunfig.toml`'s test timeout is not applied);
  - `scripts.check` is `bun run typecheck && bun run test && bun pm pack --dry-run`;
  - `scripts["check:pi"]` is `bun scripts/check-pi-compat.mjs`;
  - `packageManager` is `bun@1.4.4`;
  - `devDependencies` has no `vitest` and has `@types/bun` at exactly `1.4.4`.
- `package-lock.json` is deleted. `bun.lock` is regenerated and holds no `vitest` or `@vitest/*`
  package.
- `tsconfig.json` `compilerOptions.types` is `["node", "bun"]`.
- `bunfig.toml` sets `env = false`, so Bun loads no `.env` file into scripts, tests or the Pi
  processes tests start. The project's `.env` holds the Crucible project key.

### §S6 — Bun commands everywhere else

**Surfaces:** `README.md`, `agents-install.md`, `docs/compatibility.md`, `docs/configuration.md`,
`docs/star-history.md`, `THIRD_PARTY_NOTICES.md`, `setup-sol-pi.fish`, the usage text of
`scripts/*.mjs`, `examples/sol-pi-skill/` (`bin/sol-pi-run`, `README.md`,
`tests/test_sol_pi_skill.py`), `examples/solpi-visual/README.md`, `tests/install-guide.test.ts`.

- Each development command uses Bun:

  | Before | After |
  |---|---|
  | `npm ci --ignore-scripts` | `bun install --frozen-lockfile --ignore-scripts` |
  | `npm run <script>` | `bun run <script>` |
  | `npm audit --audit-level=high` | `bun audit --audit-level=high` |
  | `npm pack --dry-run` | `bun pm pack --dry-run` |
  | `npx vitest run <paths>` | `bun test --timeout 30000 <paths>` |
  | `node scripts/<name>.mjs` | `bun scripts/<name>.mjs` |
  | `npm test` | `bun run test` |
  | `npm install --prefix <dir> <pkg>` | `bun add --cwd <dir> <pkg>` |

  `setup-sol-pi.fish`'s full-suite run keeps excluding `tests/package.test.ts`
  (`--path-ignore-patterns`). `examples/sol-pi-skill/tests/test_sol_pi_skill.py` runs the config
  checker with `bun`.
- `setup-sol-pi.fish` and `examples/sol-pi-skill/bin/sol-pi-run` check for Bun 1.4.4 or later as a
  prerequisite, in place of npm, and stop with a message naming it when it is missing.
- Installing Pi is documented with Bun first (`bun add --global
  @earendil-works/pi-coding-agent@<version>`), with the npm command kept as the alternative. The
  compatibility check is documented for both locations, `--pi-root "$HOME/.bun/install/global/node_modules"`
  and `--pi-root "$(npm root -g)"`.
- `agents-install.md` and `README.md` list Bun 1.4.4 as a prerequisite.
- `THIRD_PARTY_NOTICES.md` names the development tools in use (`@types/bun`, TypeScript,
  `@types/node`) and the lockfile `bun.lock`.
- `tests/install-guide.test.ts` requires the Bun commands in place of the npm ones, with the same
  coverage of the guide.
- `CHANGELOG.md` `[Unreleased]` records the move to Bun and the removal of Vitest.

### §S7 — CI on the same Bun

**Surfaces:** `.github/workflows/release.yml` (`test-bun` job).

- The `oven-sh/setup-bun` step sets `bun-version: 1.4.4`.
- The `Run the tests` step runs `bun test --timeout 30000`, the per-test budget the bun Crucible
  client applies to every run it makes.

## Acceptance criteria

**Matching tests across the two runners.** A test's identity is its file, its `describe` chain and
its title (Vitest's JUnit `classname` is the file and `name` is `describe > title`; Bun's nests
the `describe` chain as test suites). Titles generated by `it.each` match when they differ only in
how the row value is printed: Vitest quotes strings (`'edit'`), shortens long values with `…`,
and prints zero as `+0`; Bun does not.

- [ ] **Fidelity** The bun client's `regression` reports **0 failed, 0 skipped**, and runs the 274
      reference tests of the Context table, with that table's per-file counts, plus only the
      `waitFor` tests in `tests/helpers.test.ts`.
- [ ] **Fidelity** Every test identity in the run is unique, and each of the 274 Vitest reference
      tests matches exactly one test in the run, by the rule above. A comparison of the two JUnit
      reports, attached to the CR's close-out, shows the mapping.
- [ ] **Fidelity** The run reports at least 3163 `expect()` calls.
- [ ] **Fidelity** Every test-file hunk in the CR's diff belongs to §S1–§S4; no `it`, `test` or `describe` is removed, and no `.skip`, `.todo`, `.only` or
      `skipIf` is added except §S2's symlink condition.
- [ ] **§S1** `git grep -n 'from "vitest"' -- tests` returns nothing.
- [ ] **§S2** `git grep -n -E 'vi\.waitFor|expect\.soft|ctx\.skip' -- tests` returns nothing.
- [ ] **§S2** `waitFor` has tests: it resolves with the callback's value once the callback stops
      throwing; with defaults it gives up after 1000 ms and rejects with the callback's last error;
      `{ timeout, interval }` overrides both.
- [ ] **§S3** The codemode tests pass in two consecutive `regression` runs and when each codemode
      test file is run alone with the client's `test --tests`.
- [ ] **§S3** The tests that start Pi in a child process start it with `node`; `git grep -n
      process.execPath -- tests` returns no Pi or script launch.
- [ ] **§S4** `tests/action-fusion.test.ts` passes from a checkout whose directory is named `SoL-Pi`.
- [ ] **§S5** `package.json` has the scripts, `packageManager` and `devDependencies` §S5 lists,
      exactly.
- [ ] **§S5** `package-lock.json` does not exist; `grep -c -i vitest bun.lock` is 0;
      `bun install --frozen-lockfile` succeeds on a clean checkout.
- [ ] **§S5** The client's `check` exits 0 with `tsconfig.json` `types` exactly `["node", "bun"]`.
- [ ] **§S5** `bunfig.toml` holds `env = false`; from the project root, with a `.env` defining
      `CRUCIBLE_PROJECT_KEY` and the variable removed from the environment (`env -u
      CRUCIBLE_PROJECT_KEY`), `bun -e 'console.log(process.env.CRUCIBLE_PROJECT_KEY ?? "unset")'`
      prints `unset`.
- [ ] **§S6** `git grep -n -E '\bnpx\b|\bnpm (ci|run|test|audit|pack|install)\b|\bnode scripts/|vitest' -- . ':!docs/changes' ':!CHANGELOG.md' ':!tests/action-fusion.test.ts' ':!tests/evidence-preserving-reducer.test.ts'`
      returns nothing, apart from the npm alternative for installing Pi that §S6 keeps. The two
      excluded files use `npm test` as a `then_run` command in their test data, which the
      reducer's diagnostic-command rule matches.
- [ ] **§S6** The parts of `bun run check` each pass: the client's `check` (typecheck), the
      client's `regression`, and `bun pm pack --dry-run`. `scripts.test` itself is not run outside
      the client.
- [ ] **§S6** With Bun missing from `PATH`, `setup-sol-pi.fish` and `sol-pi-run setup` stop
      before installing anything, naming Bun 1.4.4.
- [ ] **§S6** `CHANGELOG.md` `[Unreleased]` has an entry for the move to Bun.
- [ ] **§S6** `examples/sol-pi-skill/tests/test_sol_pi_skill.py` passes through the python
      client.
- [ ] **§S7** The `test-bun` job's `setup-bun` step has `bun-version: 1.4.4`, and its test
      command is exactly `bun test --timeout 30000`.
- [ ] **Gate** `pre-merge-gate` passes.

## Estimated size

8 points. The test changes are small and named; the bulk is the mechanical command sweep across
docs, scripts, examples and the setup script.

## Risks

- Bun's `vi` and matchers can differ from Vitest's in cases the reference run does not exercise.
  The fidelity criteria hold the suite to the reference; a difference found later is a defect
  against this CR.
- The next Bun release brings Vitest-compatible `"vitest"` semantics and fixes the `toMatchObject`
  defect. Moving to it is a deliberate version change (§S7 pins 1.4.4), not part of this CR.
- `bun audit` reports four high-severity `undici` advisories, from the Pi 1.3.0 dev dependency;
  `bun run check` does not run the audit, and the Pi upgrade is its own CR.

## Non-goals

- The star-history workflow's renderer, a third-party project with its own pnpm toolchain.
- Where `setup-sol-pi.fish` looks for an installed Pi, and its project mode and other behaviour;
  CR-SLP-005 retires the script.
- Pi 1.5.0 support (CR-SLP-002).
- The runtime Pi uses to load SoL-Pi: SoL-Pi stays a Pi extension that Node and Bun both load.
- The reducer recognising `bun test` as a diagnostic command (its own CR if wanted).
- Running the suite in a random file order (the client has no order flag).
