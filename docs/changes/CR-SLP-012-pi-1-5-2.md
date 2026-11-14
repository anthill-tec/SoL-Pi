# CR-SLP-012 — Support Pi 1.5.2

**Status:** COMPLETED (shipped 2026-11-14 on develop) · Pre-review: ran — touches another project's surface (Model B's setup runs the strict Pi compatibility check and `sol-pi-axi install`, whose warning names the tested set)
**Type:** maintenance
**Priority:** P1 — the current Pi release fails SoL-Pi's strict compatibility check, and `sol-pi-axi install` warns on it
**Depends on:** none
**Labels:** compatibility, dependencies, docs
**Phase:** 0.1.2 · wave 1
**Design reference:** `docs/compatibility.md` (`## Checking an installed Pi`, `## Pi 1.4 and 1.5`); CR-SLP-002; `docs/research/DN-sol-pi-axi.md` (D5, D6)

## Context

SoL-Pi's development dependency is Pi 1.5.0, and its tested set is 0.84.2, 1.0.4, 1.3.0 and 1.5.0
(`TESTED_PI_VERSIONS` in `scripts/check-pi-compat.mjs` and in `sol_pi_axi/pi.py`; a Python test
holds the two lists equal, in order). Pi 1.5.2 is the current release on npm (1.5.1 on 2026-11-09,
1.5.2 on 2026-11-10).

Measured 2026-11-14 on this machine, on `develop` at `0b1e6e2`:

- Baseline: the Bun gate passes 529 of 529 tests in 34 files, the Python gate 371 of 371.
- `check-pi-compat.mjs --strict --pi-root "$HOME/.bun/install/global/node_modules"` against a Bun
  global install of Pi 1.5.2 passes every API check (bash non-zero exit as an error result, bash
  output schema, codemode, `ModelRegistry.complete`) and fails only on
  `WARN: Pi 1.5.2 is not in the tested set`.
- `sol-pi-axi install` on Pi 1.5.2 warns that 1.5.2 is not a tested Pi version (`install` in
  `sol_pi_axi/install.py`).
- Pi 1.5.2's internal dependency graph is 1.5.0's, with every internal package pinned exactly at
  1.5.2; it depends on `undici` 8.12.3. `bun audit --audit-level=high` reports no vulnerability on
  the 1.5.0 development dependency.
- Both customers and this project's own sessions already run SoL-Pi on Pi 1.5.2. The CR-SLP-011
  live runs used Pi 1.5.2.
- The Python tests run `sol-pi-axi` against `tests/sol_pi_axi_stub_pi.py`, which answers as Pi
  1.5.0 does; only the integration tier runs a real Pi (`PI_BIN`, the development dependency in
  the gate). `docs/research/DN-sol-pi-axi.md` D5 and D6 record measurements on Pi 1.5.0 and 1.3.0.

### Pi 1.5.1 and 1.5.2 changes SoL-Pi meets

From Pi's `CHANGELOG.md` (`## [1.5.1]`, `## [1.5.2]`), and Pi's source where named. The spec
pre-review (2026-11-14) confirmed the message-thread behaviour below on Pi 1.5.2 with a loopback
recorder.

- **Anthropic message threads (1.5.1).** For the `anthropic` provider on `api.anthropic.com` (or a
  model whose `compat.supportsMessageThreads` is on), a request sends only the messages added since
  the previous reply, and the server continues the conversation. Pi builds the full request, passes
  it to `before_provider_request` handlers, and then decides (`prepareThreadRequest` in `pi-ai`'s
  `api/anthropic-messages.js`): when the messages it already sent hash the same as before, it sends
  a `continue` without `system` and `tools`; otherwise it sends the full request as a new thread
  (`create`). It can continue only when the previous reply carried a message id, the session has an
  id, and cache retention is not `"none"` (`recordThreadReply`). SoL-Pi changes messages already
  sent in two ways: Observation Pack replaces an earlier large tool result in the `context` event
  (a result over its size threshold, after its full sends), and a compaction replaces the
  conversation with a summary.
- **Idle prompt cache warming is the default (1.5.1).** `cacheWarming` defaults to `"idle"`, so Pi
  also replays the last request between agent runs, for up to 30 minutes. A replay sends no
  `thread` continuation (`disableContinuation`). Online Context Compact already ignores a replay,
  which reaches `before_provider_request` with no `context` event.
