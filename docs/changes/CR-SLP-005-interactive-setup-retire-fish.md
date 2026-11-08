# CR-SLP-005 — Opt-in interactive `setup` and `install`; the fish setup script retired

**Status:** PENDING · Pre-review: due — touches another project's surface (Model B passes a terminal through to the interactive run, message #1516 item 3); re-designed 2026-11-04 (`sol-pi-axi` replaces the fish script)
**Type:** feature
**Priority:** P1 — completes Model B's request and leaves `sol-pi-axi` as the one way to set SoL-Pi up
**Depends on:** CR-SLP-004, CR-SLP-007
**Labels:** setup, cli, axi, python, docs
**Phase:** 0.1.0 · wave 1
**Design reference:** the AXI standard (<https://axi.md>); CR-SLP-004 (`sol-pi-axi setup`);
CR-SLP-007 (`sol-pi-axi install`); Model B's request, Sandesh message #1516 items 2–4

## Context

CR-SLP-004 ships `sol-pi-axi setup <project dir>` and CR-SLP-007 `sol-pi-axi install`; neither
prompts: every value has a flag, and `--non-interactive` is accepted. Model B asked for prompts
when a person is at a terminal (it passes the terminal through on interactive runs), for
`PI_NONINTERACTIVE` to forbid them, and for a distinct exit code on a user's cancel. The user ruled
that prompting is opt-in: `--interactive`.

**User ruling (2026-11-04).** `sol-pi-axi` replaces `setup-sol-pi.fish`: `install` is the
user-wide setup, `setup` the per-project one, and `--interactive` the prompt flow. The fish script
is removed.

**Python at a terminal.** `input()` reads from standard input and writes its prompt to standard
output, so the command reads lines itself and writes prompts to standard error. The Ctrl+C
keystroke at a terminal in canonical mode sends `SIGINT` to the foreground process group, which
Python raises as `KeyboardInterrupt`; end of input (Ctrl+D on an empty line) makes the read return
an empty string, with no exception.

**What is retired.** `setup-sol-pi.fish` (944 lines) runs a checkout's validation (dependency
install, typecheck, tests, audit), finds Pi, runs the strict compatibility check, registers SoL-Pi
with `pi install <checkout path>`, writes `sol-pi.json` with a `.bak` beside it, runs a smoke test
and prints a report; `--uninstall` reverses it. It prompts through
`setup-sol-pi-interactive.mjs` and `scripts/query-pi-models.mjs`. `tests/setup-prompt-flow.test.ts`
tests its prompt functions through `tests/fixtures/drive-pty.py`, and skips where `fish` or
`python3` is missing. CR-SLP-001 adds a Bun prerequisite check to the script; CR-SLP-002 no longer
changes it.

## Scope

### §S1 — `--interactive`

**Surfaces:** `sol_pi_axi/` (a prompt module; the `setup` and `install` verbs); CR-SLP-004's flag
list, help text and valid-flag lists.

- `--interactive` joins the flags of `setup` and `install`, the `--help` text and the valid flags
  usage errors list. It cannot be combined with `--non-interactive` (a usage error); given to the
  home view or `uninstall`, it is a usage error.
- **When it prompts.** With `--interactive`, the run prompts when standard input and standard error
  are both terminals and `PI_NONINTERACTIVE` is unset or empty. Otherwise it prompts nowhere, adds a
  warning saying why, and behaves exactly as a run without `--interactive`.
- **What it prompts for.** `setup` prompts for the project file's values. `install` prompts only
  when it will create the agent directory's `sol-pi.json`; with that file present it prompts for
  nothing and adds no warning.
- **Order of checks.** Before any prompt, the run makes every check it makes before writing (and,
  for `install`, before registering), except one: an invalid file it needs, a malformed
  `settings.json`, a bad project path and a missing `pi` fail the run as without `--interactive`. A
  missing reducer provider or model does not: the prompts start with no default for it.
- **Prompts.** One per mechanism (yes or no), then, when the reducer is enabled, its provider and
  model as one `<provider>/<model>` answer, then the cache ratio. Each defaults to the value the
  verb's rules resolve, after any value flags given with `--interactive`. Typed answers follow the
  grammar of the matching flag; an answer outside it repeats the prompt with the rule. The model
  prompt lists as suggestions the agent directory's `settings.json` `enabledModels` entries that
  are themselves valid `--reducer` values with no glob character (`*?[]{}`) and no `:` suffix.
- **An empty reducer answer** with no default fails the run: exit 1, `failed`, with `--reducer` in
  `help[]`, nothing written and nothing registered.
- **Confirmation.** The run shows the resulting configuration and asks for confirmation. Confirmed,
  `setup` writes when the values differ from the base values (`written`) and reports `unchanged`
  otherwise; `install` registers and writes.
- **Channels.** Prompts go to standard error; standard output carries only the envelope.
- **Cancel.** Each of these cancels the run: declining the confirmation, the Ctrl+C keystroke at a
  prompt, end of input (Ctrl+D), and a `SIGINT` signal; they exit 130. `SIGTERM` exits 143 and
  `SIGHUP` (the terminal closing) 129. In every case nothing is written, nothing is registered and
  no temporary file is left.
