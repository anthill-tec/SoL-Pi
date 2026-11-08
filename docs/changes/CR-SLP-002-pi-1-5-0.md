# CR-SLP-002 — Support Pi 1.5.0; clear the `undici` advisories

**Status:** PENDING · Pre-review: ran — touches another project's surface (Model B's setup step runs the strict Pi compatibility check, message #1516 item 5); re-scoped 2026-11-04 (the setup script's Pi lookup removed: CR-SLP-005 retires the script)
**Type:** maintenance
**Priority:** P1 — Model B projects on Pi 1.5.0 cannot finish SoL-Pi's setup
**Depends on:** CR-SLP-001
**Labels:** compatibility, dependencies, security, docs
**Phase:** 0.1.0 · wave 1
**Design reference:** `docs/compatibility.md`; Model B's request, Sandesh message #1516 item 5

## Context

SoL-Pi's development dependency is Pi 1.3.0, and its tested set is 0.84.2, 1.0.4 and 1.3.0
(`TESTED_PI_VERSIONS` in `scripts/check-pi-compat.mjs`). Pi 1.5.0 is the current release.

Measured 2026-11-04 on this machine (Pi 1.5.0 installed with Bun):

- `check-pi-compat.mjs --strict --pi-root "$HOME/.bun/install/global/node_modules"` passes every
  API check (bash non-zero exit as an error result, bash output schema, codemode,
  `ModelRegistry.complete`) and fails only on `WARN: Pi 1.5.0 is not in the tested set`.
- `bun audit --audit-level=high` reports four high advisories against `undici` 8.10.2
  (GHSA-xjj6-f33q-929c, GHSA-4w7w-5xrc-9h26, GHSA-2m5v-pch6-74hx, GHSA-qrxm-fqhp-jwvm; affected
  `>=8.0.0 <8.12.2`), reached through the Pi 1.3.0 development dependency
  (`pi-coding-agent > undici` and `pi-ai > openai > undici`). Pi 1.5.0 depends on `undici` 8.12.3.
- Pi 1.5.0 pins its internal packages exactly. Besides its direct `@earendil-works/pi-*`
  dependencies it reaches `pi-schema` and `pi-telemetry` through `pi-ai` and `pi-agent-core`.
  `mixedInternalPackages` checks only the direct ones.

Pi 1.4.0 and 1.5.0 change behaviour SoL-Pi meets:

- **Tool argument validation** moves to `@earendil-works/pi-schema`. TypeBox features outside JSON
  Schema no longer apply (SoL-Pi's schemas use none), arguments are coerced (numeric strings to
  numbers, a single value to an array), and the validation-failure text changes. Arguments Pi used
  to reject can now reach the `execute` of SoL-Pi's tools.
- **Extension changelogs.** After an update, Pi 1.5.0 shows the `CHANGELOG.md` at an extension
  package's root, matching its version headings against `package.json` `version`.
- **Codemode** queues scripts for a free worker instead of failing at the worker limit.