- **Tool fixes SoL-Pi wraps (1.5.1).** The bash tool's `Command timed out` error now also reports
  the exit code (Action Fusion's `then_run` runs commands through `createBashToolDefinition`); the
  edit tool's line-ending fix (Action Fusion wraps `createEditToolDefinition`).
- **RPC mode fixes (1.5.1).** An extension's `ctx.shutdown()` while idle now shuts Pi down at once,
  and closing stdin with SIGTERM is handled. `sol-pi-axi verify` and the check at the end of
  `install` drive Pi in RPC mode and close its stdin (`run_check` in `sol_pi_axi/check.py`).
- **Extension loading through a symlinked path (1.5.1)** resolves the entry file's real path before
  importing it. `sol_pi_axi/check.py` attributes load errors to an extension by its path.
- **Session lifecycle fixes (1.5.1).** Prompts and session-tree navigation no longer overlap during
  asynchronous input hooks (Online Context Compact has `input` and `session_before_tree`
  handlers); session disposal waits for active tools; a reload waits for a running compaction
  (SoL-Pi has `session_shutdown` handlers and starts compactions).
- **Extension changelog notes no longer repeat across a prerelease suffix (1.5.1)**, which touches
  CR-SLP-002's changelog decision.
- **Sessions whose folder is gone can be forked (1.5.2)**, at startup, on `/resume`, on `/import`
  and through `ctx.switchSession()`. SoL-Pi calls none of these.
- **`GrepOperations.readFile` is no longer called for context lines (1.5.1, breaking).** SoL-Pi
  defines no grep operations.
- **Package identity and project overrides**, unchanged in 1.5.1 and 1.5.2 but met on 2026-11-14:
  Pi replaces a user-level package with a project-level one only when both name the same npm
  package, git repository or local path. An npm source and a local checkout of the same package
  both load. A project entry
  `{ "source": "npm:@anthill-tec/sol-pi", "autoload": false, "extensions": ["-src/sol-pi/index.ts"] }`
  turns the user-level copy off for that project. When no user-level copy exists (for example after
  `sol-pi-axi uninstall`), the same entry is an ordinary project package, and Pi tries to install it
  into the project.

## Scope

### §S1 — Pi 1.5.2 as the development dependency

**Surfaces:** `package.json`, `bun.lock`.

- The four `@earendil-works/pi-*` development dependencies are exactly `1.5.2`.
- `peerDependencies` keep their `>=0.84.2` floor.
- `bun.lock` resolves every `@earendil-works/pi-*` package at 1.5.2, and `bun audit
  --audit-level=high` reports no vulnerability.

### §S2 — Pi 1.5.2 joins the tested set

**Surfaces:** `scripts/check-pi-compat.mjs`, `sol_pi_axi/pi.py`, `tests/package.test.ts`,
`tests/test_sol_pi_axi_install.py`, `docs/research/DN-sol-pi-axi.md`.

- `TESTED_PI_VERSIONS` is `0.84.2`, `1.0.4`, `1.3.0`, `1.5.0`, `1.5.2` in both
  `scripts/check-pi-compat.mjs` and `sol_pi_axi/pi.py`. Pi 1.5.1 is not added: no run tested it.
- The mixed-internal-packages warning advises installing Pi 1.5.2, the latest tested release.
- `sol-pi-axi install` on Pi 1.5.2 gives no untested-version warning; on Pi 1.5.1 it still warns,
  and the warning lists the five tested versions.
- The full Bun and Python suites run on the 1.5.2 development dependency, including the Python
  integration tier, which runs `sol-pi-axi verify` and `install`'s check against the real Pi. A
  test that fails because of a Pi 1.5.1 or 1.5.2 change is fixed at the cause: a cause in SoL-Pi's
  code is fixed there with a test that fails before the fix. No test is skipped or loosened to pass.
- `docs/research/DN-sol-pi-axi.md` D6 gains a line recording the check's run on Pi 1.5.2 (this
  spec's approval covers that edit).
- The check against a Bun global install of Pi 1.5.2 is a measurement Mainline records in the CR's
  close-out; the durable check is the fake-release test.

### §S3 — The Pi 1.5.1 and 1.5.2 changes, reviewed

**Surfaces:** `docs/compatibility.md`, a test file for the Pi 1.5.1/1.5.2 changes.

- `docs/compatibility.md` lists each change from Context, and any the §S2 run finds, with SoL-Pi's
  decision for each, in a section for Pi 1.5.1 and 1.5.2 after the one for 1.4 and 1.5.0.
- A change whose code path existing tests already run on the development dependency (the tool
  fixes, the RPC fixes, symlinked loading, the session lifecycle fixes, the changelog prerelease
  fix) has the decision "covered by the suite on Pi 1.5.2" and names those tests.
- A change SoL-Pi does not meet (session fork, grep operations) is listed with the reason and has
  no test.
- **Idle cache warming.** The decision names the existing replay test. No new test.
- **Message threads.** The decision states that SoL-Pi's changes to messages already sent reach the
  model under message threads: a request after an Observation Pack replacement or a compaction is
  sent in full as a new thread, and otherwise requests continue the thread. Tests run a real Pi
  session (`createAgentSession`) with SoL-Pi's entry point loaded and every feature enabled, on a
  provider registered with `api: "anthropic-messages"`, `compat.supportsMessageThreads: true` and
  `baseUrl` at a loopback recorder whose replies carry a message id. The session has an id, and
  cache retention is not `"none"`. The tests check, in the recorded request bodies:
  - consecutive requests whose earlier messages are unchanged: the later one is a `continue`
    carrying only the new messages;
  - an Observation Pack replacement: the request just before the replacement is a `continue`, the
    request that first carries the replacement is a `create` holding every message, the
    replacement text and no copy of the original result;
  - a compaction of the session: the next request is a `create`;
  - a `before_provider_request` handler, on a request Pi sends as a `continue`, receives `system`,
    `tools` and every message.
- **Package identity.** The decision states that a project that registers a SoL-Pi checkout beside
  a user-level npm install loads both, gives the project entry from Context, and says to remove the
  entry when no user-level SoL-Pi is installed. Tests resolve a fabricated project and agent
  directory through Pi's `DefaultPackageManager`:
  - with a local SoL-Pi source and a user-level npm one, both entry points are enabled without the
    entry, and only the local one with it;
  - with the entry and no user-level npm SoL-Pi, Pi asks to install `npm:@anthill-tec/sol-pi`
    (`resolve`'s missing-package callback).

### §S4 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `docs/compatibility.md`, `CONTRIBUTING.md`,
`THIRD_PARTY_NOTICES.md`, `CHANGELOG.md`, `tests/install-guide.test.ts`.

- Pi 1.5.2 is the latest tested release and the documented default install; 1.5.0, 1.3.0, 1.0.4
  and 0.84.2 stay listed as tested. No install command names `@1.5.0`, and no sentence calls 1.5.0
  the default or the development dependency.
- `CONTRIBUTING.md` tells a developer who also has SoL-Pi installed user-wide to add the project
  entry, to remove it when no user-level copy is installed, and points to the compatibility
  document for the reason.
- `THIRD_PARTY_NOTICES.md` lists the four Pi packages at 1.5.2.
- `CHANGELOG.md` `[Unreleased]` records Pi 1.5.2 support.

## Acceptance criteria

- [x] **§S1** `package.json` `devDependencies` has the four Pi packages at exactly `1.5.2`;
      `peerDependencies` is unchanged.
- [x] **§S1** Every `@earendil-works/pi-*` entry in `bun.lock` is 1.5.2, and `bun audit
      --audit-level=high` reports no vulnerability.
- [x] **§S2** `bun scripts/check-pi-compat.mjs --strict` prints `Pi compatibility: OK` with no
      warning and exits 0 against the development dependency.
- [x] **§S2** A `tests/package.test.ts` case runs the check with `--strict` against a fake Pi 1.5.2
      that exports its own `VERSION` and whose internal packages are 1.5.2, and expects exit 0 with
      no warning; the same case for a fake Pi 1.5.1 expects the untested-version warning.
- [x] **§S2** The mixed-internal-packages test expects `install Pi 1.5.2` in the warning.
- [x] **§S2** `sol_pi_axi.pi.TESTED_PI_VERSIONS` is the five versions, and the existing Python test
      that compares it with the script's list passes.
- [x] **§S2** A Python test runs `install` against the stub Pi at version `1.5.2` and expects no
      untested-version warning; at `1.5.1` it expects the warning, naming all five tested versions.
- [x] **§S2** The Bun client's and the Python client's gates on the 1.5.2 development dependency
      pass every test, including the Python integration tier against the real Pi, and add no skip;
      the Bun count is 529 plus this CR's new tests, the Python count 371 plus this CR's new tests.
- [x] **§S2** `docs/research/DN-sol-pi-axi.md` D6 records the run on Pi 1.5.2.
- [x] **§S2** The close-out records `check-pi-compat.mjs --strict` against the Bun global install of
      Pi 1.5.2, with its output line and exit status.
- [x] **§S3** `docs/compatibility.md` lists every change from Context, and any the §S2 run found,
      each with a decision; each decision that states behaviour names its test.
- [x] **§S3** Message threads, unchanged messages: in the session described in §S3, the second of
      two consecutive requests with unchanged earlier messages is recorded with `thread.type`
      `"continue"` and only the messages added after the first reply.
- [x] **§S3** Message threads, Observation Pack: in that session, a tool result over Observation
      Pack's threshold is sent in full as often as Observation Pack sends it, with every request
      after the first a `continue`; the request that first carries the replacement is recorded
      with `thread.type` `"create"`, every message, the replacement text and no copy of the
      original result.
- [x] **§S3** Message threads, compaction: in that session, the request after a compaction is
      recorded with `thread.type` `"create"`.
- [x] **§S3** Message threads, handler payload: in that session, a `before_provider_request` handler
      receives `system`, `tools` and every message on a request recorded as a `continue`.
- [x] **§S3** Package identity: the two `DefaultPackageManager` cases of §S3 pass.
- [x] **§S4** `tests/install-guide.test.ts` passes with the five tested versions and 1.5.2 as the
      latest; README, `agents-install.md` and `docs/compatibility.md` each name the five tested
      versions; no install command in README or `agents-install.md` names `@1.5.0`; the four Pi
      rows of the `THIRD_PARTY_NOTICES.md` table read 1.5.2.
- [x] **§S4** `CONTRIBUTING.md` holds the project entry character for character as the
      compatibility document gives it, and says when to remove it.
- [x] **§S4** `CHANGELOG.md` `[Unreleased]` has an entry for Pi 1.5.2 support.
- [x] **Gate** `pre-merge-gate` passes on both stacks.

## Estimated size

8 points.

## Risks

- The suite runs on one Pi version at a time. Claims for 1.5.0, 1.3.0, 1.0.4 and 0.84.2 rest on
  earlier runs; this CR does not re-run them.
- The message-thread tests drive Pi's request code with a loopback recorder. They show what Pi
  sends; they do not show what Anthropic bills for a continued request, and this CR does not
  measure it. Online Context Compact's cost model is unchanged.
- Every Observation Pack replacement and every compaction ends the current thread, so the next
  request is sent in full. That is Pi's documented fallback, and it is what Pi sent on every
  request before 1.5.1.
- A Pi 1.5.1 or 1.5.2 difference that needs a design change in a mechanism becomes its own CR.
- The message-thread tests depend on Pi 1.5.2's `compat.supportsMessageThreads` model setting and
  on Observation Pack's threshold and send count. A later Pi or a tuning change may move them; the
  tests then fail, which is when the decision has to be re-checked.
- CR-SLP-014 also edits `scripts/check-pi-compat.mjs`; it is sequenced after this CR.

## Non-goals

- Adding Pi 1.5.1 to the tested set, dropping a version from it, or raising the 0.84.2 floor.
- A CI matrix over Pi versions.
- Adopting Pi 1.5.1/1.5.2 features: `compat.supportsMessageThreads` settings, cache warming
  decisions (`cache_warming_decision`), Markdown transformer options, `compat.promptCacheKeyMode`.
- Tuning Observation Pack or Online Context Compact to keep message threads alive longer.
- A guard in SoL-Pi against being loaded twice in one session (user ruling 2026-11-14: a
  development-only condition; the project entry is the remedy).
- Making the stub Pi of the Python tests answer as 1.5.2; the integration tier runs the real one.
- Renaming test fixtures that default to Pi 1.5.0, which stays a tested version.
