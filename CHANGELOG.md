# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `sol-pi-axi`, an installed agent-facing command (Python 3.14+, `uv tool install
  git+https://github.com/anthill-tec/SoL-Pi@<version>`). `sol-pi-axi setup <project dir>` writes
  `<project dir>/.pi/sol-pi.json` from the project file, the agent directory's `sol-pi.json` or the
  setup defaults (all four mechanisms on, ratio 12.5, the reducer on Pi's default provider and
  model), overridden by `--features`, `--reducer` and `--cache-ratio`; it never prompts, writes
  atomically, and a signal cancels it leaving nothing behind. Every run prints one TOON envelope
  (or one JSON line with `--format json`) with documented exit codes; with no verb it prints a
  home view. It reads `PI_CODING_AGENT_DIR`; the extension still reads no environment variables.
  Its one runtime dependency is `toon-format` 1.2.0 (MIT).
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

### Security

- The development dependencies no longer resolve `undici` 8.10.2, which is affected by the high
  advisories GHSA-xjj6-f33q-929c, GHSA-4w7w-5xrc-9h26, GHSA-2m5v-pch6-74hx and
  GHSA-qrxm-fqhp-jwvm (`>=8.0.0 <8.12.2`). Pi 1.5.0 brings `undici` 8.12.3, and
  `bun audit` reports no `undici` advisory.

### Changed

- The project's tooling moved to Bun 1.4.4: Bun is the package manager (`bun.lock` replaces
  `package-lock.json`), the script runner and the test runner (`bun test --timeout 30000`). The
  documentation, `setup-sol-pi.fish`, the `sol-pi-skill` example and the release workflow use the
  Bun commands, and Bun 1.4.4 is a prerequisite. Pi can be installed with Bun
  (`bun add --global`) or, as before, with npm.

### Removed

- Vitest: the tests run on Bun's own test runner (`bun:test`).

### Fixed

- Online Context Compact no longer stops the run for a boundary compaction while
  `@gotgenes/pi-subagents` agents are running or queued: pi-subagents treated the stop as the
  user's ESC and stopped every background sub-agent. The compaction is deferred to the next
  completed step, recorded as a `sol-pi-online-context-compact-deferred` entry and, in the TUI,
  shown as an info notice.
