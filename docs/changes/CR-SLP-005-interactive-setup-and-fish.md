# CR-SLP-005 — Opt-in interactive setup; the fish script on `sol-pi-setup`

**Status:** PENDING · Pre-review: due — touches another project's surface (Model B passes a terminal through to the interactive run, message #1516 item 3); split from CR-SLP-004 after its pre-review
**Type:** feature
**Priority:** P1 — completes Model B's request and removes the `.bak` and user-wide `pi install` from project setup
**Depends on:** CR-SLP-004
**Labels:** setup, cli, axi, fish, docs
**Phase:** 0.1.0 · wave 1
**Design reference:** the AXI standard (<https://axi.md>); CR-SLP-004 (`sol-pi-setup`); Model B's request, Sandesh message #1516 items 2–4

## Context

CR-SLP-004 ships `sol-pi-setup --install <project dir>`, which never prompts: every value has a
flag. Model B asked for prompts when a person is at a terminal (it passes the terminal through on
interactive runs), and for `PI_NONINTERACTIVE` to forbid them. Under AXI, prompting is opt-in:
`--interactive`.

`setup-sol-pi.fish --install <dir>` today validates the checkout (dependency install, typecheck,
tests, audit), always registers SoL-Pi user-wide with `pi install`, writes
`<dir>/.pi/sol-pi.json` and leaves a `.bak` beside it. It exits 0 when the user cancels a prompt
(including the provider and model prompts) and when its arguments are wrong.
`--uninstall <dir>` restores `sol-pi.json` from a `.bak` when one exists. It clones
`https://github.com/NVlabs/SoL-Pi.git` when SoL-Pi is missing; this project is
`anthill-tec/SoL-Pi`. Pi's `settings.json` lists `enabledModels` as patterns; absent, every model
is enabled.

## Scope

### §S1 — `--interactive`

**Surfaces:** `bin/sol-pi-setup.mjs` and its modules.

- `--interactive` prompts when standard input is a terminal and `PI_NONINTERACTIVE` is unset or
  empty. With `PI_NONINTERACTIVE` set, or without a terminal, it does not prompt and adds a warning
  saying why.
- The prompts cover each mechanism, the reducer's provider and model, and the cache ratio, each
  defaulting to the value CR-SLP-004's rules resolve, after any value flags given with it.
  Provider and model are typed, with the plain `provider/model` entries of `enabledModels` shown as
  suggestions. An enabled reducer with no provider or model fails the run.
- The run then shows the resulting configuration and asks for confirmation. A confirmed run with
  an existing valid project file writes only when the values differ from its effective values.
- Prompts go to standard error; the envelope stays the only standard output.
- Declining the confirmation, end of input at a prompt, or `SIGINT` cancels the run: nothing is
  written, no temporary file is left, the envelope reports `cancelled`, and the exit code is 130.

### §S2 — The fish setup script

**Surfaces:** `setup-sol-pi.fish`, `tests/setup-prompt-flow.test.ts`.

- `--install <dir>` runs the checkout's `bin/sol-pi-setup.mjs --install <dir> --interactive` with
  the terminal passed through, and exits with its code. It installs the checkout's dependencies
  first only when they are missing. It no longer validates the checkout, runs `pi install`, or
  writes a `.bak`. When `pi list` does not show SoL-Pi, it says that the user-wide setup
  (`--install` with no directory) is still needed.
- `--uninstall <dir>` deletes `<dir>/.pi/sol-pi.json` and does not restore from a `.bak`; it names
  a leftover `.bak`.
- `--install` with no directory (the user-wide setup) keeps its phases.
- The clone URL is `https://github.com/anthill-tec/SoL-Pi.git`.
- A cancelled prompt exits 130 at every prompt of both modes; unknown or malformed arguments exit
  2.

### §S3 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `CHANGELOG.md`.

- README and `agents-install.md` document `--interactive`, `PI_NONINTERACTIVE`, exit code 130,
  and the fish script's project mode.
- `CHANGELOG.md` `[Unreleased]` records the interactive mode and the setup script's changes.

## Acceptance criteria

Interactive cases run on a pseudo-terminal (`python3`'s `pty`), against a temporary project, agent
directory and home.

- [ ] **§S1** On a pseudo-terminal, `--interactive` prompts; answering writes the chosen values,
      and the envelope reports `written`.
- [ ] **§S1** `--interactive` with `PI_NONINTERACTIVE=1`, or with standard input not a terminal,
      does not prompt and reports a warning saying why.
- [ ] **§S1** Value flags given with `--interactive` become the prompts' defaults.
- [ ] **§S1** Declining the confirmation, closing input, and sending `SIGINT` each exit 130 with
      `cancelled`, write nothing, and leave no temporary file.
- [ ] **§S1** Standard output of an interactive run decodes as one TOON envelope and contains no
      prompt text.
- [ ] **§S2** `setup-sol-pi.fish --install <dir>` on a temporary project runs no `pi install`,
      leaves no `.bak`, exits with `sol-pi-setup`'s code, and prints the user-wide-setup notice
      when `pi list` does not show SoL-Pi.
- [ ] **§S2** `setup-sol-pi.fish --uninstall <dir>` deletes the project file without restoring a
      `.bak`.
- [ ] **§S2** A cancel at each prompt of the user-wide setup, including the provider and model
      prompts, exits 130; an unknown argument exits 2.
- [ ] **§S2** `git grep -n NVlabs -- setup-sol-pi.fish` returns nothing.
- [ ] **§S3** README and `agents-install.md` cover §S3's items, checked by
      `tests/install-guide.test.ts`; `CHANGELOG.md` `[Unreleased]` records the changes.
- [ ] **Gate** `pre-merge-gate` passes.

## Estimated size

5 points. The prompt flow with its cancel paths, the fish script's rewiring and pseudo-terminal
tests.

## Risks

- The pseudo-terminal tests need `python3`; they skip where it is missing, as the fish prompt tests
  do today.

## Non-goals

- Changing what the user-wide setup configures.
- Removing `setup-sol-pi-interactive.mjs` or `scripts/query-pi-models.mjs`.
