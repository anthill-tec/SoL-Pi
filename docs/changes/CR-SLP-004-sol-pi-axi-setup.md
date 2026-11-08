# CR-SLP-004 — `sol-pi-axi`, an installed AXI command, and its `setup` verb

**Status:** PENDING · Pre-review: ran — touches another project's surface (Model B runs `sol-pi-axi setup`, #1516 items 1–4); 8 points or more
**Type:** feature
**Priority:** P1 — Model B makes SoL-Pi a prerequisite of every Model B project on Pi
**Depends on:** CR-SLP-001
**Labels:** setup, cli, axi, python, docs
**Phase:** 0.1.0 · wave 1
**Design reference:** `docs/research/DN-sol-pi-axi.md` §D1–§D3; `docs/configuration.md`; the AXI standard (<https://axi.md>)

## Context

SoL-Pi is set up only by running `setup-sol-pi.fish` from a checkout. Its project mode runs the
checkout's validation, registers SoL-Pi user-wide with `pi install`, leaves a `.bak` beside
`.pi/sol-pi.json`, exits 0 on a cancel, and prints no machine-readable result (#1516 items 1–4).

## Scope

### §S1 — The Python package

**Surfaces:** `pyproject.toml`, `sol_pi_axi/`, `sol_pi_axi/_version.py`, `tests/__init__.py`,
`.gitignore`.

- `pyproject.toml`: distribution `sol-pi-axi`; `requires-python = ">=3.14"`; license MIT with
  `LICENSE`; `readme` `README.md`; hatchling; console script `sol-pi-axi = "sol_pi_axi.cli:main"`;
  one runtime dependency, `toon-format==1.2.0`; a `dev` extra with `unittest-xml-reporting` and
  `coverage`.
- Dynamic version from `sol_pi_axi/_version.py` (`__version__ = "X.Y.Z"`, no imports), equal to
  `package.json` `version`.
- The wheel holds only `sol_pi_axi/` and metadata; the sdist only `pyproject.toml`, `README.md`,
  `LICENSE`, `sol_pi_axi/`.
- Python tests are `tests/test_*.py`; `tests/__init__.py` makes `tests` a package. They import the
  package from an editable install in `.venv` (Python 3.14, `uv pip install -e '.[dev]'`).
- `.gitignore` adds `.venv/` and `*.egg-info/`.
- The package starts no `bun` or `node` and imports no Node or Pi code.
- A lone `-v`, `-V` or `--version` prints the bare version and exits 0 before `toon_format` or any
  verb module is imported.

### §S2 — `sol-pi-axi setup <project dir>`

**Surfaces:** `sol_pi_axi/` (`setup` verb, configuration module, writing module),
`tests/fixtures/sol-pi-config/`, a Bun conformance test.

- **Layout.** `<project>/.pi/sol-pi.json`; the agent directory is `$PI_CODING_AGENT_DIR` when
  non-empty (a leading `~` expanded), else `~/.pi/agent`.
- **Writes** at most `<project dir>/.pi/sol-pi.json`, creating `.pi/` when missing; a failed or
  cancelled run removes a `.pi/` it created. No dependency install, typecheck, test, audit or Pi
  registration.
- **Paths.** A project path that does not exist or is not a directory, `<project>/.pi` that is not a
  directory, `sol-pi.json` that is a directory, and an unwritable `.pi/` each fail the run, naming
  the path. A dangling `sol-pi.json` link is an existing file that cannot be read.
- **Base values.** A valid project file's effective values; else the agent directory's
  `sol-pi.json`, read the same way; else the setup defaults: all four mechanisms on, ratio 12.5,
  reducer on Pi's default provider and model. The agent file is not read when a project file
  exists. With no value flag, a valid project file is left untouched (`unchanged`).
- **Pi settings** (read only for the setup defaults): the agent directory's `settings.json`. Missing
  means no Pi default; invalid JSON or a non-object root fails the run. `defaultProvider` and
  `defaultModel` count only when both are non-empty strings without whitespace. The reducer enabled
  with no provider or model and no `--reducer` fails the run; the reducer disabled writes the
  built-in route (`DEFAULT_REDUCER_PROVIDER`, `DEFAULT_REDUCER_MODEL`).
- **Validation** applies `loadSolPiConfig`'s rules: a JSON object, known keys only, `version` 1,
  boolean features, a finite non-negative ratio, non-empty reducer strings trimmed as JavaScript's
  `trim()`. JSON is read as `JSON.parse` reads it: `NaN` and `Infinity` rejected, a boolean never a
  number. An invalid file the run needs fails it, untouched.
- **Conformance.** `tests/fixtures/sol-pi-config/` holds cases (a file, its verdict, its effective
  values), run by a Python test against the module and a Bun test against `loadSolPiConfig` and
  `scripts/check-sol-pi-config.mjs`. `tests/fixtures/sol-pi-config/written/` holds the bytes `setup`
  writes for fixed inputs (setup defaults, each feature-list form, reducer off, a custom ratio);
  Python asserts `setup` writes them, Bun accepts each through both validators.
- **Written form.** Every key in `sol-pi.example.json`'s order, tab indentation, final newline.
  Equal bytes are not rewritten (`unchanged`).
- **Writing.** A temporary file in the target's directory, renamed over the target; through a
  symbolic link the target is replaced and the link kept; an existing file's mode kept, a new file
  `0o666` less the umask. An optional test-only hook runs between write and rename.
- **Signals.** The command installs its own `SIGINT`, `SIGTERM` and `SIGHUP` handlers whatever it
  inherited. Each removes the temporary file and a `.pi/` the run created, writes nothing, prints
  `cancelled`, and exits 130, 143 or 129.
- A leftover `sol-pi.json.bak` is not touched and is named in `warnings`.

### §S3 — Flags; no prompts

**Surfaces:** `sol_pi_axi/` (argument parsing).

- `sol-pi-axi [<verb>] [<arguments>] [<flags>]`; verbs `setup` (one argument) and none (home view);
  flags before or after the argument; `--flag value` or `--flag=value`.
- `--features`: `all`, `none`, or a comma list of distinct names from `actionFusion`,
  `observationPack`, `evidencePreservingReducer`, `onlineContextCompact` (exact case, no empty
  entry); unlisted ones off.
- `--reducer <provider>/<model>`: split at the first `/`, both parts non-empty without whitespace.
- `--cache-ratio`: digits with an optional decimal fraction, finite.
- `--format toon|json`, default `toon`. `--non-interactive`: accepted, no effect.
- Value flags and `--non-interactive` belong to `setup`.
- `--help`/`-h` anywhere prints help and exits 0 first; otherwise `-v`/`-V`/`--version` anywhere
  prints the version and exits 0.
- Never prompts; an unresolvable value fails the run with its flag in `help[]`.

### §S4 — Envelope, errors, exit codes

**Surfaces:** `sol_pi_axi/` (envelope, help text, entry point).

- `--help` prints plain text (verbs, flags with defaults, examples); every other run except the
  version prints one envelope.
- Envelope: TOON via `toon_format.encode`, root `axi`; `--format json` gives the same object as one
  JSON line. `--format` is read first; a missing or malformed `--format` answers in TOON.
  - Every envelope: `verb`, `ok`, `version`, `warnings`, `help`; `error` when `ok` is false.
  - `verb: setup`: `outcome` (`written`, `unchanged`, `failed`, `cancelled`), `path` (absolute or
    `null`), `config` (`features` list, `reducer` `<provider>/<model>`, `cacheRatio`; or `null`),
    `context` (`project`, `agentDir`).
  - `verb: usage`: `outcome: usage`, `error`, `help`.
  - `verb: home`: `bin` (home as `~`), `description`, `project` (the working directory's
    `.pi/sol-pi.json`) and `agentConfig`, each `path` and `state` (`absent`; `valid` with `features`
    and `reducer`; `invalid` with the reason).
- Standard output carries only the envelope, version or help; diagnostics go to standard error; no
  traceback or dependency message reaches either. An unexpected exception is `failed`, its type
  named, exit 1.
- Exits: 0 `written`, `unchanged`, home view; 1 `failed`; 2 `usage`; 130/143/129 `cancelled`.
- Usage errors, checked before anything is read: an unknown verb or flag, a repeated flag, an extra
  argument, `setup` without a directory, a value outside §S3. `error` names the input and lists the
  valid verbs and flags; `--yes` gets a hint naming `--non-interactive`.
- `help[]`: after `written`, start Pi in the project and trust it; after an error, the fixing
  command or flag; from the home view, `sol-pi-axi setup <project dir>`; none after `unchanged`.
- A relative project directory resolves against the working directory.

### §S5 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `docs/configuration.md`, `THIRD_PARTY_NOTICES.md`,
`CHANGELOG.md`.

- README and `agents-install.md`: `sol-pi-axi setup`, its flags, the envelope and keys,
  `--format json`, the home view, the exit codes; install with
  `uv tool install git+https://github.com/anthill-tec/SoL-Pi@<version>` until CR-SLP-007.
- README's install lines name `anthill-tec/SoL-Pi`.
- "SoL-Pi reads no environment variables" becomes: the extension reads none; `sol-pi-axi` reads
  `PI_CODING_AGENT_DIR`.
- `docs/configuration.md` and `agents-install.md`: the extension follows Pi's configuration and
  agent directories, `sol-pi-axi` the official layout only; `docs/configuration.md` also: a project
  file is read only in a trusted project, and how `setup` chooses its values.
- `THIRD_PARTY_NOTICES.md` lists `toon-format` 1.2.0 (MIT). `CHANGELOG.md` `[Unreleased]` records
  the command.

## Acceptance criteria

Tests use a temporary project, agent directory and home with `PI_CODING_AGENT_DIR` set, and decode
envelopes with `toon_format.decode`.

- [ ] **§S1** `uv build`: the wheel holds only `sol_pi_axi/` and metadata, with the `sol-pi-axi`
      console script, `Requires-Python: >=3.14`, one requirement `toon-format==1.2.0`; the sdist
      holds only §S1's files.
- [ ] **§S1** The wheel installed with `uv tool install` into a temporary `UV_TOOL_DIR` and
      `UV_TOOL_BIN_DIR`: `--version` prints `package.json`'s version; `setup <temporary project>`
      writes the file and prints a decodable envelope; no arguments prints a decodable home view.
- [ ] **§S1** `__version__` equals `package.json` `version`; `stamp_version.py read pypi:.` reads it.
- [ ] **§S1** `bun pm pack --dry-run` lists no `.py` file and no `pyproject.toml`.
- [ ] **§S1** The suite passes through the python client's discovery and through
      `python -m unittest discover -s tests -t .`, against the editable install.
- [ ] **§S1** No `sol_pi_axi` module starts `bun` or `node` or imports Node or Pi code.
- [ ] **§S1** `-v`, `-V`, `--version` print the bare version and exit 0 with `toon_format`
      unimportable; the median of five runs of the installed script is at most twice the median of
      five `<same interpreter> -c pass` runs.
- [ ] **§S2** No configuration anywhere: `written` with the setup defaults and Pi's default, exit
      0; a second run `unchanged` with bytes and modification time unchanged.
- [ ] **§S2** A valid partial project file `{"version":1,"actionFusion":true}` with no value flag is
      unchanged byte for byte, `unchanged`, even with an invalid agent file and no Pi default.
- [ ] **§S2** No project file: the agent file's values are used.
- [ ] **§S2** An invalid project file, an invalid agent file with no project file, and malformed
      `settings.json` with the setup defaults each exit 1, `failed`, no file changed.
- [ ] **§S2** Setup defaults, no Pi default, no `--reducer`: exit 1, `failed`, no file or `.pi/`
      created, `help[]` names `--reducer`; with `--features actionFusion` the built-in reducer route
      is written, exit 0.
- [ ] **§S2** A project path that is a file or does not exist, `.pi` as a file, `sol-pi.json` as a
      directory, a dangling `sol-pi.json` link, and a read-only `.pi/` each exit 1, `failed`, no
      file changed, `error` naming the path.
- [ ] **§S2** A `settings.json` with an array root fails; a non-string, empty or whitespace-holding
      `defaultProvider` or `defaultModel`, or only one of them, counts as no Pi default.
- [ ] **§S2** `.pi/` gains no file but `sol-pi.json`; a leftover `sol-pi.json.bak` remains and is
      named in `warnings`.
- [ ] **§S2** Conformance cases: minimal valid; every key valid; unknown key; `version` `2`, `true`,
      `1.0`, `"1"`; non-boolean feature; ratio negative, string, `true`, `NaN`, `Infinity`,
      `1e999`; reducer empty, whitespace-only, padded (valid, trimmed); JSON array; malformed JSON.
      Python and Bun pass every case.
- [ ] **§S2** `setup` writes exactly the golden files' bytes; the Bun test accepts each through
      `loadSolPiConfig` and `scripts/check-sol-pi-config.mjs`.
- [ ] **§S2** Through a symbolic link the target is replaced and the link kept; an existing mode is
      kept; under umask 022 a new file is 0644.
- [ ] **§S2** With the hook holding the run: `SIGINT`, `SIGTERM`, `SIGHUP` leave no temporary or
      changed file, print `cancelled`, exit 130, 143, 129; a project without `.pi/` still has none;
      a run started with `SIGINT` ignored is still cancelled by it.
- [ ] **§S2** `PI_CODING_AGENT_DIR=~/agent` reads `$HOME/agent`; empty reads `~/.pi/agent`.
- [ ] **§S3** `--features`, `--reducer`, `--cache-ratio` override and write; repeated, `unchanged`;
      `all`, `none` and `--flag=value` work; flags before and after the directory work;
      `--non-interactive` changes nothing.
- [ ] **§S3** With standard input a terminal, no prompt.
- [ ] **§S3** `--features` `''`, `a,,b`, a duplicate, `all,actionFusion`, wrong case; `--reducer`
      `provider/`, `/model`, ` p/m`; `--cache-ratio` `''`, `-1`, `1e3`, `0x10`, ` 2`, `1` followed by
      400 zeros: each exit 2, `usage`.
- [ ] **§S4** `setup x --help` exits 0 with help; `--version` after other arguments prints the
      version.
- [ ] **§S4** Each envelope has §S4's keys for its `verb`; `--format json` is one line parsing to the
      same object; a malformed `--format` usage error answers in TOON.
- [ ] **§S4** Unknown verb, unknown flag, repeated flag, extra argument, `setup` without a
      directory, a value flag on the home view: exit 2, `usage`, `error` naming the input, valid
      verbs and flags listed; `--yes` gets the hint.
- [ ] **§S4** No traceback or dependency message on either stream, including when the
      configuration module is made to raise.
- [ ] **§S4** `written` has the start-Pi and trust steps in `help[]`; `unchanged` has none.
- [ ] **§S4** The home view shows `absent`, `valid`, `invalid` for both files and exits 0 in each.
- [ ] **§S4** A relative project directory resolves against the working directory.
- [ ] **§S5** `tests/install-guide.test.ts` checks §S5's items in README and `agents-install.md`,
      whose install lines name `anthill-tec/SoL-Pi`.
- [ ] **§S5** `docs/configuration.md` and `agents-install.md` state the layout support;
      `THIRD_PARTY_NOTICES.md` lists `toon-format` 1.2.0; `CHANGELOG.md` `[Unreleased]` names the
      command.
- [ ] **Gate** The Bun and the Python `pre-merge-gate` both pass.

## Estimated size

13 points.

## Risks

- The validation rules exist in Python and TypeScript; a rule change must add a conformance case.
- The installed-wheel test needs `toon-format` from PyPI or uv's cache.

## Non-goals

- `install`, `uninstall`, publishing (CR-SLP-007); prompts and the fish script (CR-SLP-005).
- Pi distributions with other directory names; `file://` agent directories.
- Reading a project's `.pi/settings.json`; recording trust in Pi.
