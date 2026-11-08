# CR-SLP-006 — Online Context Compact defers a boundary compaction while sub-agents run

**Status:** PENDING · Pre-review: ran — touches another project's surface (pi-subagents' published service); reported by Crucible's Mainline, Sandesh message #1531
**Type:** defect
**Priority:** P1 — a boundary compaction stops every running background sub-agent of a Model B orchestrator
**Depends on:** CR-SLP-001
**Labels:** online-context-compact, compatibility, subagents
**Phase:** 0.1.0 · wave 1
**Design reference:** `docs/compatibility.md` (`## Online Context Compact`); Crucible's fix request, Sandesh message #1531

## Context

When an `update_plan` call completes a step and Online Context Compact's economics favour a
boundary compaction, `createOnlineContextCompactExtension`'s `turn_end` handler sets `selected` and
calls `context.abort()` to stop the turn, then compacts in `agent_settled`. That is OCC's only
`context.abort()`.

pi-subagents (`@gotgenes/pi-subagents` 25.0.5, `InterruptHandler`) listens to the parent run's
abort signal from every `turn_start`. When it fires, it calls `abortAll()`, stopping every running
and queued sub-agent, unless the user set `abortAllOnInterrupt` to false. It treats the signal as
the user's ESC. SoL-Pi's abort cannot be told apart from ESC, so a boundary compaction stops the
orchestrator's background agents, recorded as "Stopped (user request)". Crucible's session lost two
RED agents this way on 2026-11-04 (#1531). Changing pi-subagents is ruled out (the user, #1531).

pi-subagents' extension factory publishes its service on `globalThis` under
`Symbol.for("@gotgenes/pi-subagents:service")` (`publishSubagentsService`), and its session-shutdown
handler deletes it (`unpublishSubagentsService`). The service's `hasRunning()` is true while any of
its agents is running or queued, which covers everything `abortAll()` would stop; foreground agents
finish inside their tool call, before `turn_end`. The slot is one value for the whole process, and
child sessions inherit the parent's extensions: each child's pi-subagents publishes its own service
over the parent's, and deletes the slot when the child shuts down. So the slot holds the parent's
service only until the first child starts.

Pi's own threshold compaction uses its own abort controller and never fires the run signal; OCC
cancels it only while `selected` is set.

## Scope

### §S1 — No boundary compaction while sub-agents run

**Surfaces:** `src/sol-pi/extensions/online-context-compact/extension.ts`, a new module for the
sub-agent probe.

- **Capture.** At its first `session_start`, OCC reads the service in the slot and keeps that
  reference for the life of the extension instance. Every extension factory, pi-subagents' included,
  has run by then, and no child session exists yet. A reload creates a new instance, which captures
  again. OCC never reads the slot after capture, so a child's service, or a deleted slot, does not
  change what it sees.
- **Probe.** The captured service's `hasRunning()`.
  - No service captured, or no `hasRunning` function: no sub-agents; behaviour is unchanged.
  - `hasRunning()` throws or returns a non-boolean: treated as running (failing safe for the
    agents).
- **Where it runs.** In the `turn_end` handler, after the economic decision says to compact and
  immediately before `selected` is set and `context.abort()` is called. A step whose economics do
  not compact is unaffected and records nothing.
- **Deferral.** While the probe says running, the compaction is not selected and the turn is not
  aborted. OCC appends a session entry `sol-pi-online-context-compact-deferred` with data
  `{ stepId, reason }`: the completed plan step's id and `"subagents-running"`. In `tui` mode it calls `ui.notify` once with "Online compaction
  deferred: sub-agents are running" at level `info`; other modes show nothing. The economic state
  is left as after a decision not to compact, so the next safe point decides afresh.
- **Next safe point.** The next completed step re-runs the economic decision. SoL-Pi does not
  compact on its own when the last agent finishes.
- ESC still stops the agents: SoL-Pi changes nothing in pi-subagents' interrupt handling.
- SoL-Pi imports nothing from pi-subagents and does not depend on it.

### §S2 — Documentation and changelog

**Surfaces:** `docs/compatibility.md` (`## Online Context Compact`), `CHANGELOG.md`.

- The Online Context Compact section describes the deferral and its entry and notice, and the
  integration: `@gotgenes/pi-subagents` 25.0.5, the `Symbol.for("@gotgenes/pi-subagents:service")`
  slot, `hasRunning()`, the capture at `session_start` and why (child sessions overwrite and delete
  the slot), and the fail-safe rule.
- `CHANGELOG.md` `[Unreleased]` records the fix under Fixed.

## Acceptance criteria

Tests run Online Context Compact through a Pi agent session (faux model) with fake services placed
in the slot, and clear the slot afterwards.

- [ ] **§S1** With a fake service whose `hasRunning()` is true, an `update_plan` step completion
      whose economics would compact does not abort the turn (no `aborted` stop), does not compact,
      and appends one `sol-pi-online-context-compact-deferred` entry whose data is exactly
      `{ stepId: <the completed step's id>, reason: "subagents-running" }`.
- [ ] **§S1** A pi-subagents-style listener on the run's abort signal, attached at `turn_start`, is
      not fired by that step completion; a user abort (`session.abort()`) during a later run still
      fires it.
- [ ] **§S1** Service A (`hasRunning()` true) is in the slot at `session_start`; afterwards the slot
      is replaced by service B (`hasRunning()` false), or deleted. The step completion is still
      deferred.
- [ ] **§S1** With `hasRunning()` true and economics that do not compact, no deferred entry is
      appended and no notice is shown.
- [ ] **§S1** With no service in the slot at `session_start`, and with `hasRunning()` false, the
      step completion compacts exactly as today (the existing compaction tests pass unchanged).
- [ ] **§S1** With `hasRunning()` throwing, or returning a non-boolean, the compaction is deferred.
- [ ] **§S1** After a deferral, the next step completion with `hasRunning()` false compacts when the
      economics favour it.
- [ ] **§S1** In `tui` mode a deferral calls `ui.notify` once with §S1's text and level; in other
      modes it calls nothing.
- [ ] **§S1** `git grep -n -E "(from|import\()\s*[\"']@gotgenes/pi-subagents" -- src` returns nothing,
      and `package.json` has no `@gotgenes/pi-subagents` entry.
- [ ] **§S2** `docs/compatibility.md` names `@gotgenes/pi-subagents` 25.0.5, the symbol,
      `hasRunning()`, the capture at `session_start` and the deferral; `CHANGELOG.md`
      `[Unreleased]` records the fix.
- [ ] **Gate** `pre-merge-gate` passes.

## Estimated size

3 points. One captured probe, one guard before the abort, a session entry and notice, tests through
a session.

## Risks

- A long-running fleet postpones compaction for as long as agents run; context grows meanwhile.
  Pi's own threshold compaction still protects the window.
- A future pi-subagents release could rename the symbol or the method, or publish after
  `session_start`. The probe then sees no service, and the defect returns; the documentation names
  the version it was built against.

## Non-goals

- Changing pi-subagents or its `abortAllOnInterrupt` setting.
- Compacting automatically when the last sub-agent finishes.
- Telling SoL-Pi's abort apart from ESC in Pi itself.
- Other extensions that react to the abort signal.
