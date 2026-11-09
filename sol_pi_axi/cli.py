# SPDX-License-Identifier: MIT
"""The `sol-pi-axi` console-script entry point: argument parsing, the envelope, the home view,
the exit codes and the signal handlers.

`--help` and the version flags are answered before anything else is imported, so `--version`
costs no more than starting the interpreter; every other run prints one envelope (TOON, or one
JSON line with `--format json`) and never a traceback."""

import sys

from ._version import __version__

_HELP_FLAGS = ("-h", "--help")
_VERSION_FLAGS = ("-v", "-V", "--version")
_VALUE_FLAGS = ("--features", "--reducer", "--cache-ratio", "--format")
_SETUP_FLAGS = ("--features", "--reducer", "--cache-ratio", "--non-interactive")
#: The flags that set configuration values (`setup` and `install`).
_VALUE_SETTING_FLAGS = ("--features", "--reducer", "--cache-ratio")
_VERBS = ("setup", "install", "uninstall", "verify")
_FORMATS = ("toon", "json")
#: The test-only hold between write and rename (see `_hold_hook`).
_HOLD_ENV = "SOL_PI_AXI_TEST_HOLD"
_EXIT_FAILED = 1
_EXIT_USAGE = 2

_DESCRIPTION = ("Agent-facing setup command for the SoL-Pi Pi extensions: registers the "
                "extension with Pi (install, uninstall) and writes <project>/.pi/sol-pi.json "
                "(setup).")

_HELP = """\
sol-pi-axi — agent-facing setup for the SoL-Pi Pi extensions

Usage:
  sol-pi-axi [<verb>] [<arguments>] [<flags>]

Verbs:
  (none)                    the home view: this command and the state of the project's
                            .pi/sol-pi.json and the agent directory's sol-pi.json
  setup <project dir>       write <project dir>/.pi/sol-pi.json, creating .pi/ when missing
  install                   register npm:@anthill-tec/sol-pi@<this version> with pi install
                            (user-wide, from home, --no-approve; $PI_BIN, else pi on PATH),
                            replace earlier SoL-Pi sources, and write the agent directory's
                            sol-pi.json with the setup defaults when it is absent, then run
                            the check verify runs (a failed check fails install)
  uninstall                 remove every SoL-Pi source with pi remove; deletes no sol-pi.json
  verify                    check that Pi loads SoL-Pi: one SoL-Pi source registered, its
                            package on disk, then pi --offline --no-approve --mode rpc
                            --no-session from home (bounded at 30 s) must show SoL-Pi's load
                            signal and no SoL-Pi error; registers nothing, writes no file

Flags (flags go before or after the argument; --flag value or --flag=value):
  --features <list>         setup, install: all, none, or a comma list of actionFusion,
                            observationPack, evidencePreservingReducer, onlineContextCompact;
                            unlisted ones off (default: the base values; with none, all four on)
  --reducer <provider>/<model>
                            setup, install: the reducer's route, split at the first /
                            (default: the base values; with none, Pi's default provider and model)
  --cache-ratio <number>    setup, install: the cache write/read ratio, digits with an optional
                            fraction (default: the base values; with none, 12.5)
  --non-interactive         setup, install, uninstall: accepted, no effect (sol-pi-axi never
                            prompts)
  --format toon|json        the envelope's encoding (default: toon); json is one line
  -h, --help                print this help and exit 0
  -v, -V, --version         print the version and exit 0

Exit codes: 0 written, installed, removed, unchanged, verified or the home view; 1 failed; 2 usage error;
130, 143, 129 cancelled by SIGINT, SIGTERM, SIGHUP.

Examples:
  sol-pi-axi
  sol-pi-axi install
  sol-pi-axi uninstall
  sol-pi-axi verify
  sol-pi-axi setup .
  sol-pi-axi setup ~/work/app --features actionFusion,observationPack --cache-ratio 8
  sol-pi-axi setup ~/work/app --reducer anthropic/claude-sonnet-4-5 --format json
"""

_VALID_INPUT = ("valid verbs: setup <project dir>, install, uninstall, verify (no verb: the home "
                "view); "
                "valid flags: "
                "--features, --reducer, --cache-ratio, --format, --non-interactive, "
                "-h/--help, -v/-V/--version")


class UsageError(Exception):
    """An invalid command line: the message names the offending input."""

    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


