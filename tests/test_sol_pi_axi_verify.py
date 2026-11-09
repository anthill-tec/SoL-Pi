# SPDX-License-Identifier: MIT
"""`sol-pi-axi verify` and the check `install` runs last: Pi's record and the package on disk
checked first, then `pi --offline --no-approve --mode rpc --no-session` started from home with
`SOL_PI_AXI_VERIFY` set to a value unique to the run and one `get_state` command on standard input,
bounded at 30 seconds; SoL-Pi's load signal (`sol-pi-axi verify <value>`, an
`extension_ui_request` notify line) proves it loaded.

Stub runs use `tests.sol_pi_axi_stub_pi`'s stub `pi` (its `--mode rpc` answer). Real-Pi runs use
the development dependency's `pi` through `$PI_BIN`, with a temporary home and agent directory
registering this checkout as a local path.

The contract these tests fix for the implementation:

- The check lives in `sol_pi_axi.check`: `VERIFY_TIMEOUT` is 30 (seconds) and
  `run_check(agent_dir: Path, *, timeout: float = VERIFY_TIMEOUT) -> CheckResult`, finding Pi as
  `sol_pi_axi.pi.find_pi` does and running it from `Path.home()`. A `CheckResult` has `ok`
  (bool), `loaded` (bool), `exit` (int, None when Pi was killed or not started), `errors` (list of
  `{extensionPath, event, error}` dicts, SoL-Pi's own handler errors only), `error` (str, None when
  ok) and `warnings` (list of str: another extension's `extension_error`, naming its path).
- The value of `SOL_PI_AXI_VERIFY` is generated per run (non-empty, different on every run).
- The envelope's `verify` key is exactly `{ok, loaded, exit, errors}`; `verify` runs print `verb:
  verify`, `ok`, `outcome` (`verified`, `failed`, `cancelled`), `verify`, `extension`
  (`{state: absent}` or `{state: registered, source}`), `context` `{agentDir}`, `error` on
  failure, `warnings`, `help`. `install`'s envelope carries `verify`, null when the run did not
  reach the check."""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.sol_pi_axi_stub_pi import (
    NPM_PACKAGE,
    PI_MODEL,
    PI_PROVIDER,
    PiCommandTestCase,
    read_packages,
    write_local_package,
)
from tests.sol_pi_axi_support import (
    REPO,
    assert_clean_streams,
    cli_environ,
    decode_envelope,
    import_sut,
    snapshot,
    venv_script,
)

EXIT_CODES = {signal.SIGINT: 130, signal.SIGTERM: 143, signal.SIGHUP: 129}
#: Runs `sol-pi-axi <argv[1:]>` in-process with `_parse` wrapped to send the process the signal
#: `SOL_PI_AXI_TEST_SIGNAL` names first.
SIGNAL_IN_PARSE = '''\
import os, signal, sys
from sol_pi_axi import cli
_parse = cli._parse
def parse(args):
    os.kill(os.getpid(), int(os.environ["SOL_PI_AXI_TEST_SIGNAL"]))
    return _parse(args)
cli._parse = parse
sys.argv = ["sol-pi-axi", *sys.argv[1:]]
sys.exit(cli.main())
'''
#: Runs `sol-pi-axi <argv[1:]>` in-process with `sol_pi_axi.check.run_check` raising an unexpected
#: error.
CHECK_RAISES = '''\
import sys
from sol_pi_axi import check, cli
def run_check(*args, **kwargs):
    raise RuntimeError("the check broke")
check.run_check = run_check
sys.argv = ["sol-pi-axi", *sys.argv[1:]]
sys.exit(cli.main())
'''
RPC_ARGV = ["--offline", "--no-approve", "--mode", "rpc", "--no-session"]
GET_STATE = {"id": "sol-pi-axi", "type": "get_state"}
INSTALL = "sol-pi-axi install"
UNINSTALL = "sol-pi-axi uninstall"
CHECKOUT_EXTENSION = Path("src") / "sol-pi" / "index.ts"


def development_pi() -> Path:
    """The development dependency's `pi`: `$PI_BIN` when set (relative to the repository), else
    `node_modules/.bin/pi`."""
    configured = os.environ.get("PI_BIN") or "node_modules/.bin/pi"
    path = Path(configured)
    return path if path.is_absolute() else REPO / path


def process_alive(pid: int | None) -> bool:
    """Whether a process (a zombie included) with `pid` still exists; a missing pid fails the
    caller's assertion through `AssertionError`."""
    if pid is None:
        raise AssertionError("the stub pi never started in rpc mode")
    return os.path.exists(f"/proc/{pid}")


