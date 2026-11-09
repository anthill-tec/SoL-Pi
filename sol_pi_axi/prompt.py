# SPDX-License-Identifier: MIT
"""The prompts of `--interactive` (`setup` and `install`): when the run may prompt, the answers'
grammar, and a session that asks for the configuration values on the terminal.

Prompts are written to standard error by this module (never through `input()`) and answers read
from standard input, so standard output carries only the envelope. A cancel at a prompt raises
`PromptCancel`; a signal raises whatever the command's signal handler raises."""

import math
import os
import re

from .config import (
    DEFAULT_REDUCER_MODEL,
    DEFAULT_REDUCER_PROVIDER,
    FEATURE_KEYS,
    ConfigError,
    enabled_model_suggestions,
    valid_route_part,
)

_PROVIDER = "evidencePreservingReducerProvider"
_MODEL = "evidencePreservingReducerModel"
_RATIO = "cacheWriteReadRatio"
_STDIN = 0
_STDERR = 2


class PromptCancel(Exception):
    """A run cancelled at a prompt without a signal: `code` its exit code, `cause` the reason."""

    def __init__(self, cause: str, code: int):
        super().__init__(cause)
        self.cause = cause
        self.code = code


def parse_switch(answer: str) -> bool:
    """A mechanism or confirmation answer: `yes` is True, `no` False."""
    if answer == "yes":
        return True
    if answer == "no":
        return False
    raise ValueError(f"answer yes or no, got {answer!r}")


def parse_route(answer: str) -> tuple[str, str]:
    """A reducer answer, `--reducer`'s grammar: `(provider, model)` split at the first `/`."""
    provider, slash, model = answer.partition("/")
    if not slash or not valid_route_part(provider) or not valid_route_part(model):
        raise ValueError(f"answer <provider>/<model>, both non-empty without whitespace, "
                         f"got {answer!r}")
    return provider, model


def parse_ratio(answer: str) -> float:
    """A cache ratio answer, `--cache-ratio`'s grammar: digits with an optional decimal
    fraction."""
    if re.fullmatch(r"[0-9]+(\.[0-9]+)?", answer) is None or not math.isfinite(float(answer)):
        raise ValueError(f"answer digits with an optional decimal fraction, got {answer!r}")
    return float(answer)


def unavailable_reason(environ=None) -> str | None:
    """Why the run cannot prompt, or None when it can: standard input and standard error are
    terminals, the process group is the terminal's foreground group, and `PI_NONINTERACTIVE` is
    unset or empty."""
    environ = os.environ if environ is None else environ
    if environ.get("PI_NONINTERACTIVE", ""):
        return "PI_NONINTERACTIVE is set"
    if not os.isatty(_STDIN):
        return "standard input is not a terminal"
    if not os.isatty(_STDERR):
        return "standard error is not a terminal"
    try:
        foreground = os.tcgetpgrp(_STDIN)
    except OSError:
        return "the process group is not the terminal's foreground group (no controlling terminal)"
    if foreground != os.getpgrp():
        return "the process group is not the terminal's foreground group (it runs in the background)"
    return None


def unavailable_warning(reason: str) -> str:
    """The warning of a run given `--interactive` that does not prompt."""
    return f"--interactive did not prompt: {reason}; the run went on as without --interactive"


def _format_ratio(ratio: float) -> str:
    return str(int(ratio)) if float(ratio).is_integer() else repr(float(ratio))


