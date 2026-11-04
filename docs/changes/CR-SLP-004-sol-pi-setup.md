# CR-SLP-004 — An installed `sol-pi-setup` command with a per-project mode

**Status:** PENDING · Pre-review: due — touches another project's surface (Model B runs this command from `modelb-axi init` and `agents`, message #1516 items 1–4); 8 points
**Type:** feature
**Priority:** P1 — Model B makes SoL-Pi a prerequisite of every Model B project on Pi
**Depends on:** CR-SLP-001
**Labels:** setup, cli, install, docs
**Phase:** 0.1.0 · wave 1
**Design reference:** `docs/configuration.md` (search order, schema, trust); Model B's request, Sandesh message #1516 items 1–4

## Context

SoL-Pi is set up today by running `setup-sol-pi.fish` from a checkout. Model B will run SoL-Pi's
per-project setup for every project it scaffolds, and reaches SoL-Pi only through what SoL-Pi's
installer puts on the machine, never through a checkout. It asked for (#1516):

1. an installed, versioned entry point outside any checkout, with a stated install command, a
   name to probe and a way to read its version;
2. a light per-project mode, `--install <project dir>`, that writes or refreshes only
   `<project dir>/.pi/sol-pi.json`: no dependency install, typecheck, tests or audit, no user-wide
   `pi install`, and no `.bak` left in the project;
3. prompts only when a person is at a terminal, plus a documented non-interactive switch and
   `PI_NONINTERACTIVE`, which take the defaults and never prompt;
4. distinct exit codes for written or unchanged, failure and cancel, and a final machine-readable
   line with the outcome and path.

`setup-sol-pi.fish --install <dir>` today validates the checkout (dependency install, typecheck,
tests, audit), always registers SoL-Pi user-wide with `pi install`, writes
`<dir>/.pi/sol-pi.json` and leaves `<dir>/.pi/sol-pi.json.bak` beside it, and exits 0 when the
user cancels a prompt. It clones `https://github.com/NVlabs/SoL-Pi.git` when SoL-Pi is missing;
this project is `anthill-tec/SoL-Pi`.

SoL-Pi reads `<project>/.pi/sol-pi.json` only in a trusted project, and otherwise
`<agent dir>/sol-pi.json` (`findConfigPath`, `loadSolPiConfig`). Pi's agent directory is
`$PI_CODING_AGENT_DIR`, else `~/.pi/agent`; its `settings.json` holds `defaultProvider` and
`defaultModel`. The setup script's defaults enable all four mechanisms, use a
`cacheWriteReadRatio` of 12.5, and point the Evidence-Preserving Reducer at Pi's default provider
and model.

## Scope

### §S1 — The installed command

**Surfaces:** `package.json` (`bin`, `files`, `peerDependenciesMeta`), a new `bin/sol-pi-setup.mjs`.

- `package.json` declares `"bin": { "sol-pi-setup": "bin/sol-pi-setup.mjs" }` and ships the file.
  The command runs under Bun (`#!/usr/bin/env bun`).
- It is installed with `bun add --global github:anthill-tec/SoL-Pi#<version>`; `npm install
  --global github:anthill-tec/SoL-Pi#<version>` is the documented alternative. Model B probes
  `sol-pi-setup` on `PATH`.
- `sol-pi-setup --version` prints the package's `version` and nothing else, and exits 0.
  `sol-pi-setup --help` prints the usage and exits 0.
- The command imports no Pi package. The Pi peer dependencies and `typebox` are marked optional,
  so a global install of SoL-Pi installs no second Pi.

### §S2 — `sol-pi-setup --install <project dir>`

**Surfaces:** `bin/sol-pi-setup.mjs`, a Pi-free configuration module shared with
`src/sol-pi/config.ts`.

- It writes or refreshes `<project dir>/.pi/sol-pi.json` and nothing else. It creates
  `<project dir>/.pi/` when missing. It runs no dependency install, typecheck, test or audit,
  registers nothing with Pi, and never touches the user-wide configuration.
- **Values.** Each key comes from the first of: the project's existing `.pi/sol-pi.json`; the
  agent directory's `sol-pi.json`; the built-in defaults: all four mechanisms enabled,
  `cacheWriteReadRatio` 12.5, and the reducer on Pi's `defaultProvider` and `defaultModel` from
  the agent directory's `settings.json`.
- **Validation.** The configuration it writes passes the same validation as `loadSolPiConfig`,
  through one implementation both use. An existing project or agent-directory configuration that
  fails validation fails the run and is left untouched.
- **Output file.** The file is written in one canonical form: every key in the schema's order,
  tab indentation, a final newline. When the canonical text equals the file's bytes, nothing is
  written (`unchanged`). Otherwise the text goes to a temporary file in the same directory, which
  is renamed over the target (`written`). No `.bak` or temporary file is left.
- **Missing model.** When the reducer is enabled and no provider or model can be resolved, the run
  fails and writes nothing.

### §S3 — Interactive only at a terminal

**Surfaces:** `bin/sol-pi-setup.mjs`.

- The run prompts when standard input is a terminal, and `--non-interactive` is not given, and
  `PI_NONINTERACTIVE` is unset or empty. Otherwise it takes the resolved values without prompting.
- The prompts cover each mechanism, the reducer's provider and model (offering the models Pi lists
  in `enabledModels`), and the cache ratio, each defaulting to the resolved value. The run then
  shows the resulting configuration and asks for confirmation before writing.