def process_gone(pid: int | None, within: float = 5.0) -> bool:
    """Whether the process `pid` is gone, or a zombie no longer running, within `within` seconds:
    a process another parent reaps (a grandchild handed to init once its parent died) may stay in
    the process table a moment after it was killed. A missing pid fails the caller's assertion."""
    if pid is None:
        raise AssertionError("the stub pi started no process to look for")
    deadline = time.monotonic() + within
    while True:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            return True
        if stat.rsplit(")", 1)[-1].split()[0] == "Z":
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def wait_for(probe, within: float = 20.0):
    """`probe()`'s first non-None value within `within` seconds, else None."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        value = probe()
        if value is not None:
            return value
        time.sleep(0.05)
    return None


def kill_quietly(pid: int | None) -> None:
    if pid is None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGKILL)


def write_extension(directory: Path, name: str, source: str) -> Path:
    """A Pi package in `directory` named `name` whose one extension, `index.ts`, is `source`."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "package.json").write_text(json.dumps({
        "name": name, "version": "0.0.1", "pi": {"extensions": ["./index.ts"]}}), encoding="utf-8")
    (directory / "index.ts").write_text(source, encoding="utf-8")
    return directory


THROW_ON_LOAD = 'throw new Error("boom on load");\n'
THROW_IN_SESSION_START = ('export default function (pi) {\n'
                          '  pi.on("session_start", () => { throw new Error("boom in session_start"); });\n'
                          '}\n')
VALID_CONFIG = (REPO / "sol-pi.example.json").read_bytes()


class VerifyTestCase(PiCommandTestCase):
    """The stub `pi` on `PATH`; the own npm source registered with its package on disk unless a
    test changes it."""

    def setUp(self):
        super().setUp()
        self.addCleanup(lambda: kill_quietly(self.pi.rpc_pid()))
        self.addCleanup(lambda: kill_quietly(self.pi.rpc_grandchild_pid()))

    @property
    def package_dir(self) -> Path:
        return self.tree.agent / "npm" / "node_modules" / "@anthill-tec" / "sol-pi"

    def register_npm(self) -> None:
        write_local_package(self.package_dir, NPM_PACKAGE)
        self.with_pi_default([self.own_source()])

    def assert_verify(self, result, outcome: str, code: int) -> dict:
        self.assert_exit(result, code)
        envelope = self.envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("verify", code == 0, outcome))
        self.assertEqual(envelope["context"], {"agentDir": str(self.tree.agent)})
        self.assertIsInstance(envelope["warnings"], list)
        self.assertIsInstance(envelope["help"], list)
        self.assertIsInstance(envelope["verify"], dict, envelope)
        self.assertEqual(sorted(envelope["verify"]), ["errors", "exit", "loaded", "ok"])
        self.assertIs(envelope["verify"]["ok"], code == 0)
        if code == 0:
            self.assertNotIn("error", envelope)
        else:
            self.assertIsInstance(envelope["error"], str)
        return envelope


# --- The check, against the stub ----------------------------------------------------------------

