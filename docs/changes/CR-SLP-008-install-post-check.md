# CR-SLP-008 — `sol-pi-axi verify`, and `install`'s check that Pi loads SoL-Pi

**Status:** PENDING · Pre-review: ran — touches another project's surface (Model B's install remediation, #1554; its `sol-pi-status` skill runs `verify`, #1558)
**Type:** feature
**Priority:** P1 — replaces the fish setup script's smoke test, which CR-SLP-005 removes
**Depends on:** CR-SLP-007
**Labels:** setup, cli, axi, python, extension
**Phase:** 0.1.0 · wave 1
**Design reference:** `docs/research/DN-sol-pi-axi.md` §D6

## Context

`sol-pi-axi install` (CR-SLP-007) registers the extension and writes its configuration, but never
starts Pi, so a SoL-Pi that fails to load, or loads with an invalid `sol-pi.json`, is reported as
installed; nothing checks a loaded SoL-Pi without registering it. Pi's RPC mode lists no loaded
extensions, and whether a package's extension loads depends on Pi's resource filters (glob
includes, `!` excludes, `+`/`-` exact overrides), so only the extension itself can say it loaded.

## Scope

### §S1 — The load signal

**Surfaces:** `src/sol-pi/index.ts` (`createSolPiExtension`), a Bun test.

- When the environment variable `SOL_PI_AXI_VERIFY` is a non-empty value, SoL-Pi's `session_start`
  handler calls `ui.notify("sol-pi-axi verify <value>", "info")` first, before it reads its
  configuration, so a loaded SoL-Pi signals even when its configuration is invalid. In Pi's RPC
  mode the call is a standard-output line `{"type":"extension_ui_request","method":"notify",
  "message":"sol-pi-axi verify <value>",…}`.
- With the variable unset or empty, SoL-Pi calls nothing extra.

### §S2 — The check

**Surfaces:** `sol_pi_axi/` (a new check module).

- **Pi's record.** The check fails, before starting Pi, when no SoL-Pi source (CR-SLP-007 §S2) is
  registered; when more than one is; when the one registered is neither an
  `npm:@anthill-tec/sol-pi` source nor a local path (an `npm:sol-pi`, `git:` or URL source:
  `help[]` names `sol-pi-axi install`, which replaces it); or when its package is not on disk. The
  package directory is `<agent dir>/npm/node_modules/@anthill-tec/sol-pi` for the npm source and
  the resolved path for a local path; on disk means its `package.json` exists. `error` names which.
- **Starting Pi.** `pi --offline --no-approve --mode rpc --no-session`, from the user's home, with
  `SOL_PI_AXI_VERIFY` set to a value unique to the run and one
  `{"id":"sol-pi-axi","type":"get_state"}` line on standard input, then end of input; bounded at 30
  seconds, after which Pi is killed and reaped.
- **Fails when** Pi exits non-zero (`error` quotes its `Failed to load extension` line), an
  `extension_error` line's `extensionPath` lies inside the SoL-Pi package directory (both sides
  compared with symbolic links resolved), no `get_state` response arrives, or no notify line
  carries the run's value (`error`: Pi started without loading SoL-Pi, for example because a
  resource filter in `settings.json` excludes it). Non-JSON standard-output lines are ignored.
- **A dialog blocks the start.** Pi reads no input until `session_start` finishes, so an extension
  that opens a dialog there (`select`, `confirm`, `input`, `editor`) holds Pi until the bound. When
  the bound kills Pi after a dialog `extension_ui_request` was seen, `error` names the dialog's
  `method` and `title` and says Pi does not name the extension that opened it.
- An `extension_error` from another extension is a warning.
- **Result:** `verify`: `ok` (boolean), `loaded` (boolean, the load signal seen), `exit` (Pi's exit
  code, `null` when it was killed or not started), `errors` (list of
  `{extensionPath, event, error}`).
- The check writes no file; Pi may create `auth.json` and `models-store.json` in the agent directory.

### §S3 — `sol-pi-axi verify`

**Surfaces:** `sol_pi_axi/` (`verify` verb), help text, valid-verb lists.

- Runs §S2's check; registers nothing and writes no SoL-Pi file.
- Envelope: `verb: verify`; `outcome` `verified`, `failed` or `cancelled`; `verify` (§S2);
  `extension` (`state` `absent` or `registered`, `source`); `context` (`agentDir`).
- Exit 0 `verified`, 1 `failed`, 130/143/129 `cancelled`. On failure `help[]` has the fix: for no
  registration, `sol-pi-axi install`; for an invalid `<agent dir>/sol-pi.json`, correct it, or delete
  it and run `sol-pi-axi install`; otherwise `sol-pi-axi install` and `sol-pi-axi uninstall`.
- Takes `--format`; any other flag is a usage error. Pi is found as CR-SLP-007 §S2 finds it.

### §S4 — `install` runs the check

**Surfaces:** `sol_pi_axi/` (`install` verb).

- Every `install` run that ends with the source registered (`installed` or `unchanged`) runs §S2's
  check last; a run that fails or is cancelled earlier does not.