- **The `cancelled` envelope.** `ok: false`, `outcome: cancelled`, `error` naming what cancelled the
  run, `path` the target configuration path (`config.path` for `install`), `config` the values shown
  so far (`null` before the first answer), and `help[]` with the command to run again.
- **Exit codes beyond AXI.** AXI names 0, 1 and 2. Exits 130, 143 and 129 for a cancel are a
  deliberate addition, from Model B's request (#1516 item 4); the documentation says so.

### §S2 — The fish setup script is retired

**Surfaces:** `setup-sol-pi.fish`, `setup-sol-pi-interactive.mjs`, `scripts/query-pi-models.mjs`,
`tests/setup-prompt-flow.test.ts`, `tests/fixtures/drive-pty.py`, and every file that names them.

- The four files are deleted, with `tests/fixtures/drive-pty.py` when nothing else uses it. Their
  tests go with them: the prompt behaviour they covered is covered by §S1's tests.
- No file outside `docs/changes/` and `CHANGELOG.md` names the deleted files.
- What the script did and where it now lives is stated in `CHANGELOG.md`: the user-wide setup is
  `sol-pi-axi install`, the project setup `sol-pi-axi setup`, the prompts `--interactive`, the
  removal `sol-pi-axi uninstall`, and the checkout's validation `bun run check` (`CONTRIBUTING.md`).

### §S3 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `CONTRIBUTING.md`, `CHANGELOG.md`.

- README and `agents-install.md` document `--interactive`, when it prompts, `PI_NONINTERACTIVE`, and
  the cancel exit codes and why they extend AXI's.
- `CHANGELOG.md` `[Unreleased]` records the interactive mode and the script's removal, with §S2's
  mapping.

## Acceptance criteria

Interactive cases use a Python pseudo-terminal harness that gives standard input and standard error
the terminal and standard output its own pipe, against a temporary project, agent directory and
home, with CR-SLP-007's stub `pi` on `PATH`.

- [ ] **§S1** On the terminal, `setup --interactive` prompts; answering writes the chosen values and
      the envelope on the standard-output pipe reports `written`; the pipe holds no prompt text.
- [ ] **§S1** `install --interactive` on an empty agent directory prompts, then registers and writes
      the chosen values; with `sol-pi.json` present it prompts for nothing and installs.
- [ ] **§S1** `--interactive` with `PI_NONINTERACTIVE=1`, with standard input not a terminal, or with
      standard error not a terminal does not prompt, carries a warning saying why, and gives the
      same outcome and exit code as the same run without `--interactive`; `PI_NONINTERACTIVE=`
      (empty) leaves the prompts on.
- [ ] **§S1** `--interactive` with `--non-interactive`, and `--interactive` on the home view or
      `uninstall`, exit 2; `--help` names `--interactive`.
- [ ] **§S1** Value flags given with `--interactive` become the prompts' defaults.
- [ ] **§S1** With no Pi default provider or model, `--interactive` prompts with no reducer default;
      a typed `<provider>/<model>` is written; an empty answer exits 1 with `failed` and `--reducer`
      in `help[]`, and `install` has run no `pi` command.
- [ ] **§S1** The model prompt lists the usable `enabledModels` entries and none with a glob
      character or a `:` suffix.
- [ ] **§S1** An invalid project file, a malformed `settings.json` and a missing `pi` (for
      `install`) fail `--interactive` before any prompt.
- [ ] **§S1** A provider and model without `/`, a ratio of `-1` or `abc`, and a mechanism answer
      other than yes or no each repeat their prompt; answering the reducer "no" skips the provider
      and model prompt.
- [ ] **§S1** Confirming values equal to the base reports `unchanged` and writes nothing.
- [ ] **§S1** Declining the confirmation, the Ctrl+C keystroke written to the terminal, end of
      input, and a `SIGINT` signal each exit 130; `SIGTERM` exits 143 and `SIGHUP` 129; each prints
      a `cancelled` envelope with the keys §S1 lists, writes nothing, registers nothing and leaves
      no temporary file.
- [ ] **§S2** `git grep -n -E 'setup-sol-pi|query-pi-models|drive-pty' -- . ':!docs/changes'
      ':!CHANGELOG.md'` returns nothing, and the deleted files are gone.
- [ ] **§S2** The Bun suite's test count falls by exactly the tests of
      `tests/setup-prompt-flow.test.ts`, and no other test is removed or skipped.
- [ ] **§S3** README and `agents-install.md` cover §S3's items, checked by
      `tests/install-guide.test.ts`; `CHANGELOG.md` `[Unreleased]` records the changes with §S2's
      mapping.
- [ ] **Gate** The Bun and the Python `pre-merge-gate` both pass.

## Estimated size

8 points. The prompt flow for two verbs with its validation, deferred failure and cancel paths, a
new Python pseudo-terminal harness, the removal of the script and its helpers with their
references, and docs.

## Risks

- Terminal behaviour differs between platforms; the tests cover Linux, where CI runs.
- Users who run the fish script from a checkout lose it; the changelog's mapping and the install
  docs point them to `sol-pi-axi`.

## Non-goals

- Prompts without `--interactive`.
- Changing what `install` registers or what the setup defaults are.
- A replacement for the script's checkout validation outside `bun run check`.