class VerifyStubTest(VerifyTestCase):
    """§S2/§S3 with the stub `pi`'s `--mode rpc` answer."""

    def test_a_loaded_sol_pi_is_verified_with_exit_0(self):
        self.register_npm()
        result = self.sol("verify")
        envelope = self.assert_verify(result, "verified", 0)
        self.assertEqual(envelope["verify"], {"ok": True, "loaded": True, "exit": 0, "errors": []})
        self.assertEqual(envelope["extension"], {"state": "registered", "source": self.own_source()})

    def test_pi_starts_once_in_rpc_mode_from_home_with_the_runs_value_and_one_get_state(self):
        self.register_npm()
        self.assert_exit(self.sol("verify"), 0)
        starts = self.pi.rpc_calls()
        self.assertEqual(len(starts), 1, self.pi.calls())
        self.assertEqual(starts[0]["argv"], RPC_ARGV)
        self.assertEqual(starts[0]["cwd"], str(self.tree.home))
        self.assertTrue(starts[0]["verifyValue"], "SOL_PI_AXI_VERIFY was unset or empty")
        inputs = self.pi.rpc_inputs()
        self.assertEqual(len(inputs), 1)
        lines = inputs[0].splitlines()
        self.assertEqual(len(lines), 1, inputs[0])
        self.assertEqual(json.loads(lines[0]), GET_STATE)

    def test_every_run_sets_a_different_value(self):
        self.register_npm()
        self.assert_exit(self.sol("verify"), 0)
        self.assert_exit(self.sol("verify"), 0)
        values = [call["verifyValue"] for call in self.pi.rpc_calls()]
        self.assertEqual(len(values), 2, self.pi.calls())
        self.assertTrue(all(values), values)
        self.assertNotEqual(values[0], values[1])

    def test_verify_runs_no_pi_install_or_remove_and_writes_no_sol_pi_file(self):
        self.register_npm()
        self.tree.agent_file.write_bytes(VALID_CONFIG)
        watched = [self.tree.agent_file, self.tree.settings_file, self.package_dir]
        before = snapshot(*watched)
        result = self.sol("verify")
        self.assert_verify(result, "verified", 0)
        self.assertEqual(self.pi.commands(), [], "verify ran pi install or pi remove")
        self.assertEqual(snapshot(*watched), before)
        self.assertFalse(self.tree.project_file.exists())

    def test_a_notify_carrying_another_runs_value_does_not_count_as_loaded(self):
        self.register_npm()
        self.pi.configure(rpc={"notify": "previous"})
        result = self.sol("verify")
        envelope = self.assert_verify(result, "failed", 1)
        self.assertEqual(envelope["verify"], {"ok": False, "loaded": False, "exit": 0, "errors": []})
        self.assertIn("without loading SoL-Pi", envelope["error"])

    def test_no_notify_fails_saying_pi_started_without_loading_sol_pi(self):
        self.register_npm()
        self.pi.configure(rpc={"notify": "none"})
        envelope = self.assert_verify(self.sol("verify"), "failed", 1)
        self.assertIs(envelope["verify"]["loaded"], False)
        self.assertIn("without loading SoL-Pi", envelope["error"])
        self.assertIn(INSTALL, envelope["help"])
        self.assertIn(UNINSTALL, envelope["help"])

    def test_non_json_lines_are_ignored(self):
        self.register_npm()
        self.pi.configure(rpc={"junk": ["Debugger attached.", "{not json", "[1, 2"]})
        envelope = self.assert_verify(self.sol("verify"), "verified", 0)
        self.assertEqual(envelope["verify"], {"ok": True, "loaded": True, "exit": 0, "errors": []})

    def test_a_non_json_line_carrying_the_signal_text_is_not_the_signal(self):
        self.register_npm()
        self.pi.configure(rpc={"notify": "none", "junk": ["sol-pi-axi verify {value}"]})
        envelope = self.assert_verify(self.sol("verify"), "failed", 1)
        self.assertIs(envelope["verify"]["loaded"], False)

    def test_no_get_state_response_fails(self):
        self.register_npm()
        self.pi.configure(rpc={"respond": False})
        envelope = self.assert_verify(self.sol("verify"), "failed", 1)
        self.assertIn("get_state", envelope["error"])

    def test_a_non_zero_exit_fails_quoting_the_failed_to_load_line(self):
        self.register_npm()
        line = 'Error: Failed to load extension "/x/other/index.ts": Failed to load extension: boom'
        self.pi.configure(rpc={"exit": 1, "stderr": line + "\nHint: Start without extensions."})
        envelope = self.assert_verify(self.sol("verify"), "failed", 1)
        self.assertEqual(envelope["verify"], {"ok": False, "loaded": False, "exit": 1, "errors": []})
        self.assertIn('Failed to load extension "/x/other/index.ts"', envelope["error"])

    def test_an_extension_error_inside_the_sol_pi_package_fails_and_is_listed(self):
        self.register_npm()
        error = {"extensionPath": str(self.package_dir / CHECKOUT_EXTENSION),
                 "event": "session_start", "error": "SoL-Pi config version must be 1"}
        self.pi.configure(rpc={"extension_errors": [error]})
        envelope = self.assert_verify(self.sol("verify"), "failed", 1)
        self.assertEqual(envelope["verify"], {"ok": False, "loaded": True, "exit": 0,
                                              "errors": [error]})

    def test_another_extensions_error_is_a_warning_naming_its_path(self):
        self.register_npm()
        other = str(self.tree.root / "other" / "index.ts")
        self.pi.configure(rpc={"extension_errors": [
            {"extensionPath": other, "event": "session_start", "error": "boom"}]})
        envelope = self.assert_verify(self.sol("verify"), "verified", 0)
        self.assertEqual(envelope["verify"]["errors"], [])
        self.assertEqual(len([w for w in envelope["warnings"] if other in w]), 1, envelope["warnings"])

    def test_format_json_prints_one_json_line(self):
        self.register_npm()
        result = self.sol("verify", "--format", "json")
        self.assert_exit(result, 0)
        self.assertEqual(result.stdout.count("\n"), 1, result.stdout)
        envelope = json.loads(result.stdout)["axi"]
        self.assertEqual((envelope["verb"], envelope["outcome"]), ("verify", "verified"))
        self.assertEqual(envelope["verify"], {"ok": True, "loaded": True, "exit": 0, "errors": []})

    def test_a_confirm_dialog_holding_the_start_fails_after_the_bound_naming_it(self):
        """The CLI's own 30-second bound: the stub opens a `confirm` dialog and never answers."""
        self.register_npm()
        self.pi.configure(rpc={"dialog": {"method": "confirm", "title": "Allow the frobnicator?",
                                          "message": "really?"}})
        started = time.monotonic()
        result = self.sol("verify")
        elapsed = time.monotonic() - started
        envelope = self.assert_verify(result, "failed", 1)
        self.assertGreaterEqual(elapsed, 29.0)
        self.assertLess(elapsed, 55.0)
        self.assertIsNone(envelope["verify"]["exit"])
        self.assertIn("confirm", envelope["error"])
        self.assertIn("Allow the frobnicator?", envelope["error"])
        pid = self.pi.rpc_pid()
        self.assertIsNotNone(pid)
        self.assertFalse(process_alive(pid), "the pi process outlived the run")


