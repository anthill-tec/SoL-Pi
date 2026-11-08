# DN — `sol-pi-axi`: distributing and setting up SoL-Pi

**Author:** Antony John (antonyj)
**Co-author:** vidushi-solpi (Mainline orchestrator — SoL-Pi)
**Date:** 2026-11-04
**Status:** ACCEPTED (CR-SLP-004, CR-SLP-005, CR-SLP-007, CR-SLP-008)
**Sources:** Model B's request (Sandesh #1516) and contract (#1534, corrected #1554, accepted
in #1555); the AXI standard (<https://axi.md>); Pi 1.5.0 (`DefaultPackageManager`, `docs/rpc.md`,
`docs/rpc-commands.md`); measurements on this machine, 2026-11-04.

## D1 — Two packages at one version

- The Pi extension ships on npm as `@anthill-tec/sol-pi`; the machine-side tool ships on PyPI as
  `sol-pi-axi`, installed with `uv tool install`. This is the pattern of Crucible (`crucible-axi` +
  `@anthill-tec/crucible-server`) and Sandesh (`sandesh-relay` + `@anthill-tec/sandesh-pi`).
- Both names were free on 2026-11-04; the unscoped npm name `sol-pi` belongs to another publisher.
- The two packages always carry the same version; `sol-pi-axi install` registers the extension at
  the tool's own version.
- Model B reaches SoL-Pi only through what is installed, never a checkout (#1516 item 1).

## D2 — One AXI command

- `sol-pi-axi` is one console script with verbs: `setup <project dir>` (per project), `install` and
  `uninstall` (user-wide), `verify` (read-only load check), and a home view with no verb.
- It follows the AXI standard as `modelb-axi` and Crucible's clients do: one TOON envelope (root
  `axi`) on standard output, `--format json` for one JSON line, exit codes 0/1/2, every value
  settable by flag, unknown input rejected, next steps in `help[]`, a fast `--version`.
- TOON is encoded with `toon-format`, the official Python implementation (MIT, no dependencies,
  1.2.0, pinned exactly). Measured: an envelope with nested objects, lists, an empty list, a path
  and a decimal round-trips unchanged.
- Python 3.14 or later, as `crucible-axi` and `modelb-axi`; uv fetches the interpreter.
- The package lives at the repository root (`pyproject.toml`, `sol_pi_axi/`) beside
  `package.json`, as in Crucible; Python tests are `tests/test_*.py` beside the Bun tests.
- The version is hatchling's dynamic version from `sol_pi_axi/_version.py`, which Model B's
  `stamp_version.py` reads and stamps.
- The tool supports the official Pi layout only (`.pi`, `$PI_CODING_AGENT_DIR` else
  `~/.pi/agent`); the extension follows Pi's `CONFIG_DIR_NAME` and `getAgentDir()`.

## D3 — One configuration schema, two runtimes

- `loadSolPiConfig` (TypeScript) and `sol_pi_axi` (Python) both validate `sol-pi.json`, and
  `scripts/check-sol-pi-config.mjs` a third time. They are held equal by a shared table of
  conformance cases and by golden files that Python writes and Bun reads, so neither runner needs
  the other's runtime in CI.
- Python reads JSON as JavaScript does: Python's `json` accepts `NaN`/`Infinity`, reads `1e999` as
  infinity, counts `True` as `1`, and trims a different whitespace set from JavaScript's `trim()`.

## D4 — Prompts are opt-in

- The command never prompts unless given `--interactive`; `--non-interactive` is accepted as a
  no-op for Model B's `--yes` (#1516 item 3). `--interactive` prompts only when standard input and
  standard error are terminals and `PI_NONINTERACTIVE` is empty.
