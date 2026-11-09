# SPDX-License-Identifier: MIT
"""A stub `pi` for the `install` and `uninstall` tests: an executable that records every
invocation (its arguments and working directory) and edits `settings.json` as Pi 1.5.0's
`pi install` and `pi remove` do (`DefaultPackageManager.addSourceToSettings` and
`removeSourceFromSettings`, user scope):

- `--version` prints the configured version (Pi prints `1.5.0`) and exits 0.
- `install <source>`: an npm source matches an entry for the same package at any version and
  replaces it in place (an object entry keeps its other fields); a git or URL source matches the
  same `host/path`; a local path must exist, is matched by its resolved path and is stored relative
  to the agent directory. A source already recorded as given is left alone; otherwise it is
  appended. Prints `Installed <source>`.
- `remove <source>`: removes every entry matching the source (a local path is resolved against the
  working directory, as Pi resolves it); none is `No matching package found for <source>` on
  standard error and exit 1.
- `-l`/`--local` (a project-scope change) and any other command exit 97: nothing in these runs may
  ask Pi for one.
- `--mode rpc` (CR-SLP-008's check) answers as Pi 1.5.0's RPC mode does with SoL-Pi loaded: it
  writes its process id to `<directory>-rpc.pid`, appends its standard input (read to its end) to
  `<directory>-rpc-stdin.jsonl`, prints the `rpc` control's `junk` lines (non-JSON; `{value}`
  replaced by the run's value), a notify
  `extension_ui_request` carrying `sol-pi-axi verify <the run's $SOL_PI_AXI_VERIFY>` (`notify`
  `own`, the default; `previous` carries the previous `--mode rpc` run's value instead; `none`
  prints no notify), an `extension_error` line for each of `extension_errors`, and a `response`
  to each `get_state` command it read (none with `respond` false), then prints `stderr` on standard error and exits with
  `exit` (default 0; a non-zero `exit` prints nothing on standard output, as a Pi that failed to
  load an extension). `hang` never answers and never exits; `dialog` (`{method, title}`) prints
  a dialog `extension_ui_request` and then never answers or exits, as Pi blocked in
  `session_start`. `grandchild` first starts a sleeping process (the stub's interpreter, as
  `PATH` holds only the stub; standard streams on `/dev/null`, so only a kill reaches it) and writes its process id to
  `<directory>-rpc-grandchild.pid`, as a Pi that started a process of its own.
- `install <npm source>` also creates the package's directory under
  `<agent dir>/npm/node_modules/<name>` with a `package.json` (an existing one, or a symbolic
  link standing in for the package, is left alone), as Pi's npm install does.

The agent directory is `$PI_CODING_AGENT_DIR` (a leading `~` expanded) else `~/.pi/agent`, as
Pi's; `settings_dir` in the control file makes the stub act on another directory instead (a Pi
that keeps its records elsewhere). `install_exit`/`remove_exit` make the command exit with that
code, printing `stub pi: <command> <source> failed` to standard error and changing nothing.

Not a test module (its name does not match `test_*.py`)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

from tests.sol_pi_axi_support import (
    TempTree,
    assert_clean_streams,
    cli_environ,
    decode_envelope,
    import_sut,
    run_cli,
)

#: Pi's default route the tests' `settings.json` names.
PI_PROVIDER = "anthropic"
PI_MODEL = "claude-sonnet-4-5"
#: The npm package the extension ships as.
NPM_PACKAGE = "@anthill-tec/sol-pi"

#: The stub's program. `{control}` and `{log}` are filled in with the control and log files.
_STUB_PROGRAM = r'''
import json, os, sys
from pathlib import Path

CONTROL = {control}
LOG = {log}

argv = sys.argv[1:]
control = json.loads(Path(CONTROL).read_text(encoding="utf-8"))
agent = control.get("settings_dir") or os.path.expanduser(
    os.environ.get("PI_CODING_AGENT_DIR") or os.path.join("~", ".pi", "agent"))
with open(LOG, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({{"argv": argv, "cwd": os.getcwd(),
                             "agentConfigExisted": os.path.lexists(
                                 os.path.join(agent, "sol-pi.json")),
                             "verifyValue": os.environ.get("SOL_PI_AXI_VERIFY")}}) + "\n")

if "--mode" in argv:
    import time
    rpc = control.get("rpc") or {{}}
    Path(LOG[:-len("-calls.jsonl")] + "-rpc.pid").write_text(str(os.getpid()), encoding="utf-8")
    last_file = Path(LOG[:-len("-calls.jsonl")] + "-rpc-last-value")
    previous = last_file.read_text(encoding="utf-8") if last_file.exists() else "another-run"
    value = os.environ.get("SOL_PI_AXI_VERIFY", "")
    last_file.write_text(value, encoding="utf-8")

    def emit(obj):
        sys.stdout.write((obj if isinstance(obj, str) else json.dumps(obj)) + "\n")
        sys.stdout.flush()

    def forever():
        while True:
            time.sleep(3600)

    if rpc.get("grandchild"):
        import subprocess
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"],
                                 stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        grandchild_file = LOG[:-len("-calls.jsonl")] + "-rpc-grandchild.pid"
        Path(grandchild_file + ".tmp").write_text(str(child.pid), encoding="utf-8")
        os.replace(grandchild_file + ".tmp", grandchild_file)

    if rpc.get("exit"):
        if rpc.get("stderr"):
            sys.stderr.write(rpc["stderr"] + "\n")
        sys.exit(rpc["exit"])
    for line in rpc.get("junk", []):
        emit(line.replace("{{value}}", value))
    if rpc.get("hang"):
        forever()
    if rpc.get("dialog"):
        emit({{"type": "extension_ui_request", "id": "dialog-1", **rpc["dialog"]}})
        forever()
    notify = rpc.get("notify", "own")
    if notify != "none":
        carried = value if notify == "own" else previous
        emit({{"type": "extension_ui_request", "id": "notify-1", "method": "notify",
              "message": f"sol-pi-axi verify {{carried}}", "notifyType": "info"}})
    for error in rpc.get("extension_errors", []):
        emit({{"type": "extension_error", **error}})
    text = sys.stdin.read()
    with open(LOG[:-len("-calls.jsonl")] + "-rpc-stdin.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(text) + "\n")
    for line in text.splitlines():
        try:
            command = json.loads(line)
        except ValueError:
            continue
        if (isinstance(command, dict) and command.get("type") == "get_state"
                and rpc.get("respond", True)):
            emit({{"id": command.get("id"), "type": "response", "command": "get_state",
                  "success": True, "data": {{"isStreaming": False}}}})
    if rpc.get("stderr"):
        sys.stderr.write(rpc["stderr"] + "\n")
    sys.exit(0)

if "--version" in argv or "-v" in argv:
    print(control["version"])
    sys.exit(0)

if "-l" in argv or "--local" in argv:
    print("stub pi: a project-scope change was asked for", file=sys.stderr)
    sys.exit(97)
positionals = [arg for arg in argv if not arg.startswith("-")]
if len(positionals) != 2 or positionals[0] not in ("install", "remove"):
    print(f"stub pi: unsupported command {{argv}}", file=sys.stderr)
    sys.exit(97)
command, source = positionals

code = control.get(command + "_exit", 0)
if code:
    print(f"stub pi: {{command}} {{source}} failed", file=sys.stderr)
    sys.exit(code)

settings_path = Path(agent) / "settings.json"
settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {{}}
packages = list(settings.get("packages", []))


def resolve(path, base):
    return os.path.normpath(os.path.join(base, os.path.expanduser(path.strip())))


def git_key(value):
    if value.startswith("git:"):
        rest = value[4:]
    elif value.startswith(("https://", "http://", "ssh://")):
        rest = value.split("://", 1)[1]
    else:
        return None
    if rest.startswith("git@"):
        rest = rest[4:].replace(":", "/", 1)
    rest = rest.split("#", 1)[0]
    host, _, path = rest.partition("/")
    path = path.split("@", 1)[0].rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return f"git:{{host}}/{{path}}"


def key(value, base):
    value = value.strip()
    if value.startswith("npm:"):
        spec = value[4:].strip()
        at = spec.find("@", 1)
        return "npm:" + (spec if at == -1 else spec[:at])
    git = git_key(value)
    if git is not None:
        return git
    return "local:" + resolve(value, base)


def entry_source(entry):
    return entry if isinstance(entry, str) else entry["source"]


def save(next_packages):
    settings["packages"] = next_packages
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


wanted = key(source, os.getcwd())
if command == "install":
    if wanted.startswith("local:"):
        resolved = resolve(source, os.getcwd())
        if not os.path.exists(resolved):
            print(f"Error: Path does not exist: {{resolved}}", file=sys.stderr)
            sys.exit(1)
        normalized = os.path.relpath(resolved, agent)
    else:
        normalized = source
        if source.startswith("npm:"):
            name = key(source, agent)[4:]
            package_dir = Path(agent) / "npm" / "node_modules" / name
            package_dir.mkdir(parents=True, exist_ok=True)
            if not (package_dir / "package.json").exists():
                (package_dir / "package.json").write_text(
                    json.dumps({{"name": name, "version": "0.0.0-stub"}}), encoding="utf-8")
    index = next((i for i, entry in enumerate(packages)
                  if key(entry_source(entry), agent) == wanted), None)
    if index is None:
        save(packages + [normalized])
    elif entry_source(packages[index]) != normalized:
        existing = packages[index]
        packages[index] = normalized if isinstance(existing, str) else {{**existing, "source": normalized}}
        save(packages)
    print(f"Installed {{source}}")
    sys.exit(0)

remaining = [entry for entry in packages if key(entry_source(entry), agent) != wanted]
if len(remaining) == len(packages):
    print(f"No matching package found for {{source}}", file=sys.stderr)
    sys.exit(1)
save(remaining)
print(f"Removed {{source}}")
sys.exit(0)
'''


class StubPi:
    """A stub `pi` in `<root>/<directory>/pi`, its control file and its call log beside it."""

    def __init__(self, root: Path, directory: str = "stub-bin"):
        self.bin_dir = Path(root) / directory
        self.bin_dir.mkdir()
        self.path = self.bin_dir / "pi"
        self.control_file = Path(root) / f"{directory}-control.json"
        self.log = Path(root) / f"{directory}-calls.jsonl"
        self.pid_file = Path(root) / f"{directory}-rpc.pid"
        self.stdin_log = Path(root) / f"{directory}-rpc-stdin.jsonl"
        self.grandchild_file = Path(root) / f"{directory}-rpc-grandchild.pid"
        self.path.write_text(
            f"#!{sys.executable}\n"
            + _STUB_PROGRAM.format(control=repr(str(self.control_file)), log=repr(str(self.log))),
            encoding="utf-8")
        self.path.chmod(0o755)
        self.configure()

    def configure(self, *, version: str = "1.5.0", install_exit: int = 0, remove_exit: int = 0,
                  settings_dir: Path | None = None, rpc: dict | None = None) -> None:
        """`rpc` controls a `--mode rpc` start (see the module docstring): `notify` (`own`,
        `previous`, `none`), `junk`, `extension_errors`, `respond`, `hang`, `dialog`, `exit`,
        `stderr`, `grandchild`."""
        self.control_file.write_text(json.dumps({
            "version": version, "install_exit": install_exit, "remove_exit": remove_exit,
            "settings_dir": str(settings_dir) if settings_dir is not None else None,
            "rpc": rpc or {},
        }), encoding="utf-8")

    def rpc_calls(self) -> list[dict]:
        """The recorded `--mode rpc` starts, in order."""
        return [call for call in self.calls() if "--mode" in call["argv"]]

    def rpc_inputs(self) -> list[str]:
        """The standard input each answering `--mode rpc` start read, in order."""
        if not self.stdin_log.exists():
            return []
        return [json.loads(line) for line in
                self.stdin_log.read_text(encoding="utf-8").splitlines()]

    def rpc_pid(self) -> int | None:
        """The process id of the last `--mode rpc` start, None when none started."""
        if not self.pid_file.exists():
            return None
        return int(self.pid_file.read_text(encoding="utf-8"))

    def rpc_grandchild_pid(self) -> int | None:
        """The process id of the `sleep` the last `grandchild` start began, None when none."""
        if not self.grandchild_file.exists():
            return None
        return int(self.grandchild_file.read_text(encoding="utf-8"))

    def calls(self) -> list[dict]:
        """Every recorded invocation, in order: `{"argv": [...], "cwd": "...",
        "agentConfigExisted": bool}` (whether the agent directory's `sol-pi.json` existed when
        the stub started)."""
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def commands(self) -> list[list[str]]:
        """The recorded `install`/`remove` invocations' arguments without `--no-approve`, in order
        (`pi --version` left out)."""
        found = []
        for call in self.calls():
            argv = [arg for arg in call["argv"] if arg != "--no-approve"]
            if argv and argv[0] in ("install", "remove"):
                found.append(argv)
        return found

    def clear(self) -> None:
        self.log.unlink(missing_ok=True)


def read_packages(settings_dir: Path) -> list:
    """`packages` of `<settings_dir>/settings.json` (empty when the file or key is missing)."""
    path = Path(settings_dir) / "settings.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("packages", [])


def write_local_package(directory: Path, name: str) -> Path:
    """A local package directory whose `package.json` is named `name`."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "package.json").write_text(json.dumps({"name": name, "version": "0.0.1"}),
                                            encoding="utf-8")
    return directory


