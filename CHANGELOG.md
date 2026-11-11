# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-11

### Upgrading

- SoL-Pi is now installed from the registries instead of a checkout: the `sol-pi-axi` command
  from PyPI registers the extension `@anthill-tec/sol-pi` from npm. The fish setup script is
  gone; its replacements are listed under Removed. Install and upgrade as the
  [install guide](https://github.com/anthill-tec/SoL-Pi/blob/main/agents-install.md) describes.

### Added

- `sol-pi-axi`, an installed agent-facing command (Python 3.14+, `uv tool install
  sol-pi-axi==<version>`). `sol-pi-axi setup <project dir>` writes
  `<project dir>/.pi/sol-pi.json` from the project file, the agent directory's `sol-pi.json` or the
  setup defaults (all four mechanisms on, ratio 12.5, the reducer on Pi's default provider and
  model), overridden by `--features`, `--reducer` and `--cache-ratio`; it prompts only with
  `--interactive`, writes
  atomically, and a signal cancels it leaving nothing behind. Every run prints one TOON envelope
  (or one JSON line with `--format json`) with documented exit codes; with no verb it prints a
  home view. It reads `PI_CODING_AGENT_DIR`.
  Its one runtime dependency is `toon-format` 1.2.0 (MIT).
- Registry distribution: SoL-Pi is published as two packages sharing one version, the
  `sol-pi-axi` command on PyPI and the Pi extension `@anthill-tec/sol-pi` on npm.
  `sol-pi-axi install` registers `npm:@anthill-tec/sol-pi@<version>` with Pi (Pi as `$PI_BIN` or
  `pi` on `PATH`), replaces other SoL-Pi sources once that succeeds, and writes the agent directory's
  `sol-pi.json` with the setup defaults when it has none; `sol-pi-axi uninstall` removes every
  SoL-Pi source and deletes no configuration file. The home view shows the extension's
  registration. The release workflow tests both stacks and publishes both packages.
- `sol-pi-axi verify` checks that Pi loads SoL-Pi, registering nothing and writing no SoL-Pi file
  (Pi may create `auth.json` and `models-store.json` in the agent directory):
  exactly one SoL-Pi source registered with its package on disk, then one
  `pi --offline --no-approve --mode rpc --no-session` start from home, bounded at 30 seconds, that
  must show SoL-Pi's load signal, answer `get_state` and report no SoL-Pi `extension_error`.
  `sol-pi-axi install` runs the same check last, and a failed check fails the run without removing
  or rewriting anything; both envelopes carry `verify` (`ok`, `loaded`, `exit`, `errors`).
- The load signal: the extension reads one environment variable, `SOL_PI_AXI_VERIFY`, only to
  answer `sol-pi-axi verify`; when it holds a value, SoL-Pi's `session_start` first notifies
  `sol-pi-axi verify <value>`, before reading its configuration.
- Pi 1.5.0 support: Pi 1.5.0 joins the tested set (0.84.2, 1.0.4, 1.3.0, 1.5.0) as the latest
  tested release, the development dependency and the documented default install.
  `scripts/check-pi-compat.mjs --strict` passes on it, and its mixed-internal-packages warning now
  follows every internal Pi package reachable through Pi's own (such as `pi-schema`) and advises
  installing Pi 1.5.0. `docs/compatibility.md` reviews the Pi 1.4 and 1.5 changes SoL-Pi meets.
- Action Fusion's `edit` and `write` tell the model when to use `then_run`: each keeps Pi's own
  prompt snippet and guidelines and adds a `then_run` clause to the snippet and three guidelines
  (use it for a command that finishes, leave it out when the result must be read first or the
  command keeps running, and fix forward after a non-zero exit). The `then_run` descriptions'
  examples now read "run, build, test, check, install, or restart a service".
- `--interactive` for `sol-pi-axi setup` and `sol-pi-axi install`: the run prompts on standard
  error for each mechanism, the reducer's `<provider>/<model>` (suggesting the usable
  `enabledModels` entries of Pi's `settings.json`) and the cache ratio, defaulting to the values
  it would use without `--interactive`, then asks for confirmation; `install` prompts only when it
  will create the agent directory's `sol-pi.json`. It prompts only when standard input and
  standard error are terminals, the process group is the terminal's foreground group and
  `PI_NONINTERACTIVE` is unset or empty; otherwise it warns and runs as without
  `--interactive`. A cancel before the confirmation exits 130 (declined, Ctrl+C, Ctrl+D,
  `SIGINT`), 143 (`SIGTERM`) or 129 (`SIGHUP`), in addition to AXI's 0, 1 and 2, and writes and
  registers nothing; its envelope's `help` gives the command to run it again, keeping the
  `--features`, `--reducer`, `--cache-ratio` and `--format` values given. `--interactive` with
  `--non-interactive`, with no verb, or on `uninstall` or `verify` is a usage error.

### Security

- The development dependencies no longer resolve `undici` 8.10.2, which is affected by the high
  advisories GHSA-xjj6-f33q-929c, GHSA-4w7w-5xrc-9h26, GHSA-2m5v-pch6-74hx and
  GHSA-qrxm-fqhp-jwvm (`>=8.0.0 <8.12.2`). Pi 1.5.0 brings `undici` 8.12.3, and
  `bun audit` reports no `undici` advisory.

### Changed

- The project's tooling moved to Bun 1.4.4: Bun is the package manager (`bun.lock` replaces
  `package-lock.json`), the script runner and the test runner (`bun test --timeout 30000`). The
  documentation, the `sol-pi-skill` example and the release workflow use the
  Bun commands, and Bun 1.4.4 is a prerequisite. Pi can be installed with Bun
  (`bun add --global`) or, as before, with npm.

### Removed

- Vitest: the tests run on Bun's own test runner (`bun:test`).
- The fish setup script `setup-sol-pi.fish` is removed, with its helpers
  `setup-sol-pi-interactive.mjs` and `scripts/query-pi-models.mjs`; `sol-pi-axi` replaces it:
  - user-wide setup: `sol-pi-axi install`;
  - project setup: `sol-pi-axi setup <dir>`;
  - prompts: `--interactive`;
  - `--uninstall`: `sol-pi-axi uninstall`, without the `.bak` restore;
  - strict Pi compatibility failure: a warning in `sol-pi-axi install`;
  - smoke test: the post-install check (`sol-pi-axi verify`);
  - registering the checkout: the npm source; checkout development is in `CONTRIBUTING.md`;
  - checkout validation, audit, all-mechanisms test: `bun run check`, `bun audit`.

### Fixed

- Online Context Compact no longer stops the run for a boundary compaction while
  `@gotgenes/pi-subagents` agents are running or queued: pi-subagents treated the stop as the
  user's ESC and stopped every background sub-agent. The compaction is deferred to the next
  completed step, recorded as a `sol-pi-online-context-compact-deferred` entry and, in the TUI,
  shown as an info notice.

[Unreleased]: https://github.com/anthill-tec/SoL-Pi/compare/0.1.0...HEAD
[0.1.0]: https://github.com/anthill-tec/SoL-Pi/releases/tag/0.1.0