- A cancel exits 130, `SIGTERM` 143, a closed terminal 129: an addition to AXI's 0/1/2 that
  Model B asked for (#1516 item 4).
- Python at a terminal (measured, Python 3.14.9): `input()` writes its prompt to standard output,
  so prompts are written to standard error by the command itself; Ctrl+C raises
  `KeyboardInterrupt` unless `SIGINT` was inherited as ignored; Ctrl+D on an empty line returns an
  empty read; a closed terminal sends `SIGHUP` only to the session leader, and a process the
  terminal was passed through to gets `EIO` instead.

## D5 — Registering the extension

- `install` registers `npm:@anthill-tec/sol-pi@<version>` user-wide with `pi install`, writes the
  agent directory's `sol-pi.json` with the setup defaults only when none exists, and replaces
  earlier SoL-Pi sources (`npm:sol-pi`, git and URL sources, a local checkout) once the new source
  is installed. `uninstall` removes the registration and deletes no configuration file.
- Pi's records (Pi 1.5.0): an npm source replaces an entry for the same package at any version in
  place, keeping its other fields; a local path is stored relative to the agent directory, while
  `pi remove` resolves its argument against the working directory; run from home, Pi reads
  `~/.pi/` as a project when home is trusted, which `--no-approve` prevents.
- A Pi version outside the tested set is a warning, not a failure.

## D6 — The post-install check

- `install` ends by starting Pi and failing when SoL-Pi does not load cleanly, carrying over the
  fish script's smoke test. `sol-pi-axi verify` runs the same check read-only, for Model B's
  `sol-pi-status` skill (CR-MDB-101), which never registers or installs SoL-Pi.
- Measured (Pi 1.5.0 and 1.3.0, offline, temporary agent directories):
  `pi --offline --no-approve --mode rpc --no-session` loads every extension, runs `session_start`,
  answers a `get_state` command and exits 0 when its input closes, in about 0.25 s, with no model,
  credentials or network; it creates `auth.json` and `models-store.json` when missing. A load
  failure exits 1 with `Failed to load extension "<path>": <reason>` on standard error. A handler
  error is an `extension_error` JSON line on standard output, and Pi carries on; an invalid
  `sol-pi.json` surfaces this way at `session_start`. An npm package's entry lies under
  `<agent dir>/npm/node_modules/<name>`.
- RPC lists no extensions or tools, and SoL-Pi registers no command, so a clean start does not
  prove SoL-Pi loaded: a filtered entry, or a missing package, starts cleanly. Pi's resource filters
  are a glob language (minimatch includes, `!` excludes, `+`/`-` exact overrides, matched on
  relative, base and absolute paths), so re-implementing them in `sol-pi-axi` would drift. The user
  ruled (2026-11-09) for a load signal instead: when `SOL_PI_AXI_VERIFY` holds a value, SoL-Pi's
  `session_start` first calls `ui.notify("sol-pi-axi verify <value>")`, which RPC mode emits as an
  `extension_ui_request` line; the check requires it, and still checks Pi's record and the package
  on disk first for a clearer error.
- SoL-Pi adds no status command: a user-facing SoL-Pi status skill belongs to Model B, the
  umbrella project.
- Another extension's handler error is a warning; the fish script failed on it.

## D7 — The fish setup script is retired

`sol-pi-axi` replaces `setup-sol-pi.fish`:

| The script | Now |
|---|---|
| user-wide setup | `sol-pi-axi install` |
| project setup | `sol-pi-axi setup <dir>` |
| prompts | `--interactive` |
| `--uninstall` | `sol-pi-axi uninstall`, without the `.bak` restore |
| strict Pi compatibility failure | a warning in `install` |
| smoke test | the post-install check (D6) |
| registering the checkout | the npm source; checkout development in `CONTRIBUTING.md` |
| checkout validation, audit, all-mechanisms test | `bun run check`, `bun audit` |

## D8 — Publishing

- `release.yml` is rendered by `modelb-axi release-workflow` for stacks `bun,python` and targets
  `pypi,npm`: a TestPyPI rehearsal and an npm dry run on release branches, PyPI trusted publishing
  and npm on a published release, every publish needing both test jobs.
- Two generator defects are fixed by hand until Model B fixes them: the production branch
  (`master` for `main`, CR-MDB-052 item 19) and a `test-python` job that installs nothing (item 21).
- `stamp_version.py` needs a two-space-indented `package.json`.
- The first npm publish needs `NPM_TOKEN`; npm's trusted publisher can be added only once the
  package exists.