class VerifyBeforeStartTest(VerifyTestCase):
    """§S2 Pi's record: these fail with exit 1 before any `--mode rpc` start."""

    def assert_failed_before_start(self, result) -> dict:
        envelope = self.assert_verify(result, "failed", 1)
        self.assertEqual(self.pi.rpc_calls(), [], "Pi was started")
        self.assertEqual(envelope["verify"], {"ok": False, "loaded": False, "exit": None,
                                              "errors": []})
        return envelope

    def test_no_sol_pi_entry(self):
        self.with_pi_default(["npm:pi-unrelated@1.0.0"])
        envelope = self.assert_failed_before_start(self.sol("verify"))
        self.assertRegex(envelope["error"], r"(?i)no SoL-Pi source|not registered")
        self.assertIn(INSTALL, envelope["help"])
        self.assertEqual(envelope["extension"]["state"], "absent")

    def test_two_sol_pi_entries(self):
        write_local_package(self.tree.root / "checkout", NPM_PACKAGE)
        write_local_package(self.package_dir, NPM_PACKAGE)
        self.with_pi_default([self.own_source(), "../checkout"])
        envelope = self.assert_failed_before_start(self.sol("verify"))
        self.assertIn(self.own_source(), envelope["error"])
        self.assertIn("../checkout", envelope["error"])

    def test_an_npm_sol_pi_entry(self):
        self.with_pi_default(["npm:sol-pi"])
        envelope = self.assert_failed_before_start(self.sol("verify"))
        self.assertIn("npm:sol-pi", envelope["error"])
        self.assertIn(INSTALL, envelope["help"])

    def test_a_git_entry_naming_anthill_tec_sol_pi(self):
        source = "git:github.com/anthill-tec/SoL-Pi"
        self.with_pi_default([source])
        envelope = self.assert_failed_before_start(self.sol("verify"))
        self.assertIn(source, envelope["error"])
        self.assertIn(INSTALL, envelope["help"])

    def test_an_npm_entry_with_no_package_directory(self):
        self.with_pi_default([self.own_source()])
        envelope = self.assert_failed_before_start(self.sol("verify"))
        self.assertIn(str(self.package_dir), envelope["error"])


class VerifyBoundTest(VerifyTestCase):
    """§S2's bound, through `sol_pi_axi.check.run_check` with a short `timeout`."""

    def run_check(self, timeout: float):
        check = import_sut("sol_pi_axi.check")
        environ = {"HOME": str(self.tree.home), "PI_CODING_AGENT_DIR": str(self.tree.agent),
                   "PI_BIN": str(self.pi.path)}
        with mock.patch.dict(os.environ, environ):
            return check.run_check(self.tree.agent, timeout=timeout)

    def test_the_bound_is_30_seconds_by_default(self):
        import inspect

        check = import_sut("sol_pi_axi.check")
        self.assertEqual(check.VERIFY_TIMEOUT, 30)
        default = inspect.signature(check.run_check).parameters["timeout"].default
        self.assertEqual(default, 30)

    def test_a_start_that_never_answers_fails_after_the_bound_with_no_pi_process_left(self):
        """Pi and the process it started are both killed: the stub's `sleep` grandchild too."""
        self.register_npm()
        self.pi.configure(rpc={"hang": True, "grandchild": True})
        started = time.monotonic()
        result = self.run_check(1.0)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 1.0)
        self.assertLess(elapsed, 15.0)
        self.assertIs(result.ok, False)
        self.assertIs(result.loaded, False)
        self.assertIsNone(result.exit)
        self.assertIsInstance(result.error, str)
        pid = self.pi.rpc_pid()
        self.assertIsNotNone(pid, "the stub pi never started in rpc mode")
        self.assertFalse(process_alive(pid), "the pi process was not killed and reaped")
        self.assertTrue(process_gone(self.pi.rpc_grandchild_pid()),
                        "the process pi started outlived the bound")

    def test_a_confirm_dialog_names_its_method_and_title_and_that_pi_does_not_name_the_extension(self):
        self.register_npm()
        self.pi.configure(rpc={"dialog": {"method": "confirm", "title": "Proceed with setup?",
                                          "message": "yes?"}})
        result = self.run_check(1.0)
        self.assertIs(result.ok, False)
        self.assertIsNone(result.exit)
        self.assertIn("confirm", result.error)
        self.assertIn("Proceed with setup?", result.error)
        self.assertRegex(result.error, r"(?i)does not name the extension")
        self.assertFalse(process_alive(self.pi.rpc_pid()))

    def test_an_answering_start_returns_the_result_fields(self):
        self.register_npm()
        result = self.run_check(10.0)
        self.assertEqual((result.ok, result.loaded, result.exit, result.errors, result.error),
                         (True, True, 0, [], None))
        self.assertEqual(result.warnings, [])