class Cancelled(BaseException):
    """A run interrupted by `SIGINT`, `SIGTERM` or `SIGHUP`; raised by the signal handler."""

    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


def main() -> int:
    """Run `sol-pi-axi`; returns the exit code."""
    args = sys.argv[1:]
    if any(arg in _HELP_FLAGS for arg in args):
        sys.stdout.write(_HELP)
        return 0
    if any(arg in _VERSION_FLAGS for arg in args):
        sys.stdout.write(f"{__version__}\n")
        return 0
    try:
        return _run(args)
    except Exception as error:  # noqa: BLE001 — the last guard: never a traceback
        sys.stderr.write(f"sol-pi-axi: unexpected {type(error).__name__}: {error}\n")
        return _EXIT_FAILED


def _run(args: list[str]) -> int:
    _install_signal_handlers()
    fmt = _read_format(args)
    try:
        command = _parse(args)
    except UsageError as error:
        return _emit(_usage_envelope(error), fmt, _EXIT_USAGE)
    if command["verb"] == "setup":
        envelope, code = _setup(command)
    elif command["verb"] == "install":
        envelope, code = _install(command)
    elif command["verb"] == "uninstall":
        envelope, code = _uninstall()
    elif command["verb"] == "verify":
        envelope, code = _verify()
    else:
        envelope, code = _home()
    return _emit(envelope, fmt, code)


# --- Arguments ---------------------------------------------------------------------------------

def _read_format(args: list[str]) -> str:
    """The envelope format, read before anything else: `json` only when one well-formed
    `--format json` is given; otherwise TOON (a malformed one is reported as a usage error)."""
    values = []
    for index, arg in enumerate(args):
        if arg == "--format":
            values.append(args[index + 1] if index + 1 < len(args) else None)
        elif arg.startswith("--format="):
            values.append(arg.partition("=")[2])
    return "json" if values == ["json"] else "toon"


def _parse(args: list[str]) -> dict:
    """The verb, its argument and the flag values; raises `UsageError`. Nothing is read."""
    positionals: list[str] = []
    flags: dict[str, str] = {}
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg.startswith("-") and arg != "-":
            name, has_value, value = arg.partition("=")
            if name not in _VALUE_FLAGS and name != "--non-interactive":
                hint = None
                if name == "--yes":
                    hint = ("sol-pi-axi never prompts, so there is nothing to confirm: drop --yes "
                            "(--non-interactive is accepted and has no effect)")
                raise UsageError(f"unknown flag {name}", hint=hint)
            if name in flags:
                raise UsageError(f"repeated flag {name}")
            if name == "--non-interactive":
                if has_value:
                    raise UsageError(f"--non-interactive takes no value: {arg}")
                flags[name] = ""
                continue
            if not has_value:
                if index >= len(args):
                    raise UsageError(f"{name} needs a value")
                value = args[index]
                index += 1
            flags[name] = value
        else:
            positionals.append(arg)

    if not positionals:
        verb = "home"
    else:
        verb = positionals[0]
        if verb not in _VERBS:
            raise UsageError(f"unknown verb {verb}")
    if verb == "setup":
        if len(positionals) < 2:
            raise UsageError("setup needs a project directory: sol-pi-axi setup <project dir>")
        if len(positionals) > 2:
            raise UsageError(f"extra argument {positionals[2]} (setup takes one project directory)")
    elif verb in ("install", "uninstall"):
        if len(positionals) > 1:
            raise UsageError(f"extra argument {positionals[1]} ({verb} takes no argument)")
        if verb == "uninstall":
            for name in _VALUE_SETTING_FLAGS:
                if name in flags:
                    raise UsageError(f"{name} does not apply to uninstall, which writes no "
                                     "configuration")
    elif verb == "verify":
        if len(positionals) > 1:
            raise UsageError(f"extra argument {positionals[1]} (verify takes no argument)")
        for name in flags:
            if name != "--format":
                raise UsageError(f"{name} does not apply to verify, which takes only --format")
    else:
        for name in _SETUP_FLAGS:
            if name in flags:
                raise UsageError(f"{name} belongs to setup: sol-pi-axi setup <project dir> {name}")

    if "--format" in flags and flags["--format"] not in _FORMATS:
        raise UsageError(f"--format must be toon or json, got {flags['--format']!r}")
    command = {"verb": verb, "project": positionals[1] if verb == "setup" else None,
               "features": None, "reducer": None, "cache_ratio": None}
    if "--features" in flags:
        command["features"] = _parse_features(flags["--features"])
    if "--reducer" in flags:
        command["reducer"] = _parse_reducer(flags["--reducer"])
    if "--cache-ratio" in flags:
        command["cache_ratio"] = _parse_ratio(flags["--cache-ratio"])
    return command


