# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
