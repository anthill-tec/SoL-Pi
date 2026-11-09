# SPDX-License-Identifier: MIT
"""SoL-Pi's configuration on the official Pi layout: the agent directory, reading and validating
`sol-pi.json` with the extension's own rules (JSON read as JavaScript's `JSON.parse` reads it),
Pi's default model route from `settings.json`, and the written form."""

import json
import math
import os
import re
from decimal import Decimal
from pathlib import Path

#: The mechanism switches, each a boolean.
FEATURE_KEYS = ("actionFusion", "observationPack", "evidencePreservingReducer", "onlineContextCompact")
#: Every key in the written form's order (`sol-pi.example.json`'s).
KEY_ORDER = (
    "version",
    "actionFusion",
    "observationPack",
    "evidencePreservingReducer",
    "evidencePreservingReducerProvider",
    "evidencePreservingReducerModel",
    "onlineContextCompact",
    "cacheWriteReadRatio",
)
_KNOWN_KEYS = frozenset(KEY_ORDER)

#: The extension's built-in reducer route and cache write/read ratio.
DEFAULT_REDUCER_PROVIDER = "openai-codex"
DEFAULT_REDUCER_MODEL = "gpt-5.6-luna"
DEFAULT_CACHE_WRITE_READ_RATIO = 12.5

#: JavaScript's `String.prototype.trim()` whitespace: WhiteSpace and LineTerminator code points.
_JS_WHITESPACE = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


class ConfigError(Exception):
    """A configuration the run needs is missing, unreadable or invalid. The message names the
    path; `flag`, when set, names the flag that fixes it."""

    def __init__(self, message: str, *, flag: str | None = None):
        super().__init__(message)
        self.flag = flag


def agent_dir() -> Path:
    """`$PI_CODING_AGENT_DIR` when non-empty (a leading `~` expanded), else `~/.pi/agent`."""
    configured = os.environ.get("PI_CODING_AGENT_DIR", "")
    if configured:
        return Path(os.path.expanduser(configured))
    return Path.home() / ".pi" / "agent"


def project_config_path(project_dir: str | os.PathLike[str]) -> Path:
    """`<project>/.pi/sol-pi.json`."""
    return Path(project_dir) / ".pi" / "sol-pi.json"


def _reject_constant(name: str):
    raise ValueError(f"{name} is not valid JSON")


def _read_json(path: Path):
    """The file's JSON value, parsed as `JSON.parse(readFileSync(path, "utf8"))` would."""
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError as error:
        raise ConfigError(f"unable to read {path}: {error.strerror or error}") from None
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except ValueError as error:
        raise ConfigError(f"invalid JSON in {path}: {error}") from None


def _js_number(value) -> float | None:
    """`value` as a finite JavaScript number, or None when it is not one (a boolean is not)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _js_trim(value: str) -> str:
    return value.strip(_JS_WHITESPACE)


def _string_value(record: dict, key: str, default: str, path: Path) -> str:
    value = record.get(key, default)
    if not isinstance(value, str) or not _js_trim(value):
        raise ConfigError(f"{key} must be a non-empty string: {path}")
    return _js_trim(value)


def validate_config(value, path: Path) -> dict:
    """The effective values (every key, written-form order) of a parsed `sol-pi.json`, with the
    extension's rules; raises `ConfigError` naming `path`."""
    if not isinstance(value, dict):
        raise ConfigError(f"SoL-Pi config must be a JSON object: {path}")
    for key in value:
        if key not in _KNOWN_KEYS:
            raise ConfigError(f"unknown SoL-Pi config key {key}: {path}")
    if _js_number(value.get("version")) != 1:
        raise ConfigError(f"version must be 1: {path}")
    effective: dict = {"version": 1}
    for key in FEATURE_KEYS:
        configured = value.get(key, False)
        if not isinstance(configured, bool):
            raise ConfigError(f"{key} must be boolean: {path}")
        effective[key] = configured
    ratio = (_js_number(value["cacheWriteReadRatio"]) if "cacheWriteReadRatio" in value
             else DEFAULT_CACHE_WRITE_READ_RATIO)
    if ratio is None or ratio < 0:
        raise ConfigError(f"cacheWriteReadRatio must be a finite non-negative number: {path}")
    effective["cacheWriteReadRatio"] = ratio
    effective["evidencePreservingReducerProvider"] = _string_value(
        value, "evidencePreservingReducerProvider", DEFAULT_REDUCER_PROVIDER, path)
    effective["evidencePreservingReducerModel"] = _string_value(
        value, "evidencePreservingReducerModel", DEFAULT_REDUCER_MODEL, path)
    return {key: effective[key] for key in KEY_ORDER}