def _parse_features(value: str) -> list[str]:
    from .config import FEATURE_KEYS

    if value == "all":
        return list(FEATURE_KEYS)
    if value == "none":
        return []
    names = value.split(",")
    for name in names:
        if not name:
            raise UsageError(f"--features has an empty entry: {value!r}")
        if name not in FEATURE_KEYS:
            raise UsageError(f"--features names an unknown mechanism {name!r} (use all, none, or "
                             f"a comma list of {', '.join(FEATURE_KEYS)})")
    if len(set(names)) != len(names):
        raise UsageError(f"--features names a mechanism twice: {value!r}")
    return names


def _parse_reducer(value: str) -> tuple[str, str]:
    from .config import valid_route_part

    provider, slash, model = value.partition("/")
    if not slash or not valid_route_part(provider) or not valid_route_part(model):
        raise UsageError(f"--reducer must be <provider>/<model>, both non-empty without "
                         f"whitespace, got {value!r}")
    return provider, model


def _parse_ratio(value: str) -> float:
    import math
    import re

    if re.fullmatch(r"[0-9]+(\.[0-9]+)?", value) is None:
        raise UsageError(f"--cache-ratio must be digits with an optional decimal fraction, "
                         f"got {value!r}")
    ratio = float(value)
    if not math.isfinite(ratio):
        raise UsageError(f"--cache-ratio must be finite, got {value!r}")
    return ratio


# --- Verbs -------------------------------------------------------------------------------------

def _setup(command: dict) -> tuple[dict, int]:
    import os

    from . import config, setup

    project = os.path.abspath(command["project"])
    context: dict = {"project": project, "agentDir": None}
    envelope: dict = {"verb": "setup", "ok": False, "version": __version__, "outcome": "failed",
                      "path": None, "config": None, "context": context}
    try:
        try:
            _arm()
            agent = config.agent_dir()
            context["agentDir"] = str(agent)
            result = setup.run_setup(project, agent_dir=agent, features=command["features"],
                                     reducer=command["reducer"],
                                     cache_ratio=command["cache_ratio"], hook=_hold_hook(),
                                     on_rename=_disarm)
        finally:
            _disarm()
    except Cancelled as cancel:
        name = _signal_name(cancel.signum)
        envelope.update(outcome="cancelled", path=_target(project),
                        error=f"cancelled by {name}; nothing was written", warnings=[], help=[])
        return envelope, 128 + cancel.signum
    except config.ConfigError as error:
        envelope.update(path=_target(project), error=str(error), warnings=[],
                        help=_fix_help(project, error.flag))
        return envelope, _EXIT_FAILED
    except Exception as error:  # noqa: BLE001 — an unexpected failure is `failed`, named
        envelope.update(path=_target(project), error=f"unexpected {type(error).__name__}: {error}",
                        warnings=[], help=_fix_help(project, None))
        return envelope, _EXIT_FAILED

    values = result.config
    help_steps = []
    if result.outcome == "written":
        help_steps = [f"cd {_quote(project)} && pi",
                      ("in Pi, run /trust to trust the project, so the extensions read "
                       ".pi/sol-pi.json")]
    envelope.update(ok=True, outcome=result.outcome, path=str(result.path),
                    config=_summary(values), warnings=list(result.warnings), help=help_steps)
    return envelope, 0


