# CR-SLP-009 — Test hygiene for 0.1.0

**Status:** COMPLETED (shipped 2026-11-11 on develop) · Pre-review: not triggered — tests only, no other project's surface
**Type:** maintenance
**Priority:** P1 — the release's test-hygiene CR; 0.1.0 starts only after it
**Depends on:** CR-SLP-001, CR-SLP-002, CR-SLP-003, CR-SLP-004, CR-SLP-005, CR-SLP-006, CR-SLP-007, CR-SLP-008
**Labels:** tests, hygiene
**Phase:** 0.1.0 · wave 1 (last)

## Context

Every release carries a test-hygiene CR, sequenced last in its final wave. A sweep of `develop`
at `cce762b` (Bun 495 tests in 32 files, Python 358 tests in 16 modules) found:

- `ruff check tests sol_pi_axi` reports three ISC004 findings (an unparenthesized implicit string
  concatenation in a collection) in `tests/test_sol_pi_axi_interactive.py`; `pyright` and
  `tsc --noEmit` are clean.
- Helpers defined with identical bodies in several test files: `createCodemodeExtension` (4
  files), `contextInput`, `sourceHash` (3 each), `boundaryResponses`, `compactions`,
  `recordingUi`, `rootFile` (2 each), and in Python `parse` (3 modules) and `development_pi` (2).
  Six more differ slightly: `bashEvent`, `createTempDir`, `wireText`, `declaredTools`,
  `reminders`, `loadFusedTools`.
- Nine `skipIf` guards in the Bun suite. Three are platform guards (`win32` once, symlink support
  twice). The other six skip when the installed Pi lacks a capability (`createCodemodeExtension`, `buildSessionProjection`, a non-zero
  `then_run` exit returned as a result); they let the suite run against the older Pi versions the
  peer range (`>=0.84.2`) admits, and with the pinned Pi 1.5.0 none of them skips, but nothing
  fails if a future pin silently loses a capability.
- Slow tests: `test_a_confirm_dialog_holding_the_start_fails_after_the_bound_naming_it` takes 30 s
  (it proves the CLI's real 30-second bound, its only proof); `test_reducer_rejects_whitespace_
  exactly_as_pis_default_route_does` takes 6.8 s (63 `sol-pi-axi` processes, one per character
  and position).
- No test reaches the network.
- The integration tiers (`package.json` `test:integration`, `tests/integration/test_integration.py`)
  are hand-kept file lists, so a new process-starting test file is missed silently.

## Scope

### §S1 — Analyzer findings

**Surfaces:** `tests/test_sol_pi_axi_interactive.py`.

- The three ISC004 findings are fixed by parenthesizing the concatenations; the strings are
  unchanged.

### §S2 — One definition per shared helper

**Surfaces:** `tests/helpers.ts`, `tests/sol_pi_axi_support.py`, the test files that define the
helpers.

- Each identical helper above moves to the shared module of its language (`tests/helpers.ts`,
  `tests/sol_pi_axi_support.py`) and every former definer imports it.
- Each of the six near-duplicates moves the same way when one definition, with a parameter where
  needed, serves every caller without changing what any test asserts; otherwise it stays, and the
  commit message names why.
- No test's name, count or assertion changes.
- `loadFusedTools`, which imports production code, lives in its own support module, which only the
  action-fusion suites load, not in `tests/helpers.ts`.

### §S3 — Capability guards that cannot hide a lost capability

**Surfaces:** a new Bun test file, the capability probes the guarded files use.

- The capability guards stay, so the suite still runs against older Pi.
- A new test asserts that, with the development dependency's Pi, every capability those guards
  probe is present, so none of them skips; it names the capability that is missing.
- It reads the development dependency's Pi version from `package.json` and names no Pi version
  itself, so a pin change needs no edit to it.
- The platform guards stay unchanged.

### §S4 — The whitespace test without 63 processes

**Surfaces:** `tests/test_sol_pi_axi_cli.py`.

- Every character in the test's set is checked, at each of its three positions, in process
  against `sol_pi_axi.config.valid_route_part`, the check `--reducer` applies to each side of its
  `/`, as well as against Pi's default route (the test's premise, unchanged).
- The `sol-pi-axi` process path keeps one character per class — a JavaScript `WhiteSpace`
  character, a `LineTerminator`, and a Python-only whitespace character — at each position (9
  processes).
- The 30-second bound test stays as it is.

### §S5 — Integration tiers kept in step

**Surfaces:** a new Bun test, a new Python test, `package.json`, `tests/integration/test_integration.py`.

- A test module belongs to its tier when:
  - **Bun:** it uses `Bun.spawn`, `Bun.spawnSync`, `node:child_process` or `piCliPath()` from
    `tests/helpers.ts`, or starts a real Pi agent session (`createAgentSession`);
  - **Python:** it imports `subprocess` or `pty`, uses `tests/pty_harness.py` or
    `tests/sol_pi_axi_stub_pi.py`, or calls `run_cli` or `venv_script` from
    `tests/sol_pi_axi_support.py`.
- Today the rule selects exactly the listed modules: the 13 Bun files and the 11 Python modules.
- A test per stack fails naming every module the rule selects that is missing from its tier list,
  and every listed module the rule does not select or that does not exist.

## Acceptance criteria

- [ ] **§S1** `ruff check tests sol_pi_axi` reports no findings; `pyright` and
  `bun x tsc --noEmit -p tsconfig.json` stay clean.
- [ ] **§S2** Each of `createCodemodeExtension`, `contextInput`, `sourceHash`, `boundaryResponses`,
  `compactions`, `recordingUi`, `rootFile`, `parse` and `development_pi` is defined once under
  `tests/`; each of the six near-duplicates is defined once or its commit message names why it
  stays.
- [ ] **§S2** The Bun and Python test counts are unchanged by §S1, §S2 and §S4; the new tests of
  §S3 and §S5 are the only additions.
- [ ] **§S3** The new test passes with the pinned Pi, names no Pi version, and fails naming the
  capability when a probe reports it missing.
- [ ] **§S4** The whitespace test checks every character at every position in process, starts 9
  `sol-pi-axi` processes, and takes under 1.5 s.
- [ ] **§S5** Both tier tests pass; each fails naming the module when a process-starting test file
  is left out of its list, or a listed file starts no process.
- [ ] Both full suites pass through the Crucible clients, with Bun's own summary line read.

## Estimated size

5 points.

## Risks

- The rule of §S5 is textual; a module that starts a process through a helper the rule does not
  name is missed. The rule names every helper in use today.

## Non-goals

- `examples/` (its own tests, its `ruff` findings).
- Shortening the 30-second bound test, or giving the CLI's bound a test seam.
- Any change to production code.
- Running the suite against older Pi versions in CI.
