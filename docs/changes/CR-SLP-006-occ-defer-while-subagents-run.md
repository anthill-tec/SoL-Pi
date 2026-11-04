# CR-SLP-006 — Online Context Compact defers a boundary compaction while sub-agents run

**Status:** PENDING · Pre-review: due — touches another project's surface (pi-subagents' published service); reported by Crucible's Mainline, Sandesh message #1531
**Type:** defect
**Priority:** P1 — a boundary compaction stops every running background sub-agent of a Model B orchestrator
**Depends on:** CR-SLP-001
**Labels:** online-context-compact, compatibility, subagents
**Phase:** 0.1.0 · wave 1
**Design reference:** `docs/compatibility.md` (`## Online Context Compact`); Crucible's fix request, Sandesh message #1531

## Context

When an `update_plan` call completes a step and Online Context Compact selects a boundary
compaction, `createOnlineContextCompactExtension`'s `turn_end` handler calls `context.abort()` to
stop the turn, then compacts in `agent_settled`.

pi-subagents (`@gotgenes/pi-subagents` 25.0.5, `InterruptHandler`) listens to the parent run's
abort signal from every `turn_start`. When the signal fires it calls `abortAll()`, stopping every
running and queued sub-agent, unless the user set `abortAllOnInterrupt` to false. It treats the
signal as the user's ESC. SoL-Pi's abort cannot be told apart from ESC, so a boundary compaction
stops the orchestrator's background agents, recorded as "Stopped (user request)". Crucible's
session lost two RED agents this way on 2026-11-04 (#1531). The child sessions are never
compacted; only the abort reaches them.

pi-subagents publishes its service on `globalThis` under `Symbol.for("@gotgenes/pi-subagents:service")`
(`publishSubagentsService`), removes it at shutdown and reload, and the service's `hasRunning()`
answers whether any agent is running or queued. It also emits lifecycle events on `pi.events`
(`subagents:created`, `:started`, `:completed`, `:failed`, `:resuming`, `:resumed`). Changing
pi-subagents is ruled out (the user, #1531).

## Scope

### §S1 — No boundary compaction while sub-agents run

**Surfaces:** `src/sol-pi/extensions/online-context-compact/extension.ts`, a new module for the
sub-agent probe.

- Before it selects a boundary compaction (and so before `context.abort()`), the `turn_end`
  handler asks whether background work is running. While it is, the compaction is not selected,
  the turn is not aborted, and the step completion is recorded as a deferral.
- The probe reads the service published under `Symbol.for("@gotgenes/pi-subagents:service")` and
  calls its `hasRunning()`. SoL-Pi imports nothing from pi-subagents.
  - No published service, or no `hasRunning` function: no sub-agents; behaviour is unchanged.
  - `hasRunning()` throws or returns a non-boolean: treated as running, so the compaction is
    deferred (failing safe for the agents).
- **Deferral.** The extension appends a session entry `sol-pi-online-context-compact-deferred`
  with the step id and the reason `subagents-running`. In the TUI it shows a one-line notice. The
  economic state is left as it is after a decision not to compact, so the next safe point decides
  afresh.
- **Next safe point.** The next completed step re-runs the economic decision with no sub-agent
  running. SoL-Pi does not compact on its own when the last agent finishes.
- ESC still stops the agents: SoL-Pi changes nothing in pi-subagents' interrupt handling.

### §S2 — Documentation and changelog

**Surfaces:** `docs/compatibility.md` (`## Online Context Compact`), `docs/configuration.md` (Pi
integration), `CHANGELOG.md`.

- The Online Context Compact section describes the deferral, the probe, its fail-safe rule and the
  deferral entry, and names pi-subagents as the integration.
- `CHANGELOG.md` `[Unreleased]` records the fix under Fixed.

## Acceptance criteria

Tests run Online Context Compact through a Pi agent session (faux model) with a fake service
published under the symbol, and remove it afterwards.

- [ ] **§S1** With a fake service whose `hasRunning()` is true, an `update_plan` step completion
      whose economics would compact does not abort the turn (no `aborted` stop), does not compact,
      and appends one `sol-pi-online-context-compact-deferred` entry with the step id and reason
      `subagents-running`.
- [ ] **§S1** A fake pi-subagents-style listener on the run's abort signal, attached at
      `turn_start`, is not fired by that step completion.
- [ ] **§S1** With the service absent, and with `hasRunning()` false, the same step completion
      compacts exactly as today (the existing compaction tests pass unchanged).
- [ ] **§S1** With `hasRunning()` throwing, or returning a non-boolean, the compaction is deferred.
- [ ] **§S1** After a deferral, the next step completion with `hasRunning()` false compacts when
      the economics favour it.
- [ ] **§S1** `git grep -n pi-subagents -- src` shows no import.
- [ ] **§S2** The documentation and `CHANGELOG.md` `[Unreleased]` describe the deferral.
- [ ] **Gate** `pre-merge-gate` passes.

## Estimated size

3 points. One probe, one guard before the abort, a session entry, tests through a session.

## Risks

- A long-running fleet postpones compaction for as long as agents run; context grows meanwhile.
  Pi's own threshold compaction still protects the window.
- A future pi-subagents release could rename the symbol or the method. The probe then sees no
  service, and the defect returns; the documentation names the version it was built against.

## Non-goals

- Changing pi-subagents or its `abortAllOnInterrupt` setting.
- Compacting automatically when the last sub-agent finishes.
- Telling SoL-Pi's abort apart from ESC in Pi itself.
- Other extensions that react to the abort signal.
