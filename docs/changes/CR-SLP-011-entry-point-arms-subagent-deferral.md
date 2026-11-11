# CR-SLP-011 — The packaged extension arms Online Context Compact's sub-agent deferral

**Status:** PENDING · Pre-review: ran — touches another project's surface (pi-subagents' published service); reported by Crucible's Mainline, Sandesh message #1606
**Type:** defect
**Priority:** P0 — in 0.1.0 a boundary compaction stops every running background sub-agent; both customers are on a workaround
**Depends on:** CR-SLP-006
**Labels:** online-context-compact, compatibility, subagents, hotfix
**Phase:** 0.1.1 · wave 1
**Design reference:** `docs/compatibility.md` (`## Online Context Compact`); CR-SLP-006; Crucible's report, Sandesh message #1606

## Context

CR-SLP-006 made Online Context Compact (OCC) defer a boundary compaction while pi-subagents has
running or queued agents. OCC captures pi-subagents' service in its own `session_start` handler
(`createOnlineContextCompactExtension`: `subagentsRunning ??= captureSubagentsProbe()`), and its
`turn_end` handler asks the captured probe before it selects a compaction and calls
`context.abort()`.

The packaged entry point (`createSolPiExtension` in `src/sol-pi/index.ts`, the `pi.extensions`
entry of `package.json`) registers the features inside its own first `session_start` handler,
through `registerConfiguredFeatures`, because the configuration needs that event's context. OCC's
`session_start` handler is therefore registered while `session_start` is already being delivered.
Pi delivers an event to the handlers that were registered when the delivery began
(`snapshotEventHandlers` in Pi 1.5.0 and 1.5.2), so OCC's handler does not run for that event. On a
session that starts normally it never runs: `subagentsRunning` stays undefined, the `turn_end`
check is falsy, and the compaction is selected and the run stopped as before CR-SLP-006.

Evidence, 2026-11-11:

