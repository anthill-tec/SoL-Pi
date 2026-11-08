# SPDX-License-Identifier: MIT
"""Registering the SoL-Pi extension with Pi: the tested Pi versions, the release's npm source,
recognising SoL-Pi sources in Pi's user `settings.json`, and running `pi install`, `pi remove`
and `pi --version` (from the user's home, with `--no-approve`, Pi's output on standard error).

Pi 1.5.0 stores an npm source as given and replaces an entry for the same package at any version
in place; it stores a local path relative to the agent directory, while `pi remove` resolves its
argument against the working directory, so a local path is passed to it absolute."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .config import ConfigError

#: The Pi versions SoL-Pi is tested against (`scripts/check-pi-compat.mjs`'s list).
TESTED_PI_VERSIONS = ("0.84.2", "1.0.4", "1.3.0", "1.5.0")
#: The npm package the extension ships as, and the unscoped name earlier checkouts carry.
NPM_PACKAGE = "@anthill-tec/sol-pi"
_EARLIER_NPM_PACKAGE = "sol-pi"
#: The repositories a git or URL source of SoL-Pi names (`owner/repo`, compared case-blind).
_REPOSITORIES = frozenset({"anthill-tec/sol-pi", "nvlabs/sol-pi"})
_NO_APPROVE = "--no-approve"
_RELEASE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class PiError(Exception):
    """A `pi` command could not run or failed, or Pi's record is not what it should be. `help`
    holds the steps that fix it."""

    def __init__(self, message: str, *, help_steps: list[str] | None = None):
        super().__init__(message)
        self.help = list(help_steps or [])


def release_source(version: str) -> str:
    """`npm:@anthill-tec/sol-pi@<version>`; `PiError` naming `version` when it is not `X.Y.Z`
    (a development build has no published package)."""
    if _RELEASE_VERSION.fullmatch(version) is None:
        raise PiError(f"sol-pi-axi {version} is not a release version (X.Y.Z), so no published "
                      f"{NPM_PACKAGE} matches it; register a checkout instead",
                      help_steps=["pi install <checkout path>"])
    return f"npm:{NPM_PACKAGE}@{version}"


def recorded_sources(agent_dir: Path) -> list[str]:
    """Every package source in `<agent dir>/settings.json` `packages`, as Pi recorded it (an
    object entry's `source`); empty when the file or the key is missing. `ConfigError` naming the
    file when it is not valid JSON or not an object."""
    path = agent_dir / "settings.json"
    if not os.path.lexists(path):
        return []
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError as error:
        raise ConfigError(f"unable to read {path}: {error.strerror or error}") from None
    try:
        settings = json.loads(text)
    except ValueError as error:
        raise ConfigError(f"invalid JSON in {path}: {error}") from None
    if not isinstance(settings, dict):
        raise ConfigError(f"Pi settings must be a JSON object: {path}")
    packages = settings.get("packages", [])
    if not isinstance(packages, list):
        return []
    sources = []
    for entry in packages:
        source = entry.get("source") if isinstance(entry, dict) else entry
        if isinstance(source, str):
            sources.append(source)
    return sources


def npm_package(source: str) -> str | None:
    """The package name of an `npm:` source (its version dropped), else None."""
    if not source.startswith("npm:"):
        return None
    spec = source[4:].strip()
    at = spec.find("@", 1)
    return spec if at == -1 else spec[:at]


def _repository(source: str) -> str | None:
    """`owner/repo` (lower-cased, `.git` dropped) of a git or URL source, else None."""
    if source.startswith("git:"):
        rest = source[4:]
    elif "://" in source:
        rest = source.split("://", 1)[1]
    elif source.startswith("git@"):
        rest = source
    else:
        return None
    if rest.startswith("git@"):
        rest = rest[4:].replace(":", "/", 1)
    rest = rest.split("#", 1)[0]
    _host, _, path = rest.partition("/")
    path = path.split("@", 1)[0].rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path.lower()


def _is_local(source: str) -> bool:
    return npm_package(source) is None and _repository(source) is None


def local_path(source: str, agent_dir: Path) -> Path:
    """A local source's absolute path, resolved against the agent directory as Pi stores it."""
    return Path(os.path.normpath(os.path.join(agent_dir, os.path.expanduser(source.strip()))))


def _local_package_name(path: Path) -> str | None:
    try:
        manifest = json.loads((path / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = manifest.get("name") if isinstance(manifest, dict) else None
    return name if isinstance(name, str) else None


def is_sol_pi(source: str, agent_dir: Path) -> bool:
    """Whether `source` is a SoL-Pi source: `npm:@anthill-tec/sol-pi` or `npm:sol-pi` at any
    version, a git or URL source naming `anthill-tec/SoL-Pi` or `NVlabs/SoL-Pi`, or a local path
    whose `package.json` is named `sol-pi` or `@anthill-tec/sol-pi`."""
    package = npm_package(source)
    if package is not None:
        return package in (NPM_PACKAGE, _EARLIER_NPM_PACKAGE)
    repository = _repository(source)
    if repository is not None:
        return repository in _REPOSITORIES
    return _local_package_name(local_path(source, agent_dir)) in (NPM_PACKAGE, _EARLIER_NPM_PACKAGE)


def removal_argument(source: str, agent_dir: Path) -> str:
    """The argument `pi remove` needs for a recorded source: a local path absolute."""
    return str(local_path(source, agent_dir)) if _is_local(source) else source


def find_pi() -> str:
    """`$PI_BIN` when set, else `pi` on `PATH`; `PiError` naming both when neither is found."""
    configured = os.environ.get("PI_BIN", "")
    if configured:
        return configured
    found = shutil.which("pi")
    if found is None:
        raise PiError("no pi command: $PI_BIN is not set and no pi is on PATH",
                      help_steps=["install Pi, or set PI_BIN to its pi command"])
    return found


class Pi:
    """One `pi` executable, run from the user's home with `--no-approve`."""

    def __init__(self, executable: str):
        self.executable = executable

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        try:
            return subprocess.run([self.executable, *args, _NO_APPROVE], cwd=Path.home(),
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  errors="replace", check=False)
        except OSError as error:
            raise PiError(f"cannot run {self.executable}: {error.strerror or error}") from None

    def version(self) -> str:
        """`pi --version`'s output, stripped."""
        result = self._run(["--version"])
        if result.returncode != 0:
            _forward(result)
            raise PiError(f"pi --version exited {result.returncode}")
        return result.stdout.strip()

    def install(self, source: str) -> None:
        self._change("install", source)

    def remove(self, source: str) -> None:
        self._change("remove", source)

    def _change(self, command: str, source: str) -> None:
        result = self._run([command, source])
        _forward(result)
        if result.returncode != 0:
            raise PiError(f"pi {command} {source} exited {result.returncode} (Pi's output is on "
                          "standard error)")


def _forward(result: subprocess.CompletedProcess) -> None:
    """Pi's output, both streams, onto standard error: standard output holds only the envelope."""
    for text in (result.stdout, result.stderr):
        if text:
            sys.stderr.write(text if text.endswith("\n") else text + "\n")
    sys.stderr.flush()
