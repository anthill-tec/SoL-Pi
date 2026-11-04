# CR-SLP-004 — `sol-pi-setup`, an installed AXI command for per-project setup

**Status:** PENDING · Pre-review: due — touches another project's surface (Model B runs this command from `modelb-axi init` and `agents`, message #1516 items 1–4); 8 points; re-scoped after its pre-review (AXI adopted, prompts split to CR-SLP-005)
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
3. prompts only when a person is at a terminal, plus a non-interactive switch and
   `PI_NONINTERACTIVE`, which take the defaults and never prompt;
4. distinct exit codes and a final machine-readable result with the outcome and path.

The command follows the AXI standard for agent-facing command lines, as Model B's own
`modelb-axi` and Crucible's clients do: a TOON envelope on standard output, errors in the same
envelope, exit codes 0/1/2, no prompts, every value settable by flag, unknown input rejected, a
home view for no arguments, next steps in `help[]`, and a fast `--version`. Model B's item 3 is met
by prompting only on request (`--interactive`, CR-SLP-005); `PI_NONINTERACTIVE` still forbids it.
Model B's item 4 is met by the envelope, or one JSON line with `--format json`.

**Configuration semantics** (`docs/configuration.md`, `findConfigPath`, `loadSolPiConfig`). SoL-Pi
reads `<project>/.pi/sol-pi.json` only in a trusted project, and otherwise
`<agent dir>/sol-pi.json`. The project file replaces the global file; the two are not merged. An
omitted feature key is `false`, an omitted reducer provider or model is the built-in route
(`DEFAULT_REDUCER_PROVIDER`, `DEFAULT_REDUCER_MODEL`), and an omitted `cacheWriteReadRatio` is
12.5. The validation rules exist three times: `loadSolPiConfig`, `scripts/check-sol-pi-config.mjs`
and the setup script's `jq` checks. The setup script's defaults enable all four mechanisms, use a
ratio of 12.5, and point the reducer at Pi's default provider and model.

**Pi.** Pi's agent directory is `$PI_CODING_AGENT_DIR` (a leading `~` expanded), else
`~/.pi/agent`. Its `settings.json` holds `defaultProvider` and `defaultModel`. Pi 1.5's package
manager installs packages with peers omitted.

**Bun.** A Bun script loads the `.env` and `bunfig.toml` of the directory it runs in. Measured
with a globally installed test command run inside a directory with its own `.env` and
`bunfig.toml`: the `.env` values reached the command, and a `preload` from that `bunfig.toml` ran.
`#!/usr/bin/env -S bun --no-env-file --config=/dev/null` stopped both. `bun add --global` installs
a package's non-optional peer dependencies.

**TOON.** The official TypeScript encoder is `@toon-format/toon` (MIT, no dependencies; 4.4.0
current). Crucible pins it as its reference implementation.

## Scope

### §S1 — The installed command

**Surfaces:** `package.json` (`bin`, `files`, `dependencies`, `peerDependenciesMeta`), a new
`bin/sol-pi-setup.mjs`, a new version leaf module.

- `package.json` declares `"bin": { "sol-pi-setup": "bin/sol-pi-setup.mjs" }` and ships it.
- The command runs under Bun with `#!/usr/bin/env -S bun --no-env-file --config=/dev/null`, so the
  `.env` and `bunfig.toml` of the directory it runs in do not reach it.
- It is installed with `bun add --global github:anthill-tec/SoL-Pi#<version>`. `npm install
  --global github:anthill-tec/SoL-Pi#<version>` is the documented alternative, which still needs
  Bun on `PATH`. Model B probes `sol-pi-setup` on `PATH`, so Bun's global `bin` directory must be
  on `PATH`.
- `@toon-format/toon` is a runtime dependency at exactly `4.4.0`, SoL-Pi's only one.
- The command imports no Pi package. The Pi peer dependencies and `typebox` are marked optional in
  `peerDependenciesMeta`, so `bun add --global` installs no Pi package.
- **Version fast path.** `-v`, `-V` and `--version`, as the only argument, print the bare version
  and exit 0. The version comes from a leaf module that imports nothing; the rest of the command
  loads through a dynamic `import()` only after that check.

### §S2 — `sol-pi-setup --install <project dir>`

**Surfaces:** `bin/sol-pi-setup.mjs` and its modules, a new Pi-free configuration module that
`src/sol-pi/config.ts` and `scripts/check-sol-pi-config.mjs` also use.

- **Scope of the run.** It writes at most `<project dir>/.pi/sol-pi.json`, creating
  `<project dir>/.pi/` when missing. It runs no dependency install, typecheck, test or audit,
  registers nothing with Pi, and writes nothing outside that file.
- **Base values.** When the project file exists and is valid, its effective values (the runtime
  defaults for omitted keys). Otherwise, the agent directory's `sol-pi.json` when it exists, read
  the same way. Otherwise the setup defaults: all four mechanisms enabled, ratio 12.5, the reducer
  on Pi's `defaultProvider` and `defaultModel`.
- **Flags override the base** (§S3). With no value flag, an existing valid project file is left
  untouched: the run is a no-op (`unchanged`). The agent directory's file is not consulted when a
  project file exists.
