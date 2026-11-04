# CR-SLP-004 — `sol-pi-setup`, an installed AXI command for per-project setup

**Status:** PENDING · Pre-review: ran — touches another project's surface (Model B runs this command from `modelb-axi init` and `agents`, message #1516 items 1–4); 8 points or more; re-reviewed after re-scoping (AXI adopted, prompts split to CR-SLP-005)
**Type:** feature
**Priority:** P1 — Model B makes SoL-Pi a prerequisite of every Model B project on Pi
**Depends on:** CR-SLP-001
**Labels:** setup, cli, axi, install, docs
**Phase:** 0.1.0 · wave 1
**Design reference:** the AXI standard (<https://axi.md>; its skill, `kunchenguid/axi`
`.agents/skills/axi/SKILL.md`); the TOON specification (<https://toonformat.dev>);
`docs/configuration.md` (search order, schema, trust); Model B's request, Sandesh message #1516
items 1–4

## Context

SoL-Pi is set up today by running `setup-sol-pi.fish` from a checkout. Model B will run SoL-Pi's
per-project setup for every project it scaffolds, and reaches SoL-Pi only through what SoL-Pi's
installer puts on the machine, never through a checkout. It asked for (#1516):

1. an installed, versioned entry point outside any checkout, with a stated install command, a
   name to probe and a way to read its version;
2. a light per-project mode, `--install <project dir>`, that writes or refreshes only
   `<project dir>/.pi/sol-pi.json`: no dependency install, typecheck, tests or audit, no user-wide
   `pi install`, and no `.bak` left in the project;
3. prompts only when a person is at a terminal, plus a non-interactive switch (passed under
   Model B's `--yes`) and `PI_NONINTERACTIVE`, which take the defaults and never prompt;
4. distinct exit codes and a final machine-readable result with the outcome and path.

The command follows the AXI standard, as Model B's `modelb-axi` and Crucible's clients do: a TOON
envelope on standard output, errors in the same envelope, exit codes 0/1/2, no prompts, every
value settable by flag, unknown input rejected, a home view for no arguments, next steps in
`help[]`, and a fast `--version`. The user ruled: prompts only on request (`--interactive`,
CR-SLP-005, which also reads `PI_NONINTERACTIVE`); the envelope is TOON by default, and
`--format json` gives one JSON line; the encoder is the official `@toon-format/toon`.

**Configuration semantics** (`docs/configuration.md`, `findConfigPath`, `loadSolPiConfig`). SoL-Pi
reads `<project>/.pi/sol-pi.json` only in a trusted project, and otherwise
`<agent dir>/sol-pi.json`. The project file replaces the global file; the two are not merged. An
omitted feature key is `false`, an omitted reducer provider or model is the built-in route
(`DEFAULT_REDUCER_PROVIDER`, `DEFAULT_REDUCER_MODEL`), and an omitted `cacheWriteReadRatio` is
12.5. The validation rules exist three times: `loadSolPiConfig`, `scripts/check-sol-pi-config.mjs`
and the setup script's `jq` checks. The setup script's defaults enable all four mechanisms, use a
ratio of 12.5, and point the reducer at Pi's default provider and model.

**Pi.** The extension finds its files through Pi's `CONFIG_DIR_NAME` and `getAgentDir()`. For the
official Pi these are `.pi`, and `$PI_CODING_AGENT_DIR` (when non-empty; a leading `~` expanded)
else `~/.pi/agent`. A Pi distribution may change them. The agent directory's `settings.json`
holds `defaultProvider` and `defaultModel`. Pi 1.5's package manager installs packages with peers
omitted; `pi install <local path>` records the path without installing anything.

**Bun.** A Bun script loads the `.env` and `bunfig.toml` of the directory it runs in. Measured: a
globally installed test command run inside a directory with its own `.env` and `bunfig.toml` saw
the `.env` values and ran the `bunfig.toml` `preload`;
`#!/usr/bin/env -S bun --no-env-file --config=/dev/null` stopped both. `bun add --global`
installs a package's non-optional peers, and with them marked optional installs none.

**TOON.** The official TypeScript encoder is `@toon-format/toon` (MIT, no dependencies; 4.4.0
current). Measured: the envelope's shapes (a null `path`, empty lists, quoted paths, version
strings) encode and decode back unchanged.

## Scope

### §S1 — The installed command

**Surfaces:** `package.json` (`bin`, `files`, `dependencies`, `peerDependenciesMeta`), a new
`bin/sol-pi-setup.mjs`, a new version module, `.github/scripts/stamp_version.py`.

- `package.json` declares `"bin": { "sol-pi-setup": "bin/sol-pi-setup.mjs" }`, and `files` ships
  `bin/` and every module the command loads.
- The command runs under Bun with `#!/usr/bin/env -S bun --no-env-file --config=/dev/null`.
- It is installed with `bun add --global github:anthill-tec/SoL-Pi#<version>`. `npm install
  --global github:anthill-tec/SoL-Pi#<version>` is the documented alternative, which still needs
  Bun on `PATH`. Model B probes `sol-pi-setup` on `PATH`, so Bun's global `bin` directory must be
  on `PATH`.
- `@toon-format/toon` is a runtime dependency at exactly `4.4.0`, SoL-Pi's only one.
- The command imports no Pi package. The Pi peer dependencies and `typebox` are marked optional in
  `peerDependenciesMeta`, so `bun add --global` installs no Pi package. `pi install` is unaffected:
  Pi installs packages with peers omitted.
- **Version fast path.** A version module exports `VERSION` and imports nothing. `bin` checks for a
  lone `-v`, `-V` or `--version` before loading anything else, prints the bare version and exits 0;
  the rest of the command loads through a dynamic `import()`. The release tooling's version stamp
  (`stamp_version.py`) updates the module with `package.json`, and a test keeps the two equal.

### §S2 — `sol-pi-setup --install <project dir>`

**Surfaces:** `bin/sol-pi-setup.mjs` and its modules, a new Pi-free TypeScript configuration module
in `src/sol-pi/` that `src/sol-pi/config.ts`, `scripts/check-sol-pi-config.mjs` and the command
all import.

- **Layout.** The command supports the official Pi layout only: `<project>/.pi/sol-pi.json`, and
  the agent directory `$PI_CODING_AGENT_DIR` (when non-empty, with a leading `~` expanded) else
  `~/.pi/agent`.
- **Scope of the run.** It writes at most `<project dir>/.pi/sol-pi.json`, creating
  `<project dir>/.pi/` when missing; a run that fails removes a `.pi/` it created. It runs no
  dependency install, typecheck, test or audit, registers nothing with Pi, and writes nothing
  else. A project path that does not exist, or is not a directory, fails the run.
- **Base values.** When the project file exists and is valid, its effective values (the runtime
  defaults for omitted keys). Otherwise, the agent directory's `sol-pi.json` when it exists, read
  the same way. Otherwise the setup defaults: all four mechanisms enabled, ratio 12.5, the reducer
  on Pi's `defaultProvider` and `defaultModel`.
- **Flags override the base** (§S3). With no value flag, an existing valid project file is left
  untouched (`unchanged`). The agent directory's file is not consulted when a project file exists.
- **Pi settings.** Read only when the setup defaults are used: the agent directory's
  `settings.json`, not a project's. A missing file means no Pi default; a malformed one fails the
  run. When the resulting configuration enables the reducer and has no provider or model (no Pi
  default and no `--reducer`), the run fails. With the reducer disabled, the reducer keys are the
  built-in route.
- **Validation.** The shared module holds the schema and validation; `loadSolPiConfig` and
  `scripts/check-sol-pi-config.mjs` use it. An invalid file the run needs fails it and is left
  untouched.
- **Written form.** Every key, in the order of `sol-pi.example.json`, tab indentation, a final
  newline. When the text equals the file's bytes, nothing is written (`unchanged`).
- **Writing.** The text goes to a temporary file in the target's directory, renamed over the
  target. Through a symbolic link, the link's target file is replaced and the link kept. An existing
  file's permission bits are kept. The writing module takes an optional hook between writing the
  temporary file and renaming it, which only tests set.
- **Signals.** `SIGINT`, `SIGTERM` or `SIGHUP` during a run removes the temporary file, writes
  nothing, prints the envelope with `outcome` `cancelled`, and exits 130, 143 or 129.
- **Earlier backups.** A `sol-pi.json.bak` left by an earlier setup script is not touched; a
  warning names it.

### §S3 — Every value by flag; no prompts

**Surfaces:** `bin/sol-pi-setup.mjs` and its modules.

- **Flags.** Each takes its value as `--flag value` or `--flag=value`.
  - `--features <list>`: `all`, `none`, or a comma-separated list of distinct mechanism names
    (`actionFusion`, `observationPack`, `evidencePreservingReducer`, `onlineContextCompact`,
    exact case, no empty entries); the others are disabled.
  - `--reducer <provider>/<model>`: split at the first `/`; both parts non-empty with no
    whitespace (the model may contain `/`).
  - `--cache-ratio <number>`: digits with an optional decimal fraction (no sign, exponent, hex or
    surrounding space).
  - `--format toon|json`: the output encoding; `toon` by default.
  - `--non-interactive`: accepted and changes nothing, since the command never prompts; it is the
    switch Model B passes under its `--yes`.
- **Help and version anywhere.** `--help` anywhere in the arguments prints the help and exits 0,
  before any other check. Otherwise `-v`, `-V` or `--version` anywhere prints the bare version and
  exits 0.
- The command never prompts. A value it cannot resolve fails the run, with the flag that supplies
  it in `help[]`.

### §S4 — AXI output, errors and exit codes

**Surfaces:** `bin/sol-pi-setup.mjs` and its modules.

- **What prints outside the envelope.** The version path prints the bare version; `--help` prints
  a plain-text reference: the flags with their defaults, the arguments, two or three examples.
  Every other run prints one envelope.
- **Envelope.** One TOON document encoded with `@toon-format/toon`, root key `axi`; with
  `--format json`, the same object as one JSON line. `--format` is read from the arguments before
  anything else is checked; a run whose `--format` is missing or malformed answers in TOON.
  - Every envelope: `verb`, `ok`, `version`, `warnings`, `help`, and `error` when `ok` is false.
  - `verb: install`: `outcome` (`written`, `unchanged`, `failed`, `cancelled`), `path` (the
    absolute configuration path, or `null`), `config` (`features` as the enabled mechanisms,
    `reducer` as `<provider>/<model>`, `cacheRatio`; `null` when no configuration was resolved),
    `context` (`project`, `agentDir`).
  - `verb: usage` (an argument error): `outcome: usage`, `error`, `help`.
  - `verb: home`: `bin` (the executable path, home as `~`), `description` (one sentence), and
    `project` and `agentConfig`, each with `path` and `state` (`absent`, `valid` with its
    `features` and `reducer`, or `invalid` with the reason).
- **Channels.** Standard output carries only the envelope (or the version or help text);
  diagnostics go to standard error. No stack trace or dependency message reaches either.
- **Exit codes.** 0 for `written`, `unchanged` and the home view (an invalid file shown there is
  reported, not a failure); 1 for `failed`; 2 for `usage`; 130, 143 or 129 for `cancelled`.
- **Unknown input.** An unknown flag, a repeated flag, an extra argument, `--install` without a
  directory, and a value outside §S3's grammar are usage errors, checked before anything is read.
  The error names the offending input and lists the valid flags. `--yes` gets a targeted hint:
  the command never prompts, and `--non-interactive` is the explicit switch.
- **Next steps.** `help[]` carries complete commands with `<placeholders>`: after `written`, start
  Pi in the project and trust it there; after an error, the command or flag that fixes it; from the
  home view, `--install` for the working directory. `unchanged` carries none.
- A relative project directory resolves against the working directory.

### §S5 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `docs/configuration.md`, `THIRD_PARTY_NOTICES.md`,
`CHANGELOG.md`.

- README and `agents-install.md` document:
  - the install command and its npm alternative, that both need Bun, and that Bun's global `bin`
    directory must be on `PATH`;
  - `sol-pi-setup --install`, its flags (including `--non-interactive`), the envelope and its keys,
    `--format json`, the home view and the exit codes;
  - that the Pi extension (`pi install git:github.com/anthill-tec/SoL-Pi@<version>`) and the
    command are two installs, made at the same version.
- README's install lines name `anthill-tec/SoL-Pi`, not `NVlabs/SoL-Pi`.
- The statements that SoL-Pi reads no environment variables say instead that the extension reads
  none and `sol-pi-setup` reads `PI_CODING_AGENT_DIR`.
- `docs/configuration.md` and `agents-install.md` state that the extension follows Pi's
  configuration directory and agent directory, while `sol-pi-setup` supports only the official
  layout; `docs/configuration.md` also notes that a project file is read only in a trusted project,
  and how `sol-pi-setup` chooses its values.
- `THIRD_PARTY_NOTICES.md` lists `@toon-format/toon` 4.4.0.
- `CHANGELOG.md` `[Unreleased]` records the command.

## Acceptance criteria

Tests run the command against a temporary project, agent directory and home, with
`PI_CODING_AGENT_DIR` set, and decode envelopes with `@toon-format/toon`'s `decode`.

- [ ] **§S1** `bun pm pack` lists `bin/sol-pi-setup.mjs`, the version module, the shared
      configuration module and every module the command imports; `package.json` maps
      `sol-pi-setup` to the bin, with §S1's shebang, and `dependencies` is exactly
      `{"@toon-format/toon": "4.4.0"}`.
- [ ] **§S1** From the packed tarball installed with `bun add --global` into a temporary
      `BUN_INSTALL`: the install adds no `@earendil-works/*` or `typebox` package; `sol-pi-setup
      --version` prints `package.json`'s version; `sol-pi-setup --install <temporary project>`
      writes the file and prints a decodable envelope; `sol-pi-setup` with no arguments prints a
      decodable home view.
- [ ] **§S1** Run from a directory whose `.env` sets `PI_CODING_AGENT_DIR` and whose `bunfig.toml`
      has a `preload`, the installed command does not see the variable and the preload does not
      run.
- [ ] **§S1** The command's modules import no `@earendil-works/*` package; the version module
      imports nothing; a test asserts `VERSION` equals `package.json`'s `version`, and
      `stamp_version.py` updates both.
- [ ] **§S1** `-v`, `-V` and `--version` each print the bare version and exit 0; the median of five
      runs takes no more than twice the median of five `bun -e "console.log(1)"` runs in the same
      test.
- [ ] **§S2** With no configuration anywhere, `--install` writes the setup defaults with Pi's
      default provider and model, exits 0 and reports `written`; a second run reports `unchanged`
      and leaves the bytes and modification time alone.
- [ ] **§S2** A valid partial project file (for example `{"version":1,"actionFusion":true}`) is
      left byte-for-byte unchanged by a run with no value flag, which reports `unchanged`, even
      when the agent directory's file is invalid and Pi has no default model.
- [ ] **§S2** With no project file, the agent directory's `sol-pi.json` supplies the values.
- [ ] **§S2** An invalid project file, or an invalid agent-directory file when there is no project
      file, exits 1 with `failed` and changes no file; so does a malformed `settings.json` when the
      setup defaults are used.
- [ ] **§S2** With the setup defaults, no Pi default provider or model and no `--reducer`, the run
      exits 1 with `failed`, creates neither the file nor `.pi/`, and its `help[]` names
      `--reducer`; the same with `--features actionFusion` (reducer off) writes the built-in
      reducer route and exits 0.
- [ ] **§S2** A project path that is a regular file, or does not exist, exits 1 with `failed`.
- [ ] **§S2** Listing `<project dir>/.pi/` before and after any run shows no added file other than
      `sol-pi.json`; a leftover `sol-pi.json.bak` is still there and named in `warnings`.
- [ ] **§S2** Every written file is accepted by `loadSolPiConfig` and by
      `scripts/check-sol-pi-config.mjs`, and both import the shared module.
- [ ] **§S2** A write through a symbolic link replaces the link's target and keeps the link; an
      existing file's permission bits are kept.
- [ ] **§S2** With the test hook holding a run between writing and renaming, `SIGINT`, `SIGTERM`
      and `SIGHUP` each leave no temporary file and no changed file, print `cancelled`, and exit
      130, 143 and 129.
- [ ] **§S2** `PI_CODING_AGENT_DIR=~/agent` reads `$HOME/agent`; an empty `PI_CODING_AGENT_DIR`
      reads `~/.pi/agent`.
- [ ] **§S3** `--features`, `--reducer` and `--cache-ratio` each override the base values and
      write; repeating the same flags reports `unchanged`; `--features all`, `--features none` and
      the `--flag=value` form work; `--non-interactive` changes nothing.
- [ ] **§S3** With standard input a terminal, the command does not prompt.
- [ ] **§S3** `--features ''`, `a,,b`, a duplicate name, `all,actionFusion` and a wrongly cased
      name; `--reducer` `provider/`, `/model` and ` p/m`; `--cache-ratio` `''`, `-1`, `1e3`, `0x10`
      and ` 2` each exit 2 with `usage`.
- [ ] **§S4** `--help` anywhere (for example `--install x --help`) exits 0 with the help text;
      `--version` after other arguments prints the version.
- [ ] **§S4** Every run other than help and version prints one envelope with the keys §S4 gives for
      its `verb`; with `--format json` it is one line that parses as the same object; a usage error
      with a malformed `--format` answers in TOON.
- [ ] **§S4** An unknown flag, a repeated flag, an extra argument and `--install` without a
      directory each exit 2 with `usage`, an `error` naming the input, and the valid flags; `--yes`
      carries the targeted hint.
- [ ] **§S4** No output on either stream contains a stack trace or a dependency's raw message.
- [ ] **§S4** `written` carries the start-Pi and trust next steps in `help[]`; `unchanged` carries
      none.
- [ ] **§S4** The home view shows `absent`, `valid` and `invalid` states for the project and agent
      files, and exits 0 in each.
- [ ] **§S4** A relative project directory resolves against the working directory.
- [ ] **§S5** README and `agents-install.md` cover every item §S5 lists, checked by
      `tests/install-guide.test.ts`; their install lines name `anthill-tec/SoL-Pi`.
- [ ] **§S5** `docs/configuration.md` and `agents-install.md` state the layout support;
      `THIRD_PARTY_NOTICES.md` lists `@toon-format/toon` 4.4.0; `CHANGELOG.md` `[Unreleased]`
      records the command.
- [ ] **Gate** `pre-merge-gate` passes.

## Estimated size

13 points. A non-interactive command with an install path, a strict flag grammar, an AXI envelope
for three verbs, signal handling, a shared validation module, the version stamp and docs.

## Risks

- `@toon-format/toon` becomes a runtime dependency, so a `pi install` from npm or git installs it
  alongside the extension. It has no dependencies of its own.
- A GitHub install builds nothing, so the command must run from source as shipped.

## Non-goals

- Prompts, `PI_NONINTERACTIVE` and the fish script (CR-SLP-005).
- An `--uninstall` mode.
- AXI session integrations (hooks) and an installable skill for the command.
- Pi distributions with their own configuration or agent directory names, and `file://` agent
  directories.
- Publishing to the npm registry (the name `sol-pi` belongs to another publisher).
- Reading a project's `.pi/settings.json` for Pi defaults, or recording trust in Pi.
- Keeping the Pi extension and the command at the same version automatically.
- README's star-history chart and its workflow, which still point at `NVlabs/SoL-Pi`.