class VerifyUsageTest(VerifyTestCase):
    """§S3: only `--format` is accepted; the help text and valid-verb lists name `verify`."""

    def test_any_flag_but_format_exits_2(self):
        self.register_npm()
        for flag in (["--non-interactive"], ["--features", "all"], ["--reducer", "a/b"],
                     ["--cache-ratio", "4"], ["--bogus"]):
            with self.subTest(flag=flag):
                result = self.sol("verify", *flag)
                self.assert_exit(result, 2)
                envelope = self.envelope(result)
                self.assertEqual((envelope["verb"], envelope["outcome"]), ("usage", "usage"))
                self.assertIn(flag[0], envelope["error"])
                # The flag is refused, not the verb.
                self.assertNotRegex(envelope["error"], r"unknown verb")
        self.assertEqual(self.pi.calls(), [], "a pi command ran on a usage error")

    def test_an_unknown_verb_lists_verify_among_the_valid_verbs(self):
        envelope = self.envelope(self.sol("frobnicate"))
        self.assertEqual(envelope["verb"], "usage")
        self.assertRegex(envelope["error"], r"\bverify\b")

    def test_the_help_text_describes_verify(self):
        result = self.sol("--help")
        self.assert_exit(result, 0)
        self.assertRegex(result.stdout, r"(?m)^\s+verify\b")

    def test_each_signal_cancels_verify_with_its_exit_code_and_starts_no_pi(self):
        self.register_npm()
        for signum, code in EXIT_CODES.items():
            with self.subTest(signal=signum.name):
                result = subprocess.run(
                    [sys.executable, "-c", SIGNAL_IN_PARSE, "verify"], cwd=self.tree.project,
                    env=self.environ(SOL_PI_AXI_TEST_SIGNAL=str(int(signum))),
                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False)
                assert_clean_streams(self, result)
                self.assert_exit(result, code)
                envelope = decode_envelope(self, result.stdout)
                self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                                 ("verify", False, "cancelled"))
                self.assertEqual(self.pi.rpc_calls(), [])


class SignalWhilePiRunsTest(VerifyTestCase):
    """§S3/§S4: SIGINT, SIGTERM or SIGHUP arriving while Pi runs the check cancels the run with
    130/143/129 and leaves neither Pi nor a process it started."""

    def signal_while_pi_runs(self, verb: str, signum: int):
        """Run `sol-pi-axi <verb>` with the stub hanging after starting its `sleep` grandchild;
        once the grandchild runs, send the command `signum`. Returns the finished run."""
        for path in (self.pi.pid_file, self.pi.grandchild_file):
            path.unlink(missing_ok=True)
        process = subprocess.Popen([str(venv_script()), verb], cwd=self.tree.project,
                                   env=self.environ(), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            grandchild = wait_for(self.pi.rpc_grandchild_pid)
            if grandchild is None:
                process.kill()
                stdout, stderr = process.communicate()
                self.fail(f"pi never started its process:\n{stdout}\n{stderr}")
            process.send_signal(signum)
            stdout, stderr = process.communicate(timeout=20)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        assert_clean_streams(self, result)
        self.assertFalse(process_alive(self.pi.rpc_pid()), "the pi process outlived the cancel")
        self.assertTrue(process_gone(grandchild), "the process pi started outlived the cancel")
        return result

    def test_each_signal_while_pi_runs_cancels_verify_and_leaves_no_pi_process(self):
        self.register_npm()
        self.pi.configure(rpc={"hang": True, "grandchild": True})
        for signum, code in EXIT_CODES.items():
            with self.subTest(signal=signum.name):
                result = self.signal_while_pi_runs("verify", signum)
                self.assert_exit(result, code)
                envelope = decode_envelope(self, result.stdout)
                self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                                 ("verify", False, "cancelled"))
                self.assertEqual(envelope["error"], f"cancelled by {signum.name}")
                self.assertEqual(envelope["verify"], {"ok": False, "loaded": False, "exit": None,
                                                      "errors": []})

    def test_each_signal_during_installs_check_cancels_it_and_leaves_no_pi_process(self):
        self.with_pi_default()
        self.pi.configure(rpc={"hang": True, "grandchild": True})
        for signum, code in EXIT_CODES.items():
            with self.subTest(signal=signum.name):
                result = self.signal_while_pi_runs("install", signum)
                self.assert_exit(result, code)
                envelope = decode_envelope(self, result.stdout)
                self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                                 ("install", False, "cancelled"))
                self.assertEqual(envelope["error"], f"cancelled by {signum.name}")
                self.assertIn("verify", envelope)
                self.assertIsNone(envelope["verify"])
                self.assertEqual(envelope["extension"]["registered"], True)
                self.assertEqual(self.packages(), [self.own_source()])


