# SPDX-License-Identifier: MIT
"""The configuration core of `sol-pi-axi setup <project dir>`: choose the values and write at
most `<project>/.pi/sol-pi.json`."""

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .config import (
    DEFAULT_CACHE_WRITE_READ_RATIO,
    DEFAULT_REDUCER_MODEL,
    DEFAULT_REDUCER_PROVIDER,
    FEATURE_KEYS,
    KEY_ORDER,
    ConfigError,
    pi_default_route,
    project_config_path,
    read_config,
    render_config,
)
from .write import RenameHook, WriteHook, write_file

_PROVIDER = "evidencePreservingReducerProvider"
_MODEL = "evidencePreservingReducerModel"
_RATIO = "cacheWriteReadRatio"


@dataclass(frozen=True)
class SetupResult:
    """A successful run: `outcome` is `"written"` or `"unchanged"`; `config` holds the eight
    effective values in the written form's order."""

    outcome: str
    path: Path
    config: dict
    warnings: list[str] = field(default_factory=list)


def _project_dir(project_dir: str | os.PathLike[str]) -> Path:
    project = Path(os.path.abspath(project_dir))
    if not project.exists():
        raise ConfigError(f"project directory does not exist: {project}")
    if not project.is_dir():
        raise ConfigError(f"project path is not a directory: {project}")
    return project


def _base_values(target: Path, agent_directory: Path) -> tuple[dict | None, bool]:
    """`(values, from_file)`: a valid project file's effective values, else the agent file's;
    `(None, False)` when neither exists (the setup defaults apply)."""
    if os.path.lexists(target):
        if target.is_dir():
            raise ConfigError(f"sol-pi.json is a directory: {target}")
        return read_config(target), True
    agent_file = agent_directory / "sol-pi.json"
    if os.path.lexists(agent_file):
        return read_config(agent_file), False
    return None, False


def _setup_defaults(enabled: set[str], reducer: tuple[str, str] | None,
                    agent_directory: Path, *, route_optional: bool = False) -> dict:
    """The setup defaults for the enabled mechanisms: the reducer on `reducer`, else on Pi's
    default route when enabled, else on the built-in route. An enabled reducer with no route
    raises `ConfigError` naming `--reducer`, or with `route_optional` leaves the route None."""
    if reducer is not None:
        provider, model = reducer
    elif "evidencePreservingReducer" in enabled:
        route = pi_default_route(agent_directory)
        if route is None and route_optional:
            route = (None, None)
        if route is None:
            raise ConfigError(
                f"the reducer is enabled but {agent_directory / 'settings.json'} names no default "
                "provider and model; give the route with --reducer <provider>/<model>",
                flag="--reducer")
        provider, model = route
    else:
        provider, model = DEFAULT_REDUCER_PROVIDER, DEFAULT_REDUCER_MODEL
    values: dict = {"version": 1, _PROVIDER: provider, _MODEL: model,
                    _RATIO: DEFAULT_CACHE_WRITE_READ_RATIO}
    values.update({key: key in enabled for key in FEATURE_KEYS})
    return {key: values[key] for key in KEY_ORDER}


def default_values(agent_dir: str | os.PathLike[str], *, features: Iterable[str] | None = None,
                   reducer: tuple[str, str] | None = None,
                   cache_ratio: float | None = None, route_optional: bool = False) -> dict:
    """The setup defaults after the given values, as `run_setup` writes them when no
    configuration exists: `features` the enabled mechanisms (`None`: all four), `reducer`
    `(provider, model)` (`None`: Pi's default route when the reducer is enabled), `cache_ratio`
    the cache write/read ratio. Raises `ConfigError` naming `--reducer` when the reducer is
    enabled with no route, unless `route_optional`, which leaves the route None for a prompt
    to ask."""
    enabled: set[str] = set(FEATURE_KEYS if features is None else features)
    values = _setup_defaults(enabled, reducer, Path(agent_dir), route_optional=route_optional)
    if cache_ratio is not None:
        values[_RATIO] = float(cache_ratio)
    return values


def run_setup(project_dir: str | os.PathLike[str], *, agent_dir: str | os.PathLike[str] | None = None,
              features: Iterable[str] | None = None, reducer: tuple[str, str] | None = None,
              cache_ratio: float | None = None, hook: WriteHook | None = None,
              on_rename: RenameHook | None = None,
              ask: Callable[[dict], dict] | None = None) -> SetupResult:
    """Write `<project>/.pi/sol-pi.json` from its base values and the given values.

    `features` names the enabled mechanisms (the others off), `reducer` is `(provider, model)`,
    `cache_ratio` the cache write/read ratio; `None` leaves each as the base values have it. A
    valid project file with no value given is left untouched. `hook` is the writing module's
    test-only hook; `on_rename` its callback right after the rename, run with the signals
    blocked (the command line disarms its signal handlers there). A failure raises `ConfigError` naming the path and changes nothing; a `.pi/`
    the run created is removed when it fails.

    `ask`, when given, turns the values into the confirmed ones before anything is written (the
    `--interactive` prompts): it runs after every check, with the reducer route None when the
    reducer is enabled with no route; values equal to a valid project file's are `unchanged`."""
    project = _project_dir(project_dir)
    agent_directory = Path(agent_dir) if agent_dir is not None else config.agent_dir()
    pi_dir = project / ".pi"
    if os.path.lexists(pi_dir) and not pi_dir.is_dir():
        raise ConfigError(f".pi is not a directory: {pi_dir}")
    target = project_config_path(project)
    backup = pi_dir / "sol-pi.json.bak"
    warnings = ([f"a leftover {backup} was left untouched"] if os.path.lexists(backup) else [])

    base, from_project = _base_values(target, agent_directory)
    flagged = features is not None or reducer is not None or cache_ratio is not None
    if base is not None and from_project and not flagged and ask is None:
        return SetupResult("unchanged", target, base, warnings)

    enabled = set(features) if features is not None else None
    if base is None:
        values = _setup_defaults(set(FEATURE_KEYS) if enabled is None else enabled, reducer,
                                 agent_directory, route_optional=ask is not None)
    else:
        values = dict(base)
        if enabled is not None:
            values.update({key: key in enabled for key in FEATURE_KEYS})
        if reducer is not None:
            values[_PROVIDER], values[_MODEL] = reducer
    if cache_ratio is not None:
        values[_RATIO] = float(cache_ratio)
    if ask is not None:
        values = ask(values)
        if base is not None and from_project and values == base:
            return SetupResult("unchanged", target, base, warnings)

    created = not os.path.lexists(pi_dir)
    try:
        if created:
            try:
                pi_dir.mkdir()
            except OSError as error:
                raise ConfigError(f"cannot create {pi_dir}: {error.strerror or error}") from None
        try:
            outcome = write_file(target, render_config(values), hook=hook, on_rename=on_rename)
        except OSError as error:
            raise ConfigError(f"cannot write {target} in {pi_dir}: {error.strerror or error}") from None
    except BaseException:
        # A `.pi/` the run created is removed only while it holds no written file.
        if created and not os.path.lexists(target):
            pi_dir.rmdir()
        raise
    return SetupResult(outcome, target, values, warnings)