class Session:
    """One run's prompts. `shown` holds the values the run has shown so far (`features`,
    `reducer`, `cacheRatio`, each None before its answer); `warnings` the suggestions' warnings;
    `hung_up` turns True when the terminal is closed, after which nothing more is written to it."""

    def __init__(self) -> None:
        self.shown: dict = {"features": None, "reducer": None, "cacheRatio": None}
        self.started = False
        self.confirmed = False
        self.hung_up = False
        self.warnings: list[str] = []

    # --- the terminal ----------------------------------------------------------------------

    def _hang_up(self) -> PromptCancel:
        self.hung_up = True
        return PromptCancel("cancelled: the terminal was closed (SIGHUP)", 129)

    def _write(self, text: str) -> None:
        if self.hung_up:
            return
        data = text.encode("utf-8", "replace")
        try:
            while data:
                data = data[os.write(_STDERR, data):]
        except OSError:
            raise self._hang_up() from None

    def _read_line(self) -> str:
        """One answer line without its line end. An empty read is Ctrl+D, or a closed terminal
        when writing to it then fails."""
        line = b""
        while not line.endswith(b"\n"):
            try:
                chunk = os.read(_STDIN, 4096)
            except OSError:
                raise self._hang_up() from None
            if not chunk:
                self._write("\n")
                raise PromptCancel("cancelled at end of input (Ctrl+D)", 130)
            line += chunk
        return line[:-1].decode("utf-8", "replace").rstrip("\r")

    def _ask(self, label: str, shown_default: str | None, parse, default=None):
        """The answer to `label`: `default` for an empty answer (None: there is none), else
        `parse`'s value; an invalid answer writes its rule and asks again."""
        prompt = f"{label}: " if shown_default is None else f"{label} [{shown_default}]: "
        while True:
            self._write(prompt)
            answer = self._read_line()
            if answer == "":
                return default
            try:
                return parse(answer)
            except ValueError as error:
                self._write(f"  {error}\n")

    # --- the values ------------------------------------------------------------------------

    def ask_values(self, values: dict, agent_dir) -> dict:
        """The values answered at the prompts, `values` their defaults (the reducer route None
        when there is no default). An empty reducer answer with no default raises `ConfigError`
        naming `--reducer`."""
        self.started = True
        values = dict(values)
        for key in FEATURE_KEYS:
            values[key] = self._ask(f"{key} (yes/no)", "yes" if values[key] else "no",
                                    parse_switch, values[key])
        self.shown["features"] = [key for key in FEATURE_KEYS if values[key]]
        if values["evidencePreservingReducer"]:
            suggestions, warnings = enabled_model_suggestions(agent_dir)
            self.warnings.extend(warnings)
            if suggestions:
                self._write("enabled models in Pi's settings:\n"
                            + "".join(f"  {entry}\n" for entry in suggestions))
            if values[_PROVIDER] is None:
                route = self._ask("reducer <provider>/<model>", None, parse_route)
            else:
                current = (values[_PROVIDER], values[_MODEL])
                route = self._ask("reducer <provider>/<model>", "/".join(current), parse_route,
                                  current)
            if not isinstance(route, tuple):
                raise ConfigError("the reducer is enabled but no route was given: answer the "
                                  "reducer prompt, or run again with --reducer",
                                  flag="--reducer")
            values[_PROVIDER], values[_MODEL] = route
        elif values[_PROVIDER] is None:
            values[_PROVIDER], values[_MODEL] = DEFAULT_REDUCER_PROVIDER, DEFAULT_REDUCER_MODEL
        self.shown["reducer"] = f"{values[_PROVIDER]}/{values[_MODEL]}"
        values[_RATIO] = self._ask(_RATIO, _format_ratio(values[_RATIO]), parse_ratio,
                                   values[_RATIO])
        ratio = values[_RATIO]
        self.shown["cacheRatio"] = int(ratio) if float(ratio).is_integer() else ratio
        return values

    def confirm(self, path) -> None:
        """Show the result for `path` and ask to proceed; declining raises `PromptCancel`."""
        features = ", ".join(self.shown["features"]) or "none"
        self._write(f"{path}:\n  features: {features}\n  reducer: {self.shown['reducer']}\n"
                    f"  cache write/read ratio: {_format_ratio(float(self.shown['cacheRatio']))}\n")
        if not self._ask("proceed (yes/no)", "yes", parse_switch, True):
            raise PromptCancel("cancelled: the confirmation was declined", 130)
        self.confirmed = True
