# CR-SLP-007 — `@anthill-tec/sol-pi` on npm, `sol-pi-axi install`/`uninstall`, publishing

**Status:** PENDING · Pre-review: ran — touches another project's surface (Model B's install contract, #1554); 8 points or more
**Type:** feature
**Priority:** P1 — 0.1.0 is the first release Model B installs
**Depends on:** CR-SLP-004, CR-SLP-002, CR-SLP-001
**Labels:** release, packaging, npm, pypi, cli, docs
**Phase:** 0.1.0 · wave 1
**Design reference:** `docs/research/DN-sol-pi-axi.md` §D1, §D5, §D8

## Context

`package.json` is named `sol-pi`, `private`, tab-indented, at the inherited version `0.1.1`, with
no `repository` or `publishConfig`; nothing publishes it. Nothing registers the extension with Pi
outside `setup-sol-pi.fish`, which registers a checkout path. `release.yml` publishes nothing.

## Scope

### §S1 — The npm package

**Surfaces:** `package.json`, `sol_pi_axi/_version.py`, `tests/package.test.ts`.

- `name` `@anthill-tec/sol-pi`; no `private`; `publishConfig` `{"access": "public"}`; `repository`
  `{"type": "git", "url": "git+https://github.com/anthill-tec/SoL-Pi.git"}` (npm's normalised
  form); `keywords` include `pi-package`.
- Two-space indentation.
- `version` and `__version__` are `0.1.0`.
- `files`, `pi.extensions`, `peerDependencies` and `dependencies` are unchanged.

### §S2 — `sol-pi-axi install`

**Surfaces:** `sol_pi_axi/` (`install` verb, a Pi module), help text, valid-verb lists.

