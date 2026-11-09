# SPDX-License-Identifier: MIT
"""The check that Pi loads SoL-Pi (DN-sol-pi-axi §D6), run by `sol-pi-axi verify` and last by
`sol-pi-axi install`.

Pi's record and the package on disk are checked first; then Pi starts in RPC mode from the user's
home with `SOL_PI_AXI_VERIFY` set to a value unique to the run and one `get_state` command on
standard input, bounded at `VERIFY_TIMEOUT` seconds. SoL-Pi's `session_start` answers the value
with a notify `extension_ui_request` (the load signal), which proves it loaded. The check writes
no file; Pi may create `auth.json` and `models-store.json` in the agent directory."""

import json
import os
import secrets
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import ConfigError, read_config
from .pi import (
    NPM_PACKAGE,
    PiError,
    find_pi,
    is_sol_pi,
    local_path,
    npm_package,
    recorded_sources,
)

#: The bound on Pi's start, in seconds; Pi is killed and reaped after it.
VERIFY_TIMEOUT = 30
#: Where Pi's own npm install puts packages, under the agent directory. This is a data path Pi
#: writes, not a Node command or a Node/Pi source this package runs or imports.
PI_NPM_INSTALL_ROOT = ("npm", "node_modules")
#: The variable that carries the run's value to SoL-Pi's load signal.
VERIFY_ENV = "SOL_PI_AXI_VERIFY"
#: Pi's arguments for the check: one RPC start, no session, offline, no approval prompts.
_RPC_COMMAND = "--offline --no-approve --mode rpc --no-session"
_GET_STATE = {"id": "sol-pi-axi", "type": "get_state"}
_SIGNAL_PREFIX = "sol-pi-axi verify "
_DIALOG_METHODS = frozenset({"select", "confirm", "input", "editor"})
_LOAD_FAILURE = "Failed to load extension"
_INSTALL = "sol-pi-axi install"
_UNINSTALL = "sol-pi-axi uninstall"


@dataclass
class CheckResult:
    """The check's outcome. `exit` is Pi's exit code (None when Pi was killed or not started);
    `errors` holds SoL-Pi's own `{extensionPath, event, error}` entries; `error` is None when
    `ok`; `warnings` name other extensions' errors by path; `source` is the SoL-Pi source Pi
    records (None when none); `help` holds the steps that fix a failure."""

    ok: bool = False
    loaded: bool = False
    exit: int | None = None
    errors: list[dict] = field(default_factory=list)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    source: str | None = None
    help: list[str] = field(default_factory=list)

    def verify(self) -> dict:
        """The envelope's `verify` key: `{ok, loaded, exit, errors}`."""
        return {"ok": self.ok, "loaded": self.loaded, "exit": self.exit,
                "errors": [dict(entry) for entry in self.errors]}


def run_check(agent_dir: Path, *, timeout: float = VERIFY_TIMEOUT) -> CheckResult:
    """Check that Pi, with the agent directory `agent_dir`, loads SoL-Pi cleanly; never raises
    for a failed check (the result says why)."""
    result = CheckResult()
    try:
        package_dir = _registered_package(agent_dir, result)
        if package_dir is None:
            return _fail(result, agent_dir)
        executable = find_pi()
    except (PiError, ConfigError) as error:
        result.error = str(error)
        result.help = list(getattr(error, "help", []))
        return _fail(result, agent_dir)
    _start(executable, package_dir, result, timeout)
    if result.error is None:
        result.ok = True
        return result
    return _fail(result, agent_dir)


def _registered_package(agent_dir: Path, result: CheckResult) -> Path | None:
    """The registered SoL-Pi package's directory, symbolic links resolved; None (with
    `result.error` and `result.help` set) when Pi's record or the disk does not hold exactly
    one usable SoL-Pi package."""
    sources = [entry for entry in recorded_sources(agent_dir) if is_sol_pi(entry, agent_dir)]
    if not sources:
        result.error = (f"no SoL-Pi source is registered in {agent_dir / 'settings.json'}: "
                        "SoL-Pi is not registered with Pi")
        result.help = [_INSTALL]
        return None
    result.source = sources[0]
    if len(sources) > 1:
        result.error = f"more than one SoL-Pi source is registered: {', '.join(sources)}"
        return None
    source = sources[0]
    package = npm_package(source)
    if package == NPM_PACKAGE:
        directory = agent_dir.joinpath(*PI_NPM_INSTALL_ROOT, NPM_PACKAGE)
    elif package is None and "://" not in source and not source.startswith("git:"):
        directory = local_path(source, agent_dir)
    else:
        result.error = (f"the registered SoL-Pi source {source} is neither an "
                        f"npm:{NPM_PACKAGE} source nor a local path; {_INSTALL} replaces it")
        result.help = [_INSTALL]
        return None
    if not (directory / "package.json").is_file():
        result.error = (f"the SoL-Pi package of {source} is not on disk: "
                        f"{directory / 'package.json'} does not exist")
        return None
    return Path(os.path.realpath(directory))


