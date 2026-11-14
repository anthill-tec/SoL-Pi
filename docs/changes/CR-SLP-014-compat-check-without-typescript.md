# CR-SLP-014 — Pi compatibility check without the TypeScript compiler API; TypeScript 7

**Status:** PENDING · Pre-review: ran — touches another project's surface (Model B's setup runs `check-pi-compat.mjs --strict`)
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
- The type check is the setting's enforcement: the pre-merge gate and `bun run check` run it. CI
  runs no type check today, for any type error, and this CR does not add one (Mainline's scoping
  call, reported to the user).

### §S2 — The compatibility check reads runtime imports without TypeScript

**Surfaces:** `scripts/check-pi-compat.mjs`, `tests/package.test.ts`.

- The script loads no TypeScript and transpiles nothing. It collects, from every `.ts` file under
  `src/`, the names imported from `@earendil-works/*` by import statements that are not
  `import type`, leaving out each name marked `type` inside the braces. A name imported
  `as` another keeps the exported name, as now. Braces may span several lines.
- Forms the script does not check, as today: a namespace import (`import * as pi from …`; today
  `online-context-compact/projection.ts` reaches `buildSessionProjection` that way, through a
  cast), a default import, and `export … from`. The header comment says so.
- Comments are removed before the imports are read, so an import written inside a comment is not
  checked. No Pi import appears in a comment or string in `src/` today.
- On today's `src/` the script collects exactly the names the TypeScript 6.0.3 transpile collects
  (measured at the pre-review: nine from `pi-coding-agent`, `complete` from `pi-ai/compat`,
  `Container` and `Text` from `pi-tui`).
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
- [ ] **§S1** A test writes a temporary fixture inside the repository tree but outside
      `tsconfig.json`'s `include` globs (so `bun run typecheck` never sees it), with a temporary
      config that extends the repository's `tsconfig.json` and includes only the fixture. The
      fixture imports a Pi type without `type`. The test runs the repository's `tsc --noEmit -p`
      on that config and expects exactly one diagnostic, TS1484; the same fixture written with
      `import type` gives none. The fixture and config are removed afterwards.
- [ ] **§S2** `scripts/check-pi-compat.mjs` contains no `from "typescript"`, no
      `require("typescript")`, no `createRequire(…)("typescript")` and no `transpileModule(`.
- [ ] **§S2** The existing test "checks only the Pi imports that survive TypeScript import
      elision" is rewritten for the new rule and passes, with one fixture file per form and its
      expected result:
      - `import type { … }`, on one line and over several lines: not checked;
      - braces over several lines mixing `type` names and value names: only the value names
        checked;
      - `import { complete as completeCompat } from "@earendil-works/pi-ai/compat"`: `complete`
        checked against the compat entrypoint;
      - `import * as pi from …`, a default import, and `export { x } from …`: not checked;
      - an import inside a comment: not checked;
      - a missing name imported without `type`: the check fails and names it.
- [ ] **§S2** A test builds a fake checkout with no `node_modules` of its own, under a temporary
      root with no `node_modules` above it, asserts that `typescript` does not resolve from it,
      and runs the script there with `--strict --pi-root` pointing at a fake Pi at a tested
      version. It expects exit 0 and no warning.
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

- **The rule reads text, not syntax.** A future import form not in the §S2 list could escape it.
  The §S2 tests pin the forms the source uses today; a new form needs a test with it.
- **A type imported without `type` passes CI.** Only the gate and `bun run check` type-check. The
  script would then report it as a missing Pi export, unless a runtime export has the same name.
- **Crucible and TypeScript 7 diagnostics.** `bun-crucible.py check` ingests the type checker's
  output; whether Crucible 0.3.0 parses TypeScript 7's diagnostics (which add "The file is in the
  program because:" lines) is unchecked. GREEN runs `check` with a deliberate type error once and
  reports what the board shows; a parsing gap is reported to Crucible, not fixed here.
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
