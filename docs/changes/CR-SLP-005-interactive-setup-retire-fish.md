# CR-SLP-005 — `--interactive` for `setup` and `install`; the fish setup script removed

**Status:** PENDING · Pre-review: ran — touches another project's surface (Model B passes a terminal to the interactive run, #1516 item 3)
**Type:** feature
**Priority:** P1 — completes Model B's request; `sol-pi-axi` becomes the only setup
**Depends on:** CR-SLP-004, CR-SLP-007, CR-SLP-008
**Labels:** setup, cli, axi, python, docs
**Phase:** 0.1.0 · wave 1
**Design reference:** `docs/research/DN-sol-pi-axi.md` §D4, §D7

## Context

`sol-pi-axi setup` (CR-SLP-004) and `install` (CR-SLP-007) never prompt. `setup-sol-pi.fish`
prompts through `scripts/query-pi-models.mjs`, is tested by `tests/setup-prompt-flow.test.ts`
through `tests/fixtures/drive-pty.py`, and is replaced by `sol-pi-axi` (DN §D7).
`setup-sol-pi-interactive.mjs` is referenced by nothing.

## Scope

### §S1 — `--interactive`

**Surfaces:** `sol_pi_axi/` (a prompt module; `setup` and `install`), help text, valid-flag lists.

- `--interactive` is a flag of `setup` and `install`; with `--non-interactive`, on the home view, on
  `uninstall` or on `verify` it is a usage error.
- It prompts when standard input and standard error are terminals and `PI_NONINTERACTIVE` is unset
  or empty; otherwise it adds a warning saying why and runs as without `--interactive`.
- `setup` prompts for the project file's values; `install` only when it will create the agent
  `sol-pi.json`, and otherwise prompts for nothing and adds no warning.
- Before any prompt, every check the verb makes before writing or registering runs, except the
  missing reducer provider or model, whose prompt then has no default.
- Prompts: each mechanism (yes or no); with the reducer on, `<provider>/<model>`; the cache ratio.
  Defaults are the verb's resolved values after any value flags. An answer outside the matching
  flag's grammar repeats the prompt with the rule. The reducer prompt suggests the agent
  `settings.json` `enabledModels` entries that are valid `--reducer` values without `*?[]{}` or a
  `:` suffix.
- An empty reducer answer with no default: exit 1, `failed`, `--reducer` in `help[]`, nothing
  written or registered.
- The run shows the result and asks for confirmation; confirmed, `setup` writes when values differ
  (`written`) else `unchanged`, and `install` proceeds.
- Prompts go to standard error, written by the command; standard output carries only the envelope.
- Before the confirmation is answered: declining it, Ctrl+C, Ctrl+D on an empty line, and `SIGINT`
  exit 130; `SIGTERM` 143; a closed terminal 129, whether `SIGHUP` or an `OSError` on the terminal.
  Nothing is written or registered and no temporary file is left.
- After the confirmation, signals follow CR-SLP-004 §S2, CR-SLP-007 §S2 and CR-SLP-008 §S4;
  `install`'s `cancelled` envelope reports the registration in `extension`, and `install` runs
  its load check last as without `--interactive`.
- `cancelled` envelope before the confirmation: `ok: false`, `outcome: cancelled`, `error` naming
  the cause, `help[]` with the command to run again.
  - `setup`: `path` the target file, `config` the values shown so far (`null` before the first
    answer).
  - `install`: `config` in CR-SLP-007's shape with `path` the target file, `state` `null`, and
    `features`, `reducer`, `cacheRatio` the values shown so far (each `null` before the first
    answer); `extension` reports nothing registered; `verify` `null`.

### §S2 — The fish setup script removed

**Surfaces:** `setup-sol-pi.fish`, `setup-sol-pi-interactive.mjs`, `scripts/query-pi-models.mjs`,
`tests/setup-prompt-flow.test.ts`, `tests/fixtures/drive-pty.py`, `tests/pty_harness.py` (new).

- The five files are deleted; the pseudo-terminal harness for §S1's tests is `tests/pty_harness.py`.
- No file outside `docs/` and `CHANGELOG.md` names a deleted file.

### §S3 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `CONTRIBUTING.md`, `CHANGELOG.md`.

