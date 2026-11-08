# CR-SLP-004 — `sol-pi-axi`, an installed AXI command, and its `setup` verb

**Status:** PENDING · Pre-review: ran — touches another project's surface (Model B runs `sol-pi-axi setup` from `modelb-axi init` and `agents`, message #1516 items 1–4); 8 points or more; re-designed 2026-11-04 (Python package on PyPI, in place of a Bun command)
**Type:** feature
**Priority:** P1 — Model B makes SoL-Pi a prerequisite of every Model B project on Pi
**Depends on:** CR-SLP-001
**Labels:** setup, cli, axi, python, docs
**Phase:** 0.1.0 · wave 1
**Design reference:** the AXI standard (<https://axi.md>; its skill, `kunchenguid/axi`
`.agents/skills/axi/SKILL.md`); the TOON specification (<https://toonformat.dev>);
`docs/configuration.md` (search order, schema, trust); Model B's request, Sandesh message #1516
items 1–4; the distribution pattern of Crucible (`crucible-axi` on PyPI beside
`@anthill-tec/crucible-server` on npm) and Sandesh (`sandesh-relay` beside `@anthill-tec/sandesh-pi`)

## Context

SoL-Pi is set up today by running `setup-sol-pi.fish` from a checkout. Model B will run SoL-Pi's
per-project setup for every project it scaffolds, and reaches SoL-Pi only through what SoL-Pi's
installer puts on the machine, never through a checkout. It asked for (#1516):

1. an installed, versioned entry point outside any checkout, with a stated install command, a
   name to probe and a way to read its version;
2. a light per-project mode that writes or refreshes only `<project dir>/.pi/sol-pi.json`: no
   dependency install, typecheck, tests or audit, no user-wide `pi install`, and no `.bak` left in
   the project;
3. prompts only when a person is at a terminal, plus a non-interactive switch (passed under
   Model B's `--yes`) and `PI_NONINTERACTIVE`, which take the defaults and never prompt;
4. distinct exit codes and a final machine-readable result with the outcome and path.

**Distribution (user ruling, 2026-11-04).** SoL-Pi follows the pattern of Crucible and Sandesh:
the Pi extension is an npm package, and the machine-side tool is a Python package installed with
`uv tool install`. The tool is `sol-pi-axi`, one console script with verbs. This CR creates the
package with its `setup` verb and home view; CR-SLP-007 adds `install`/`uninstall` (registering the
extension with Pi at the tool's own version) and publishes both packages; CR-SLP-005 adds
`--interactive`.

The command follows the AXI standard, as Model B's `modelb-axi` and Crucible's clients do: a TOON
envelope on standard output, errors in the same envelope, exit codes 0/1/2, no prompts, every
value settable by flag, unknown input rejected, a home view for no arguments, next steps in
`help[]`, and a fast `--version`. The user ruled: prompts only on request (`--interactive`,
CR-SLP-005, which also reads `PI_NONINTERACTIVE`); the envelope is TOON by default, and
`--format json` gives one JSON line; the encoder is the official one.

**Configuration semantics** (`docs/configuration.md`, `findConfigPath`, `loadSolPiConfig`). SoL-Pi
reads `<project>/.pi/sol-pi.json` only in a trusted project, and otherwise
`<agent dir>/sol-pi.json`. The project file replaces the global file; the two are not merged. An
omitted feature key is `false`, an omitted reducer provider or model is the built-in route
(`DEFAULT_REDUCER_PROVIDER`, `DEFAULT_REDUCER_MODEL`), and an omitted `cacheWriteReadRatio` is
12.5. The validation rules exist in `loadSolPiConfig`, in `scripts/check-sol-pi-config.mjs` and in
the setup script's `jq` checks. The setup script's defaults enable all four mechanisms, use a
ratio of 12.5, and point the reducer at Pi's default provider and model.

**Pi.** The extension finds its files through Pi's `CONFIG_DIR_NAME` and `getAgentDir()`. For the
official Pi these are `.pi`, and `$PI_CODING_AGENT_DIR` (when non-empty; a leading `~` expanded)
else `~/.pi/agent`. A Pi distribution may change them. The agent directory's `settings.json`
holds `defaultProvider` and `defaultModel`.

**Python and TOON.** Crucible's `crucible-axi` and Model B's `modelb-axi` require Python 3.14 or
later; `uv tool install` fetches that interpreter when the machine lacks it. The official Python
TOON implementation is `toon-format` on PyPI (MIT, from the `toon-format` project that publishes
`@toon-format/toon`; 1.2.0 current; no runtime dependencies). Measured: an envelope with nested
objects, a list of strings, an empty list, a path and a decimal encodes and decodes back unchanged.
Model B's release tooling (`stamp_version.py`) reads a `pypi` target's version from
`[project] version`, or under hatchling's dynamic version from the `__version__` line of the file
`[tool.hatch.version] path` names.

## Scope

### §S1 — The Python package

**Surfaces:** a new `pyproject.toml` and `sol_pi_axi/` package at the repository root, a new
`sol_pi_axi/_version.py`, `.gitignore`, `package.json` `files` (unchanged, verified).

- `pyproject.toml` declares the distribution `sol-pi-axi`: `requires-python = ">=3.14"`, license
  MIT with `LICENSE`, `readme` `README.md`, the hatchling build backend, the console script
  `sol-pi-axi = "sol_pi_axi.cli:main"`, and exactly one runtime dependency, `toon-format==1.2.0`.
- A `dev` optional-dependency group lists what the tests need beyond the runtime dependency:
  `unittest-xml-reporting` and `coverage`.
- **Version.** The version is dynamic, from `sol_pi_axi/_version.py`'s `__version__ = "X.Y.Z"`
  (`[tool.hatch.version] path`), which imports nothing. It equals `package.json`'s `version`; a
  test keeps the two equal.
- **What ships.** The wheel holds only the `sol_pi_axi` package and its metadata. The source
  distribution holds only `pyproject.toml`, `README.md`, `LICENSE` and `sol_pi_axi/`. The npm
  package holds no Python file: `package.json` `files` already lists only the extension's files.
- **Python tests** are `tests/test_*.py`, run with `unittest` discovery from `tests`, beside the
  Bun tests; neither runner collects the other's files. A new `tests/__init__.py` makes `tests` a
  package, for dotted test targets and discovery with `-t .`. The tests import `sol_pi_axi` as an
  installed package: the project's `.venv` (Python 3.14) holds it editable with its `dev` extra
  (`uv venv --python 3.14`, then `uv pip install -e '.[dev]'`), which is the precondition of the
  Python test runs. Until CR-SLP-007 adds the `test-python` CI job, the Python tests are gated
  locally only.
- `.gitignore` adds `.venv/` and `*.egg-info/`.
- The package imports no Node or Pi code and runs no `bun` or `node`.
- **Version fast path.** A lone `-v`, `-V` or `--version` prints the bare version and exits 0
  before `toon_format` or any verb module is imported.

### §S2 — `sol-pi-axi setup <project dir>`

**Surfaces:** `sol_pi_axi/` (its `setup` verb, a configuration module, a writing module).

- **Layout.** The command supports the official Pi layout only: `<project>/.pi/sol-pi.json`, and
  the agent directory `$PI_CODING_AGENT_DIR` (when non-empty, with a leading `~` expanded) else
  `~/.pi/agent`.
- **Scope of the run.** It writes at most `<project dir>/.pi/sol-pi.json`, creating
  `<project dir>/.pi/` when missing; a run that fails or is cancelled removes a `.pi/` it created. It runs no
  dependency install, typecheck, test or audit, registers nothing with Pi, and writes nothing
  else. A project path that does not exist, or is not a directory, fails the run.
- **Target paths.** Each of these fails the run, changes no file and names the path in `error`:
  `<project>/.pi` existing as something other than a directory; `.pi/sol-pi.json` existing as a
  directory; a `.pi/` the run cannot write to. A `sol-pi.json` symbolic link whose target does not
  exist is an existing project file that cannot be read.
- **Base values.** When the project file exists and is valid, its effective values (the runtime
  defaults for omitted keys). Otherwise, the agent directory's `sol-pi.json` when it exists, read
  the same way. Otherwise the setup defaults: all four mechanisms enabled, ratio 12.5, the reducer
  on Pi's `defaultProvider` and `defaultModel`.
- **Flags override the base** (§S3). With no value flag, an existing valid project file is left
  untouched (`unchanged`). The agent directory's file is not consulted when a project file exists.
- **Pi settings.** Read only when the setup defaults are used: the agent directory's
  `settings.json`, not a project's. A missing file means no Pi default; one that is not valid JSON,
  or whose root is not an object, fails the run. A `defaultProvider` or `defaultModel` that is not a
  non-empty string free of whitespace counts as absent. Pi's default is used only when both are
  present. When the resulting configuration enables the reducer and has no provider or model (no
  usable Pi default and no `--reducer`), the run fails. With the reducer disabled, the reducer keys are the
  built-in route.
- **Validation.** `sol_pi_axi`'s configuration module applies the rules of `loadSolPiConfig`: a
  JSON object, only known keys, `version` 1, boolean features, a finite non-negative ratio,
  non-empty reducer strings trimmed as JavaScript's `trim()` trims. JSON is read as JavaScript's
  `JSON.parse` reads it: the `NaN` and `Infinity` literals are rejected, and a boolean is never a
  number (`version: true` and a ratio of `true` are invalid). A shared table of conformance cases
  under `tests/fixtures/sol-pi-config/` (each a configuration file and its expected verdict and
  effective values) is run by a Python test against the module and by a Bun test against
  `loadSolPiConfig` and `scripts/check-sol-pi-config.mjs`, so the implementations cannot drift
  apart.
- **Golden written files.** `tests/fixtures/sol-pi-config/written/` holds the files `setup` writes
  for a fixed set of inputs (the setup defaults, every feature list form, the reducer off, a custom
  ratio). A Python test asserts `setup` writes exactly those bytes; the Bun test runs each through
  `loadSolPiConfig` and `scripts/check-sol-pi-config.mjs`. Neither runner needs the other's
  runtime. An invalid
  file the run needs fails it and is left untouched.
- **Written form.** Every key, in the order of `sol-pi.example.json`, tab indentation, a final
  newline. When the text equals the file's bytes, nothing is written (`unchanged`).
- **Writing.** The text goes to a temporary file in the target's directory, renamed over the
  target. Through a symbolic link, the link's target file is replaced and the link kept. An existing
  file's permission bits are kept; a new file gets `0o666` less the process's umask. The writing module takes an optional hook between writing the
  temporary file and renaming it, which only tests set.
- **Signals.** `SIGINT`, `SIGTERM` or `SIGHUP` during a run removes the temporary file and a `.pi/`
  the run created, writes nothing, prints the envelope with `outcome` `cancelled`, and exits 130,
  143 or 129. The command installs its own handlers for the three whatever disposition it
  inherited.
- **Earlier backups.** A `sol-pi.json.bak` left by an earlier setup script is not touched; a
  warning names it.

### §S3 — Every value by flag; no prompts

**Surfaces:** `sol_pi_axi/` (argument parsing).

- **Grammar.** `sol-pi-axi [<verb>] [<arguments>] [<flags>]`. The verbs this CR adds are `setup`
  (one argument, the project directory) and none (the home view). Flags may come before or after
  the verb's argument.
- **Flags.** Each takes its value as `--flag value` or `--flag=value`.
  - `--features <list>`: `all`, `none`, or a comma-separated list of distinct mechanism names
    (`actionFusion`, `observationPack`, `evidencePreservingReducer`, `onlineContextCompact`,
    exact case, no empty entries); the others are disabled.
  - `--reducer <provider>/<model>`: split at the first `/`; both parts non-empty with no
    whitespace (the model may contain `/`).
  - `--cache-ratio <number>`: digits with an optional decimal fraction (no sign, exponent, hex or
    surrounding space), whose value is finite.
  - `--format toon|json`: the output encoding; `toon` by default.
  - `--non-interactive`: accepted and changes nothing, since the command never prompts; it is the
    switch Model B passes under its `--yes`.
  - The value flags (`--features`, `--reducer`, `--cache-ratio`, `--non-interactive`) belong to
    `setup`; given to the home view they are usage errors.
- **Help and version anywhere.** `--help` or `-h` anywhere in the arguments prints the help and
  exits 0, before any other check. Otherwise `-v`, `-V` or `--version` anywhere prints the bare
  version and exits 0.
- The command never prompts. A value it cannot resolve fails the run, with the flag that supplies
  it in `help[]`.

### §S4 — AXI output, errors and exit codes

**Surfaces:** `sol_pi_axi/` (envelope, help text, entry point).

- **What prints outside the envelope.** The version path prints the bare version; `--help` prints
  a plain-text reference: the verbs, the flags with their defaults, two or three examples. Every
  other run prints one envelope.
- **Envelope.** One TOON document encoded with `toon_format.encode`, root key `axi`; with
  `--format json`, the same object as one JSON line. `--format` is read from the arguments before
  anything else is checked; a run whose `--format` is missing or malformed answers in TOON.
  - Every envelope: `verb`, `ok`, `version`, `warnings`, `help`, and `error` when `ok` is false.
  - `verb: setup`: `outcome` (`written`, `unchanged`, `failed`, `cancelled`), `path` (the absolute
    configuration path, or `null`), `config` (`features` as the enabled mechanisms, `reducer` as
    `<provider>/<model>`, `cacheRatio`; `null` when no configuration was resolved), `context`
    (`project`, `agentDir`).
  - `verb: usage` (an argument error): `outcome: usage`, `error`, `help`.
  - `verb: home`: `bin` (the executable path, home as `~`), `description` (one sentence), and
    `project` (the working directory's `.pi/sol-pi.json`) and `agentConfig`, each with `path` and
    `state` (`absent`, `valid` with its `features` and `reducer`, or `invalid` with the reason).
- **Channels.** Standard output carries only the envelope (or the version or help text);
  diagnostics go to standard error. No traceback or dependency message reaches either: an
  unexpected exception is reported as `failed` with its type named, exit 1.
- **Exit codes.** 0 for `written`, `unchanged` and the home view (an invalid file shown there is
  reported, not a failure); 1 for `failed`; 2 for `usage`; 130, 143 or 129 for `cancelled`.
- **Unknown input.** An unknown verb, an unknown flag, a repeated flag, an extra argument, `setup`
  without a directory, and a value outside §S3's grammar are usage errors, checked before anything
  is read. The error names the offending input and lists the valid verbs and flags. `--yes` gets a
  targeted hint: the command never prompts, and `--non-interactive` is the explicit switch.
- **Next steps.** `help[]` carries complete commands with `<placeholders>`: after `written`, start
  Pi in the project and trust it there; after an error, the command or flag that fixes it; from the
  home view, `sol-pi-axi setup <project dir>`. `unchanged` carries none.
- A relative project directory resolves against the working directory.

### §S5 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `docs/configuration.md`, `THIRD_PARTY_NOTICES.md`,
`CHANGELOG.md`.

- README and `agents-install.md` document `sol-pi-axi setup`, its flags (including
  `--non-interactive`), the envelope and its keys, `--format json`, the home view and the exit
  codes. The install command for `sol-pi-axi` is CR-SLP-007's; until it lands, the documented
  install is `uv tool install git+https://github.com/anthill-tec/SoL-Pi@<version>`.
- README's install lines name `anthill-tec/SoL-Pi`, not `NVlabs/SoL-Pi`.
- The statements that SoL-Pi reads no environment variables say instead that the extension reads
  none and `sol-pi-axi` reads `PI_CODING_AGENT_DIR`.
- `docs/configuration.md` and `agents-install.md` state that the extension follows Pi's
  configuration directory and agent directory, while `sol-pi-axi` supports only the official
  layout; `docs/configuration.md` also notes that a project file is read only in a trusted project,
  and how `sol-pi-axi setup` chooses its values.
- `THIRD_PARTY_NOTICES.md` lists `toon-format` 1.2.0 (MIT).
- `CHANGELOG.md` `[Unreleased]` records the command.

## Acceptance criteria

Tests run the command against a temporary project, agent directory and home, with
`PI_CODING_AGENT_DIR` set, and decode envelopes with `toon_format.decode`.

- [ ] **§S1** `uv build` produces a wheel holding only `sol_pi_axi/` and its metadata, with the
      `sol-pi-axi` console script, `Requires-Python: >=3.14` and the single requirement
      `toon-format==1.2.0`; the source distribution holds only §S1's files.
- [ ] **§S1** The wheel installed with `uv tool install` into a temporary `UV_TOOL_DIR` and
      `UV_TOOL_BIN_DIR`: `sol-pi-axi --version` prints `package.json`'s version;
      `sol-pi-axi setup <temporary project>` writes the file and prints a decodable envelope;
      `sol-pi-axi` with no arguments prints a decodable home view.
- [ ] **§S1** `__version__` equals `package.json`'s `version`, and `stamp_version.py read pypi:.`
      reads it.
- [ ] **§S1** `bun pm pack --dry-run` lists no `.py` file and no `pyproject.toml`.
- [ ] **§S1** The Python suite runs through the python client's discovery from `tests` and through
      `python -m unittest discover -s tests -t .`, both against the editable install, with the same
      tests passing.
- [ ] **§S1** No module of `sol_pi_axi` starts `bun` or `node` or imports Node or Pi code.
- [ ] **§S1** `-v`, `-V` and `--version` each print the bare version and exit 0 with `toon_format`
      not imported (checked by a run that makes the import fail); the median of five runs of the
      installed script takes no more than twice the median of five `<same interpreter> -c pass`
      runs in the same test.
- [ ] **§S2** With no configuration anywhere, `setup` writes the setup defaults with Pi's default
      provider and model, exits 0 and reports `written`; a second run reports `unchanged` and
      leaves the bytes and modification time alone.
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
- [ ] **§S2** `<project>/.pi` as a regular file, `.pi/sol-pi.json` as a directory, a dangling
      `sol-pi.json` link, and a read-only `.pi/` each exit 1 with `failed`, change no file and name
      the path in `error`.
- [ ] **§S2** A `settings.json` whose root is an array fails the run; a non-string, empty or
      whitespace-holding `defaultProvider` or `defaultModel`, and only one of the two present, each
      count as no Pi default, so the run fails with `--reducer` in `help[]` when the reducer is
      enabled.
- [ ] **§S2** Listing `<project dir>/.pi/` before and after any run shows no added file other than
      `sol-pi.json`; a leftover `sol-pi.json.bak` is still there and named in `warnings`.
- [ ] **§S2** The conformance table covers at least: a minimal valid file, every key valid, an
      unknown key, `version` 2, `true`, `1.0` and `"1"`, a non-boolean feature, a negative, string
      and `true` ratio, the `NaN` and `Infinity` literals and `1e999` as the ratio, an empty, a
      whitespace-only and a padded reducer string (the last valid, its value trimmed), a JSON array
      and malformed JSON. The Python test and the Bun test each pass every case.
- [ ] **§S2** `setup` writes exactly the golden files' bytes for their inputs, and the Bun test
      accepts every golden file through `loadSolPiConfig` and `scripts/check-sol-pi-config.mjs`.
- [ ] **§S2** Under umask 022, a newly written `sol-pi.json` has mode 0644.
- [ ] **§S2** A write through a symbolic link replaces the link's target and keeps the link; an
      existing file's permission bits are kept.
- [ ] **§S2** With the test hook holding a run between writing and renaming, `SIGINT`, `SIGTERM`
      and `SIGHUP` each leave no temporary file and no changed file, print `cancelled`, and exit
      130, 143 and 129; started on a project with no `.pi/`, the project still has none; started
      with `SIGINT` ignored, `SIGINT` still cancels.
- [ ] **§S2** `PI_CODING_AGENT_DIR=~/agent` reads `$HOME/agent`; an empty `PI_CODING_AGENT_DIR`
      reads `~/.pi/agent`.
- [ ] **§S3** `--features`, `--reducer` and `--cache-ratio` each override the base values and
      write; repeating the same flags reports `unchanged`; `--features all`, `--features none` and
      the `--flag=value` form work; flags before and after the directory work;
      `--non-interactive` changes nothing.
- [ ] **§S3** With standard input a terminal, the command does not prompt.
- [ ] **§S3** `--features ''`, `a,,b`, a duplicate name, `all,actionFusion` and a wrongly cased
      name; `--reducer` `provider/`, `/model` and ` p/m`; `--cache-ratio` `''`, `-1`, `1e3`, `0x10`
      and ` 2`, and `1` followed by 400 zeros, each exit 2 with `usage`.
- [ ] **§S4** `--help` anywhere (for example `setup x --help`) exits 0 with the help text;
      `--version` after other arguments prints the version.
- [ ] **§S4** Every run other than help and version prints one envelope with the keys §S4 gives for
      its `verb`; with `--format json` it is one line that parses as the same object; a usage error
      with a malformed `--format` answers in TOON.
- [ ] **§S4** An unknown verb, an unknown flag, a repeated flag, an extra argument, `setup`
      without a directory and a value flag on the home view each exit 2 with `usage`, an `error`
      naming the input, and the valid verbs and flags; `--yes` carries the targeted hint.
- [ ] **§S4** No output on either stream contains a traceback or a dependency's raw message,
      including a run whose configuration module is made to raise.
- [ ] **§S4** `written` carries the start-Pi and trust next steps in `help[]`; `unchanged` carries
      none.
- [ ] **§S4** The home view shows `absent`, `valid` and `invalid` states for the project and agent
      files, and exits 0 in each.
- [ ] **§S4** A relative project directory resolves against the working directory.
- [ ] **§S5** README and `agents-install.md` cover every item §S5 lists, checked by
      `tests/install-guide.test.ts`; their install lines name `anthill-tec/SoL-Pi`.
- [ ] **§S5** `docs/configuration.md` and `agents-install.md` state the layout support;
      `THIRD_PARTY_NOTICES.md` lists `toon-format` 1.2.0; `CHANGELOG.md` `[Unreleased]` records the
      command.
- [ ] **Gate** The Bun and the Python `pre-merge-gate` both pass.

## Estimated size

13 points, at the cap. A new Python package with its packaging and test layout, a strict flag
grammar, an AXI envelope for three verbs, signal handling, a validation module held equal to the
extension's by a shared conformance table and golden files across two runtimes, the target-path
edge cases, the version fast path and docs.

## Risks

- The validation rules now live in Python as well as TypeScript; the conformance table is the only
  thing holding them equal, so a rule change must add a case.
- The installed-wheel test needs `toon-format` from PyPI or uv's cache.
- `toon-format` 1.x is young; it is pinned exactly, and moving it is a deliberate change.

## Non-goals

- `install`, `uninstall`, publishing to PyPI and npm, and the extension's registration
  (CR-SLP-007).
- Prompts, `PI_NONINTERACTIVE` and retiring the fish script (CR-SLP-005).
- AXI session integrations (hooks) and an installable skill for the command.
- Pi distributions with their own configuration or agent directory names, and `file://` agent
  directories.
- Reading a project's `.pi/settings.json` for Pi defaults, or recording trust in Pi.
- README's star-history chart and its workflow, which still point at `NVlabs/SoL-Pi`.