def _install(command: dict) -> tuple[dict, int]:
    from . import _version, config
    from .install import InstallReport, run_install
    from .pi import PiError, recorded_sources

    version = _version.__version__
    report = InstallReport(agent_dir=config.agent_dir())
    envelope: dict = {"verb": "install", "ok": False, "version": version, "outcome": "failed",
                      "context": {"agentDir": str(report.agent_dir)}}
    error_text = None
    help_steps: list[str] = []
    code = _EXIT_FAILED
    try:
        try:
            _arm()
            run_install(report, version=version, features=command["features"],
                        reducer=command["reducer"], cache_ratio=command["cache_ratio"],
                        on_rename=_disarm)
        finally:
            _disarm()
    except Cancelled as cancel:
        report.outcome = "cancelled"
        error_text = f"cancelled by {_signal_name(cancel.signum)}"
        code = 128 + cancel.signum
    except PiError as error:
        error_text, help_steps = str(error), error.help
    except config.ConfigError as error:
        error_text = str(error)
        help_steps = (["sol-pi-axi install --reducer <provider>/<model>",
                       "sol-pi-axi install --features <list without evidencePreservingReducer>"]
                      if error.flag == "--reducer" else
                      ["fix the path named in error, then rerun: sol-pi-axi install"])
    except Exception as error:  # noqa: BLE001 — an unexpected failure is `failed`, named
        error_text = f"unexpected {type(error).__name__}: {error}"
    else:
        code = 0

    verify = None
    if code == 0:
        # The run ended with the source registered: the check runs last.
        verify, code, check_error, check_help = _install_check(report)
        if check_error is not None:
            error_text, help_steps = check_error, check_help

    if code != 0 and report.source is not None:
        # Report the registration as the run left it.
        try:
            report.registered = report.source in recorded_sources(report.agent_dir)
        except config.ConfigError:
            report.registered = False
    envelope.update(ok=code == 0, outcome=report.outcome)
    if report.source is not None:
        envelope["extension"] = {"source": report.source, "registered": report.registered,
                                 "replaced": list(report.replaced), "pi": report.pi_version}
    if report.config_path is not None and report.config_state is not None:
        values = report.config_values
        summary = _summary(values) if values is not None else {
            "features": None, "reducer": None, "cacheRatio": None}
        envelope["config"] = {"path": str(report.config_path), "state": report.config_state,
                              **summary}
    envelope["verify"] = verify
    if error_text is not None:
        envelope["error"] = error_text
    if report.outcome == "installed":
        help_steps = ["sol-pi-axi setup <project dir>"]
    envelope.update(warnings=list(report.warnings), help=help_steps)
    return envelope, code


def _install_check(report) -> tuple[dict | None, int, str | None, list[str]]:
    """Run the check after a registering install run: its `verify` key (None when cancelled),
    the exit code, and the error and help on failure. A failed check fails the run and leaves
    the registration and the configuration as the run left them."""
    from .check import run_check

    try:
        try:
            _arm()
            result = run_check(report.agent_dir)
        finally:
            _disarm()
    except Cancelled as cancel:
        report.outcome = "cancelled"
        return None, 128 + cancel.signum, f"cancelled by {_signal_name(cancel.signum)}", []
    report.warnings.extend(result.warnings)
    if result.ok:
        return result.verify(), 0, None, []
    report.outcome = "failed"
    return result.verify(), _EXIT_FAILED, result.error, list(result.help)


def _verify() -> tuple[dict, int]:
    from . import config
    from .check import CheckResult, run_check

    agent = config.agent_dir()
    envelope: dict = {"verb": "verify", "ok": False, "version": __version__, "outcome": "failed",
                      "context": {"agentDir": str(agent)}}
    result = CheckResult()
    try:
        try:
            _arm()
            result = run_check(agent)
        finally:
            _disarm()
    except Cancelled as cancel:
        envelope.update(outcome="cancelled", verify=result.verify(),
                        extension={"state": "absent"},
                        error=f"cancelled by {_signal_name(cancel.signum)}", warnings=[], help=[])
        return envelope, 128 + cancel.signum
    extension = ({"state": "absent"} if result.source is None else
                 {"state": "registered", "source": result.source})
    envelope.update(ok=result.ok, outcome="verified" if result.ok else "failed",
                    verify=result.verify(), extension=extension)
    if result.error is not None:
        envelope["error"] = result.error
    envelope.update(warnings=list(result.warnings), help=[] if result.ok else list(result.help))
    return envelope, 0 if result.ok else _EXIT_FAILED


def _uninstall() -> tuple[dict, int]:
    from . import config
    from .install import UninstallReport, run_uninstall
    from .pi import PiError

    report = UninstallReport(agent_dir=config.agent_dir())
    envelope: dict = {"verb": "uninstall", "ok": False, "version": __version__,
                      "outcome": "failed", "context": {"agentDir": str(report.agent_dir)}}
    error_text = None
    help_steps: list[str] = []
    code = _EXIT_FAILED
    try:
        try:
            _arm()
            run_uninstall(report)
        finally:
            _disarm()
    except Cancelled as cancel:
        report.outcome = "cancelled"
        error_text = f"cancelled by {_signal_name(cancel.signum)}"
        code = 128 + cancel.signum
    except (PiError, config.ConfigError) as error:
        error_text = str(error)
        help_steps = list(getattr(error, "help", [])) or ["sol-pi-axi uninstall"]
    except Exception as error:  # noqa: BLE001 — an unexpected failure is `failed`, named
        error_text = f"unexpected {type(error).__name__}: {error}"
    else:
        code = 0
    envelope.update(ok=code == 0, outcome=report.outcome, removed=list(report.removed))
    if error_text is not None:
        envelope["error"] = error_text
    envelope.update(warnings=list(report.warnings), help=help_steps)
    return envelope, code