class UnexpectedCheckErrorTest(VerifyTestCase):
    """An unexpected error in the check is a named `failed` envelope, as in the other verbs: never
    only `main`'s last-guard line on standard error."""

    def run_raising(self, verb: str):
        result = subprocess.run(
            [sys.executable, "-c", CHECK_RAISES, verb], cwd=self.tree.project,
            env=self.environ(), stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=60, check=False)
        assert_clean_streams(self, result)
        self.assert_exit(result, 1)
        return decode_envelope(self, result.stdout)

    def test_verify_reports_a_failed_envelope_with_its_verify_key(self):
        self.register_npm()
        envelope = self.run_raising("verify")
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("verify", False, "failed"))
        self.assertEqual(envelope["verify"], {"ok": False, "loaded": False, "exit": None,
                                              "errors": []})
        self.assertEqual(envelope["error"], "unexpected RuntimeError: the check broke")
        self.assertEqual(envelope["extension"], {"state": "registered", "source": self.own_source()})
        self.assertEqual(envelope["context"], {"agentDir": str(self.tree.agent)})
        self.assertEqual(envelope["help"], [INSTALL, UNINSTALL])

    def test_install_reports_a_failed_envelope_keeping_registration_and_configuration(self):
        self.with_pi_default()
        envelope = self.run_raising("install")
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("install", False, "failed"))
        self.assertEqual(envelope["verify"], {"ok": False, "loaded": False, "exit": None,
                                              "errors": []})
        self.assertEqual(envelope["error"], "unexpected RuntimeError: the check broke")
        self.assertEqual(envelope["extension"]["source"], self.own_source())
        self.assertEqual(envelope["extension"]["registered"], True)
        self.assertEqual(envelope["config"]["state"], "written")
        self.assertEqual(self.packages(), [self.own_source()], "the registration was removed")
        self.assertTrue(self.tree.agent_file.is_file(), "the configuration was removed")
        self.assertEqual(envelope["help"], [INSTALL, UNINSTALL])


# --- install runs the check (stub) --------------------------------------------------------------

class InstallCheckStubTest(VerifyTestCase):
    """§S4 with the stub `pi`."""

    def test_an_installed_run_ends_with_the_check(self):
        self.with_pi_default()
        result = self.sol("install")
        self.assert_exit(result, 0)
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "installed")
        self.assertEqual(envelope["verify"], {"ok": True, "loaded": True, "exit": 0, "errors": []})
        calls = self.pi.calls()
        self.assertEqual(len(self.pi.rpc_calls()), 1, calls)
        self.assertEqual(calls[-1]["argv"], RPC_ARGV, "the check was not the run's last pi command")
        self.assertEqual(calls[-1]["cwd"], str(self.tree.home))
        self.assertTrue(calls[-1]["agentConfigExisted"], "the check ran before sol-pi.json was written")

    def test_an_unchanged_run_runs_the_check(self):
        self.with_pi_default()
        self.assert_exit(self.sol("install"), 0)
        self.pi.clear()
        result = self.sol("install")
        self.assert_exit(result, 0)
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "unchanged")
        self.assertEqual(envelope["verify"], {"ok": True, "loaded": True, "exit": 0, "errors": []})
        self.assertEqual(len(self.pi.rpc_calls()), 1)

    def test_a_failed_check_fails_the_run_and_leaves_registration_and_configuration(self):
        self.with_pi_default()
        self.pi.configure(rpc={"notify": "none"})
        result = self.sol("install")
        self.assert_exit(result, 1)
        envelope = self.envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("install", False, "failed"))
        self.assertEqual(envelope["verify"], {"ok": False, "loaded": False, "exit": 0, "errors": []})
        self.assertIn("without loading SoL-Pi", envelope["error"])
        self.assertEqual(envelope["extension"]["registered"], True)
        self.assertEqual(envelope["config"]["state"], "written")
        self.assertEqual(self.packages(), [self.own_source()], "the registration was removed")
        self.assertTrue(self.tree.agent_file.is_file(), "the configuration was removed")
        self.assertEqual(self.pi.commands(), [["install", self.own_source()]], "a pi remove ran")
        self.assertIn(INSTALL, envelope["help"])
        self.assertIn(UNINSTALL, envelope["help"])

    def test_a_run_failing_before_registering_has_verify_null_and_starts_no_pi(self):
        self.with_pi_default(["npm:sol-pi"])
        self.pi.configure(install_exit=1)
        result = self.sol("install")
        self.assert_exit(result, 1)
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "failed")
        self.assertIn("verify", envelope)
        self.assertIsNone(envelope["verify"])
        self.assertEqual(self.pi.rpc_calls(), [])

    def test_mode_rpc_is_named_in_the_package_source(self):
        """§S4: `git grep -n -- '--mode rpc' sol_pi_axi/` returns a non-test line."""
        result = subprocess.run(["git", "grep", "-n", "--", "--mode rpc", "sol_pi_axi/"], cwd=REPO,
                                capture_output=True, text=True, check=False)
        lines = [line for line in result.stdout.splitlines() if line and "test" not in line.split(":")[0]]
        self.assertGreaterEqual(len(lines), 1, result.stdout + result.stderr)


