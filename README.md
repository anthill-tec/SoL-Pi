<p align="center">
  <img src="https://raw.githubusercontent.com/anthill-tec/SoL-Pi/main/assets/sol-pi-hero.png" width="100%" alt="SoL-Pi: Scaling Auto-Research Loops for Efficient Agent Harnesses" />
</p>

# ⚡ SoL-Pi: Scaling Auto-Research Loops for Efficient Agent Harnesses

<p align="center">
  <a href="https://arxiv.org/abs/2609.20519"><img src="https://img.shields.io/badge/arXiv-2609.20519-B31B1B?logo=arxiv&amp;logoColor=white" alt="arXiv: 2609.20519" /></a>
  <a href="#getting-started"><img src="https://img.shields.io/badge/Getting%20Started-Install-76B900" alt="Getting Started" /></a>
  <a href="https://github.com/anthill-tec/SoL-Pi/blob/main/docs/configuration.md"><img src="https://img.shields.io/badge/Docs-Configuration-555555" alt="Configuration" /></a>
  <a href="https://nvlabs.github.io/SoL-Pi/"><img src="https://img.shields.io/badge/Blog-SoL--Pi-76B900" alt="SoL-Pi Blog" /></a>
  <a href="https://github.com/anthill-tec/SoL-Pi/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="MIT License" /></a>
</p>

