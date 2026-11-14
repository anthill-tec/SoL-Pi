# SoL-Pi Agent Installation and Configuration Protocol

This is the canonical procedure for Codex, Claude Code, and other coding agents that install, configure, or validate SoL-Pi. SoL-Pi installs from the registries (PyPI and npm); its validation runs from a full source checkout. Follow the phases in order. Explicit user instructions take precedence. An extracted npm package is not a substitute for the checkout because it does not contain the test suite.

Installation and configuration are complete only when Pi remains unmodified, the repository checks pass, Pi lists the package, all four mechanisms are enabled in one effective `sol-pi.json`, and Pi starts without an extension error.

## Rules

- Do not modify, patch, fork, or vendor upstream Pi. SoL-Pi must load as a standalone extension through Pi's public package interface.
- Use Node.js 22.19 or newer and a tested Pi release: `@earendil-works/pi-coding-agent@1.5.2` (latest tested, the default), `@earendil-works/pi-coding-agent@1.5.0`, `@earendil-works/pi-coding-agent@1.3.0`, or `@earendil-works/pi-coding-agent@0.84.2` (supported floor). `@earendil-works/pi-coding-agent@1.0.4` is also tested, but do not install it or any other Pi 1.0.x or 1.1.0 release fresh: those releases do not pin their internal packages, so a fresh install now pairs them with newer ones and Pi fails to start. Treat any other Pi version as a compatibility change: `scripts/check-pi-compat.mjs --strict` rejects it, so use it only on explicit user direction and after the full suite passes against it.
- Do not clean, reset, switch, or overwrite unrelated repository changes.
- Do not print, log, commit, upload, or include any secret in a command line. Check only whether a credential is present.
- Keep SoL-Pi settings in `sol-pi.json`. The Evidence-Preserving Reducer provider/model route is a SoL-Pi setting; provider URLs, credentials, the main agent model, and shell behavior remain Pi settings.
- Keep persistent artifacts under Pi's session-derived `sol-pi/<session-id>/` root. For `--no-session` and in-memory sessions, use the automatic private directory under the system temporary directory; do not configure a separate storage path. Temporary archives remain after worker exit for callers to read, with cleanup managed by the host or caller.
- Pi codemode (`codemode.mode` `"on"` or `"only"`) is a Pi setting. SoL-Pi works with either and needs no configuration for it; see [Codemode](docs/compatibility.md#codemode).

## Inputs

Resolve these values before making changes:

- `sol_pi_root`: absolute path to the intended SoL-Pi checkout;
- `target_project`: project in which Pi will run;
- configuration scope: project-local or user-wide (the extension itself registers user-wide);
- exact SoL-Pi branch and commit.

Do not guess an ambiguous path or configuration scope.

## Phase 1: validate the checkout

From `sol_pi_root`, record the repository state without changing it:

```bash
git status --short --branch
git rev-parse HEAD
node --version
bun --version
```

Require Node.js 22.19 or newer and Bun 1.4.4 or newer. Install from the lockfile and run the source checks:

```bash
bun install --frozen-lockfile --ignore-scripts
bun run check
bun audit --audit-level=high
bun scripts/check-pi-compat.mjs --strict
bun test --timeout 30000 tests/all-mechanisms.test.ts
```

`bun run check` covers type checking, the complete test suite, and package inspection. These checks run against the checkout's development dependency, Pi 1.5.2. `tests/all-mechanisms.test.ts` confirms that one all-enabled configuration registers all four mechanisms against Pi's public extension API. The tests run without a model provider.

Stop if any command fails. Do not hide a failure with `|| true` or replace `bun install --frozen-lockfile` with an unlocked install.

## Phase 2: install Pi and SoL-Pi

Install the tested Pi release without changing its source. Use `1.5.2` unless the user asked for `1.5.0`, `1.3.0` or `0.84.2`:

```bash
bun add --global @earendil-works/pi-coding-agent@1.5.2
pi --version
```

Alternatively, install it with npm:

```bash
npm install --global --ignore-scripts @earendil-works/pi-coding-agent@1.5.2
pi --version
```

Require `pi --version` to report the version you installed. From `sol_pi_root`, check that installed Pi against the APIs SoL-Pi uses. For a Pi installed with Bun:

```bash
bun scripts/check-pi-compat.mjs --strict --pi-root "$HOME/.bun/install/global/node_modules"
```

For a Pi installed with npm:

```bash
bun scripts/check-pi-compat.mjs --strict --pi-root "$(npm root -g)"
```

Require exit status 0. The output must name the installed version; with `--strict`, an untested version fails.

Install the `sol-pi-axi` command from PyPI (Python 3.14 or newer and uv; `<version>` is the SoL-Pi release matching the commit of `sol_pi_root`) and let it register the extension with Pi user-wide:

```bash
uv tool install sol-pi-axi==<version>
sol-pi-axi install
pi list --approve
```

`sol-pi-axi install` registers `npm:@anthill-tec/sol-pi@<version>` with Pi and writes the agent directory's `sol-pi.json` with the setup defaults when it has none (see "Registering the extension with `sol-pi-axi install`" below). On a Pi with no `defaultProvider` and `defaultModel` in its `settings.json` (a Pi never started), give the reducer's route, `sol-pi-axi install --reducer <provider>/<model>`, or leave the reducer off with `--features actionFusion,observationPack,onlineContextCompact`; otherwise the run fails and names `--reducer`. Then configure each project with `sol-pi-axi setup <project dir>` (Phase 3).

Alternatively, register the extension with Pi directly, from npm:

```bash
pi install npm:@anthill-tec/sol-pi@<version> --approve
pi list --approve
```

The PyPI package `sol-pi-axi` and the npm package `@anthill-tec/sol-pi` share the same release version; `sol-pi-axi install` registers the extension at its own version.

Pi installs an `npm:` source by running `npm`, or the command array in its `npmCommand` setting (for example `["pnpm"]` or `["bun"]`); that command must be on `PATH`.

The `pi list` output must show the exact SoL-Pi source. Do not register SoL-Pi from more than one source. Installing from a checkout is for SoL-Pi development only; see `CONTRIBUTING.md`.

### Registering the extension with `sol-pi-axi install`

`sol-pi-axi install` runs Pi as `$PI_BIN` when it is set, else `pi` on `PATH`; with neither it fails, naming both. Every `pi` command runs from the home directory with `--no-approve`. It registers `npm:@anthill-tec/sol-pi@<version>` unless Pi's `settings.json` already holds exactly that source; an `npm:@anthill-tec/sol-pi` entry at another version is replaced in place by Pi, and other SoL-Pi sources (`npm:sol-pi`, a git or URL source, a local checkout path) are removed with `pi remove` only after `pi install` succeeds. An existing `sol-pi.json` in the agent directory is kept untouched; `--features`, `--reducer` and `--cache-ratio` apply only when the file is written. Its envelope adds `outcome` (`installed`, `unchanged`, `failed` or `cancelled`), `extension` (`source`, `registered`, `replaced`, `pi`), `config` (`path`, `state` `written` or `kept`, and the values) and `context` (`agentDir`); `unchanged` means nothing was registered and nothing written. Require exit status 0 and `ok: true`.

`sol-pi-axi uninstall` removes every SoL-Pi source Pi has registered with `pi remove`, and deletes no configuration file (`warnings` names the agent directory's `sol-pi.json` when it exists). Its envelope adds `outcome` (`removed`, `unchanged`, `failed` or `cancelled`), `removed` (the sources removed) and `context` (`agentDir`).

`sol-pi-axi install` ends, once the source is registered (`installed` or `unchanged`), by running the check that `sol-pi-axi verify` runs, proving Pi loads SoL-Pi; a failed check fails the run (exit 1, `failed`) and removes or rewrites nothing, reporting the registration and configuration as the run left them. Its envelope adds `verify` (below), `null` when the run ended before the check. A cancel during the check also gives `verify: null`.

`sol-pi-axi verify` runs that check alone; it registers nothing and writes no SoL-Pi file. It first requires exactly one SoL-Pi source in Pi's `settings.json`, an `npm:@anthill-tec/sol-pi` source or a local path, with its package on disk; then it starts `pi --offline --no-approve --mode rpc --no-session` from the home directory with `SOL_PI_AXI_VERIFY` set to a value unique to the run, sends one `get_state` command, and waits at most 30 seconds. It fails when Pi exits non-zero (a load failure: `error` quotes Pi's `Failed to load extension` line), when SoL-Pi reports a handler error (an `extension_error` inside its package, such as an invalid `sol-pi.json` at `session_start`), when no `get_state` response arrives, or when Pi started without loading SoL-Pi (no load signal carried the run's value, for example because a resource filter in `settings.json` excludes it). An extension that opens a dialog (`select`, `confirm`, `input` or `editor`) in `session_start` holds Pi until the 30-second bound kills it; `error` then names the dialog's method and title, as Pi does not name the extension that opened it. Another extension's `extension_error` is a warning. Its envelope adds `outcome` (`verified`, `failed` or `cancelled`), `verify`, `extension` (`state`, `source`) and `context` (`agentDir`); `verify` has `ok`, `loaded` (SoL-Pi's load signal was seen), `exit` (Pi's exit code, `null` when Pi was killed or not started) and `errors` (SoL-Pi's own `extensionPath`, `event`, `error` entries). Exit codes: 0 `verified`, 1 `failed`, 130, 143 and 129 `cancelled`. On failure `help` holds the fix: `sol-pi-axi install` when no usable source is registered; for an invalid agent-directory `sol-pi.json`, correct it, or delete it and run `sol-pi-axi install`; otherwise `sol-pi-axi install` and `sol-pi-axi uninstall`. Pi may create `auth.json` and `models-store.json` in the agent directory. Require exit status 0 and `ok: true`.

### The home view's extension

With no verb, the home view also shows the extension: `extension` has `state` (`absent` or `registered`) and the registered `source`. When the registered source is not `npm:@anthill-tec/sol-pi` at `sol-pi-axi`'s own version, the home view warns and adds `sol-pi-axi install` to `help`.

## Phase 3: configure all four mechanisms

SoL-Pi defaults every mechanism to disabled. For this managed installation, create exactly one effective configuration with every mechanism enabled:

```json
{
  "version": 1,
  "actionFusion": true,
  "observationPack": true,
  "evidencePreservingReducer": true,
  "evidencePreservingReducerProvider": "provider-id",
  "evidencePreservingReducerModel": "model-id",
  "onlineContextCompact": true,
  "cacheWriteReadRatio": 12.5
}
```

`evidencePreservingReducerProvider` and `evidencePreservingReducerModel` select the nested reducer route that Evidence-Preserving Reducer resolves through Pi's model registry. They default to the built-in reducer route and must be non-empty strings when supplied. Change them only when a different reducer model is intended.

`cacheWriteReadRatio` is the only pricing-related input SoL-Pi reads. It defaults to `12.5`, accepts any finite non-negative number, and treats `0` as an explicit statement that a cache write adds no cost relative to a cache read. SoL-Pi does not inspect Pi model prices. The value controls one compaction decision and is not a bill estimate. The default follows the GPT-5.6 Sol OpenAI Standard cache-write/read ratio checked on 2026-08-21; see [OpenAI API pricing](https://developers.openai.com/api/docs/pricing). Change it when a different policy is required.

Use one location matching the selected scope. Resolve the directory through Pi; the official Pi defaults are shown in parentheses:

- project-local: `<target_project>/<Pi config directory>/sol-pi.json` (`<target_project>/.pi/sol-pi.json`);
- user-wide: `<Pi agent directory>/sol-pi.json` (`~/.pi/agent/sol-pi.json`).

SoL-Pi uses Pi's public `CONFIG_DIR_NAME` and `getAgentDir()` APIs. Do not assume the defaults when Pi reports different directories.

The extension follows Pi's configuration and agent directories as Pi reports them; `sol-pi-axi` supports the official Pi layout only (`.pi/` in the project, `$PI_CODING_AGENT_DIR` or `~/.pi/agent` for the agent directory). With another layout, write the file by hand.

### Writing the project file with `sol-pi-axi setup`

For the project-local scope on the official Pi layout, `sol-pi-axi setup` writes the file, using the `sol-pi-axi` command installed in Phase 2. For this all-enabled profile:

```bash
sol-pi-axi setup /absolute/path/to/target_project --features all --reducer provider-id/model-id --cache-ratio 12.5
```

`sol-pi-axi setup <project dir>` writes `<project dir>/.pi/sol-pi.json` (creating `.pi/` when missing) and nothing else; it prompts only with `--interactive` (below). Its base values are a valid project file's values, else the agent directory's `sol-pi.json`, else the setup defaults (all four mechanisms on, ratio 12.5, the reducer on Pi's `defaultProvider` and `defaultModel` from the agent directory's `settings.json`); with no value flag a valid project file is left `unchanged`. Flags: `--features` (`all`, `none`, or a comma list of mechanism keys; unlisted ones off), `--reducer <provider>/<model>`, `--cache-ratio <number>`, `--format toon|json` (default `toon`), `--interactive` (prompt for the values, below), `--non-interactive` (accepted; a usage error with `--interactive`), `--help`, `--version`.

Every run except `--help` and `--version` prints one envelope on standard output, TOON under the root `axi`, or one JSON line with `--format json`. Every envelope has `verb`, `ok`, `version`, `warnings` and `help` (the next steps), and `error` when `ok` is false. A `setup` envelope adds `outcome` (`written`, `unchanged`, `failed` or `cancelled`), `path`, `config` (`features`, `reducer`, `cacheRatio`) and `context` (`project`, `agentDir`); a usage error has `verb: usage` and `outcome: usage`. With no verb, `sol-pi-axi` prints the home view: `bin`, `description`, and the state of the working directory's `.pi/sol-pi.json` and the agent directory's `sol-pi.json`.

Exit status: exit code 0 for `written`, `unchanged` and the home view; 1 for `failed`; 2 for a usage error; 130, 143 or 129 for a run `cancelled` by `SIGINT`, `SIGTERM` or `SIGHUP`. Require exit status 0 and `ok: true`, record `path`, and still validate the file with `check-sol-pi-config.mjs` below.

`sol-pi-axi setup --interactive` and `sol-pi-axi install --interactive` prompt for the values a person would otherwise pass as flags: each mechanism (yes or no), the reducer's `<provider>/<model>` when the reducer is on, and the cache ratio, then show the result and ask for confirmation. `setup` prompts for the project file's values; `install` prompts only when it will create the agent directory's `sol-pi.json`. The defaults are the values the run would use without `--interactive`, after any value flags. Prompts go to standard error and standard output carries only the envelope. `--interactive` is a usage error (exit 2) with `--non-interactive`, with no verb, and on `uninstall` and `verify`. An unattended agent run does not pass `--interactive`; it passes the value flags.

`--interactive` prompts only when standard input and standard error are both terminals, the process group is that terminal's foreground group, and `PI_NONINTERACTIVE` is unset or empty. Otherwise the run adds a warning saying why and runs as without `--interactive`, with the same outcome and exit status; set `PI_NONINTERACTIVE=1` to keep a terminal session from prompting.

Before the confirmation, a prompted run is cancelled by declining it, Ctrl+C, Ctrl+D on an empty line or `SIGINT` (exit 130), `SIGTERM` (143) or a closed terminal, `SIGHUP` (129). These cancel exit codes are an addition to AXI's exit codes 0, 1 and 2; the run prints a `cancelled` envelope, writes and registers nothing, and leaves no temporary file.

The project file replaces the user-wide file; the two are not merged. After `sol-pi-axi install` the agent directory's file exists and a project's file replaces it; if a file you did not write exists at either location, inspect it and obtain direction before changing it. Unknown keys, unsupported versions, malformed JSON, non-boolean feature values, invalid reducer model fields, and invalid ratios must remain fatal.

Do not put provider URL, credentials, shell path, command prefix, storage path, or run ID in `sol-pi.json`. SoL-Pi either reads those values from Pi or derives them from the Pi session.

The extension reads one environment variable, `SOL_PI_AXI_VERIFY`, only to answer `sol-pi-axi verify` (it sends the load signal that check waits for). The `sol-pi-axi` command reads `PI_CODING_AGENT_DIR` to find the agent directory (default `~/.pi/agent`). Evidence-Preserving Reducer uses the configured reducer provider/model route and Pi-managed authentication. Configure credentials in Pi and do not copy them into `sol-pi.json`.

From `sol_pi_root`, validate the exact effective file:

```bash
bun scripts/check-sol-pi-config.mjs \
  --config /absolute/path/to/effective/sol-pi.json \
  --require-all-enabled
```

Require exit status 0 and retain its JSON output. The check applies SoL-Pi's default values, rejects unknown keys and wrong types, and confirms all four mechanisms are enabled. A partially enabled file can be valid SoL-Pi configuration, but it does not satisfy this all-enabled profile.

## Phase 4: verify the installation

1. Run `pi list --approve` from `target_project` and confirm the expected SoL-Pi source and scope.
2. Run `check-sol-pi-config.mjs --require-all-enabled` against the effective `sol-pi.json`, and re-run `check-pi-compat.mjs --strict --pi-root` against the installed Pi.
3. Re-run `bun test --timeout 30000 tests/all-mechanisms.test.ts` from `sol_pi_root`.
4. Start Pi with `--offline --approve`, send no prompt, confirm there is no extension load error, and exit.
   `sol-pi-axi verify` makes the same check without starting an interactive Pi: require exit status 0 and `outcome: verified`.
5. Confirm that upstream Pi was not patched and that the SoL-Pi checkout contains no vendored Pi monorepo source.

## Completion report

Report:

- SoL-Pi absolute path, branch, and commit;
- repository state before and after installation;
- Node, Bun, and Pi versions, and the `check-pi-compat.mjs` result for the installed Pi;
- install scope and the exact entry shown by `pi list`;
- effective config path, four enabled flags, EPR reducer provider/model, and `cacheWriteReadRatio`, without secrets;
- every validation command and result;
- any blocker or deviation.

Do not describe the installation as successful if a required check is missing.

## Agent entry files

`agents-install.md` is the single source of truth, but agents do not universally auto-discover arbitrary filenames. Root `AGENTS.md` tells Codex to read this file, while root `CLAUDE.md` imports it for Claude Code. Keep those entry files short and keep executable installation details here.

- [Codex `AGENTS.md` discovery](https://developers.openai.com/codex/guides/agents-md)
- [Claude Code project memory and imports](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)
