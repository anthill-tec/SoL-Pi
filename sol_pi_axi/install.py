# SPDX-License-Identifier: MIT
"""The cores of `sol-pi-axi install` and `uninstall`: register the extension's release source
user-wide with Pi, replace earlier SoL-Pi sources, write an absent `<agent dir>/sol-pi.json` with
the setup defaults; and remove every SoL-Pi source again.

Each run fills in a report as it goes, so a failure or a cancel reports the state it left."""

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .config import ConfigError, read_config, render_config
from .pi import (
    NPM_PACKAGE,
    TESTED_PI_VERSIONS,
    Pi,
    PiError,
    find_pi,
    is_sol_pi,
    npm_package,
    recorded_sources,
    release_source,
    removal_argument,
)
from .setup import default_values
from .write import RenameHook, write_file


@dataclass
class InstallReport:
    """What an install run did so far. `config_state` is `written` or `kept`; `config_values`
    the agent file's effective values (None while unresolved, or when the kept file is
    invalid)."""

    agent_dir: Path
    outcome: str = "failed"
    source: str | None = None
    registered: bool = False
    replaced: list[str] = field(default_factory=list)
    pi_version: str | None = None
    config_path: Path | None = None
    config_state: str | None = None
    config_values: dict | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class UninstallReport:
    """What an uninstall run removed so far, each source as Pi recorded it."""

    agent_dir: Path
    outcome: str = "failed"
    removed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _settings_path(agent_dir: Path) -> Path:
    return agent_dir / "settings.json"


def _resolve_config(report: InstallReport, *, features: Iterable[str] | None,
                    reducer: tuple[str, str] | None, cache_ratio: float | None) -> dict | None:
    """The values to write when the agent file is absent, else None (the file is kept; an invalid
    one and any value flag are named in `warnings`)."""
    path = report.agent_dir / "sol-pi.json"
    report.config_path = path
    if not os.path.lexists(path):
        return default_values(report.agent_dir, features=features, reducer=reducer,
                              cache_ratio=cache_ratio)
    report.config_state = "kept"
    try:
        report.config_values = read_config(path)
    except ConfigError as error:
        report.warnings.append(f"{path} is invalid and was left untouched: {error}")
    for flag, value in (("--features", features), ("--reducer", reducer),
                        ("--cache-ratio", cache_ratio)):
        if value is not None:
            report.warnings.append(f"{flag} was ignored: {path} exists and was left untouched")
    return None


def run_install(report: InstallReport, *, version: str, features: Iterable[str] | None = None,
                reducer: tuple[str, str] | None = None, cache_ratio: float | None = None,
                on_rename: RenameHook | None = None) -> None:
    """Register `npm:@anthill-tec/sol-pi@<version>` and write an absent agent file, filling in
    `report`. In order: the source, the configuration (no `pi` command runs before both are
    resolved), `pi --version`, `pi install` unless Pi already records exactly the source, Pi's
    record read again, `pi remove` for every other SoL-Pi source, then the agent file. Raises
    `PiError` or `ConfigError`; a failure before `pi install` changes nothing."""
    agent = report.agent_dir
    source = release_source(version)
    report.source = source
    values = _resolve_config(report, features=features, reducer=reducer, cache_ratio=cache_ratio)

    pi = Pi(find_pi())
    report.pi_version = pi.version()
    if report.pi_version not in TESTED_PI_VERSIONS:
        report.warnings.append(f"pi {report.pi_version} is not a tested Pi version "
                               f"({', '.join(TESTED_PI_VERSIONS)})")

    recorded = recorded_sources(agent)
    earlier = [entry for entry in recorded if entry != source and is_sol_pi(entry, agent)]
    changed = False
    if source in recorded:
        report.registered = True
    else:
        pi.install(source)
        recorded = recorded_sources(agent)
        if source not in recorded:
            raise PiError(f"pi install {source} exited 0, but {_settings_path(agent)} does not "
                          f"record it: Pi keeps its records outside the agent directory {agent}",
                          help_steps=["set PI_CODING_AGENT_DIR to the agent directory Pi uses"])
        report.registered = True
        changed = True
        # Pi replaced an entry for the same package at another version in place.
        for entry in earlier:
            if npm_package(entry) == NPM_PACKAGE and entry not in recorded:
                report.replaced.append(entry)
                report.warnings.append(f"replaced the earlier SoL-Pi source {entry} with {source}")

    for entry in earlier:
        if npm_package(entry) == NPM_PACKAGE:
            continue
        pi.remove(removal_argument(entry, agent))
        report.replaced.append(entry)
        report.warnings.append(f"removed the earlier SoL-Pi source {entry}, replaced by {source}")
        changed = True

    if values is not None and report.config_path is not None:
        try:
            state = write_file(report.config_path, render_config(values), on_rename=on_rename)
        except OSError as error:
            raise ConfigError(f"cannot write {report.config_path}: "
                              f"{error.strerror or error}") from None
        report.config_state = "written"
        report.config_values = values
        changed = changed or state == "written"
    report.outcome = "installed" if changed else "unchanged"


def registered_source(agent_dir: Path, version: str) -> str | None:
    """The SoL-Pi source Pi records: the own release source when recorded, else the first
    SoL-Pi source, else None."""
    recorded = recorded_sources(agent_dir)
    own = f"npm:{NPM_PACKAGE}@{version}"
    if own in recorded:
        return own
    return next((entry for entry in recorded if is_sol_pi(entry, agent_dir)), None)


def run_uninstall(report: UninstallReport) -> None:
    """Remove every SoL-Pi source Pi records with `pi remove` (no `pi` command when there is
    none), filling in `report`; deletes no configuration file. Raises `PiError` or
    `ConfigError`."""
    agent = report.agent_dir
    agent_file = agent / "sol-pi.json"
    if os.path.lexists(agent_file):
        report.warnings.append(f"{agent_file} was kept; delete it to remove SoL-Pi's agent "
                               "configuration")
    sources = [entry for entry in recorded_sources(agent) if is_sol_pi(entry, agent)]
    if not sources:
        report.outcome = "unchanged"
        return
    pi = Pi(find_pi())
    for entry in sources:
        pi.remove(removal_argument(entry, agent))
        report.removed.append(entry)
    report.outcome = "removed"