- Declining the confirmation, end of input at a prompt, or an interrupt (`SIGINT`) cancels the run;
  nothing is written.

### §S4 — Exit codes and the result line

**Surfaces:** `bin/sol-pi-setup.mjs`.

- Exit codes: 0 when the file is written or unchanged; 1 on a failure (an invalid existing
  configuration, no provider or model, a missing project directory, a write error); 2 on a usage
  error (an unknown option, `--install` without a directory); 130 on a cancel.
- Standard output carries one line, the last thing an `--install` run prints:
  `{"outcome":"written"|"unchanged"|"failed"|"usage"|"cancelled","path":<absolute config path or null>,"version":"<version>"}`,
  with an `"error"` string added for `failed` and `usage`. Prompts and messages go to standard
  error.

### §S5 — The fish setup script

**Surfaces:** `setup-sol-pi.fish`, `tests/setup-prompt-flow.test.ts`.

- `--install <dir>` runs the checkout's `bin/sol-pi-setup.mjs --install <dir>` with the terminal
  passed through, and exits with its code. It no longer validates the checkout, runs `pi install`,
  or writes a `.bak`. When `pi list` does not show SoL-Pi, it says that the user-wide setup
  (`--install` with no directory) is still needed.
- `--install` with no directory (the user-wide setup) keeps its phases.
- The clone URL is `https://github.com/anthill-tec/SoL-Pi.git`.
- A cancelled prompt exits 130, not 0.

### §S6 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `docs/configuration.md`, `CHANGELOG.md`.

- README and `agents-install.md` document the install command, `sol-pi-setup --install`, its
  switches, `PI_NONINTERACTIVE`, the exit codes and the result line.
- `docs/configuration.md` notes that a project's `.pi/sol-pi.json` is read only in a trusted
  project.
- `CHANGELOG.md` `[Unreleased]` records the command and the setup script's changes.

## Acceptance criteria

- [ ] **§S1** `bun pm pack` lists `bin/sol-pi-setup.mjs`, and `package.json` maps `sol-pi-setup`
      to it.
- [ ] **§S1** Installing the packed tarball with `bun add --global` into a temporary `BUN_INSTALL`
      puts `sol-pi-setup` in that install's `bin`, `sol-pi-setup --version` there prints
      `package.json`'s version, and the install adds no `@earendil-works/*` package.
- [ ] **§S1** `bin/sol-pi-setup.mjs` and the module it imports import no `@earendil-works/*`
      package.
- [ ] **§S1** Pi still loads SoL-Pi from `pi install` of the packed package with the peers marked
      optional (the package integration tests pass).
- [ ] **§S2** In a temporary project and agent directory, a non-interactive `--install` with no
      configuration anywhere writes the built-in defaults with Pi's default provider and model,
      exits 0, and prints `outcome` `written`; a second run prints `unchanged` and leaves the
      file's bytes and modification time alone.
- [ ] **§S2** An agent-directory `sol-pi.json` supplies the values when the project has none; an
      existing project file's values win over both.
- [ ] **§S2** An invalid existing project or agent configuration exits 1 with `failed`, and the
      project file's bytes are unchanged.
- [ ] **§S2** With the reducer enabled and no `defaultProvider` or `defaultModel`, the run exits 1
      with `failed` and creates no file.
- [ ] **§S2** After any run, `<project dir>/.pi/` holds no file other than `sol-pi.json`.
- [ ] **§S2** Every written file is accepted by `loadSolPiConfig`.
- [ ] **§S3** With `--non-interactive`, or with `PI_NONINTERACTIVE=1`, a run on a terminal does
      not prompt; without a terminal, no run prompts.
- [ ] **§S3** On a pseudo-terminal, answering the prompts writes the chosen values; declining the
      confirmation, closing input, or sending `SIGINT` exits 130 with `cancelled` and writes
      nothing.
- [ ] **§S4** An unknown option and `--install` without a directory exit 2 with `usage`; a missing
      project directory exits 1 with `failed`.
- [ ] **§S4** Every `--install` run's standard output is exactly one JSON line with the fields §S4
      lists.
- [ ] **§S5** `setup-sol-pi.fish --install <dir>` on a temporary project runs no `pi install`,
      leaves no `.bak`, and exits with `sol-pi-setup`'s code; a cancelled prompt exits 130.
- [ ] **§S5** `git grep -n NVlabs/SoL-Pi.git -- setup-sol-pi.fish` returns nothing.
- [ ] **§S6** README and `agents-install.md` name the install command, the probe, `--version`,
      `--install`, `--non-interactive`, `PI_NONINTERACTIVE`, the four exit codes and the result
      line; `tests/install-guide.test.ts` passes.
- [ ] **Gate** `pre-merge-gate` passes.

## Estimated size

8 points. A new command with interactive, non-interactive and failure paths, its install path,
the fish script's rewiring, and docs.

## Risks

- Marking the Pi peers optional changes how package managers install SoL-Pi. Pi loads extensions
  against its own Pi packages; the §S1 integration criterion checks that this still holds.
- A GitHub install builds nothing, so the command must run from source as shipped.

## Non-goals

- An `--uninstall` mode for `sol-pi-setup`.
- Publishing to the npm registry (the name `sol-pi` belongs to another publisher).
- Changing what the user-wide setup does, or recording a project as trusted in Pi.
- Removing `setup-sol-pi-interactive.mjs` or `scripts/query-pi-models.mjs`.
