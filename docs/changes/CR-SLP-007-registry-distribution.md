# CR-SLP-007 — Registry distribution: `@anthill-tec/sol-pi` on npm, `sol-pi-axi install` and publishing

**Status:** PENDING · Pre-review: due — touches another project's surface (Model B's contract names the install commands, message #1534); new CR; release workflow and two public registries
**Type:** feature
**Priority:** P1 — 0.1.0 is the first release Model B installs; it must come from the registries
**Depends on:** CR-SLP-004, CR-SLP-001
**Labels:** release, packaging, npm, pypi, cli, docs
**Phase:** 0.1.0 · wave 1
**Design reference:** CR-SLP-004 (`sol-pi-axi`); Model B's release workflow generator
(`modelb-axi release-workflow`, targets `pypi` and `npm`); the distribution of Crucible
(`crucible-axi` + `@anthill-tec/crucible-server`) and Sandesh (`sandesh-relay` +
`@anthill-tec/sandesh-pi`); Pi's package sources (`pi install npm:<name>@<version>`)

## Context

**User ruling (2026-11-04).** SoL-Pi ships as two packages at one version, as Crucible and Sandesh
do: the Pi extension as the npm package `@anthill-tec/sol-pi`, and the machine-side tool as the
PyPI package `sol-pi-axi` (CR-SLP-004), installed with `uv tool install`. `sol-pi-axi install`
registers the extension with Pi at the tool's own version and writes the agent directory's
`sol-pi.json` with the setup defaults only when none exists; `sol-pi-axi uninstall` removes the
registration and leaves both configuration files. Publishing is in 0.1.0. Both names are free:
npm answers 404 for `@anthill-tec/sol-pi`, PyPI for `sol-pi-axi`. The unscoped npm name `sol-pi`
belongs to another publisher.

**The package today.** `package.json` is named `sol-pi`, `private: true`, tab-indented, version
`0.1.1` (inherited from the upstream project), with no `repository` or `publishConfig`. Its `files`
list holds the extension, docs and `scripts/check-sol-pi-config.mjs`; `pi.extensions` names
`./src/sol-pi/index.ts`. Pi loads an npm package's TypeScript entry directly and installs packages
with peers omitted.

**Pi's records.** `pi install <source>` adds the source to the agent directory's `settings.json`
`packages` list (an entry is the source string, or an object with `source`); `pi remove <source>`
takes it out. `pi --version` prints the bare version.

**Release workflow.** `.github/workflows/release.yml` is rendered by `modelb-axi release-workflow`
from `PROJECT_STACKS` and `RELEASE_TARGETS`. Rendered for `bun,python` and `pypi,npm` it adds a
`test-python` job, a `rehearse` job on `release/**` and `hotfix/**` pushes (stamps a dev version,
uploads to TestPyPI, dry-runs the npm publish) and `publish-pypi` and `publish-npm` jobs on a
published release, each needing every test job, with PyPI trusted publishing (OIDC). Measured
defects of the rendering, reported to Model B: it targets `master` (this repository's production
branch is `main`) in the trigger, `create-release` and both publish guards; and its `test-python`
job runs `python -m unittest` without installing the project or its dependencies. Its
`stamp_version.py` refuses a `package.json` whose top-level `"version"` is not at a two-space
indent. CR-SLP-001 sets `test-bun`'s `bun-version: 1.4.4` and its command
`bun test --timeout 30000`.

## Scope

### §S1 — The npm package

**Surfaces:** `package.json`, `tests/package.test.ts`.

- `name` is `@anthill-tec/sol-pi`; `private` is removed; `publishConfig` is
  `{"access": "public"}`; `repository` names `https://github.com/anthill-tec/SoL-Pi`; `keywords`
  include `pi-package`.
- `package.json` is indented with two spaces, so `stamp_version.py` can stamp and check it.
- `files`, `pi.extensions`, `peerDependencies` and `dependencies` are unchanged; the package holds
  no Python file (CR-SLP-004 §S1).

### §S2 — `sol-pi-axi install`

**Surfaces:** `sol_pi_axi/` (an `install` verb, a Pi module), its help text and valid-verb lists.

