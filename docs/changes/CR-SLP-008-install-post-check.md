# CR-SLP-008 — `sol-pi-axi install` checks that Pi loads SoL-Pi

**Status:** PENDING · Pre-review: ran — touches another project's surface (Model B's install remediation, #1554)
**Type:** feature
**Priority:** P1 — replaces the fish setup script's smoke test, which CR-SLP-005 removes
**Depends on:** CR-SLP-007
**Labels:** setup, cli, axi, python
**Phase:** 0.1.0 · wave 1
**Design reference:** `docs/research/DN-sol-pi-axi.md` §D6

## Context

`sol-pi-axi install` (CR-SLP-007) registers the extension and writes its configuration, but never
starts Pi, so a SoL-Pi that fails to load, or loads with an invalid `sol-pi.json`, is reported as
installed.

## Scope

### §S1 — The check

**Surfaces:** `sol_pi_axi/` (`install` verb, a new check module).

- Every `install` run that ends with the source registered (`installed` or `unchanged`) runs the
  check last; a run that fails or is cancelled earlier does not.
- **Pi's record.** The check fails when the registered SoL-Pi entry is an object whose `extensions`
  filter excludes `src/sol-pi/index.ts`, or when the package is not on disk
  (`<agent dir>/npm/node_modules/@anthill-tec/sol-pi/package.json` for the npm source; the path's
  `package.json` for a local path). `error` names which.
- **Starting Pi.** `pi --offline --no-approve --mode rpc --no-session`, from the user's home, with
  one `{"id":"sol-pi-axi","type":"get_state"}` line on standard input, then end of input; bounded
  at 30 seconds, after which Pi is killed and reaped.
- **Fails when** Pi exits non-zero (`error` quotes its `Failed to load extension` line), an
  `extension_error` line's `extensionPath` lies inside the SoL-Pi package directory, or no
  `get_state` response arrives. Non-JSON standard-output lines are ignored.
- An `extension_error` from another extension is a warning.
- **A failed check** fails the run: exit 1, `failed`, registration and configuration reported as the
  run left them (nothing removed or rewritten), `help[]` with the fix (for an invalid
  `<agent dir>/sol-pi.json`: correct it, or delete it and run `sol-pi-axi install` again) and
  `sol-pi-axi uninstall`.
- **Envelope.** `install` gains `verify`: `ok` (boolean), `exit` (Pi's exit code, `null` when it was
  killed or not started), `errors` (list of `{extensionPath, event, error}`); `verify` is `null`
  when the run did not reach the check.

### §S2 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `CHANGELOG.md`.

- README and `agents-install.md` document the check, what fails it, `verify`, and that Pi may create
  `auth.json` and `models-store.json` in the agent directory.
- `CHANGELOG.md` `[Unreleased]` records the check.

## Acceptance criteria

Real-Pi cases run the development dependency's `pi` through `$PI_BIN`, offline, with a temporary
agent directory and home registering the checkout as a local path. Stub cases extend CR-SLP-007's
stub `pi` to answer `--mode rpc`.

- [ ] **§S1** Real Pi, valid `sol-pi.json`: `install` reports `installed`, `verify.ok` true,
      `verify.exit` 0, `verify.errors` empty; a second run reports `unchanged` and its `verify` is
      not `null`.
- [ ] **§S1** Real Pi, agent-directory `sol-pi.json` `{"version":2}`: exit 1, `failed`, one
      `verify.errors` entry with `event` `session_start`, `help[]` naming the file; the file's bytes
      are unchanged.
- [ ] **§S1** Real Pi: a second registered extension that throws on load fails the run, `error`
      naming its path; one that throws in `session_start` gives `installed` with a warning naming
      its path.
- [ ] **§S1** Real Pi: a trusted home whose `~/.pi/settings.json` registers a throwing extension
      gives `installed`.
- [ ] **§S1** An entry with `"extensions": []`, and an npm entry with no package directory, each fail
      with exit 1 before any `--mode rpc` start (the stub records none), `error` naming the cause.
- [ ] **§S1** Stub: an RPC start that never answers fails after the bound with `verify.exit` `null`
      and no `pi` process left; non-JSON standard-output lines are ignored; a run failing before
      registering has `verify` `null`.
- [ ] **§S1** `git grep -n -- '--mode rpc' sol_pi_axi/` returns at least one non-test line.
- [ ] **§S2** `tests/install-guide.test.ts` checks README and `agents-install.md` for `verify` and
      the check; `CHANGELOG.md` `[Unreleased]` names the check.
- [ ] **Gate** The Bun and the Python `pre-merge-gate` both pass.

## Estimated size

5 points.

## Risks

- Pi's RPC output is not a stable contract; the real-Pi tests catch a change on the development
  dependency.

## Non-goals

- A SoL-Pi status command or skill.
- Running the check from `setup` or the home view.
- Failing on another extension's handler error.