> [!NOTE]
> This repository contains the open-source version of SoL-Pi, a standalone extension for [Pi](https://github.com/earendil-works/pi). It is not an official distribution of Pi.
>
> SoL-Pi is under active development to support pi-v1 and the latest model checkpoints.

## 📰 News

- **2026-10-14** — Released the [SoL-Pi Skill](https://github.com/anthill-tec/SoL-Pi/blob/main/examples/sol-pi-skill/README.md) example: use SoL-Pi as a skill from Claude Code (`/sol-pi`) or Codex (`$sol-pi`). The current task is handed to SoL-Pi with the host conversation as context, runs in the background, and its result is reported back to the session.
- **2026-10-13** — Released the [SoL-Pi Visual](https://github.com/anthill-tec/SoL-Pi/blob/main/examples/solpi-visual/README.md) example for 3D scene reconstruction in Blender. On this task, it lowers the cost per scene by **37%** compared with Codex, with 13% fewer model calls. See the example for visual scores and scene comparisons.

## 💡 TL;DR

**Spend less without making the agent do less useful work.**

SoL-Pi is a standalone extension for Pi that packages four reusable efficiency mechanisms discovered through scaled auto-research loops. It reduces repeated model turns, context replay, oversized observations, and unnecessary long-log reading while preserving the work and evidence an agent needs to finish a task.

SoL-Pi installs on top of an unmodified Pi release. Every mechanism is opt-in and disabled by default.

## Introduction

Long-running coding agents accumulate repeated work. A file edit is often followed by a predictable validation command. Large tool results are replayed long after their first use. Completed subtasks remain in active context, and a frontier model may spend a full request reading a log when only a few lines affect the next decision.

SoL-Pi grew out of a broader question from our auto-research work: before scaling agent loops, can agents first make the harness itself more efficient? The search focused on constrained efficiency: reducing token traffic, inference work, and agent turns without stopping early, skipping verification, or hiding evidence.

The standalone release contains four mechanisms that survived that process. They operate at different parts of the harness and compose through Pi's public extension APIs.

## What SoL-Pi Adds

| Area | Mechanism | What changes |
|---|---|---|
| Tools | **Action Fusion** | An edit or write can run its follow-up validation command in the same tool call. |
| Observations | **ObservationPack** | Repeated large text results become stable handles with exact paged recall. |
| Delegation | **Evidence-Preserving Reducer** | Long diagnostic logs become compact receipts only when every retained quotation matches the archived source. |
| Context | **Online Context Compact** | Completed plan steps become candidate points for Pi's native compaction, subject to economic and window-pressure checks; after a successful compaction, Pi continues the task in a new turn. |

The mechanisms share four rules:

- **No Pi patches.** SoL-Pi imports public Pi APIs and does not vendor the Pi source tree.
- **Explicit opt-in.** A missing configuration leaves every mechanism disabled.
- **Preserve evidence.** Original observations remain available locally, and reducer failures leave the original result unchanged.
- **Use Pi's runtime choices.** Authentication, provider URLs, and the main model remain under Pi's control.

## Technical Details and Core Insights

Read the [SoL-Pi blog](https://nvlabs.github.io/SoL-Pi/) for a deeper look at the technical details, design rationale, and core insights behind SoL-Pi, including how auto-research led to the four efficiency mechanisms and how they work.

## Paper

Read our paper: [SoL-Pi: Recursively Scaling Auto-Research Loops for Efficient Agent Harness](https://arxiv.org/abs/2609.20519).

## Getting Started

### Requirements

- Node.js 22.19 or newer
- Bun 1.4.4 or newer
- `@earendil-works/pi-coding-agent` 0.84.2 or newer; tested with 0.84.2, 1.0.4, 1.3.0, and 1.5.0. Install 1.5.0, the latest tested release: a fresh install of Pi 1.0.x or 1.1.0 now fails to start, because those releases do not pin their internal packages. Other versions are untested: `scripts/check-pi-compat.mjs` warns on them, and `--strict` fails.

### Install

Install the latest tested Pi release with Bun:

```bash
bun add --global @earendil-works/pi-coding-agent@1.5.0
```

Or, with npm:

```bash
npm install --global @earendil-works/pi-coding-agent@1.5.0
```

Pi 1.3.0 and 0.84.2 remain supported and tested; install `@earendil-works/pi-coding-agent@1.3.0` or `@earendil-works/pi-coding-agent@0.84.2` instead to stay on one of them.

Then install the `sol-pi-axi` command from PyPI and let it register the extension with Pi. It needs Python 3.14 or newer and [uv](https://docs.astral.sh/uv/); `<version>` is a SoL-Pi release:

```bash
uv tool install sol-pi-axi==<version>
sol-pi-axi install
```

`sol-pi-axi install` registers the extension `npm:@anthill-tec/sol-pi@<version>` with Pi (`pi install`, run from your home directory) and writes the agent directory's `sol-pi.json` with the setup defaults when it has none. Then configure each project:

```bash
sol-pi-axi setup <project dir>
```

Alternatively, register the extension with Pi yourself, from npm:

```bash
pi install npm:@anthill-tec/sol-pi@<version>
```

The PyPI package `sol-pi-axi` and the npm package `@anthill-tec/sol-pi` share the same release version; `sol-pi-axi install` registers the extension at its own version.

Pi installs an `npm:` source by running `npm`, or the command array in its `npmCommand` setting (for example `["pnpm"]` or `["bun"]`); that command must be on `PATH`.

### Configure

SoL-Pi uses a single effective configuration. With the official Pi distribution, it looks for a `sol-pi.json` file in the following locations, in order:

1. `.pi/sol-pi.json` in the current project, if the project is trusted and the file exists;
2. `~/.pi/agent/sol-pi.json` otherwise.

If neither file exists, SoL-Pi uses its built-in defaults. The project-level configuration takes precedence over the user-level configuration; the two files are not merged.

The following conservative configuration enables only the two local mechanisms that make no additional model calls and do not stop an active run:

```json
{
  "version": 1,
  "actionFusion": true,
  "observationPack": true,
  "evidencePreservingReducer": false,
  "onlineContextCompact": false,
  "cacheWriteReadRatio": 12.5
}
```

Enable additional mechanisms only after reviewing their configuration and security implications. The extension reads no dedicated environment variables; feature flags, the reducer provider/model route, and the compaction ratio are configured in `sol-pi.json`. The `sol-pi-axi` command reads `PI_CODING_AGENT_DIR` to find the agent directory (default `~/.pi/agent`). See [sol-pi.example.json](https://github.com/anthill-tec/SoL-Pi/blob/main/sol-pi.example.json) for a template listing every key.

### `sol-pi-axi setup`

`sol-pi-axi setup <project dir>` writes `<project dir>/.pi/sol-pi.json` (creating `.pi/` when missing) and nothing else. It never prompts. Its base values are a valid project file's values, else the agent directory's `sol-pi.json`, else the setup defaults: all four mechanisms on, ratio 12.5, and the reducer on Pi's `defaultProvider` and `defaultModel` from the agent directory's `settings.json`. With no value flag, a valid project file is left `unchanged`. The flags override the base values:

| Flag | Value |
|---|---|
| `--features` | `all`, `none`, or a comma list of `actionFusion`, `observationPack`, `evidencePreservingReducer`, `onlineContextCompact`; unlisted ones off |
| `--reducer` | `<provider>/<model>`, split at the first `/` |
| `--cache-ratio` | digits with an optional decimal fraction |
| `--format` | `toon` (default) or `json` |
| `--non-interactive` | accepted, no effect |
| `-h`, `--help` | plain-text help |
| `-v`, `-V`, `--version` | the bare version |

```bash
sol-pi-axi setup . --features actionFusion,observationPack --cache-ratio 8
sol-pi-axi setup ~/work/app --reducer anthropic/claude-sonnet-4-5 --format json
```

Every run except `--help` and `--version` prints one envelope on standard output: [TOON](https://github.com/toon-format/spec) under the root `axi`, or the same object as one JSON line with `--format json`. Every envelope has `verb`, `ok`, `version`, `warnings` and `help` (the next steps), and `error` when `ok` is false. A `setup` envelope adds `outcome` (`written`, `unchanged`, `failed` or `cancelled`), `path` (the file, absolute, or null), `config` (`features`, `reducer`, `cacheRatio`; null on failure) and `context` (`project`, `agentDir`). A usage error has `verb: usage` and `outcome: usage`.

With no verb, `sol-pi-axi` prints the home view: `bin`, `description`, and the state (`absent`, `valid` or `invalid`) of the working directory's `.pi/sol-pi.json` and of the agent directory's `sol-pi.json`.

Exit codes: exit code 0 for `written`, `unchanged` and the home view; 1 for `failed`; 2 for a usage error; 130, 143 and 129 for a run `cancelled` by `SIGINT`, `SIGTERM` or `SIGHUP` (nothing is written). After `written`, start `pi` in the project and trust it, so the extension reads the project file.

### `sol-pi-axi install` and `sol-pi-axi uninstall`

`sol-pi-axi install` runs Pi as `$PI_BIN` when it is set, else `pi` on `PATH`; with neither it fails, naming both. Every `pi` command runs from your home directory with `--no-approve`. It registers `npm:@anthill-tec/sol-pi@<version>` unless Pi's `settings.json` already holds exactly that source; an `npm:@anthill-tec/sol-pi` entry at another version is replaced in place by Pi, and other SoL-Pi sources (`npm:sol-pi`, a git or URL source, a local checkout path) are removed with `pi remove` only after `pi install` succeeds. An existing `sol-pi.json` in the agent directory is kept untouched; `--features`, `--reducer` and `--cache-ratio` apply only when the file is written. Its envelope adds `outcome` (`installed`, `unchanged`, `failed` or `cancelled`), `extension` (`source`, `registered`, `replaced`, `pi`), `config` (`path`, `state` `written` or `kept`, and the values) and `context` (`agentDir`); `unchanged` means nothing was registered and nothing written.

`sol-pi-axi uninstall` removes every SoL-Pi source Pi has registered with `pi remove`, and deletes no configuration file (`warnings` names the agent directory's `sol-pi.json` when it exists). Its envelope adds `outcome` (`removed`, `unchanged`, `failed` or `cancelled`), `removed` (the sources removed) and `context` (`agentDir`).

The home view also shows the extension: `extension` has `state` (`absent` or `registered`) and the registered `source`. When the registered source is not `npm:@anthill-tec/sol-pi` at `sol-pi-axi`'s own version, the home view warns and adds `sol-pi-axi install` to `help`.

For the complete schema, see [Configuration](https://github.com/anthill-tec/SoL-Pi/blob/main/docs/configuration.md). Coding agents and automated environments should follow the canonical [agent installation and configuration protocol](https://github.com/anthill-tec/SoL-Pi/blob/main/agents-install.md), which describes an all-enabled configuration checked with `scripts/check-sol-pi-config.mjs --require-all-enabled`.

### Pi 1.x and codemode

SoL-Pi is tested with Pi 0.84.2, 1.0.4, 1.3.0, and 1.5.0. All four mechanisms work with Pi codemode in both `codemode.mode: "on"` and `"only"`. In `"only"` mode, the model reaches bash, edit, and write through codemode scripts, and Evidence-Preserving Reducer skips script calls, so it has no effect there. See [Codemode](https://github.com/anthill-tec/SoL-Pi/blob/main/docs/compatibility.md#codemode) for per-mechanism behavior.

To check the Pi that will load SoL-Pi, install the checkout's dependencies, then run the check from the checkout; `--strict` also fails on an untested Pi version. Without `bun install`, the check cannot load TypeScript, prints a warning, and fails under `--strict` even on a tested Pi. For a Pi installed with Bun:

```bash
bun install --frozen-lockfile --ignore-scripts
bun scripts/check-pi-compat.mjs --pi-root "$HOME/.bun/install/global/node_modules"
```

For a Pi installed with npm:

```bash
bun scripts/check-pi-compat.mjs --pi-root "$(npm root -g)"
```

## Storage and Security

ObservationPack and Evidence-Preserving Reducer store session-specific archives under:

```text
<session-directory>/sol-pi/<session-id>/
├── observation-pack/
└── evidence-preserving-reducer/
```

They archive eligible source material in this directory. The archived copies remain local and are not automatically deleted when the Pi session ends.

With `pi --no-session` or `SessionManager.inMemory()`, Pi provides no session directory. SoL-Pi instead creates a private directory named `sol-pi-<session-id>-<random>/` under the operating system's temporary directory. ObservationPack and Evidence-Preserving Reducer share this directory for the lifetime of the loaded extension. These modes disable Pi's session-log persistence; SoL-Pi still writes archive files for exact recall. Temporary archives are also retained after the session or worker exits so callers can read referenced evidence. Their eventual cleanup follows the host's temporary-file policy or the caller's cleanup, and they are not guaranteed to survive system cleanup or support session recovery.

Online Context Compact stores its state in Pi's session log. After a successful compaction, it starts a new turn and automatically continues the active task; after a failed compaction, it continues the task without compacting and reports the error. Cancelling the compaction or exiting Pi does not trigger automatic continuation.

Evidence-Preserving Reducer may send eligible diagnostic-log content to its configured reducer model using Pi-managed authentication. Review [SECURITY.md](https://github.com/anthill-tec/SoL-Pi/blob/main/SECURITY.md) before enabling it. Do not enable remote reduction for logs that must remain local.

## Documentation

| Document | Purpose |
|---|---|
| [Configuration](https://github.com/anthill-tec/SoL-Pi/blob/main/docs/configuration.md) | Config search order, schema, defaults, and trust behavior |
| [Compatibility](https://github.com/anthill-tec/SoL-Pi/blob/main/docs/compatibility.md) | Supported Pi APIs and standalone integration details |
| [Security](https://github.com/anthill-tec/SoL-Pi/blob/main/SECURITY.md) | Local storage, remote reduction, and sensitive behavior |
| [Agent installation](https://github.com/anthill-tec/SoL-Pi/blob/main/agents-install.md) | Reproducible installation and all-enabled validation procedure |

## Development

To install SoL-Pi from a checkout while developing it, see [CONTRIBUTING.md](https://github.com/anthill-tec/SoL-Pi/blob/main/CONTRIBUTING.md). Install from the lockfile and run the complete source checks:

```bash
bun install --frozen-lockfile --ignore-scripts
bun run check
bun audit --audit-level=high
bun run check:pi
```

`bun run check` covers TypeScript, the complete test suite, and package inspection. `bun run check:pi` runs `scripts/check-pi-compat.mjs` against the development dependency; pass `-- --strict` to fail on warnings, or `-- --pi-root <dir>` to check another Pi installation. The development dependency set is pinned to Pi 1.5.0. To check another tested Pi version, install its four Pi packages over the development dependency (for 1.0.4 also `pi-codemode`, `pi-mcp` and `chord` at 1.0.4) and rerun the checks; runtime Pi packages remain peer dependencies so Pi owns their installation and upgrades.

## Project Status

SoL-Pi is developed and maintained by NVIDIA as a standalone extension for Pi.

We welcome tested, Pi-compatible extension PRs that improve token efficiency and reduce token cost. Our team will help benchmark contributions, publish results on a regular reporting cycle, and credit authors of accepted PRs as Contributors. See [CONTRIBUTING.md](https://github.com/anthill-tec/SoL-Pi/blob/main/CONTRIBUTING.md) for details.

## Acknowledgements

SoL-Pi builds on the public extension interfaces provided by [Pi](https://github.com/earendil-works/pi). Pi remains an independent upstream project and is not vendored into this repository.

## License

SoL-Pi is released under the [MIT License](https://github.com/anthill-tec/SoL-Pi/blob/main/LICENSE).

## Star History

<a href="https://www.star-history.com/?repos=NVlabs%2FSoL-Pi&amp;type=date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/NVlabs/SoL-Pi/star-history/star-history-dark.svg" />
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/NVlabs/SoL-Pi/star-history/star-history-light.svg" />
    <img alt="SoL-Pi star history chart" src="https://raw.githubusercontent.com/NVlabs/SoL-Pi/star-history/star-history-light.svg" width="100%" />
  </picture>
</a>