The failure Model B reported (#1516 item 5) is in `setup-sol-pi.fish`, which runs the check with
`--strict` against a Pi it finds by guessing directories. CR-SLP-005 retires that script, and
CR-SLP-007's `sol-pi-axi install` reads the version of the `pi` that runs and warns when it is
outside the tested set this CR extends.

## Scope

### §S1 — Pi 1.5.0 as the development dependency

**Surfaces:** `package.json`, `bun.lock`.

- The four `@earendil-works/pi-*` development dependencies are exactly `1.5.0`.
- `peerDependencies` keep their `>=0.84.2` floor.
- `bun.lock` resolves no `undici` below 8.12.2. If a dependency path still resolves one, an
  `overrides` entry pins `undici` to a fixed version.

### §S2 — Pi 1.5.0 joins the tested set

**Surfaces:** `scripts/check-pi-compat.mjs`, `tests/package.test.ts`.

- `TESTED_PI_VERSIONS` is `["0.84.2", "1.0.4", "1.3.0", "1.5.0"]`.
- The mixed-internal-packages warning advises installing Pi 1.5.0, the latest tested release, in
  place of 1.3.0.
- `mixedInternalPackages` covers every `@earendil-works/pi-*` package reachable through Pi's
  `@earendil-works/pi-*` dependencies, not only the direct ones.
- The full suite runs on the 1.5.0 development dependency. A test that fails because of a Pi 1.4
  or 1.5 change is fixed at the cause: a cause in SoL-Pi's code is fixed there with a test that
  fails before the fix. No test is skipped or loosened to pass.

### §S3 — The Pi 1.4/1.5 changes, reviewed

**Surfaces:** `docs/compatibility.md`, tests where a decision claims behaviour.

- `docs/compatibility.md` lists each Pi 1.4/1.5 change from Context (tool argument validation and
  coercion, extension changelogs, the codemode worker queue) and any the §S2 run finds, with
  SoL-Pi's decision for each.
- A decision that states how SoL-Pi behaves on Pi 1.5.0 has a test through a real Pi session on the
  development dependency.
- For extension changelogs, the decision covers how SoL-Pi's `CHANGELOG.md` version headings meet
  Pi's matching once a release adds them.

### §S4 — Documentation and changelog

**Surfaces:** `README.md`, `agents-install.md`, `docs/compatibility.md`, `THIRD_PARTY_NOTICES.md`,
`CHANGELOG.md`.

- Pi 1.5.0 is the latest tested release and the documented default install; 1.3.0, 1.0.4 and
  0.84.2 stay listed as tested.
- `THIRD_PARTY_NOTICES.md` lists the four Pi packages at 1.5.0.
- `CHANGELOG.md` `[Unreleased]` records Pi 1.5.0 support and the `undici` fix.

## Acceptance criteria

- [ ] **§S1** `package.json` `devDependencies` has the four Pi packages at exactly `1.5.0`;
      `peerDependencies` is unchanged.
- [ ] **§S1** Every `undici@` entry in `bun.lock` is 8.12.2 or later, and `bun audit` reports no
      `undici` advisory.
- [ ] **§S2** `bun scripts/check-pi-compat.mjs --strict` prints `Pi compatibility: OK` with no
      warning and exits 0 against the development dependency, and against a Bun global install of
      Pi 1.5.0 (`--pi-root "$HOME/.bun/install/global/node_modules"`).
- [ ] **§S2** A `tests/package.test.ts` case runs the check with `--strict` against a fake Pi 1.5.0
      that exports its own `VERSION` (not the development dependency's) and whose internal packages
      are 1.5.0, and expects exit 0 with no warning.
- [ ] **§S2** The mixed-internal-packages test expects `install Pi 1.5.0` in the warning, and a new
      case warns when an indirect internal package (for example `pi-schema`) comes from another
      release.
- [ ] **§S2** The bun client's `regression` on the 1.5.0 development dependency passes every test,
      runs every test CR-SLP-001's fidelity criteria name, and adds no skip.
- [ ] **§S3** `docs/compatibility.md` lists the three Pi 1.4/1.5 changes from Context, and any the
      §S2 run found, each with a decision; each decision that states behaviour names its test.
- [ ] **§S4** `tests/install-guide.test.ts` passes; README, `agents-install.md` and
      `docs/compatibility.md` each name the four tested versions; the four Pi rows of the
      `THIRD_PARTY_NOTICES.md` table read 1.5.0.
- [ ] **§S4** `CHANGELOG.md` `[Unreleased]` has entries for Pi 1.5.0 support and the `undici`
      advisories.
- [ ] **Gate** `pre-merge-gate` passes. A new high advisory against a package other than `undici`
      found while this CR is open does not block it; it is filed as its own CR.

## Estimated size

3 points. The version bump and docs are mechanical; the indirect internal-package check and the
reviewed change list add work, and the suite's result on Pi 1.5.0 is the uncertainty. (5 before
the setup script's Pi lookup was removed.)

## Risks

- The suite runs on one Pi version at a time. Claims for 1.3.0, 1.0.4 and 0.84.2 rest on earlier
  runs; this CR does not re-run them.
- A Pi 1.5.0 difference that needs a design change in a mechanism becomes its own CR.
- Model B reaches SoL-Pi through an installed release (CR-SLP-004, CR-SLP-007), so #1516 item 5 is
  closed for Model B when this CR, CR-SLP-005, CR-SLP-007 and release 0.1.0 have landed.

## Non-goals

- Dropping a version from the tested set or raising the 0.84.2 floor.
- A CI matrix over Pi versions.
- Adopting Pi 1.4/1.5 features (`PI_CODEMODE_MAX_WORKERS`, `collapseChangelog`, `pi-schema`
  schemas).
- The setup script, which CR-SLP-005 retires.
