# CR-SLP-015 — Test hygiene for 0.1.2

**Status:** DRAFT · Pre-review: due — the gap analysis needs a ruling from the user (the disposition of each F2 item in §S1)
**Type:** maintenance
**Priority:** P1 — the release's test-hygiene CR; the 0.1.2 release branch starts only after it
**Depends on:** CR-SLP-012, CR-SLP-013, CR-SLP-014
**Labels:** tests, hygiene
**Phase:** 0.1.2 · wave 1 (last)

## Context

Every regular release carries a test-hygiene CR, sequenced last in its final wave. 0.1.2 carries
three items forward and adds a sweep of what CR-SLP-012 to CR-SLP-014 leave behind.

**F2, accepted at the 0.1.0 release gate.** The no-mistakes review of release 0.1.0 found that
several tests prove behaviour only by matching source or document text, so a wrong document or dead
code that keeps the words passes. The release accepted the finding and moved it here. Its items,
with the tests named as they stand on `develop` at `0b1e6e2`:

1. `tests/install-guide.test.ts` hard-codes the lists it checks the documents against:
   `SETUP_FLAGS`, `ENVELOPE_KEYS` and `OUTCOMES` (describe "sol-pi-axi documentation"),
   `INSTALL_OUTCOMES` and `INSTALL_KEYS` (describe "registry install documentation"). A flag, key or
   outcome added to or removed from `sol_pi_axi` without a document change passes.
2. Most other tests in that file check that a document contains a phrase. The changelog tests that
   did this were already replaced at the 0.1.0 gate by the executable check "CHANGELOG.md has a
   non-empty section for the package version, as the release workflow extracts it".
3. `tests/test_sol_pi_axi_package.py`: "test_gitignore_ignores_the_venv_and_egg_info" reads
   `.gitignore` lines instead of asking git, and
   "test_version_file_is_one_literal_with_no_imports_equal_to_package_json" checks the version with a
   regular expression although the next test imports it.
4. `tests/setup-references.test.ts` uses `git grep` to show that retired names and the retired
   "never prompts" statement appear nowhere.
5. `tests/integration-tier.test.ts` and `tests/test_integration_tier.py` decide by pattern, from
   each test file's source, whether the file starts a process.
6. `tests/package.test.ts` "is indented with two spaces" compares `package.json`'s text with its
   own re-serialisation.
7. Cross-language sync checks read a constant out of another language's source with a regular
   expression: the tested Pi versions (`tests/test_sol_pi_axi_install.py`, from
   `scripts/check-pi-compat.mjs`) and the configuration constants (`tests/sol_pi_axi_support.py`,
   from `src/sol-pi/config.ts`).

**CR-SLP-011's VERIFY suggestions.** Three were left for this CR:

- The rule "a feature that registers a `session_start` handler from `registerConfiguredFeatures`
  misses the first `session_start`" is held only by a comment on that function.
- Four entry-point scenarios in `tests/online-context-compact-subagents.test.ts` passed before the
  fix; they guard against regressions and prove nothing about the fix. That is their purpose, and
  this CR changes nothing there.
- The Crucible client filed CR-SLP-011's targeted run with no tier. That is the Crucible client's
  behaviour, not SoL-Pi's code, so it is not in this CR.

## Scope

### §S1 — F2: tests that check text

**Surfaces:** `tests/install-guide.test.ts`, `tests/test_sol_pi_axi_package.py`, the test helpers.

Proposed disposition of each F2 item (PROPOSED until the user rules):

