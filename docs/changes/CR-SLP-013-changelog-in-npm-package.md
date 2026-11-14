# CR-SLP-013 — Ship CHANGELOG.md in the npm package

**Status:** DRAFT · Pre-review: none — no trigger
**Type:** defect
**Priority:** P2 — after an update from npm, Pi shows no update notes for SoL-Pi
**Depends on:** none
**Labels:** packaging, changelog, docs
**Phase:** 0.1.2 · wave 1
**Design reference:** `docs/compatibility.md` (`## Pi 1.4 and 1.5`, the extension update changelogs
row); CR-SLP-002 §S3; CR-SLP-007 §S1

## Context

Since Pi 1.5.0, on the first fresh launch after a package update, Pi shows the entries of the
package's `CHANGELOG.md` that are newer than the version it last saw, under "Extension Updates"
(`getExtensionChangelogUpdates` in Pi's interactive mode). It reads `CHANGELOG.md` at the package
root unless `pi.changelogPath` says otherwise, and shows nothing when the file is missing.

CR-SLP-002 checked that SoL-Pi's `CHANGELOG.md` headings match Pi's rule, with tests that run Pi's
own step on a package built from the checkout (`tests/pi-1-5-changes.test.ts`, "Pi 1.5.0 extension
update changelogs"). The npm package never carries the file:

- `package.json` `files` does not list `CHANGELOG.md`, and npm adds a changelog to a package only
  when `files` names it.
- Measured 2026-11-14: the published `@anthill-tec/sol-pi@0.1.1` tarball holds no `CHANGELOG.md`.
- So a customer who upgraded from 0.1.0 to 0.1.1 saw no update notes, and the 0.1.1 notes asked
  them to drop a workaround. `docs/compatibility.md` already records the gap ("the npm package does
  not include `CHANGELOG.md` yet").
- CR-SLP-007 pinned the package's file list in `tests/package.test.ts`: `BASE_FILES` (the `files`
  field) and `BASE_PACKED_FILES` (what `bun pm pack --dry-run` lists). Those two tests have to
  change with the fix.

## Scope

### §S1 — The npm package carries CHANGELOG.md

**Surfaces:** `package.json`, `tests/package.test.ts`.

- `package.json` `files` lists `CHANGELOG.md`. No other entry changes, and `pi.changelogPath` stays
  unset, so Pi reads the file at the package root.
- The file-list tests expect `CHANGELOG.md` in `files` and in the packed files, and nothing else
  new.
- A test packs the checkout as the release workflow does, unpacks the tarball, and runs Pi's own
  changelog step on the unpacked package, as the CR-SLP-002 tests do on a copied checkout. With a
  last-seen version older than the package's, it expects the update to hold exactly the package
  version's section of the shipped `CHANGELOG.md`.

### §S2 — Documentation and changelog

**Surfaces:** `docs/compatibility.md`, `CHANGELOG.md`.

- The extension update changelogs row of `docs/compatibility.md` says the npm package carries
  `CHANGELOG.md` and names the §S1 test; the "does not include `CHANGELOG.md` yet" text goes.
- `CHANGELOG.md` `[Unreleased]` records the fix.

## Acceptance criteria

- [ ] **§S1** `package.json` `files` is CR-SLP-007's list plus `CHANGELOG.md`, and `pi` is
      unchanged (no `changelogPath`).
- [ ] **§S1** `tests/package.test.ts` expects `CHANGELOG.md` in `files` and in the
      `bun pm pack --dry-run` list; every other packed file is unchanged.
- [ ] **§S1** A test packs the checkout, unpacks it, and runs Pi's changelog step on the unpacked
      package with a last-seen version below the package's version. The update it gets holds the
      heading and entries of the package version's `CHANGELOG.md` section, and no `[Unreleased]`
      entry. It fails while `files` lacks `CHANGELOG.md`.
- [ ] **§S2** `docs/compatibility.md` no longer says the npm package lacks `CHANGELOG.md`, and its
      extension update changelogs row names the §S1 test.
- [ ] **§S2** `CHANGELOG.md` `[Unreleased]` has a Fixed entry: Pi now shows SoL-Pi's update notes
      after an upgrade from npm.
- [ ] **Gate** `pre-merge-gate` passes on both stacks.

## Estimated size

2 points.

## Risks

- The §S1 test packs the checkout on each run, as the existing pack test does, which adds a few
  seconds to the suite.
- Between releases the package version has no section in `CHANGELOG.md` (its entries sit under
  `[Unreleased]`). The §S1 test therefore builds its expectation from the section the release
  workflow's own `changelog_section.py` extracts for the version, and checks that one exists, as
  `tests/install-guide.test.ts` already requires.
- Pi shows the notes only on an interactive fresh launch, not in print or RPC mode; that is Pi's
  behaviour, unchanged here.

## Non-goals

- A `pi.changelogPath` or a changelog kept outside the package root.
- Shipping `CHANGELOG.md` in the PyPI package `sol-pi-axi`.
- Changing the changelog's format or its headings, which CR-SLP-002 settled.
- Showing release notes outside Pi (the GitHub release already carries them).