def _extension_state(agent) -> tuple[dict, list[str]]:
    """The home view's `extension` and its warnings: `absent`, or `registered` with the SoL-Pi
    source Pi records; a warning when it is not the own release source."""
    from . import config
    from .install import registered_source

    try:
        source = registered_source(agent, __version__)
    except config.ConfigError as error:
        return {"state": "absent"}, [f"cannot read Pi's package list: {error}"]
    if source is None:
        return {"state": "absent"}, []
    warnings = []
    if source != f"npm:@anthill-tec/sol-pi@{__version__}":
        warnings.append(f"the registered SoL-Pi source {source} is not this version's "
                        f"npm:@anthill-tec/sol-pi@{__version__}; run sol-pi-axi install")
    return {"state": "registered", "source": source}, warnings


def _home() -> tuple[dict, int]:
    import os

    from . import config

    envelope: dict = {"verb": "home", "ok": True, "version": __version__, "bin": _bin(),
                      "description": _DESCRIPTION}
    try:
        try:
            _arm()
            project_file = config.project_config_path(os.getcwd())
            agent_file = config.agent_dir() / "sol-pi.json"
            envelope["project"] = _file_state(project_file)
            envelope["agentConfig"] = _file_state(agent_file)
            envelope["extension"], extension_warnings = _extension_state(config.agent_dir())
        finally:
            _disarm()
    except Cancelled as cancel:
        envelope.update(ok=False, error=f"cancelled by {_signal_name(cancel.signum)}",
                        warnings=[], help=[])
        return envelope, 128 + cancel.signum
    except Exception as error:  # noqa: BLE001 — an unexpected failure is reported, named
        envelope.update(ok=False, error=f"unexpected {type(error).__name__}: {error}",
                        warnings=[], help=["sol-pi-axi setup <project dir>"])
        return envelope, _EXIT_FAILED
    help_steps = ["sol-pi-axi setup <project dir>"]
    if extension_warnings:
        help_steps.insert(0, "sol-pi-axi install")
    envelope.update(warnings=extension_warnings, help=help_steps)
    return envelope, 0


def _file_state(path) -> dict:
    import os

    from . import config

    if not os.path.lexists(path):
        return {"path": str(path), "state": "absent"}
    try:
        values = config.read_config(path)
    except config.ConfigError as error:
        return {"path": str(path), "state": "invalid", "reason": str(error)}
    summary = _summary(values)
    return {"path": str(path), "state": "valid", "features": summary["features"],
            "reducer": summary["reducer"]}


# --- Envelope ----------------------------------------------------------------------------------

def _usage_envelope(error: UsageError) -> dict:
    message = f"{error}; {_VALID_INPUT}"
    help_steps = ["sol-pi-axi --help"]
    if error.hint:
        message = f"{error} ({error.hint}); {_VALID_INPUT}"
        help_steps.insert(0, "sol-pi-axi setup <project dir> --non-interactive")
    return {"verb": "usage", "ok": False, "version": __version__, "outcome": "usage",
            "error": message, "warnings": [], "help": help_steps}


def _emit(envelope: dict, fmt: str, code: int) -> int:
    """Print `envelope` under the root `axi`, in `fmt`; returns `code`."""
    document = {"axi": _printable(_ordered(envelope))}
    if fmt == "json":
        import json

        text = json.dumps(document, ensure_ascii=False)
    else:
        import toon_format

        text = toon_format.encode(document)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()
    return code


_KEY_ORDER = ("verb", "ok", "version", "outcome", "path", "extension", "removed", "config",
              "verify", "context", "bin", "description", "project", "agentConfig", "error", "warnings",
              "help")


def _ordered(envelope: dict) -> dict:
    return {key: envelope[key] for key in _KEY_ORDER if key in envelope}