def read_config(path: str | os.PathLike[str]) -> dict:
    """The effective values of the `sol-pi.json` at `path`; raises `ConfigError` naming it when it
    is missing, unreadable (a dangling link included) or invalid."""
    path = Path(path)
    return validate_config(_read_json(path), path)


def valid_route_part(value) -> bool:
    """A provider or model name as Pi's default route and `--reducer` accept it: a non-empty
    string without whitespace, Python's or JavaScript's."""
    return (isinstance(value, str) and bool(value)
            and not any(char.isspace() or char in _JS_WHITESPACE for char in value))


def _route_part(value) -> str | None:
    return value if valid_route_part(value) else None


def pi_default_route(agent_directory: str | os.PathLike[str]) -> tuple[str, str] | None:
    """Pi's `(defaultProvider, defaultModel)` from `<agent dir>/settings.json`: None when the file
    is missing or either value is not a non-empty string without whitespace; `ConfigError` naming
    the file when it is not valid JSON or its root is not an object."""
    path = Path(agent_directory) / "settings.json"
    if not os.path.lexists(path):
        return None
    settings = _read_json(path)
    if not isinstance(settings, dict):
        raise ConfigError(f"Pi settings must be a JSON object: {path}")
    provider = _route_part(settings.get("defaultProvider"))
    model = _route_part(settings.get("defaultModel"))
    if provider is None or model is None:
        return None
    return provider, model


#: The characters that keep an `enabledModels` entry out of the reducer suggestions: a glob
#: character, or the `:` that starts a suffix.
_UNSUGGESTED_CHARACTERS = frozenset("*?[]{}:")


def _suggestable(entry) -> bool:
    if not isinstance(entry, str) or any(char in _UNSUGGESTED_CHARACTERS for char in entry):
        return False
    provider, slash, model = entry.partition("/")
    return bool(slash) and valid_route_part(provider) and valid_route_part(model)


def enabled_model_suggestions(
        agent_directory: str | os.PathLike[str]) -> tuple[list[str], list[str]]:
    """The reducer prompt's suggestions and their warnings: the `enabledModels` entries of
    `<agent dir>/settings.json` that are valid `--reducer` values without any of `*?[]{}` or a
    `:` suffix, in the file's order. Never raises: a missing or malformed file, a root that is
    not an object, a non-array `enabledModels`, or entries none of which is usable give no
    suggestions and one warning."""
    path = Path(agent_directory) / "settings.json"
    if not os.path.lexists(path):
        return [], [f"no reducer suggestions: {path} does not exist"]
    try:
        settings = _read_json(path)
    except ConfigError as error:
        return [], [f"no reducer suggestions: {error}"]
    if not isinstance(settings, dict):
        return [], [f"no reducer suggestions: Pi settings must be a JSON object: {path}"]
    if "enabledModels" not in settings:
        return [], []
    entries = settings["enabledModels"]
    if not isinstance(entries, list):
        return [], [f"no reducer suggestions: enabledModels is not an array in {path}"]
    suggestions = [entry for entry in entries if _suggestable(entry)]
    if entries and not suggestions:
        return [], [(f"no reducer suggestions: no enabledModels entry in {path} is a provider "
                     "and model without a glob character or a : suffix")]
    return suggestions, []


def _format_number(value: float) -> str:
    """A finite number as JavaScript's `Number.prototype.toString()` writes it."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    _, digit_tuple, exponent = Decimal(repr(abs(float(value)))).normalize().as_tuple()
    digits = "".join(map(str, digit_tuple))
    count = len(digits)
    point = count + int(exponent)  # value = 0.<digits> x 10^point
    if count <= point <= 21:
        text = digits + "0" * (point - count)
    elif 0 < point <= 21:
        text = f"{digits[:point]}.{digits[point:]}"
    elif -6 < point <= 0:
        text = "0." + "0" * -point + digits
    else:
        power = point - 1
        mantissa = digits if count == 1 else f"{digits[0]}.{digits[1:]}"
        text = f"{mantissa}e{'+' if power >= 0 else '-'}{abs(power)}"
    return sign + text


def _format_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _format_number(value)
    text = json.dumps(value, ensure_ascii=False)
    # JSON.stringify escapes a lone surrogate; Python would leave it unencodable.
    return _LONE_SURROGATE.sub(lambda match: f"\\u{ord(match.group()):04x}", text)


def render_config(values: dict) -> bytes:
    """The written form: `JSON.stringify(values, null, "\\t") + "\\n"` with every key in
    `sol-pi.example.json`'s order."""
    lines = [f"\t{json.dumps(key)}: {_format_value(values[key])}" for key in KEY_ORDER]
    return ("{\n" + ",\n".join(lines) + "\n}\n").encode("utf-8")