- A failed check fails the run: exit 1, `failed`, registration and configuration reported as the
  run left them (nothing removed or rewritten), `help[]` as §S3.
- `install`'s envelope gains `verify` (§S2), `null` when the run did not reach the check.

### §S5 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `docs/configuration.md`, `CHANGELOG.md`.

- README and `agents-install.md` document `verify`, the check in `install`, what fails it, the
  `verify` key, and that Pi may create `auth.json` and `models-store.json` in the agent directory.
- README, `agents-install.md` and `docs/configuration.md` say the extension reads one environment
  variable, `SOL_PI_AXI_VERIFY`, only to answer `sol-pi-axi verify`, in place of their statement
  that it reads none; `CHANGELOG.md`'s `[Unreleased]` statement that it reads none is corrected the
  same way.
- `CHANGELOG.md` `[Unreleased]` records `verify`, the check and the load signal.

## Acceptance criteria

Real-Pi cases run the development dependency's `pi` through `$PI_BIN`, offline, with a temporary
agent directory and home registering the checkout as a local path. Stub cases extend CR-SLP-007's
stub `pi` to answer `--mode rpc`.

- [ ] **§S1** Bun, a real Pi agent session (faux model) with SoL-Pi loaded and `SOL_PI_AXI_VERIFY=n1`:
      `session_start` notifies exactly `"sol-pi-axi verify n1"` at `info`, before reading the
      configuration (it still notifies with an invalid `sol-pi.json`); with the variable unset or
      empty, SoL-Pi makes no such call.
- [ ] **§S2** Real Pi, valid `sol-pi.json`: `verify` reports `verified`, `verify.ok` true,
      `verify.loaded` true, `verify.exit` 0, `verify.errors` empty, exit 0.
- [ ] **§S2** Real Pi, agent-directory `sol-pi.json` `{"version":2}`: `verify` exits 1, `failed`,
      `verify.loaded` true, one `verify.errors` entry with `event` `session_start`, `help[]` naming
      the file; the file's bytes are unchanged.
- [ ] **§S2** Real Pi: the SoL-Pi entry with `"extensions": []`, and with `"extensions":
      ["!**/index.ts"]`, each fail with exit 1, `verify.loaded` false, `error` saying Pi started
      without loading SoL-Pi.
- [ ] **§S2** Real Pi: a second registered extension that throws on load fails the check, `error`
      naming its path; one that throws in `session_start` gives `verified` with a warning naming its
      path.
- [ ] **§S2** Real Pi: a trusted home whose `~/.pi/settings.json` registers a throwing extension
      gives `verified`.
- [ ] **§S2** No SoL-Pi entry, two SoL-Pi entries, an `npm:sol-pi` entry, a `git:` entry naming
      `anthill-tec/SoL-Pi`, and an `npm:@anthill-tec/sol-pi` entry with no package directory each
      fail with exit 1 before any `--mode rpc` start (the stub records none), `error` naming the
      cause; no SoL-Pi entry, `npm:sol-pi` and `git:` have `sol-pi-axi install` in `help[]`.
- [ ] **§S2** Real Pi: the checkout registered through a symbolic link, with `{"version":2}`, fails
      with the `session_start` error in `verify.errors` (not a warning).
- [ ] **§S2** Stub: an RPC start that emits a `confirm` dialog request and never answers fails after
      the bound, `error` naming `confirm` and the dialog's title.
- [ ] **§S2** Stub: an RPC start that never answers fails after the bound with `verify.exit` `null`
      and no `pi` process left; non-JSON standard-output lines are ignored; a notify carrying another
      run's value does not count as loaded.
- [ ] **§S3** `verify` runs no `pi install` or `pi remove` (the stub records none), and the agent
      directory's SoL-Pi files and `settings.json` keep their bytes and modification times; any
      flag but `--format` exits 2.
- [ ] **§S4** Real Pi: `install` reports `installed` with `verify.ok` true; a second run reports
      `unchanged` with a non-`null` `verify`; with `{"version":2}` it exits 1, `failed`, the file
      unchanged; a run failing before registering has `verify` `null`.
- [ ] **§S4** `git grep -n -- '--mode rpc' sol_pi_axi/` returns at least one non-test line, called
      from both `verify` and `install`.
- [ ] **§S5** `tests/install-guide.test.ts` checks README and `agents-install.md` for `verify` and
      the check; its case on what the extension reads is rewritten to require, in README,
      `agents-install.md` and `docs/configuration.md`, the one-variable statement naming
      `SOL_PI_AXI_VERIFY` and no statement that the extension reads no environment variables;
      `CHANGELOG.md` `[Unreleased]` names `verify`, the check and the signal, and no longer says the
      extension reads no environment variables.
- [ ] **Gate** The Bun and the Python `pre-merge-gate` both pass.

## Estimated size

8 points.

## Risks

- Pi's RPC output is not a stable contract; the real-Pi tests catch a change on the development
  dependency.

## Non-goals

- A SoL-Pi status command or skill; any user-visible effect of the load signal outside
  `sol-pi-axi verify`.
- Running the check from `setup` or the home view.
- Failing on another extension's handler error.