def _printable(value):
    """`value` with every string valid UTF-8 text: a byte a path or argument could not decode (held
    as a surrogate escape) is written `\\xNN`, any other lone surrogate `\\uNNNN`, so the envelope
    can always be encoded and printed."""
    if isinstance(value, str):
        try:
            raw = value.encode("utf-8", "surrogateescape")
        except UnicodeEncodeError:
            raw = value.encode("utf-8", "backslashreplace")
        return raw.decode("utf-8", "backslashreplace")
    if isinstance(value, dict):
        return {key: _printable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_printable(item) for item in value]
    return value


def _summary(values: dict) -> dict:
    """The envelope's view of effective values: enabled features, reducer route, ratio."""
    from .config import FEATURE_KEYS

    ratio = values["cacheWriteReadRatio"]
    if isinstance(ratio, float) and ratio.is_integer() and abs(ratio) < 2 ** 53:
        ratio = int(ratio)
    return {"features": [key for key in FEATURE_KEYS if values[key]],
            "reducer": (f"{values['evidencePreservingReducerProvider']}/"
                        f"{values['evidencePreservingReducerModel']}"),
            "cacheRatio": ratio}


def _fix_help(project: str, flag: str | None) -> list[str]:
    command = f"sol-pi-axi setup {_quote(project)}"
    if flag == "--reducer":
        return [f"{command} --reducer <provider>/<model>",
                f"{command} --features <list without evidencePreservingReducer>"]
    if flag is not None:
        return [f"{command} {flag} <value>"]
    return [f"fix the path named in error, then rerun: {command}"]


def _target(project: str) -> str | None:
    import os

    return os.path.join(project, ".pi", "sol-pi.json") if os.path.isdir(project) else None


def _bin() -> str:
    """This command's path, the home directory written as `~`."""
    import os

    path = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else "sol-pi-axi"
    home = os.path.expanduser("~").rstrip("/")
    if home and path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


def _quote(text: str) -> str:
    import shlex

    return shlex.quote(text)


# --- Signals and the test hold -----------------------------------------------------------------

#: The run's signal phase: `before` its work (a signal is kept as `pending`), `armed` during it (a
#: signal cancels it), `done` after it (the outcome is decided; a signal is ignored, so the one
#: envelope is printed whole). `Cancelled` is raised only while `armed`, and only inside the verbs'
#: `except Cancelled`, so it never escapes `main`.
_SIGNALS: dict = {"phase": "before", "pending": None}


def _on_signal(signum, _frame) -> None:
    """Cancel the armed run once; before the work, keep the first signal for `_arm`; after it,
    or during the clean-up of a cancel, ignore it."""
    if _SIGNALS["phase"] == "armed":
        _SIGNALS["phase"] = "done"
        raise Cancelled(signum)
    if _SIGNALS["phase"] == "before" and _SIGNALS["pending"] is None:
        _SIGNALS["pending"] = signum


def _install_signal_handlers() -> None:
    """Install this command's own handlers, whatever it inherited (an ignored SIGINT included).
    They stay unarmed until the verb's work starts (`_arm`)."""
    import signal

    _SIGNALS.update(phase="before", pending=None)
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        signum = getattr(signal, name, None)
        if signum is not None:
            signal.signal(signum, _on_signal)


def _arm() -> None:
    """Start the work: a signal that arrived before it cancels the run now, before anything is
    read or written; from here a signal cancels it."""
    pending = _SIGNALS["pending"]
    if pending is not None:
        _SIGNALS.update(phase="done", pending=None)
        raise Cancelled(pending)
    _SIGNALS["phase"] = "armed"


def _disarm() -> None:
    """End the work: the outcome is decided, and a later signal is ignored."""
    _SIGNALS["phase"] = "done"


def _signal_name(signum: int) -> str:
    import signal

    try:
        return signal.Signals(signum).name
    except ValueError:
        return f"signal {signum}"


def _hold_hook():
    """The test-only hold, when `SOL_PI_AXI_TEST_HOLD` names a file: between write and rename,
    write the temporary file's absolute path and a newline to it, then wait until it is removed."""
    import os

    hold = os.environ.get(_HOLD_ENV, "")
    if not hold:
        return None

    def hook(temporary) -> None:
        import time

        with open(hold, "w", encoding="utf-8") as handle:
            handle.write(os.path.abspath(temporary) + "\n")
        while os.path.lexists(hold):
            time.sleep(0.01)

    return hook