- **Pi settings.** Read only when the setup defaults are used: the agent directory's
  `settings.json`, not a project's `.pi/settings.json`. A missing file means no Pi default; a
  malformed one fails the run. Setup defaults with no Pi default provider or model and no
  `--reducer` flag fail the run.
- **Validation.** One Pi-free module holds the schema and validation; `loadSolPiConfig` and
  `scripts/check-sol-pi-config.mjs` use it. An invalid file the run needs fails it and is left
  untouched.
- **Written form.** Every key, in the order of `sol-pi.example.json`, tab indentation, a final
  newline. With the reducer disabled and no provider or model to hand, the reducer keys are the
  built-in route, so the file always passes validation. When the text equals the file's bytes,
  nothing is written (`unchanged`).
- **Writing.** The text goes to a temporary file in the target's directory, renamed over the
  target. Through a symbolic link, the link's target file is replaced and the link kept. An existing
  file's permission bits are kept. The temporary file is removed on every failure and on `SIGINT`,
  `SIGTERM` and `SIGHUP`.
- **Earlier backups.** A `sol-pi.json.bak` left by an earlier setup script is not touched; a
  warning names it.

### §S3 — Every value by flag; no prompts

**Surfaces:** `bin/sol-pi-setup.mjs`.

- `--features <list>`: the enabled mechanisms, a comma-separated subset of `actionFusion`,
  `observationPack`, `evidencePreservingReducer`, `onlineContextCompact`, or `all` or `none`; the
  rest are disabled.
- `--reducer <provider>/<model>`: the reducer's provider and model (the model may contain `/`).
- `--cache-ratio <number>`: a finite non-negative number.
- `--format toon|json`: the output encoding; `toon` by default.
- The command never prompts without `--interactive` (CR-SLP-005). A required value it cannot
  resolve fails the run, with the flag that supplies it in `help[]`.

### §S4 — AXI output, errors and exit codes

**Surfaces:** `bin/sol-pi-setup.mjs`.

- **Envelope.** Standard output carries one TOON document, encoded with `@toon-format/toon`, whose
  root key is `axi`: `verb`, `ok`, `outcome` (`written`, `unchanged`, `failed`, `usage`, or
  `cancelled` from CR-SLP-005), `path` (the absolute configuration path, or `null`), `version`,
  `config` (`features` as a list of the enabled mechanisms, `reducer` as `<provider>/<model>`,
  `cacheRatio`), `context` (`project`, `agentDir`), `warnings`, `help`, and `error` when `ok` is
  false. `--format json` writes the same object as one JSON line.
- **Channels.** Standard output carries only the envelope; diagnostics go to standard error.
- **Exit codes.** 0 for `written` and `unchanged` (a no-op is success); 1 for `failed` (an invalid
  configuration or `settings.json`, no provider or model, a missing project directory, a write
  error); 2 for `usage`. Errors are envelopes on standard output, with no stack trace.
- **Unknown input.** An unknown flag, a repeated flag, an extra argument, `--install` without a
  directory, and a malformed flag value are usage errors, checked before anything is read. The
  error names the offending input and lists the valid flags.
- **Next steps.** `help[]` carries complete commands with `<placeholders>`: after `written`, start
  Pi in the project and trust it there (SoL-Pi reads the project file only in a trusted project);
  after an error, the command or flag that fixes it. A self-contained result carries none.
- **Home view.** With no arguments, the command prints, as an envelope with `verb` `home`: its
  executable path with the home directory as `~`, a one-sentence description, and the state of
  the working directory: whether `.pi/sol-pi.json` exists, its enabled mechanisms and reducer, and
  whether the agent directory has a `sol-pi.json`; with next steps. Exit 0.
- **Help.** `--help` prints the flags with their defaults, the arguments and two or three examples,
  and exits 0.
- `PI_CODING_AGENT_DIR` is read as Pi reads it, including a leading `~`. A relative project
  directory resolves against the working directory.

### §S5 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `docs/configuration.md`, `CHANGELOG.md`.

- README and `agents-install.md` document:
  - the install command and its npm alternative, that both need Bun, and that Bun's global `bin`
    directory must be on `PATH`;
  - `sol-pi-setup --install`, its flags, `PI_NONINTERACTIVE`, the envelope, `--format json` and
    the exit codes;
  - that the Pi extension (`pi install git:github.com/anthill-tec/SoL-Pi@<version>`) and the
    command are two installs, made at the same version.
- README installs the Pi package from `anthill-tec/SoL-Pi`, not `NVlabs/SoL-Pi`.
- The statements that SoL-Pi reads no environment variables say instead that the extension reads
  none, and `sol-pi-setup` reads `PI_NONINTERACTIVE` and `PI_CODING_AGENT_DIR`.
- `docs/configuration.md` notes that a project's `.pi/sol-pi.json` is read only in a trusted
  project, and how `sol-pi-setup` chooses its values.
- `THIRD_PARTY_NOTICES.md` lists `@toon-format/toon`.
- `CHANGELOG.md` `[Unreleased]` records the command.