- Crucible's session lost a just-dispatched GREEN agent ("Stopped (user request)", 572 ms, 0 tool
  uses) on SoL-Pi 0.1.0 from npm (#1606).
- The same turn shape on SoL-Pi's own session stopped a probe agent after 0.3 s; the session holds
  no `sol-pi-online-context-compact-deferred` entry.
- On Pi 1.5.2, a handler registered during the first `session_start` is not called at startup. It
  is called when a second `session_start` reaches the same extension instance.
- With pi-subagents 25.0.5, a service captured at `session_start` reports `hasRunning()` true at
  the dispatch turn's `turn_end`. The slot itself already holds the child's service by then, so
  reading the slot at the decision is not a fix.

CR-SLP-006's tests register OCC with its own factory, never through `createSolPiExtension`, so they
pass. OCC's `session_start` handler also restores OCC's state; the handlers that run before a
boundary decision (`context`, `before_provider_request`, `input`, and the `update_plan` tool)
restore it on first use (`ensureRestored`), so only the capture is lost. OCC is the only feature
that registers a `session_start` handler.

## Scope

### §S1 — The entry point captures the sub-agents probe at `session_start`

**Surfaces:** `src/sol-pi/index.ts` (`registerConfiguredFeatures`),
`src/sol-pi/extensions/online-context-compact/index.ts` (`registerOnlineContextCompact`),
`src/sol-pi/extensions/online-context-compact/extension.ts` (`OnlineContextCompactOptions`,
`createOnlineContextCompactExtension`).

- **Capture.** When the configuration enables Online Context Compact, `registerConfiguredFeatures`
  calls `captureSubagentsProbe()` and passes the probe to OCC as it registers OCC. With the feature
  disabled it does not read the slot. The entry point calls `registerConfiguredFeatures` inside its
  first `session_start`, so the slot is read at the moment CR-SLP-006 specified: every extension
  factory has run and no child session of this session exists.
- **Option.** `OnlineContextCompactOptions` gains an optional `subagentsRunning` probe, and
  `registerOnlineContextCompact` an optional third parameter that it forwards. OCC starts with the
  given probe; without one it captures at its own first `session_start`, as today.
- **Never re-read.** OCC keeps the first probe it holds. Neither a later `session_start` nor the
  `turn_end` decision reads the slot again.
- **Comments.** The comments on `subagentsRunning` (`extension.ts`) and on `captureSubagentsProbe`
  (`subagents.ts`) state both capture points. A comment at `registerConfiguredFeatures` states that
  a `session_start` handler a feature registers there misses the first `session_start`.
- CR-SLP-006's behaviour is otherwise unchanged: the probe's rules, the deferral entry, the notice,
  the next safe point. SoL-Pi still imports nothing from pi-subagents.

### §S2 — Documentation and changelog

**Surfaces:** `docs/compatibility.md` (`## Online Context Compact`), `CHANGELOG.md`.

- The Online Context Compact section says that the packaged extension captures the service while
  it registers its features during `session_start`.
- `CHANGELOG.md` `[Unreleased]` records under Fixed that 0.1.0 never deferred a boundary
  compaction for running sub-agents, and that this release does.

## Acceptance criteria

The tests run through a Pi agent session (faux model) with fake services in the slot, as
`tests/online-context-compact-subagents.test.ts` does. "Both registrations" means OCC registered by
`createOnlineContextCompactExtension` alone, and OCC registered by `createSolPiExtension` with a
configuration that enables only Online Context Compact. Under `createSolPiExtension` the scenarios
take `keepRecentTokens` from the session's `compaction` settings and use a configuration with
`cacheWriteReadRatio: 0`, because `registerOnlineContextCompact` forwards only the ratio.

- [ ] **§S1** Every scenario of `tests/online-context-compact-subagents.test.ts` runs under both
      registrations and passes: deferral while `hasRunning()` is true; the `turn_start` abort
      listener; the captured service kept when the slot is replaced or deleted after
      `session_start`; no deferral when the economics do not compact; compaction unchanged with no
      service, with no `hasRunning` function and with `hasRunning()` false; deferral when
      `hasRunning()` throws or returns a non-boolean; compaction at the next step after a deferral;
      the notice in `tui` mode and none in `print`, `json` and `rpc` modes.
- [ ] **§S1** Under both registrations, with no service in the slot at `session_start` and a
      service whose `hasRunning()` is true published afterwards, the step completion compacts and
      that service's `hasRunning()` is never called.
- [ ] **§S1** Under both registrations, service A (`hasRunning()` true) is in the slot at the first
      `session_start`; the slot is then replaced by service B (`hasRunning()` false) and a second
      `session_start` is delivered to the same extension instance. A favourable step completion is
      still deferred, and B's `hasRunning()` is never called.
- [ ] **§S1** With a configuration that disables Online Context Compact, `registerConfiguredFeatures`
      does not read the slot (a getter placed on the slot is never called).
- [ ] **§S1** The comments on `subagentsRunning` and `captureSubagentsProbe` name both capture
      points, and a comment at `registerConfiguredFeatures` states the missed-first-event rule.
- [ ] **§S1** Without the change to `registerConfiguredFeatures`, the scenarios that expect a
      deferral fail under the `createSolPiExtension` registration (the RED evidence).
- [ ] **§S1** `git grep -n -E "(from|import\()\s*[\"']@gotgenes/pi-subagents" -- src` returns
      nothing, and `package.json` has no `@gotgenes/pi-subagents` entry.
- [ ] **§S2** `docs/compatibility.md` states that the packaged extension captures the service
      while it registers its features during `session_start`, and no longer says that Online
      Context Compact always captures at its own first `session_start`; `CHANGELOG.md`
      `[Unreleased]` records the fix under Fixed.
- [ ] **Gate** `pre-merge-gate` passes for both stacks.

## Estimated size

2 points. One capture moved to the entry point, one optional option, the existing scenarios run
under a second registration.

## Risks

- A future feature that registers its own `session_start` handler from
  `registerConfiguredFeatures` misses the first event in the same way. The comment at
  `registerConfiguredFeatures` states the rule; nothing enforces it.
- With the deferral armed, a long-running fleet postpones boundary compaction for as long as
  agents run, as CR-SLP-006 accepted. Pi's own threshold compaction still protects the window.
- A child session that does not load pi-subagents (`excludedExtensionPackages`) captures whatever
  the slot holds: its parent's service, a sibling's, or none. With the parent's, it never
  boundary-compacts, since it is itself one of the parent's running agents; Pi's threshold
  compaction still applies. This is CR-SLP-006's capture rule, armed for the first time by this CR.

## Non-goals

- Delivering the first `session_start` to every handler a feature registers (a general replay).
- Registering the features before `session_start`.
- Changing pi-subagents, or reading its service at the compaction decision.
- A test against the real pi-subagents package.
- The two Online Context Compact state entries seen per save when SoL-Pi is installed twice.