# --- Real Pi ------------------------------------------------------------------------------------

class RealPiTestCase(VerifyTestCase):
    """The development dependency's `pi` through `$PI_BIN`, a temporary home and agent directory."""

    def setUp(self):
        super().setUp()
        self.real_pi = development_pi()
        self.assertTrue(self.real_pi.exists(), f"the development dependency's pi is missing: {self.real_pi}")
        node = shutil.which("node")
        self.assertIsNotNone(node, "node is not on PATH")
        self.node_dir = os.path.dirname(str(node))

    def real_environ(self, pi_bin: Path | None = None) -> dict:
        return cli_environ(self.tree, PATH=self.node_dir, PI_OFFLINE="1",
                           PI_BIN=str(pi_bin if pi_bin is not None else self.real_pi))

    def register(self, *entries) -> None:
        self.tree.write_settings({"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL,
                                  "packages": list(entries)})

    def verify(self):
        return self.sol("verify", env=self.real_environ())


class VerifyRealPiTest(RealPiTestCase):
    """§S2 with the real Pi, the checkout registered as a local path."""

    def test_a_valid_sol_pi_json_is_verified(self):
        self.register(str(REPO))
        self.tree.agent_file.write_bytes(VALID_CONFIG)
        envelope = self.assert_verify(self.verify(), "verified", 0)
        self.assertEqual(envelope["verify"], {"ok": True, "loaded": True, "exit": 0, "errors": []})
        self.assertEqual(envelope["extension"], {"state": "registered", "source": str(REPO)})

    def test_an_invalid_sol_pi_json_fails_with_its_session_start_error_and_is_left_unchanged(self):
        self.register(str(REPO))
        self.tree.agent_file.write_text('{"version":2}', encoding="utf-8")
        before = snapshot(self.tree.agent_file)
        envelope = self.assert_verify(self.verify(), "failed", 1)
        self.assertIs(envelope["verify"]["loaded"], True)
        errors = envelope["verify"]["errors"]
        self.assertEqual(len(errors), 1, errors)
        self.assertEqual(errors[0]["event"], "session_start")
        self.assertTrue(errors[0]["extensionPath"].endswith(str(CHECKOUT_EXTENSION)), errors[0])
        self.assertTrue(any(str(self.tree.agent_file) in step for step in envelope["help"]),
                        envelope["help"])
        self.assertEqual(snapshot(self.tree.agent_file), before)

    def test_an_entry_with_no_extensions_fails_as_not_loaded(self):
        self.register({"source": str(REPO), "extensions": []})
        envelope = self.assert_verify(self.verify(), "failed", 1)
        self.assertIs(envelope["verify"]["loaded"], False)
        self.assertIn("without loading SoL-Pi", envelope["error"])

    def test_an_entry_excluding_index_ts_fails_as_not_loaded(self):
        self.register({"source": str(REPO), "extensions": ["!**/index.ts"]})
        envelope = self.assert_verify(self.verify(), "failed", 1)
        self.assertIs(envelope["verify"]["loaded"], False)
        self.assertIn("without loading SoL-Pi", envelope["error"])

    def test_a_second_extension_throwing_on_load_fails_naming_its_path(self):
        bad = write_extension(self.tree.root / "bad-load", "bad-load", THROW_ON_LOAD)
        self.register(str(REPO), str(bad))
        envelope = self.assert_verify(self.verify(), "failed", 1)
        self.assertEqual(envelope["verify"]["exit"], 1)
        self.assertIn("Failed to load extension", envelope["error"])
        self.assertIn(str(bad / "index.ts"), envelope["error"])

    def test_a_second_extension_throwing_in_session_start_is_a_warning(self):
        bad = write_extension(self.tree.root / "bad-session", "bad-session", THROW_IN_SESSION_START)
        self.register(str(REPO), str(bad))
        envelope = self.assert_verify(self.verify(), "verified", 0)
        self.assertEqual(envelope["verify"], {"ok": True, "loaded": True, "exit": 0, "errors": []})
        self.assertTrue(any(str(bad / "index.ts") in warning for warning in envelope["warnings"]),
                        envelope["warnings"])

    def test_a_trusted_homes_throwing_extension_is_not_loaded(self):
        bad = write_extension(self.tree.root / "bad-load", "bad-load", THROW_ON_LOAD)
        self.register(str(REPO))
        (self.tree.agent / "trust.json").write_text(json.dumps({str(self.tree.home): True}),
                                                    encoding="utf-8")
        (self.tree.home / ".pi").mkdir()
        (self.tree.home / ".pi" / "settings.json").write_text(
            json.dumps({"packages": [str(bad)]}), encoding="utf-8")
        envelope = self.assert_verify(self.verify(), "verified", 0)
        self.assertEqual(envelope["verify"], {"ok": True, "loaded": True, "exit": 0, "errors": []})

    def test_the_checkout_registered_through_a_symbolic_link_reports_its_own_error(self):
        link = self.tree.root / "checkout-link"
        link.symlink_to(REPO, target_is_directory=True)
        self.register(str(link))
        self.tree.agent_file.write_text('{"version":2}', encoding="utf-8")
        envelope = self.assert_verify(self.verify(), "failed", 1)
        errors = envelope["verify"]["errors"]
        self.assertEqual(len(errors), 1, errors)
        self.assertEqual(errors[0]["event"], "session_start")
        self.assertFalse(any("session_start" in warning and "index.ts" in warning
                             for warning in envelope["warnings"]), envelope["warnings"])