- README and `agents-install.md`: `--interactive`, when it prompts, `PI_NONINTERACTIVE`, the cancel
  exit codes as an addition to AXI's; their statements that `setup` never prompts say it prompts
  only with `--interactive`.
- `CONTRIBUTING.md`: validating a checkout with `bun run check` and `bun audit --audit-level=high`.
- `CHANGELOG.md` `[Unreleased]`: `--interactive`, and the script's removal with DN §D7's mapping;
  the earlier `[Unreleased]` entries that name `setup-sol-pi.fish` drop it, since 0.1.0 never
  ships the script.

## Acceptance criteria

Interactive cases use `tests/pty_harness.py`: standard input and standard error on a
pseudo-terminal, standard output on its own pipe; a temporary project, agent directory and home;
CR-SLP-007's stub `pi`.

- [ ] **§S1** `setup --interactive`: prompts; answers are written; the pipe holds the envelope
      (`written`) and no prompt text.
- [ ] **§S1** `install --interactive`, empty agent directory: prompts, registers, writes the
      answers. With `sol-pi.json` present: no prompt, installs, no interactive-mode warning.
- [ ] **§S1** `PI_NONINTERACTIVE=1`, standard input not a terminal, or standard error not a terminal:
      no prompt, a warning naming why, the same outcome and exit as without `--interactive`.
      `PI_NONINTERACTIVE=` prompts.
- [ ] **§S1** `--interactive --non-interactive`, and `--interactive` on the home view, `uninstall`
      and `verify`: exit 2. `--help` names `--interactive`.
- [ ] **§S1** `install --interactive`, confirmed: the run ends with the load check (`verify` not
      `null`), as without `--interactive`.
- [ ] **§S1** Value flags become the prompts' defaults.
- [ ] **§S1** No Pi default: the reducer prompt has no default; a typed `<provider>/<model>` is
      written; an empty answer exits 1, `failed`, `--reducer` in `help[]`, no `pi` command run.
- [ ] **§S1** The reducer prompt lists usable `enabledModels` entries, none with a glob character
      or `:` suffix.
- [ ] **§S1** An invalid project file, malformed `settings.json`, and (for `install`) no `pi` fail
      before any prompt.
- [ ] **§S1** A reducer answer without `/`, a ratio of `-1` or `abc`, a mechanism answer other than
      yes or no repeat their prompt; reducer "no" skips the reducer prompt.
- [ ] **§S1** Confirming the base values: `unchanged`, nothing written.
- [ ] **§S1** At a prompt: declining, Ctrl+C, Ctrl+D on an empty line, `SIGINT` exit 130; `SIGTERM`
      143; `SIGHUP` 129; each prints `cancelled` with §S1's keys for its verb (for `install`,
      `config.state` `null` and `verify` `null`), writes and registers nothing, leaves no temporary
      file.
- [ ] **§S1** Closing the pseudo-terminal master, the command not its session's leader: exit 129,
      `cancelled` on the pipe.
- [ ] **§S1** Started with `SIGINT` ignored, Ctrl+C exits 130.
- [ ] **§S1** `SIGTERM` while the stub `pi install` runs after confirmation: exit 143, `cancelled`,
      `extension` reporting the registration, no temporary file.
- [ ] **§S2** `git grep -n -E 'setup-sol-pi|query-pi-models|drive-pty' -- . ':!docs'
      ':!CHANGELOG.md'` returns nothing; the five files are gone.
- [ ] **§S2** The Bun suite's passed-plus-skipped count falls by exactly 6, the cases of
      `tests/setup-prompt-flow.test.ts`; no other test changes name or status.
- [ ] **§S3** `tests/install-guide.test.ts` checks §S3's items in README, `agents-install.md` and
      `CONTRIBUTING.md`, and that neither README nor `agents-install.md` says `setup` never prompts;
      `CHANGELOG.md` `[Unreleased]` has DN §D7's mapping and names `setup-sol-pi.fish` only in it.
- [ ] **Gate** The Bun and the Python `pre-merge-gate` both pass.

## Estimated size

8 points.

## Risks

- Terminal behaviour differs by platform; tests cover Linux, where CI runs.

## Non-goals

- Prompts without `--interactive`.
- A strict (failing) Pi compatibility check in `install`.
