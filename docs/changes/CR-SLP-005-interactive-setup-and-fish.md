# CR-SLP-005 — Opt-in interactive setup; the fish script on `sol-pi-setup`

**Status:** PENDING · Pre-review: ran — touches another project's surface (Model B passes a terminal through to the interactive run, message #1516 item 3); split from CR-SLP-004 after its pre-review
**Type:** feature
**Priority:** P1 — completes Model B's request and removes the `.bak` and user-wide `pi install` from project setup
**Depends on:** CR-SLP-004, CR-SLP-002 (both edit `setup-sol-pi.fish`; this CR lands after CR-SLP-002's Pi lookup)
**Labels:** setup, cli, axi, fish, ci, docs
**Phase:** 0.1.0 · wave 1
**Design reference:** the AXI standard (<https://axi.md>); CR-SLP-004 (`sol-pi-setup`); Model B's request, Sandesh message #1516 items 2–4

## Context

CR-SLP-004 ships `sol-pi-setup --install <project dir>`, which never prompts: every value has a
flag, and `--non-interactive` is accepted. Model B asked for prompts when a person is at a terminal
(it passes the terminal through on interactive runs), for `PI_NONINTERACTIVE` to forbid them, and
for a distinct exit code on a user's cancel. The user ruled that prompting is opt-in:
`--interactive`.

Measured on Node 22.23.4 and Bun 1.4.4: at a `readline/promises` prompt on a terminal, the Ctrl+C
keystroke sends no signal; `question()` rejects with `AbortError` and the process would exit 0.
End of input (Ctrl+D) rejects the same way. A `process.on("SIGINT")` handler runs only for a signal
sent with `kill`. With standard error not a terminal, readline writes its prompts where nobody sees
them.

`setup-sol-pi.fish --install <dir>` today runs the prerequisite checks, validates the checkout
(Phase 0: dependency install, typecheck, tests, audit), finds Pi and runs the strict compatibility
check (Phase 1, rewritten by CR-SLP-002), always registers SoL-Pi user-wide with `pi install`
(Phase 2), writes `<dir>/.pi/sol-pi.json` with a `.bak` beside it (Phase 3), runs a smoke test and
the all-mechanisms test (Phase 4), and prints a completion report. It treats the working directory
as the checkout and clones into it when `.git` is missing. It accepts only project paths starting
with `/`, `~/` or `../`, ignores extra arguments, and exits 0 on argument errors and on a cancel
(the `c` answer, including at the provider and model prompts). Its prompts test
`PI_NONINTERACTIVE` with `set -q`, so an empty value counts as set. `--uninstall <dir>` restores
`sol-pi.json` from a `.bak` when one exists. Its "already registered" check is a case-sensitive
`grep sol-pi` on `pi list`. It clones `https://github.com/NVlabs/SoL-Pi.git`.

The prompt tests skip where `fish` or `python3` is missing; the release workflow's `test-bun` job
runs on `ubuntu-latest`, which has no `fish`. The existing pseudo-terminal fixture
(`tests/fixtures/drive-pty.py`, `pty.fork()`) puts all three standard streams on one terminal.

## Scope

### §S1 — `--interactive`

**Surfaces:** `bin/sol-pi-setup.mjs` and its modules; CR-SLP-004's flag list, help text and
valid-flag lists.

- `--interactive` joins CR-SLP-004's flags, its `--help` text and the valid flags its usage errors
  list. It cannot be combined with `--non-interactive` (a usage error).
- **When it prompts.** With `--interactive`, the run prompts when standard input and standard error
  are both terminals and `PI_NONINTERACTIVE` is unset or empty. Otherwise it prompts nowhere, adds a
  warning saying why, and behaves exactly as a run without `--interactive`.
- **Order of checks.** Before any prompt, the run makes every check CR-SLP-004 makes before
  writing, except one: an invalid project file, an invalid agent-directory file it needs, a
  malformed `settings.json`, and a bad project path fail the run as without `--interactive`. A
  missing reducer provider or model does not: the prompts start with no default for it.
- **Prompts.** One per mechanism (yes or no), then, when the reducer is enabled, its provider and
  model as one `<provider>/<model>` answer, then the cache ratio. Each defaults to the value
  CR-SLP-004's rules resolve, after any value flags given with `--interactive`. Typed answers follow
  the grammar of the matching flag; an answer outside it repeats the prompt with the rule. The
  model prompt lists as suggestions the `enabledModels` entries that are themselves valid
  `--reducer` values with no glob character (`*?[]{}`) and no `:` suffix.
- **An empty reducer answer** with no default fails the run: exit 1, `failed`, with `--reducer` in
  `help[]`, nothing written.
- **Confirmation.** The run shows the resulting configuration and asks for confirmation. Confirmed,
  it writes when the values differ from the base values (`written`) and reports `unchanged`
  otherwise.
- **Channels.** Prompts go to standard error; standard output carries only the envelope.
- **Cancel.** Each of these cancels the run: declining the confirmation, the Ctrl+C keystroke at a
  prompt, end of input (Ctrl+D), and a `SIGINT` signal; they exit 130. `SIGTERM` exits 143 and
  `SIGHUP` (the terminal closing) 129. In every case nothing is written and no temporary file is
  left.
- **The `cancelled` envelope.** `ok: false`, `outcome: cancelled`, `error` naming what cancelled the
  run, `path` the target configuration path, `config` the values shown so far (`null` before the
  first answer), and `help[]` with the command to run again.
- **Exit codes beyond AXI.** AXI names 0, 1 and 2. Exits 130, 143 and 129 for a cancel are a
  deliberate addition, from Model B's request (#1516 item 4); the documentation says so.

### §S2 — The fish setup script

**Surfaces:** `setup-sol-pi.fish`, `tests/setup-prompt-flow.test.ts`, a pseudo-terminal fixture.

- **Project mode** (`--install <dir>`) keeps the argument handling and the Bun prerequisite check,
  then runs the `bin/sol-pi-setup.mjs` beside the script (found from the script's own path, never
  the working directory) with `--install <dir> --interactive`, the terminal passed through, and
  exits with its code. It no longer clones, validates the checkout, finds Pi, runs the
  compatibility check, runs `pi install`, writes a `.bak`, runs the smoke or all-mechanisms tests,
  or prints the completion report; the command's envelope is the report.
- **Dependencies.** When `node_modules/@toon-format/toon` is missing beside the script, project
  mode first runs `bun install --frozen-lockfile --ignore-scripts` there; otherwise it installs
  nothing.
- **Registration notice.** After the command, project mode looks for SoL-Pi in `pi list`: a
  case-insensitive match on `sol-pi`, the checkout's absolute path, or `anthill-tec/SoL-Pi`. With no
  match it prints that the user-wide setup (`--install` with no directory) is still needed. With no
  `pi`, or `pi list` failing, it prints a warning instead. Neither changes the exit code.
- **Arguments.** A relative project directory is accepted and resolved against the working
  directory, as `sol-pi-setup` does. Unknown options and extra arguments exit 2; a missing directory
  is reported by `sol-pi-setup` (exit 1).
- **Uninstall.** `--uninstall <dir>` deletes `<dir>/.pi/sol-pi.json` and does not restore from a
  `.bak`; a leftover `.bak` stays and is named.
- **User-wide mode** (`--install` with no directory) keeps its phases. A cancel at any of its prompts
  (the `c` answer, Ctrl+C, or end of input), including the provider and model prompts, exits 130.
- **`PI_NONINTERACTIVE`** counts as set only when non-empty, in the fish prompts as in
  `sol-pi-setup`.
- The clone URL is `https://github.com/anthill-tec/SoL-Pi.git`.

### §S3 — CI runs the prompt tests

**Surfaces:** `.github/workflows/release.yml` (`test-bun` job).

- The `test-bun` job installs `fish` before running the tests, so the prompt and fish tests run in
  CI rather than skip.

### §S4 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `CHANGELOG.md`.

- README and `agents-install.md` document `--interactive`, when it prompts, `PI_NONINTERACTIVE`, the
  cancel exit codes and why they extend AXI's, and the fish script's project mode.
- `CHANGELOG.md` `[Unreleased]` records the interactive mode and the setup script's changes.

## Acceptance criteria

Interactive cases use a pseudo-terminal harness that gives standard input and standard error the
terminal and standard output its own pipe, against a temporary project, agent directory and home.
Fish cases run the script against a temporary project with a stub `pi` on `PATH`.

- [ ] **§S1** On the terminal, `--interactive` prompts; answering writes the chosen values and the
      envelope on the standard-output pipe reports `written`; the pipe holds no prompt text.
- [ ] **§S1** `--interactive` with `PI_NONINTERACTIVE=1`, with standard input not a terminal, or with
      standard error not a terminal does not prompt, carries a warning saying why, and writes or
      reports `unchanged` with exit 0 as the same run without `--interactive`.
- [ ] **§S1** `--interactive` with `--non-interactive` exits 2; `--help` names `--interactive`.
- [ ] **§S1** Value flags given with `--interactive` become the prompts' defaults.
- [ ] **§S1** With no Pi default provider or model, `--interactive` prompts with no reducer default;
      a typed `<provider>/<model>` is written; an empty answer exits 1 with `failed` and `--reducer`
      in `help[]`.
- [ ] **§S1** An invalid project file or a malformed `settings.json` fails `--interactive` before any
      prompt.
- [ ] **§S1** A provider and model without `/`, a ratio of `-1` or `abc`, and a mechanism answer
      other than yes or no each repeat their prompt; answering the reducer "no" skips the provider
      and model prompt.
- [ ] **§S1** Confirming values equal to the base reports `unchanged` and writes nothing.
- [ ] **§S1** Declining the confirmation, the Ctrl+C keystroke written to the terminal, end of input,
      and a `SIGINT` signal each exit 130; `SIGTERM` exits 143 and `SIGHUP` 129; each prints a
      `cancelled` envelope with the keys §S1 lists, writes nothing and leaves no temporary file.
- [ ] **§S2** `setup-sol-pi.fish --install <dir>` on a temporary project, run from another working
      directory, runs `sol-pi-setup` beside the script, runs no `pi install`, leaves no `.bak`, and
      exits with `sol-pi-setup`'s code; a Ctrl+C at its prompt exits 130.
- [ ] **§S2** With `node_modules/@toon-format/toon` missing, project mode installs the dependencies
      first; with it present, it installs nothing.
- [ ] **§S2** The registration notice appears when the stub `pi list` shows no SoL-Pi entry, is
      absent for entries `sol-pi`, `/abs/path/SoL-Pi` and `git:github.com/anthill-tec/SoL-Pi`, and
      becomes a warning when `pi list` fails; the exit code is unchanged in each case.
- [ ] **§S2** A relative project directory works; an unknown option and an extra argument exit 2.
- [ ] **§S2** `--uninstall <dir>` deletes the project file, does not restore a `.bak`, and keeps
      and names a leftover `.bak`.
- [ ] **§S2** In the user-wide setup, the `c` answer, Ctrl+C and end of input at each prompt,
      including the provider and model prompts, exit 130.
- [ ] **§S2** `PI_NONINTERACTIVE=` (empty) leaves the fish prompts on.
- [ ] **§S2** `git grep -n NVlabs -- setup-sol-pi.fish` returns nothing.
- [ ] **§S3** The `test-bun` job installs `fish`; the gate run's JUnit report shows the prompt and
      fish tests passed, none skipped.
- [ ] **§S4** README and `agents-install.md` cover §S4's items, checked by
      `tests/install-guide.test.ts`; `CHANGELOG.md` `[Unreleased]` records the changes.
- [ ] **Gate** `pre-merge-gate` passes on a machine with `fish` and `python3`.

## Estimated size

8 points. The prompt flow with its validation, deferred failure and cancel paths, a new
pseudo-terminal harness, the fish script's rewiring, and CI.

## Risks

- Terminal behaviour differs between platforms; the tests cover Linux, where CI runs.

## Non-goals

- Changing what the user-wide setup configures.
- Removing `setup-sol-pi-interactive.mjs` or `scripts/query-pi-models.mjs`.
- Prompts in `sol-pi-setup` without `--interactive`.
