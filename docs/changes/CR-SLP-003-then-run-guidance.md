# CR-SLP-003 — Tell the model when to use `then_run` on `edit` and `write`

**Status:** COMPLETED · Pre-review: ran — touches another project's surface (Model B relies on SoL-Pi's tool registrations for tool guidance, message #1516 item 6)
**Type:** feature
**Priority:** P1 — Model B projects learn `then_run` only from its parameter description
**Depends on:** CR-SLP-001
**Labels:** action-fusion, prompts
**Phase:** 0.1.0 · wave 1
**Design reference:** `docs/compatibility.md` (Action Fusion); Model B's request, Sandesh message #1516 item 6

## Context

Action Fusion replaces Pi's `edit` and `write` with versions that take an optional `then_run`
(`createActionFusionExtension`). Each registration spreads Pi's built-in definition
(`createEditToolDefinition`, `createWriteToolDefinition`), so it carries Pi's own `promptSnippet`
and `promptGuidelines` unchanged. Every supported Pi (0.84.2, 1.3.0 and 1.5.0 checked) gives both
tools a snippet and guidelines. Their text differs between versions: Pi 1.5.0 has two `edit`
guidelines and one `write` guideline; Pi 1.3.0 and 0.84.2 have four `edit` guidelines. None
mentions `then_run`.

The model meets `then_run` only in the parameter's description (`EDIT_THEN_RUN_DESCRIPTION`,
`WRITE_THEN_RUN_DESCRIPTION`): "Command to run next on this file after the edit succeeds — e.g.
run, build, start/restart, install, or check it; optional timeout in seconds …".
`createThenRunSchema` sets no default timeout, so a command that keeps running (a server started in
the foreground) holds the call until it exits or its timeout ends. The command runs through
`createBashToolDefinition(ctx.cwd, …)`, in the session's working directory.

SoL-Pi's own tools, `obs_recall` and `update_plan`, carry their own snippet and guidelines. Model B
asked for the same on `edit` and `write`, saying when to use `then_run`; it never copies that text
into a project. Model B's Pi hook will check `then_run.command` as a shell call; a hook that blocks
a tool call stops the whole call, so neither the change nor the command runs.

Pi builds the system prompt from each active tool's snippet and `promptGuidelines`, dropping a rule
whose trimmed text it has already added. With a custom system prompt, Pi omits the tool list and
the rules on every supported version; in codemode `"only"` mode, `edit` and `write` are not
declared to the model and their rules are dropped.

## Scope

### §S1 — Snippet and guidelines on the fused tools

**Surfaces:** `src/sol-pi/extensions/action-fusion/index.ts`.

- A pure exported helper builds a fused tool's `promptSnippet` and `promptGuidelines` from a base
  tool definition and the tool's name. `createActionFusionExtension` uses it for `edit` and
  `write`.
- `promptSnippet` is the base snippet followed by a short clause saying the tool can run a
  follow-up command (`then_run`). When the base has no snippet, it is SoL-Pi's clause alone, as a
  full sentence.
- `promptGuidelines` is the base guidelines, unchanged and in order (none when the base has none),
  followed by three SoL-Pi guidelines, one sentence each, each naming the tool and `then_run`:
  1. use `then_run` when the next step after the change is a command that finishes (run, build,
     test, check, install, or restart a service); it runs in the session's working directory;
  2. leave it out when the next step needs the change's result read first, or when the command
     keeps running (a server or a watcher in the foreground), which is started separately;
  3. the command runs only after a successful change; a non-zero exit fails the call but keeps the
     change, so the next call fixes forward and does not repeat the change.
- The six SoL-Pi guidelines are distinct after trimming, so Pi keeps all of them.
- With Action Fusion disabled, SoL-Pi registers no `edit` or `write`, and Pi's built-in guidance is
  unchanged.

### §S2 — The `then_run` parameter descriptions

**Surfaces:** `EDIT_THEN_RUN_DESCRIPTION`, `WRITE_THEN_RUN_DESCRIPTION`.

- The examples name only commands that finish ("run, build, test, check, install, or restart a
  service"), in place of "start/restart", so the description and guideline 2 agree. The rest of
  each description is unchanged.

### §S3 — Documentation and changelog

**Surfaces:** `docs/compatibility.md` (`## Action Fusion`), `CHANGELOG.md`.

- The Action Fusion section states that the fused tools add `then_run` guidance to Pi's own
  guidance for `edit` and `write`, that the command runs in the session's working directory, and
  that a hook blocking the call stops both the change and the command, so the change is repeated
  without `then_run` or with an allowed command.
- `CHANGELOG.md` `[Unreleased]` records the guidance.

## Acceptance criteria

Every expected Pi snippet or guideline in a test is read at run time from
`createEditToolDefinition` and `createWriteToolDefinition`, never written as a literal, so the tests
hold on every tested Pi version.

- [ ] **§S1** With Action Fusion enabled, the registered `edit` and `write` each have a
      `promptSnippet` that starts with the base tool's snippet and contains `then_run`.
- [ ] **§S1** Each registered tool's `promptGuidelines` equals the base tool's guidelines, in
      order, followed by exactly three entries, each containing the tool's name and `then_run`;
      the six added entries are distinct after trimming.
- [ ] **§S1** The helper, given a base definition with no `promptSnippet` and no
      `promptGuidelines`, returns SoL-Pi's snippet sentence and its three guidelines alone.
- [ ] **§S1** A session with Action Fusion enabled, Pi's default system prompt (no custom prompt,
      no `SYSTEM.md`) and codemode off has a `session.systemPrompt` containing each tool's new
      snippet and, as bullet lines, each of the six SoL-Pi guidelines once and each base
      `edit` and `write` guideline once.
- [ ] **§S1** The same session with Action Fusion disabled has a `session.systemPrompt` whose
      `edit` and `write` snippets and guidelines are the base tools' and contains no `then_run`.
- [ ] **§S2** Neither `then_run` description contains `start/restart`; each names "restart a
      service" among its examples.
- [ ] **§S3** The Action Fusion documentation covers the guidance, the working directory and a
      blocked call; `CHANGELOG.md` `[Unreleased]` records the guidance.
- [ ] **Gate** `pre-merge-gate` passes.

## Estimated size

3 points. One helper, its use in the registration, two description edits and a system-prompt test.

## Risks

- Extra rules add tokens to every request of a session with Action Fusion enabled. Each guideline
  is one sentence.

## Non-goals

- Changing `then_run`'s behaviour, its schema or its timeout.
- Guidance for codemode scripts that call `edit` or `write` through `ctx.executeTool()`, and for
  codemode `"only"` mode, where `edit` and `write` are not declared.
- Text in Model B's scaffolded `AGENTS.md`.