| Item | Disposition |
|---|---|
| 1. Hard-coded flag, key and outcome lists | **Fix.** The test reads them from `sol_pi_axi` at run time, and checks both directions: every flag the CLI accepts, every envelope key and every outcome is documented, and every flag the documents list is one the CLI accepts. |
| 2. Phrase checks in documents | **Keep** the ones whose phrase is a command, a path, a version or a link a reader copies (they are the documents' contract); **remove** a phrase check whose behaviour a behaviour test already covers, naming that test in the commit. |
| 3. `.gitignore` lines; `_version.py` regex | **Fix.** Ask `git check-ignore`; drop the regex and keep the import test and the no-import check. |
| 4. `git grep` for retired text | **Keep by design.** The claim is that no tracked file names the retired things, and `git grep` checks exactly that. |
| 5. Integration tier by source pattern | **Keep by design.** Detecting process starts at run time means running the whole suite under a tracer; the pattern check is cheap and fails loudly. |
| 6. `package.json` text | **Keep by design.** The claim is the file's formatting. |
| 7. Cross-language constants by regex | **Keep by design.** No executable form exists without running the other language's module; CR-SLP-012 relies on the Pi-version check. |

- For item 1, the source of truth is the package itself: the parser's declared flags, and the
  envelope keys and outcomes of real `sol-pi-axi` runs against the stub Pi the Python tests use, or
  constants the package exports for them. When `sol_pi_axi` exposes no such list, this CR may add
  one, used by the code it describes.
- For item 2, the commit that removes a phrase check names the behaviour test that covers it.

### §S2 — The first-`session_start` rule is a test

**Surfaces:** a test file for the packaged entry point.

- A test registers every feature through `registerConfiguredFeatures` with every feature enabled,
  on a recording extension API, and expects the events those features subscribe to at
  `session_start` to be exactly Online Context Compact's, whose duty at the first event the entry
  point already performs. A new feature that subscribes to `session_start` fails the test, and the
  failure message names the rule and `registerConfiguredFeatures`.

### §S3 — Sweep after CR-SLP-012 to CR-SLP-014

**Surfaces:** whatever the sweep finds, tests and test helpers only.

- On `develop` with CR-SLP-012, CR-SLP-013 and CR-SLP-014 merged: Ruff and Pyright over
  `sol_pi_axi/` and `tests/`, `bun run typecheck` under TypeScript 7, `bun audit --audit-level=high`,
  and a check for helpers defined twice. Each finding is fixed, or listed in the CR's close-out with
  the reason it stays.
- New test files from those CRs that start a process are in the integration tier (the tier tests
  enforce it).

## Acceptance criteria

- [ ] **§S1** The user's ruling on each F2 item is recorded in this spec before RED.
- [ ] **§S1** `tests/install-guide.test.ts` holds no hard-coded list of `sol-pi-axi` flags, envelope
      keys or outcomes; the lists come from `sol_pi_axi` at run time.
- [ ] **§S1** Adding a flag to `setup`'s parser without documenting it fails a test; documenting a
      flag the parser does not accept fails a test (shown by the RED agent's deliberate break, in
      its commit message).
- [ ] **§S1** Each phrase check removed under item 2 is named in a commit message with the behaviour
      test that covers it.
- [ ] **§S1** The `.gitignore` test runs `git check-ignore` on `.venv/` and on an `*.egg-info/`
      path and expects both ignored; the `_version.py` regex is gone.
- [ ] **§S2** The `session_start` test exists, passes, and fails when a feature registered by
      `registerConfiguredFeatures` subscribes to `session_start` (deliberate break in the RED
      commit message).
- [ ] **§S3** The sweep's tools report no finding, or each remaining finding is listed with its
      reason in the close-out.
- [ ] **Gate** `pre-merge-gate` passes on both stacks; no test is skipped.

## Estimated size

5 points.

## Risks

- Reading envelope keys from real runs couples the documentation test to the CLI's behaviour; a
  CLI change then fails the documentation test first, which is the point.
- The item 2 judgement (contract phrase or behaviour already tested) is made per test; the
  commit messages record each removal so VERIFY can check it.

## Non-goals

- Rewriting the documents themselves.
- Runtime detection of process-starting tests.
- Changing the Crucible client's tier filing.
- `examples/`, which stays outside the hygiene sweep.
