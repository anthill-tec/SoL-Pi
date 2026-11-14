# Contributing

We welcome external pull requests that improve token efficiency and reduce token cost through Pi-compatible extensions.

## Pull Request Requirements

Your PR should:

- Implement a Pi-compatible extension using Pi's public extension APIs, without modifying Pi's core.
- Be tested before submission, with relevant automated tests and reproducible validation steps.
- Clearly explain how the extension reduces token cost or improves token efficiency, including local measurements where available.
- Document its configuration, expected behavior, and any trade-offs. Efficiency improvements will be evaluated alongside correctness and task performance.

## Installing from a Checkout for Development

Users install SoL-Pi from the registries (see the README). To work on SoL-Pi itself, install from a checkout instead. From the checkout, install the locked dependencies and validate the checkout: `bun run check` runs the typecheck and the tests, and `bun audit --audit-level=high` checks the locked dependencies for high and critical advisories:

```bash
bun install --frozen-lockfile --ignore-scripts
bun run check
bun audit --audit-level=high
```

The `sol-pi-axi` tests need Python 3.14 and run against an editable install of the checkout:

```bash
python -m pip install -e ".[dev]"
PI_BIN=node_modules/.bin/pi python -m unittest discover -s tests -t .
```

Then register the checkout with Pi, user-wide or, from a trusted project, project-locally:

```bash
pi install "/absolute/path/to/SoL-Pi" --approve
pi install "/absolute/path/to/SoL-Pi" --local --approve
```

Install the `sol-pi-axi` command from the checkout in editable mode with `uv tool install --editable "/absolute/path/to/SoL-Pi"`. Remove any registry install of SoL-Pi first (`sol-pi-axi uninstall`), so that Pi registers one SoL-Pi source.

If you also have SoL-Pi installed user-wide from npm, a project that registers the checkout loads both copies. Add this entry to the project's `.pi/settings.json` `packages` to turn the user-level copy off for that project:

```json
{ "source": "npm:@anthill-tec/sol-pi", "autoload": false, "extensions": ["-src/sol-pi/index.ts"] }
```

Remove the entry when no user-level SoL-Pi is installed, for example after `sol-pi-axi uninstall`: Pi then treats it as an ordinary project package and tries to install it into the project. The [compatibility document](https://github.com/anthill-tec/SoL-Pi/blob/main/docs/compatibility.md#pi-151-and-152) gives the reason under package identity.

## Publishing a Release

A release publishes two packages that share one version: the `sol-pi-axi` command to PyPI and the Pi extension `@anthill-tec/sol-pi` to npm. `.github/workflows/release.yml` runs the Bun and the Python tests on every run and gates every publish on them:

- a `release/**` or `hotfix/**` push rehearses: it stamps a dev version, publishes `sol-pi-axi` to TestPyPI and dry-runs the npm publish;
- a `main` push creates the GitHub Release for the version tag at HEAD, after checking that the tag matches both version sources (`pyproject`'s and `package.json`'s);
- the published release publishes `sol-pi-axi` to PyPI and `@anthill-tec/sol-pi` to npm, each guarded to a version tag on `main`'s history.

### One-time setup

Before the first release branch's rehearsal:

- the repository secret `RELEASE_PAT`: a fine-grained token for this repository only, Contents read/write;
- the GitHub environments `pypi` and `npm`, which admit the version tags (the release event's ref is the tag), and `testpypi`, which admits the `release/**` and `hotfix/**` branches and carries no required reviewers;
- pending trusted publishers for `sol-pi-axi` on pypi.org and test.pypi.org, for this repository's `release.yml` and the environments `pypi` and `testpypi`;
- the repository secret `NPM_TOKEN` for the first npm publish of `@anthill-tec/sol-pi`; then add the npm trusted publisher for `release.yml` and delete the token.

### Re-rendering the Release Workflow

`release.yml` is the `modelb-axi release-workflow` rendering for the Bun and Python stacks and the `pypi,npm` targets, plus a fixed set of hand edits (`main` for `master`, the pinned Bun 1.4.4 and test timeout, Node 22 for both test jobs, and the Python job's project, Bun and `PI_BIN` setup). The rendering is committed verbatim as `tests/fixtures/release-workflow/rendered.yml`, and `tests/release-workflow.test.ts` checks that `release.yml` differs from it by exactly those edits. To take a new rendering, render in a scratch copy of the repository with `modelb-axi release-workflow`, copy the result over `tests/fixtures/release-workflow/rendered.yml`, re-apply the hand edits to `release.yml`, and run the tests. Run in place, `modelb-axi release-workflow` skips the hand-modified `release.yml`; with `--force-managed` it overwrites the file and drops the hand edits.

## Benchmarking and Reports

Our team will help benchmark submitted extensions to evaluate token usage, model cost, and task performance.

We will publish updated benchmark reports on a regular reporting cycle, sharing evaluated changes, results, and any observed trade-offs.

## Contributor Recognition

Authors of accepted PRs will be credited as Contributors in the project documentation and the relevant benchmark reports.
