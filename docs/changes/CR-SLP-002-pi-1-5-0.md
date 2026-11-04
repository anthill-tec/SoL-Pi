# CR-SLP-002 — Support Pi 1.5.0; clear the `undici` advisories

**Status:** PENDING · Pre-review: due — touches another project's surface (Model B's setup step runs the strict Pi compatibility check, message #1516 item 5)
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
  `setup-sol-pi.fish` runs the check with `--strict`, so it stops on Pi 1.5.0 (#1516 item 5).
- `bun audit --audit-level=high` reports four high advisories against `undici` 8.10.2
  (GHSA-xjj6-f33q-929c, GHSA-4w7w-5xrc-9h26, GHSA-2m5v-pch6-74hx, GHSA-qrxm-fqhp-jwvm; affected
  `>=8.0.0 <8.12.2`), reached through the Pi 1.3.0 development dependency
  (`pi-coding-agent > undici` and `pi-ai > openai > undici`). Pi 1.5.0 depends on `undici` 8.12.3.
- Pi 1.4.0 and 1.5.0 list one breaking change: tool argument validation moves to
  `@earendil-works/pi-schema`, and TypeBox features outside JSON Schema (`Type.Refine()`,
  `Type.BigInt()`, `Type.Undefined()`, codecs, `Format.Set()`) no longer apply. SoL-Pi's tool
  schemas use none of them. Pi 1.4.0 also queues codemode scripts for a free worker instead of
  failing at the worker limit.

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
  place of 1.3.0. Pi 1.5.0 pins its internal packages (`pi-agent-core`, `pi-ai`, `pi-codemode`,
  `pi-mcp`, `pi-tui`) exactly, so a fresh install passes that rule unchanged.
- The full suite runs on the 1.5.0 development dependency. A test that fails because of a Pi 1.4
  or 1.5 change is fixed at the cause: a cause in SoL-Pi's code is fixed there with a test that
  fails before the fix, and every such behaviour difference is recorded in
  `docs/compatibility.md`. No test is skipped or loosened to pass.

### §S3 — Documentation names Pi 1.5.0

**Surfaces:** `README.md`, `agents-install.md`, `docs/compatibility.md`, `THIRD_PARTY_NOTICES.md`,
`CHANGELOG.md`.

- Pi 1.5.0 is the latest tested release and the documented default install; 1.3.0, 1.0.4 and
  0.84.2 stay listed as tested.
- `THIRD_PARTY_NOTICES.md` lists the Pi packages at 1.5.0.
- `CHANGELOG.md` `[Unreleased]` records Pi 1.5.0 support and the `undici` fix.

## Acceptance criteria

- [ ] **§S1** `package.json` `devDependencies` has the four Pi packages at exactly `1.5.0`;
      `peerDependencies` is unchanged.
- [ ] **§S1** `bun audit --audit-level=high` exits 0.
- [ ] **§S2** `bun scripts/check-pi-compat.mjs --strict` prints `Pi compatibility: OK` with no
      warning and exits 0 against the development dependency, and against a Bun global install of
      Pi 1.5.0 (`--pi-root "$HOME/.bun/install/global/node_modules"`).
- [ ] **§S2** A `tests/package.test.ts` case runs the check with `--strict` against a fake Pi 1.5.0
      whose internal packages are 1.5.0 and expects exit 0 with no warning; the existing cases for
      untested versions and mixed internal versions keep passing.
- [ ] **§S2** The bun client's `regression` on the 1.5.0 development dependency passes every test,
      runs every test CR-SLP-001's fidelity criteria name, and adds no skip.
- [ ] **§S2** Each Pi 1.4/1.5 behaviour difference found in §S2 has a failing-first test and an
      entry in `docs/compatibility.md` (none is a valid outcome, stated in the CR's close-out).
- [ ] **§S3** `tests/install-guide.test.ts` passes, and README, `agents-install.md` and
      `docs/compatibility.md` each name the four tested versions.
- [ ] **§S3** `CHANGELOG.md` `[Unreleased]` has an entry for Pi 1.5.0 support and one for the
      `undici` advisories.
- [ ] **Gate** `pre-merge-gate` passes.

## Estimated size

3 points. The version bump and docs are mechanical; the uncertainty is what the suite finds on
Pi 1.5.0.

## Risks

- The suite runs on one Pi version at a time. Claims for 1.3.0, 1.0.4 and 0.84.2 rest on earlier
  runs; this CR does not re-run them.
- A Pi 1.5.0 difference that needs a design change in a mechanism becomes its own CR.

## Non-goals

- Dropping a version from the tested set or raising the 0.84.2 floor.
- A CI matrix over Pi versions.
- Adopting Pi 1.4/1.5 features (`PI_CODEMODE_MAX_WORKERS`, `pi-schema`, extension changelogs).