## Acceptance criteria

Tests run the command against a temporary project, agent directory and home, with
`PI_CODING_AGENT_DIR` set, and decode its output with `@toon-format/toon`'s `decode`.

- [ ] **§S1** `bun pm pack` lists `bin/sol-pi-setup.mjs` and the leaf version module; `package.json`
      maps `sol-pi-setup` to it, with the shebang §S1 gives, and `dependencies` is exactly
      `{"@toon-format/toon": "4.4.0"}`.
- [ ] **§S1** Installing the packed tarball with `bun add --global` into a temporary `BUN_INSTALL`
      puts `sol-pi-setup` in that install's `bin` and adds no `@earendil-works/*` or `typebox`
      package; `sol-pi-setup --version` there prints `package.json`'s version.
- [ ] **§S1** Run from a directory whose `.env` sets `PI_CODING_AGENT_DIR` and whose `bunfig.toml`
      has a `preload`, the installed command does not see the variable and the preload does not
      run.
- [ ] **§S1** `bin/sol-pi-setup.mjs` and the modules it imports import no `@earendil-works/*`
      package; the version module imports nothing.
- [ ] **§S1** `pi install` of the packed tarball into a temporary agent directory succeeds offline,
      and `pi list` shows it.
- [ ] **§S1** `-v`, `-V` and `--version` each print the bare version and exit 0, and take no more
      than twice the time of `bun -e "console.log(1)"` measured in the same test.
- [ ] **§S2** With no configuration anywhere, `--install` writes the setup defaults with Pi's
      default provider and model, exits 0 and reports `written`; a second run reports `unchanged`
      and leaves the bytes and modification time alone.
- [ ] **§S2** A valid partial project file (for example `{"version":1,"actionFusion":true}`) is
      left byte-for-byte unchanged by a run with no value flag, which reports `unchanged`, even
      when the agent directory's file is invalid and Pi has no default model.
- [ ] **§S2** With no project file, the agent directory's `sol-pi.json` supplies the values.
- [ ] **§S2** An invalid project file, or an invalid agent-directory file when there is no project
      file, exits 1 with `failed`, and no file changes; so does a malformed `settings.json` when
      the setup defaults are used.
- [ ] **§S2** With the setup defaults, no Pi default provider or model and no `--reducer`, the run
      exits 1 with `failed`, creates no file, and its `help[]` names `--reducer`.
- [ ] **§S2** Listing `<project dir>/.pi/` before and after any run shows no added file other than
      `sol-pi.json`; a leftover `sol-pi.json.bak` is still there and named in `warnings`.
- [ ] **§S2** Every written file is accepted by `loadSolPiConfig` and by
      `scripts/check-sol-pi-config.mjs`, and both use the shared module.
- [ ] **§S2** A write through a symbolic link replaces the link's target and keeps the link; an
      existing file's permission bits are kept; a run killed with `SIGTERM` during the write
      leaves no temporary file.
- [ ] **§S3** `--features`, `--reducer` and `--cache-ratio` each override the base values and
      write; repeating the same flags reports `unchanged`. `--features all` and `--features none`
      work.
- [ ] **§S3** With standard input a terminal and no `--interactive`, the command does not prompt.
- [ ] **§S4** Every run's standard output decodes as TOON to one object with root key `axi` and the
      keys §S4 lists; with `--format json` it is one line that parses as the same object.
- [ ] **§S4** An unknown flag, a repeated flag, an extra argument, `--install` without a directory
      and a malformed `--features`, `--reducer` or `--cache-ratio` value each exit 2 with `usage`,
      an `error` naming the input, and the valid flags; a missing project directory exits 1.
- [ ] **§S4** No error output contains a stack trace or a dependency's raw message.
- [ ] **§S4** `written` carries the start-Pi and trust next steps in `help[]`; `unchanged` carries
      none.
- [ ] **§S4** No arguments prints the home view and exits 0; `--help` exits 0 and names every
      flag with its default.
- [ ] **§S4** `PI_CODING_AGENT_DIR=~/agent` reads `$HOME/agent`; a relative project directory
      resolves against the working directory.
- [ ] **§S5** README and `agents-install.md` cover every item §S5 lists, and
      `tests/install-guide.test.ts` checks them; `git grep -n NVlabs -- README.md agents-install.md`
      returns nothing.
- [ ] **Gate** `pre-merge-gate` passes.

## Estimated size

8 points. A non-interactive command with an install path, flags, an AXI envelope and its failure
paths, a shared validation module and docs.

## Risks

- `@toon-format/toon` becomes a runtime dependency, so `pi install` installs it alongside the
  extension. It has no dependencies of its own.
- A GitHub install builds nothing, so the command must run from source as shipped.

## Non-goals

- Prompts, cancel handling and the fish script (CR-SLP-005).
- An `--uninstall` mode.
- AXI session integrations (hooks) and an installable skill for the command.
- Publishing to the npm registry (the name `sol-pi` belongs to another publisher).
- Reading a project's `.pi/settings.json` for Pi defaults, or recording trust in Pi.
- Keeping the Pi extension and the command at the same version automatically.
