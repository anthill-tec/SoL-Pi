# CR-SLP-003 — Tell the model when to use `then_run` on `edit` and `write`

**Status:** PENDING · Pre-review: due — touches another project's surface (Model B relies on SoL-Pi's tool registrations for tool guidance, message #1516 item 6)
**Type:** feature
**Priority:** P1 — Model B projects learn `then_run` only from its parameter description
**Depends on:** CR-SLP-001
**Labels:** action-fusion, prompts
**Phase:** 0.1.0 · wave 1
**Design reference:** `docs/compatibility.md` (Action Fusion); Model B's request, Sandesh message #1516 item 6

## Context

Action Fusion replaces Pi's `edit` and `write` with versions that take an optional `then_run`
(`createActionFusionExtension`). Each registration spreads Pi's built-in definition, so it carries
Pi's own `promptSnippet` and `promptGuidelines` unchanged. On Pi 1.5.0 those are:

- `edit`: snippet "Make precise file edits with exact text replacement, including multiple disjoint
  edits in one call"; guidelines "Use edit for targeted changes. Batch changes to one file in a
  single call." and the `edits[].oldText` matching rule.
- `write`: snippet "Create or overwrite files"; guideline "Use write only for new files or complete
  rewrites."

Neither mentions `then_run`. The model meets it only in the parameter's description
(`EDIT_THEN_RUN_DESCRIPTION`, `WRITE_THEN_RUN_DESCRIPTION`). SoL-Pi's own tools, `obs_recall` and
`update_plan`, carry their own snippet and guidelines. Model B asked for the same on `edit` and
`write`, saying when to use `then_run`; it never copies that text into a project.

Pi builds the system prompt's rules from each active tool's `promptGuidelines`, dropping a rule
whose trimmed text it has already added (`buildRules`).

## Scope

### §S1 — Snippet and guidelines on the fused tools

**Surfaces:** `src/sol-pi/extensions/action-fusion/index.ts`.

- Each fused tool's `promptSnippet` is Pi's snippet for that tool followed by a short clause
  saying it can run a follow-up command (`then_run`). When the Pi version's definition has no
  snippet, it is SoL-Pi's clause alone, as a full sentence.
- Each fused tool's `promptGuidelines` is Pi's guidelines for that tool, unchanged and in order,
  followed by SoL-Pi's `then_run` guidelines. These say, for that tool by name:
  - use `then_run` when the next step after the change is a command on the changed file or its
    project (run, build, test, check, install, restart), so both happen in one call;
  - leave it out when the next step needs the change's result read first, or when the command
    keeps running (a server, a watcher), which is started separately;
  - the command runs only after a successful change; a non-zero exit fails the call but keeps the
    change, so the next call fixes forward and does not repeat the change.
- Every SoL-Pi guideline names its tool, so the `edit` and `write` rules stay distinct after
  Pi drops repeated rules.
- With Action Fusion disabled, SoL-Pi registers no `edit` or `write`, and Pi's built-in guidance is
  unchanged.

### §S2 — Documentation and changelog

**Surfaces:** `docs/compatibility.md` (`## Action Fusion`), `CHANGELOG.md`.

- The Action Fusion section states that the fused tools add `then_run` guidance to Pi's own
  guidance for `edit` and `write`.
- `CHANGELOG.md` `[Unreleased]` records the guidance.

## Acceptance criteria

- [ ] **§S1** With Action Fusion enabled, the registered `edit` and `write` each have a
      `promptSnippet` that starts with Pi's snippet for that tool and mentions `then_run`.
- [ ] **§S1** Each registered tool's `promptGuidelines` starts with Pi's guidelines for that tool,
      in Pi's order, and adds the three `then_run` guidelines §S1 lists, each naming the tool.
- [ ] **§S1** When Pi's definition has no `promptSnippet` or `promptGuidelines`, the tool still
      registers, with SoL-Pi's snippet sentence and its three guidelines alone.
- [ ] **§S1** A session started with Action Fusion enabled (Pi's agent session, faux model) has a
      system prompt whose tool list shows the new snippets and whose rules contain all six
      SoL-Pi guidelines once each and Pi's `edit` and `write` guidelines once each.
- [ ] **§S1** A session with Action Fusion disabled has the same `edit` and `write` snippets and
      rules as Pi's built-in tools.
- [ ] **§S2** The Action Fusion documentation and `CHANGELOG.md` `[Unreleased]` describe the
      guidance.
- [ ] **Gate** `pre-merge-gate` passes.

## Estimated size

3 points. One registration change, a fallback branch and a system-prompt test.

## Risks

- Extra rules add tokens to every request of a session with Action Fusion enabled. The three
  guidelines per tool are kept to one sentence each.

## Non-goals

- Changing `then_run`'s behaviour or its parameter descriptions.
- Guidance for codemode scripts that call `edit` or `write` through `ctx.executeTool()`.
- Text in Model B's scaffolded `AGENTS.md`.