def _start(executable: str, package_dir: Path, result: CheckResult, timeout: float) -> None:
    """Start Pi once in RPC mode and read its answer into `result` (`error` set on failure)."""
    value = secrets.token_hex(12)
    environ = {**os.environ, VERIFY_ENV: value}
    home = Path.home()
    try:
        process = subprocess.Popen(
            [executable, *_RPC_COMMAND.split()], cwd=home, env=environ,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            errors="replace", start_new_session=True)
    except OSError as error:
        if error.filename is not None and os.fspath(error.filename) == os.fspath(home):
            # The child could not enter its working directory: the home, not Pi, is missing.
            result.error = (f"cannot start pi from the home directory {home}, Pi's working "
                            f"directory: {error.strerror or error}")
        else:
            result.error = f"cannot run {executable}: {error.strerror or error}"
        return
    killed = False
    try:
        try:
            stdout, stderr = process.communicate(json.dumps(_GET_STATE) + "\n", timeout=timeout)
        except subprocess.TimeoutExpired:
            killed = True
            _kill(process)
            stdout, stderr = process.communicate()
    finally:
        if process.returncode is None:
            _kill(process)
            process.wait()
    _read_answer(stdout or "", stderr or "", value, package_dir, result,
                 None if killed else process.returncode, timeout)


def _kill(process: subprocess.Popen) -> None:
    """Kill Pi and anything it started (its own session's process group)."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


def _read_answer(stdout: str, stderr: str, value: str, package_dir: Path, result: CheckResult,
                 code: int | None, timeout: float) -> None:
    """Fill in `result` from Pi's output: the load signal, the `get_state` response, extension
    errors (SoL-Pi's own fail, others warn) and dialogs; non-JSON lines are ignored."""
    result.exit = code
    responded = False
    dialog: dict | None = None
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict):
            continue
        kind = message.get("type")
        if kind == "extension_ui_request":
            method = message.get("method")
            if method == "notify" and message.get("message") == _SIGNAL_PREFIX + value:
                result.loaded = True
            elif method in _DIALOG_METHODS and dialog is None:
                dialog = message
        elif kind == "extension_error":
            entry = {"extensionPath": message.get("extensionPath"), "event": message.get("event"),
                     "error": message.get("error")}
            if _inside(entry["extensionPath"], package_dir):
                result.errors.append(entry)
            else:
                result.warnings.append(f"the extension {entry['extensionPath']} failed in "
                                       f"{entry['event']}: {entry['error']}")
        elif (kind == "response" and message.get("command") == "get_state"
              and message.get("id") == _GET_STATE["id"]):
            responded = True

    if code is None:
        if dialog is not None:
            result.error = (f"Pi was held by a {dialog.get('method')} dialog titled "
                            f"{dialog.get('title')!r} until the {timeout:g}-second bound killed "
                            "it: an extension opened it in session_start, and Pi does not name "
                            "the extension that opened it")
        else:
            result.error = f"Pi did not answer within {timeout:g} seconds and was killed"
    elif code != 0:
        failure = next((line.strip() for line in stderr.splitlines() if _LOAD_FAILURE in line),
                       None)
        result.error = (f"pi exited {code}: {failure}" if failure is not None else
                        f"pi exited {code} without a '{_LOAD_FAILURE}' line")
    elif result.errors:
        first = result.errors[0]
        result.error = f"SoL-Pi failed in {first['event']}: {first['error']}"
    elif not responded:
        result.error = "Pi sent no response to the get_state command"
    elif not result.loaded:
        result.error = ("Pi started without loading SoL-Pi: no load signal carried this run's "
                        "value (a resource filter in settings.json may exclude it)")


def _inside(path, package_dir: Path) -> bool:
    """Whether `path` lies inside `package_dir`, both with symbolic links resolved."""
    if not isinstance(path, str) or not path:
        return False
    return Path(os.path.realpath(path)).is_relative_to(package_dir)


def _fail(result: CheckResult, agent_dir: Path) -> CheckResult:
    """`result` as a failure, with the fix in `help`: an invalid agent `sol-pi.json` is named,
    else both `sol-pi-axi install` and `sol-pi-axi uninstall` unless a fix is already set."""
    result.ok = False
    agent_file = agent_dir / "sol-pi.json"
    if result.source is not None and os.path.lexists(agent_file):
        try:
            read_config(agent_file)
        except ConfigError:
            result.help = [f"correct {agent_file}, or delete it and run: {_INSTALL}"]
            return result
    if not result.help:
        result.help = [_INSTALL, _UNINSTALL]
    return result