- **Pi.** `$PI_BIN` when set, else `pi` on `PATH`; neither fails the run naming both. Every `pi`
  command runs from the user's home with `--no-approve`. A `pi --version` outside
  `TESTED_PI_VERSIONS` (equal to `scripts/check-pi-compat.mjs`'s list) is a warning.
- **Source.** `npm:@anthill-tec/sol-pi@<version>`, `<version>` being `sol-pi-axi`'s. A version
  that is not `X.Y.Z` fails before any `pi` command, naming the version, with
  `pi install <checkout path>` in `help[]`.
- **Order.** Resolve the agent configuration, then register, then write it. A failure before
  registering changes nothing.
- **Registering.** When `settings.json` `packages` holds exactly the source, nothing is registered.
  Otherwise `pi install <source>`; an `npm:@anthill-tec/sol-pi` entry at another version is
  replaced in place by Pi. Other SoL-Pi sources (`npm:sol-pi`; a `git:` or URL source naming
  `anthill-tec/SoL-Pi` or `NVlabs/SoL-Pi`; a local path whose `package.json` is named `sol-pi` or
  `@anthill-tec/sol-pi`) are removed with `pi remove` only after `pi install` succeeds, a local
  path passed absolute, resolved against the agent directory. Every replaced source is named in
  `replaced` and `warnings`.
- **Pi's record.** After `pi install`, `settings.json` is read again; a missing source fails the
  run, naming the directory read.
- **Configuration.** An absent `<agent dir>/sol-pi.json` is written with CR-SLP-004's setup
  defaults after `--features`, `--reducer`, `--cache-ratio`, using its validation, written form and
  atomic write; a missing reducer provider or model fails before registering. An existing file is
  left untouched; an invalid one, and value flags given with an existing one, are named in
  `warnings`.
- **Failures.** A `pi` command exiting non-zero fails the run, `error` naming the command and exit
  code, Pi's output on standard error. A failed `pi install` leaves earlier sources registered. A
  `failed` envelope's `extension` reports the registration as the run left it.
- **Envelope.** `verb: install`; `outcome` `installed`, `unchanged`, `failed` or `cancelled`;
  `extension` (`source`, `registered` boolean, `replaced` list, `pi` version); `config` (`path`,
  `state` `written` or `kept`, values as `setup` reports them); `context` (`agentDir`). `unchanged`
  means nothing registered and nothing written. `help[]` after `installed`:
  `sol-pi-axi setup <project dir>`. Exit codes, signals, channels and unknown input as CR-SLP-004
  §S4; `--non-interactive` and `--format` accepted.

### §S3 — `sol-pi-axi uninstall`

**Surfaces:** `sol_pi_axi/` (`uninstall` verb).

- Removes with `pi remove` every SoL-Pi source §S2 recognises (a local path passed absolute,
  resolved against the agent directory); with none, `unchanged` and no `pi` command.
- Deletes no configuration file; `warnings` names `<agent dir>/sol-pi.json` when it exists.
- Envelope: `verb: uninstall`; `outcome` `removed`, `unchanged`, `failed` or `cancelled`; `removed`
  list; `context` (`agentDir`). A value flag is a usage error.

### §S4 — The home view shows the extension

**Surfaces:** `sol_pi_axi/` (home view).

- `extension`: `state` `absent` or `registered`, with `source`. A warning when the registered source
  is not `npm:@anthill-tec/sol-pi@<own version>`; then `help[]` adds `sol-pi-axi install`.

### §S5 — Publishing

**Surfaces:** `.github/workflows/release.yml`, `.github/scripts/`,
`tests/fixtures/release-workflow/rendered.yml`, `tests/release-workflow.test.ts`, `.env`
`RELEASE_TARGETS`.

- `RELEASE_TARGETS=pypi,npm`; `release.yml` rendered by `modelb-axi release-workflow`; the
  rendering committed as `tests/fixtures/release-workflow/rendered.yml`.
- Hand edits to the rendering:
  - `main` for `master`: header lines, push trigger, `create-release` condition, both publish
    guards (step names, `git fetch` ref, `origin/main`);
  - `test-bun`: `bun-version: 1.4.4`, `bun test --timeout 30000`;
  - `test-python`: installs the project with its `dev` extra, `oven-sh/setup-bun` at 1.4.4 and
    `bun install --frozen-lockfile`, and sets `PI_BIN` to `node_modules/.bin/pi`, before discovery;
  - `test-bun` and `test-python`: `actions/setup-node` at the rendering's own pin with
    `node-version: "22"` before their tests, since Pi needs Node 22.19 or later and the tests start
    it with `node`.
- The header lists the one-time setup: environments `pypi`, `npm` (version tags) and `testpypi`
  (`release/**`, `hotfix/**`); pending trusted publishers for `sol-pi-axi` on pypi.org and
  test.pypi.org; `NPM_TOKEN` for the first npm publish.

### §S6 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `CONTRIBUTING.md`, `CHANGELOG.md`,
`tests/install-guide.test.ts`.

- README and `agents-install.md`: install with `uv tool install sol-pi-axi==<version>` then
  `sol-pi-axi install`; per project `sol-pi-axi setup <project dir>`; the alternative
  `pi install npm:@anthill-tec/sol-pi@<version>`; the shared version; `install`, `uninstall`,
  `$PI_BIN`, their envelopes, the home view's `extension`. No install from a checkout path.
- README and `agents-install.md` state that Pi installs an `npm:` source by running `npm`, or the
  command array in its `npmCommand` setting (for example `["pnpm"]` or `["bun"]`), which must be
  on `PATH`.
- README's repository-relative targets become absolute, in Markdown `](…)`, HTML `href=`, `src=`
  and `srcset=` alike: images `https://raw.githubusercontent.com/anthill-tec/SoL-Pi/main/<path>`,
  links `https://github.com/anthill-tec/SoL-Pi/blob/main/<path>`; in-page `#` anchors and targets
  already absolute are unchanged. The two `install-guide.test.ts` assertions that pin relative
  README links take the absolute forms.
- `CONTRIBUTING.md`: installing from a checkout for development; the release's publishing and its
  one-time setup; re-rendering `rendered.yml`.
- `CHANGELOG.md` `[Unreleased]`: the two packages, `install`, `uninstall`.

## Acceptance criteria

Command tests use a temporary agent directory and home and a stub `pi` on `PATH` that records its
arguments and working directory and edits `settings.json` as `pi install` and `pi remove` do.

- [ ] **§S1** `package.json` matches §S1 with two-space indentation;
      `stamp_version.py check 0.1.0 pypi:. npm:.` exits 0.
- [ ] **§S1** `bun pm pack --dry-run` lists the same files as on the base branch.
- [ ] **§S1** The packed tarball, unpacked and loaded by the development dependency's Pi with its
      path as the extension, registers SoL-Pi's tools.
- [ ] **§S2** An agent directory with no SoL-Pi registration and no `sol-pi.json`, whose
      `settings.json` names a Pi default provider and model: `install` runs `pi install npm:@anthill-tec/sol-pi@<own
      version>`, writes `sol-pi.json` with the setup defaults, exits 0, `installed`. A second run
      runs no `pi install` or `pi remove`, leaves the file's bytes and modification time, `unchanged`.
- [ ] **§S2** Every recorded `pi` command ran from the home directory with `--no-approve`.
- [ ] **§S2** `npm:@anthill-tec/sol-pi@0.0.9` is replaced by `pi install` alone (no `pi remove`) and
      named in `replaced`. `npm:sol-pi`, `git:github.com/NVlabs/SoL-Pi`,
      `https://github.com/anthill-tec/SoL-Pi` and a relative local checkout path are each removed
      with `pi remove` after `pi install` succeeds, the path passed absolute, and named in
      `replaced` and `warnings`. An unrelated package and a project's `.pi/settings.json` are
      untouched.
- [ ] **§S2** With `npm:sol-pi` registered and `pi install` exiting 1: no `pi remove` runs,
      `npm:sol-pi` stays registered, `failed`, `extension.registered` false.
- [ ] **§S2** `__version__` `0.1.0.dev3` fails before any `pi` command, `error` naming it.
- [ ] **§S2** A stub writing another directory's `settings.json` fails the run, naming the directory
      read.
- [ ] **§S2** Real Pi (`$PI_BIN` = the development dependency's `pi`), temporary agent directory,
      offline: a local-path source registered by `pi install` is recognised and removed by
      `uninstall` run from another working directory.
- [ ] **§S2** An existing valid `sol-pi.json` is kept byte for byte with value flags named in
      `warnings`; an invalid one is kept and named; no reducer default and no `--reducer` fails
      before any `pi` command.
- [ ] **§S2** No `pi` and no `$PI_BIN`: exit 1 naming both. `$PI_BIN` is used when set.
      `pi install` exiting 3: `failed`, `error` naming the command and `3`, no configuration file
      written.
- [ ] **§S2** `pi --version` `9.9.9`: a warning, and the run installs. `TESTED_PI_VERSIONS` equals
      `scripts/check-pi-compat.mjs`'s list.
- [ ] **§S2** `SIGINT`, `SIGTERM`, `SIGHUP` before registering: exit 130, 143, 129, `cancelled`, no
      `pi` command, nothing written.
- [ ] **§S3** `uninstall` removes every recognised source, `removed`; with none, no `pi` command,
      `unchanged`; deletes no configuration file and names the agent file; a value flag exits 2.
- [ ] **§S4** The home view shows `absent`, `registered` at the own version, and `registered` at
      another version with the warning and `sol-pi-axi install` in `help[]`.
- [ ] **§S5** `tests/release-workflow.test.ts` parses `release.yml`: push branches `main`,
      `release/**`, `hotfix/**`; no `master`; `create-release`, `rehearse`, `publish-pypi`,
      `publish-npm` each need `test-bun` and `test-python`; `publish-pypi` and `rehearse` have
      `id-token: write`; guards check `origin/main`; `test-bun` as §S5; `test-python` installs the
      project and the Bun dependencies and sets `PI_BIN` before discovery; `test-bun` and
      `test-python` each set up Node 22 with `actions/setup-node` at the SHA the rendering pins,
      before their tests; `create-release` checks `pypi:.` and
      `npm:.`.
- [ ] **§S5** `release.yml` differs from `rendered.yml` by exactly §S5's hand edits.
- [ ] **§S6** `tests/install-guide.test.ts` checks §S6's items in README and `agents-install.md`,
      and that neither installs from a checkout path; `CHANGELOG.md` `[Unreleased]` names the two
      packages, `install` and `uninstall`.
- [ ] **§S6** No Markdown `](…)`, HTML `href=`, `src=` or `srcset=` target in README is a
      relative path (in-page `#` anchors excepted); each image that was a repository path is a
      `raw.githubusercontent.com/anthill-tec/SoL-Pi/main/` URL to a file that exists in the
      repository, and each such link a `github.com/anthill-tec/SoL-Pi/blob/main/` URL to one.
- [ ] **§S6** README and `agents-install.md` each contain `npmCommand` and `npm` in the statement of
      what `pi install npm:…` needs.
- [ ] **Gate** The Bun and the Python `pre-merge-gate` both pass.

## Estimated size

8 points.

## Risks

- The release branch's rehearsal is the first end-to-end publishing proof; the one-time setup must
  precede it.
- Re-rendering `release.yml` drops the hand edits until Model B fixes CR-MDB-052 items 19 and 21;
  the workflow test catches it.
- README links point at `main`, which PyPI and npm freeze at upload: a later rename or removal on
  `main` breaks an older release's page. Accepted: pinning them to the release tag would need
  README stamped on each release.

## Non-goals

- `--interactive` (CR-SLP-005); the post-install check (CR-SLP-008).
- The unscoped npm name `sol-pi`; installing the extension project-locally.