def stub_environ(environ: dict, *bin_dirs: Path) -> dict:
    """`environ` with `PATH` holding only `bin_dirs`, so no real `pi` is reachable."""
    result = dict(environ)
    result["PATH"] = os.pathsep.join(str(path) for path in bin_dirs)
    result.pop("PI_BIN", None)
    return result


class PiCommandTestCase(unittest.TestCase):
    """A temporary home, project and agent directory, a stub `pi` as the only `pi` on `PATH`
    (no `$PI_BIN`), and `sol-pi-axi` run from the project directory. Holds no tests."""

    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)
        self.pi = StubPi(self.tree.root)

    # --- values ---------------------------------------------------------------------------

    def own_version(self) -> str:
        return import_sut("sol_pi_axi._version").__version__

    def own_source(self) -> str:
        return f"npm:{NPM_PACKAGE}@{self.own_version()}"

    def with_pi_default(self, packages: list | None = None) -> None:
        """`settings.json` naming Pi's default route, and `packages` when given."""
        settings: dict = {"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL}
        if packages is not None:
            settings["packages"] = packages
        self.tree.write_settings(settings)

    def packages(self) -> list:
        return read_packages(self.tree.agent)

    # --- running --------------------------------------------------------------------------

    def environ(self, **extra: str) -> dict:
        return stub_environ(cli_environ(self.tree, **extra), self.pi.bin_dir)

    def sol(self, *args, cwd=None, env=None):
        """Run `sol-pi-axi <args>` from the project directory; neither stream may carry a
        traceback or dependency message."""
        result = run_cli(args, tree=self.tree, cwd=cwd if cwd is not None else self.tree.project,
                         env=env if env is not None else self.environ())
        assert_clean_streams(self, result)
        return result

    def envelope(self, result) -> dict:
        return decode_envelope(self, result.stdout)

    def assert_exit(self, result, code: int) -> None:
        self.assertEqual(result.returncode, code,
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")

    def assert_every_pi_call_from_home_with_no_approve(self, stub: StubPi | None = None) -> None:
        """Every recorded `pi` invocation ran with the home directory as its working directory
        and `--no-approve` exactly once among its arguments, and none asked for project scope."""
        calls = (stub or self.pi).calls()
        self.assertTrue(calls, "no pi command was recorded")
        for call in calls:
            with self.subTest(argv=call["argv"]):
                self.assertEqual(call["cwd"], str(self.tree.home))
                self.assertEqual(call["argv"].count("--no-approve"), 1, call["argv"])
                self.assertNotIn("-l", call["argv"])
                self.assertNotIn("--local", call["argv"])
