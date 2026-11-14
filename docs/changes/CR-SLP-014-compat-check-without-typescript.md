# CR-SLP-014 — Pi compatibility check without the TypeScript compiler API; TypeScript 7

**Status:** DRAFT · Pre-review: due — touches another project's surface (Model B's setup runs `check-pi-compat.mjs --strict`)
**Type:** maintenance
**Priority:** P2 — blocks the TypeScript 7 upgrade; the strict check fails on a tested Pi when the checkout's dependencies are not installed
**Depends on:** CR-SLP-012 (both edit `scripts/check-pi-compat.mjs`)
**Labels:** compatibility, tooling, dependencies
**Phase:** 0.1.2 · wave 1
**Design reference:** `docs/compatibility.md` (`## Checking an installed Pi`)

## Context

`scripts/check-pi-compat.mjs` checks that every Pi export SoL-Pi imports at runtime exists in the
Pi under test. An import that names only types does not exist at runtime: Pi's extension loader
(jiti) drops it, and the script must not report it as missing. `tsconfig.json` does not set
`verbatimModuleSyntax`, so a type can be imported without `type`
(`import { ExtensionAPI } from …`). To tell such names apart, the script transpiles each source
file with the checkout's TypeScript compiler API (`ts.transpileModule` in `piValueImports`) and
reads the imports that survive.

This blocks two things:

- **TypeScript 7.** TypeScript 7.0.2 is the current `latest` on npm. Its package no longer exports
  the JavaScript compiler API (its root export is `lib/version.cjs`; the rest is under
  `./unstable/*`), so the script cannot load it. The 2026-11-11 dependency chore therefore kept
  TypeScript 6.0.3.
- **Checking without the checkout's dependencies.** Without `bun install` the script cannot load
  TypeScript, checks every imported name as a runtime value, and warns, so `--strict` fails even on
  a tested Pi. `README.md` and `docs/compatibility.md` document this limitation.

Measured 2026-11-14 on a scratch copy of `develop` at `0b1e6e2`:

- With `verbatimModuleSyntax: true` added to `tsconfig.json`, both TypeScript 6.0.3 and 7.0.2
  type-check `src/` and `tests/` with no error: every type-only import already carries `type`.
- With the setting on, a file that imports a type without `type` fails the type check with
  TS1484, so the setting keeps the source in that form.
- TypeScript 7.0.2's `tsc --noEmit` passes on the unchanged `tsconfig.json` too. Its package
  installs a native compiler through a per-platform optional dependency
  (`@typescript/typescript-linux-x64` here).
- Pi's loader drops a type-only named import whichever form it is written in (checked with jiti's
  `transform`).

Options for the script (recommendation first):

1. **`verbatimModuleSyntax` in `tsconfig.json`; the script reads imports from the source as
   written.** With the setting, a name imported without `type` is a runtime import, and the type
   check rejects any other form. The script needs no transpiler, so it runs the same with or
   without `bun install`, under Bun or Node. It already skips names marked `type`; it must also
   skip `import type { … }` statements.
2. Transpile with Pi's own loader (jiti's `transform`, resolved from the Pi under test). It mirrors
   Pi exactly, but its output is CommonJS, so the script would have to read property accesses on
   `require` results instead of import lists, and it depends on a Pi internal.
3. Bun's transpiler with `trimUnusedImports`. Bun only; the script also runs under Node
   (`tests/install-guide.test.ts`).
4. Node's `stripTypeScriptTypes`. It removes type syntax but keeps a type-only named import, so it
   needs option 1 anyway, and it is experimental in Node 22.

## Scope

### §S1 — Type-only imports are marked in the source

**Surfaces:** `tsconfig.json`.

- `tsconfig.json` sets `verbatimModuleSyntax: true`. The type check of `src/` and `tests/` passes
  with no source change.

### §S2 — The compatibility check reads runtime imports without TypeScript

**Surfaces:** `scripts/check-pi-compat.mjs`, `tests/package.test.ts`.