class InstallRealPiTest(RealPiTestCase):
    """§S4 with the real Pi starting for the check. The npm package is not published (and the run
    is offline), so `pi install`/`pi remove`/`pi --version` go to the stub while `--mode rpc` goes
    to the real Pi; the package directory the npm install would create is a symbolic link to this
    checkout."""

    def setUp(self):
        super().setUp()
        self.package_dir.parent.mkdir(parents=True)
        self.package_dir.symlink_to(REPO, target_is_directory=True)
        self.router = self.tree.root / "router-bin" / "pi"
        self.router.parent.mkdir()
        self.router.write_text(
            "#!/bin/sh\n"
            'for arg in "$@"; do\n'
            f'  [ "$arg" = "--mode" ] && exec {self.real_pi} "$@"\n'
            "done\n"
            f'exec {self.pi.path} "$@"\n', encoding="utf-8")
        self.router.chmod(0o755)
        self.with_pi_default()

    def install(self):
        return self.sol("install", env=self.real_environ(self.router))

    def test_install_is_installed_with_the_check_ok(self):
        result = self.install()
        self.assert_exit(result, 0)
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "installed")
        self.assertEqual(envelope["verify"], {"ok": True, "loaded": True, "exit": 0, "errors": []})

    def test_a_second_run_is_unchanged_with_a_verify_result(self):
        self.assert_exit(self.install(), 0)
        result = self.install()
        self.assert_exit(result, 0)
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "unchanged")
        self.assertIsNotNone(envelope["verify"])
        self.assertIs(envelope["verify"]["ok"], True)

    def test_an_invalid_sol_pi_json_fails_the_run_and_is_left_unchanged(self):
        self.tree.agent_file.write_text('{"version":2}', encoding="utf-8")
        before = snapshot(self.tree.agent_file)
        result = self.install()
        self.assert_exit(result, 1)
        envelope = self.envelope(result)
        self.assertEqual((envelope["ok"], envelope["outcome"]), (False, "failed"))
        self.assertIs(envelope["verify"]["loaded"], True)
        self.assertEqual([error["event"] for error in envelope["verify"]["errors"]], ["session_start"])
        self.assertEqual(snapshot(self.tree.agent_file), before)
        self.assertEqual(read_packages(self.tree.agent), [self.own_source()])

    def test_a_run_failing_before_registering_has_verify_null(self):
        self.pi.configure(install_exit=1)
        result = self.install()
        self.assert_exit(result, 1)
        envelope = self.envelope(result)
        self.assertIn("verify", envelope)
        self.assertIsNone(envelope["verify"])


if __name__ == "__main__":
    unittest.main()