- **Pi.** The command runs the `pi` named by `$PI_BIN` when set, else the `pi` on `PATH`. With
  neither, the run fails naming both. It reads `pi --version`; a version outside the tested set
  (`TESTED_PI_VERSIONS`, which a test holds equal to `scripts/check-pi-compat.mjs`'s) is a warning,
  not a failure.
- **The source.** The extension's source is `npm:@anthill-tec/sol-pi@<version>`, `<version>` being
  `sol-pi-axi`'s own.
- **Order.** The run first resolves the agent directory's configuration (below), then registers
  the extension, then writes the configuration. A failure before registering changes nothing.
- **Registering.** When the agent directory's `settings.json` `packages` already holds exactly the
  source, nothing is registered. When it holds another SoL-Pi source — an `npm:@anthill-tec/sol-pi`
  source at another version, an `npm:sol-pi` source, a `git:` or URL source naming
  `anthill-tec/SoL-Pi` or `NVlabs/SoL-Pi`, or a local path whose `package.json` is named `sol-pi` or
  `@anthill-tec/sol-pi` — the run removes it with `pi remove` and names it in `warnings`, then
  runs `pi install <source>`. Project-level `.pi/settings.json` files are never read or changed.
- **Configuration.** When `<agent dir>/sol-pi.json` is absent, the run writes it with CR-SLP-004's
  setup defaults, after the value flags `--features`, `--reducer` and `--cache-ratio`, using
  CR-SLP-004's validation, written form and atomic write. A missing reducer provider or model fails
  the run before registering, as `setup` does. An existing file, valid or invalid, is left
  untouched; an invalid one is named in `warnings`, and value flags given with an existing file are
  named in `warnings` as not applied.
- **Pi failing.** A `pi` command that exits non-zero fails the run: `error` names the command and
  its exit code, `pi`'s own output goes to standard error, and a file not yet written stays
  unwritten.
- **Envelope.** `verb: install`, with `outcome` (`installed`, `unchanged`, `failed`,
  `cancelled`), `extension` (`source`, `replaced` as the list of removed sources, `pi` as Pi's
  version), `config` (`path`, `state` `written` or `kept`, and the values as `setup` reports them),
  and `context` (`agentDir`). `unchanged` means nothing was registered and nothing written.
  `help[]` after `installed` carries `sol-pi-axi setup <project dir>`. Exit codes, signals, channels
  and unknown input follow CR-SLP-004 §S4; `--non-interactive` and `--format` are accepted.

### §S3 — `sol-pi-axi uninstall`

**Surfaces:** `sol_pi_axi/` (an `uninstall` verb).

- The run removes, with `pi remove`, every SoL-Pi source §S2 recognises in the agent directory's
  `settings.json` `packages`; with none, it reports `unchanged` and runs no `pi` command.
- It deletes no configuration file. `warnings` names `<agent dir>/sol-pi.json` when it exists, and
  says project files are left as they are.
- **Envelope.** `verb: uninstall`, with `outcome` (`removed`, `unchanged`, `failed`,
  `cancelled`), `removed` (the list of sources), `context` (`agentDir`). It takes no value flags;
  given one, it is a usage error.

### §S4 — The home view shows the extension

**Surfaces:** `sol_pi_axi/` (home view).

- The home view gains `extension`: `state` (`absent`, or `registered` with its `source`), and a
  warning when the registered source is not this tool's own version or is not an
  `npm:@anthill-tec/sol-pi` source. Its `help[]` adds `sol-pi-axi install` when the extension is
  absent or at another version.

### §S5 — Publishing

**Surfaces:** `.github/workflows/release.yml`, `.github/scripts/`, `tests/release-workflow.test.ts`
(new), `.env` `RELEASE_TARGETS` (machine-local, mirrored to the board's project metadata).

- `RELEASE_TARGETS` is `pypi,npm`, and `release.yml` is rendered from it with
  `modelb-axi release-workflow`.
- Hand edits to the rendering, kept until Model B's generator makes them unnecessary:
  - `main` in place of `master`: the comment header, the push trigger, `create-release`'s branch
    condition, and both publish guards;
  - `test-bun` keeps CR-SLP-001's `bun-version: 1.4.4` and `bun test --timeout 30000`;
  - `test-python` installs the project with its `dev` extra before discovery, and runs the same
    discovery.
- Every publish job and the rehearsal need both test jobs; the rehearsal uploads to TestPyPI and
  dry-runs the npm publish; `create-release` checks the tag against `pypi:.` and `npm:.`.
- **One-time setup** (the release workflow's header lists it): GitHub environments `pypi` and
  `npm` admitting the version tags and `testpypi` admitting `release/**` and `hotfix/**`; pending
  trusted publishers for `sol-pi-axi` on pypi.org and test.pypi.org naming this repository,
  `release.yml` and the environment; the repository secret `NPM_TOKEN` for the first npm publish,
  replaced by an npm trusted publisher afterwards. `RELEASE_PAT` is already set.

### §S6 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `CONTRIBUTING.md`, `CHANGELOG.md`.

- README and `agents-install.md` give the install as `uv tool install sol-pi-axi==<version>` then
  `sol-pi-axi install`, and per project `sol-pi-axi setup <project dir>`; the direct
  `pi install npm:@anthill-tec/sol-pi@<version>` is the documented alternative for the extension
  alone. They state that the two packages share a version and that `install` keeps them together.
  They document `install`, `uninstall`, `$PI_BIN`, their envelopes and the home view's `extension`.
- `agents-install.md`'s install phase no longer installs from a checkout path; installing from a
  checkout is described in `CONTRIBUTING.md` for development.
- `CONTRIBUTING.md` describes the release's publishing and its one-time setup.
- `CHANGELOG.md` `[Unreleased]` records the two packages, `install` and `uninstall`.

## Acceptance criteria

Command tests run against a temporary agent directory and home with a stub `pi` on `PATH` that
records its arguments and edits `settings.json` the way `pi install` and `pi remove` do.

- [ ] **§S1** `package.json` has §S1's `name`, `publishConfig`, `repository` and `keywords`, no
      `private`, two-space indentation; `stamp_version.py check <version> pypi:. npm:.` passes on
      the tree.
- [ ] **§S1** `bun pm pack --dry-run` lists the same files as before this CR, under the new name.
- [ ] **§S1** The packed tarball, unpacked and loaded by a real Pi session on the development
      dependency with its path as the extension, registers SoL-Pi's tools.
- [ ] **§S2** On an empty agent directory, `install` runs `pi install npm:@anthill-tec/sol-pi@<own
      version>`, writes `sol-pi.json` with the setup defaults, exits 0 and reports `installed`; a
      second run runs no `pi install` or `pi remove`, leaves the file's bytes and modification time
      alone, and reports `unchanged`.
- [ ] **§S2** Each of `npm:@anthill-tec/sol-pi@0.0.9`, `npm:sol-pi`,
      `git:github.com/NVlabs/SoL-Pi`, `https://github.com/anthill-tec/SoL-Pi` and a local checkout
      path in `packages` is removed with `pi remove` and named in `replaced` and `warnings` before
      the new source is installed; an unrelated package is left alone; a project's
      `.pi/settings.json` is untouched.
- [ ] **§S2** An existing valid `sol-pi.json` is kept byte for byte, with value flags named as not
      applied; an invalid one is kept and named; a missing reducer default with no `--reducer`
      fails before any `pi` command runs.
- [ ] **§S2** With no `pi` and no `$PI_BIN`, the run exits 1 naming both; `$PI_BIN` is used when
      set; a `pi install` exiting 3 fails the run naming the command and code, and writes no
      configuration file.
- [ ] **§S2** A `pi --version` outside the tested set gives a warning and the run still installs;
      `TESTED_PI_VERSIONS` equals `scripts/check-pi-compat.mjs`'s list.
- [ ] **§S2** `SIGINT`, `SIGTERM` and `SIGHUP` before registering exit 130, 143 and 129 with
      `cancelled`, run no `pi` command and write nothing.
- [ ] **§S3** `uninstall` removes every recognised SoL-Pi source and reports `removed`; with none
      it runs no `pi` command and reports `unchanged`; it deletes no configuration file and names
      the agent file in `warnings`; a value flag exits 2.
- [ ] **§S4** The home view shows `absent`, `registered` at the tool's version, and `registered` at
      another version with its warning and the `install` next step.
- [ ] **§S5** `tests/release-workflow.test.ts` parses `release.yml` and checks: the push trigger is
      `main`, `release/**` and `hotfix/**`; no `master` remains; `create-release`, `rehearse`,
      `publish-pypi` and `publish-npm` each need `test-bun` and `test-python`; `publish-pypi` and
      `rehearse` have `id-token: write`; the publish guards check `origin/main`; `test-bun` pins
      Bun 1.4.4 and runs `bun test --timeout 30000`; `test-python` installs the project before its
      discovery; `create-release` checks `pypi:.` and `npm:.`.
- [ ] **§S5** Run against the rendered workflow with the same stacks and targets, the test's
      differences are exactly §S5's hand edits.
- [ ] **§S6** README and `agents-install.md` cover §S6's items, checked by
      `tests/install-guide.test.ts`; neither installs SoL-Pi from a checkout path;
      `CHANGELOG.md` `[Unreleased]` records the changes.
- [ ] **Gate** The Bun and the Python `pre-merge-gate` both pass.

## Estimated size

8 points. The npm package's metadata and pack check, two verbs that drive `pi` through a stub, the
recognition of earlier SoL-Pi sources, the home view's extension state, the rendered workflow with
its hand edits and a test that pins them, and the install docs.

## Risks

- The first real publish happens on the 0.1.0 release, after this CR merges; the rehearsal on the
  release branch is the first end-to-end proof, and the one-time setup must be done before it.
- npm's trusted publisher can only be added once the package exists, so the first publish uses
  `NPM_TOKEN`.
- Re-rendering `release.yml` later overwrites the hand edits unless Model B's generator has taken
  them up; the workflow test catches a regression.

## Non-goals

- `--interactive` for `install` (CR-SLP-005).
- Publishing under the unscoped npm name `sol-pi`.
- A Pi package gallery entry beyond the `pi-package` keyword.
- Installing the extension project-locally (`pi install -l`).