- The script loads no TypeScript and transpiles nothing. It collects, from every `.ts` file under
  `src/`, the names imported from `@earendil-works/*` by import statements that are not
  `import type`, leaving out each name marked `type` inside the braces. A name imported
  `as` another keeps the exported name, as now.
- The "typescript is not installed" warning is gone, so `--strict` passes on a tested Pi whether or
  not the checkout's dependencies are installed, provided the Pi under test resolves.
- Every other check is unchanged: the version policy, the mixed-internal-packages check, the method
  checks, the bash and codemode probes, and the exit codes.
- The script's header comment describes the new rule.

### §S3 — TypeScript 7

**Surfaces:** `package.json`, `bun.lock`, `THIRD_PARTY_NOTICES.md`.

- The `typescript` development dependency is exactly `7.0.2`; `typecheck` stays `tsc --noEmit`.
- `bun.lock` records TypeScript 7.0.2 and its platform packages, and `bun install
  --frozen-lockfile` passes on Linux, where CI runs.
- `THIRD_PARTY_NOTICES.md` still lists TypeScript as a development tool under Apache-2.0.

### §S4 — Documentation and changelog

**Surfaces:** `README.md`, `docs/compatibility.md`, `CONTRIBUTING.md`, `CHANGELOG.md`.

- `README.md` and `docs/compatibility.md` no longer say the check needs the checkout's TypeScript
  or fails under `--strict` without `bun install`. They say what the check still needs: the Pi under
  test, found through `--pi-root` or the checkout's development dependency.
- `CONTRIBUTING.md` says a type-only import is written with `type`, which the type check enforces.
- `CHANGELOG.md` `[Unreleased]` records that the compatibility check no longer needs the checkout's
  dependencies installed.

## Acceptance criteria

- [ ] **§S1** `tsconfig.json` has `verbatimModuleSyntax: true`, and `bun run typecheck` passes.
- [ ] **§S1** A test type-checks a fixture file that imports a Pi type without `type` under the
      repository's `tsconfig.json` settings and expects error TS1484.
- [ ] **§S2** `scripts/check-pi-compat.mjs` contains no `typescript` import, `require` or
      `transpileModule`.
- [ ] **§S2** The existing test "checks only the Pi imports that survive TypeScript import
      elision" is rewritten for the new rule and passes: names in `import type { … }` and names
      marked `type` inside braces are not checked; a missing name imported without `type` fails the
      check and is named in the output.
- [ ] **§S2** A test runs the script with `--strict` from a fake checkout with no `typescript`
      package resolvable, against a fake Pi at a tested version, and expects exit 0 with no
      warning.
- [ ] **§S2** The existing script tests (version policy, mixed internal packages, method checks,
      bash and codemode reporting) pass unchanged in what they expect.
- [ ] **§S3** `package.json` `devDependencies.typescript` is `7.0.2`; `bun.lock` resolves it;
      `bun run check` passes.
- [ ] **§S4** `README.md` and `docs/compatibility.md` no longer describe the TypeScript-dependent
      warning; `CONTRIBUTING.md` states the `type` rule; `CHANGELOG.md` `[Unreleased]` has the
      entry.
- [ ] **Gate** `pre-merge-gate` passes on both stacks, under TypeScript 7.0.2.

## Estimated size

3 points.

## Risks

- **The rule reads text, not syntax.** A future import written over several lines with comments,
  or a re-export (`export { x } from "@earendil-works/…"`), could escape the regular expression.
  The §S2 tests pin the forms the source uses today; a new form needs a test with it.
- **TypeScript 7 is a native compiler.** It installs per platform through optional dependencies.
  A platform without a native package cannot type-check. Pi and the npm package are unaffected:
  TypeScript is a development tool only.
- **TypeScript 7 type-checks differently from 6 in places.** The measured run passed; a later
  difference shows up in the gate and is fixed in this CR.
- An extension source that Pi loads but `src/` does not hold (none today) would not be checked, as
  now.

## Non-goals

- Changing what the script checks besides the import rule.
- Moving the script into the npm package.
- Using TypeScript 7's `unstable` APIs.
- Re-checking older Pi versions under TypeScript 7; the gate runs on the development dependency.
