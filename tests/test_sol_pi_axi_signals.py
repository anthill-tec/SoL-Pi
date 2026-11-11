# SPDX-License-Identifier: MIT
"""§S2 signals through the `sol-pi-axi` command line: with the writing module's test-only hook
holding a `setup` run between write and rename, `SIGINT`, `SIGTERM` and `SIGHUP` each leave no
temporary or changed file, print a `cancelled` envelope and exit 130, 143 and 129; a project
without `.pi/` still has none; a run started with `SIGINT` ignored is still cancelled by it.

The hold is reached through `HOLD_ENV` (see `tests.sol_pi_axi_support`): the run writes the
temporary file's path and a newline to the named file, then waits until that file is removed."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

from tests.sol_pi_axi_support import (
    HOLD_ENV,
    SIGNAL_IN_PARSE,
    TempTree,
    assert_clean_streams,
    cli_environ,
    decode_envelope,
    package_json_version,
    snapshot,
    venv_script,
)

EXIT_CODES = {signal.SIGINT: 130, signal.SIGTERM: 143, signal.SIGHUP: 129}
HOLD_TIMEOUT = 30.0
#: Ignores `SIGINT`, then replaces itself with `argv[1:]`: an ignored disposition survives the
#: exec, so the command starts with `SIGINT` ignored (without `preexec_fn`, unsafe with threads).
IGNORE_SIGINT_THEN_EXEC = ("import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_IGN); "
                           "os.execv(sys.argv[1], sys.argv[1:])")
#: The file the slowed `toon_format` (`SLOW_TOON_FORMAT`) holds its import on.
IMPORT_HOLD_ENV = "SOL_PI_AXI_TEST_IMPORT_HOLD"
#: A `toon_format` put first on `PYTHONPATH`: its import writes `held` and a newline to the file
#: `IMPORT_HOLD_ENV` names, waits until that file is removed, then loads the real `toon_format` in
#: its place. The command imports `toon_format` only to print a TOON envelope, so the hold stops a
#: run while its envelope is being printed.
SLOW_TOON_FORMAT = '''\
import importlib, os, sys, time
_shadow = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_hold = os.environ["SOL_PI_AXI_TEST_IMPORT_HOLD"]
with open(_hold, "w", encoding="utf-8") as _handle:
    _handle.write("held\\n")
while os.path.lexists(_hold):
    time.sleep(0.01)
sys.path[:] = [entry for entry in sys.path if os.path.abspath(entry or ".") != _shadow]
del sys.modules[__name__]
importlib.import_module(__name__)
'''
#: Runs `sol-pi-axi <argv[1:]>` in-process with `os.replace` wrapped to send the process the
#: signal `SOL_PI_AXI_TEST_SIGNAL` names right after the rename — a signal that lands once the file
#: is written, before the run has recorded it.
SIGNAL_AFTER_RENAME = '''\
import os, sys
_replace = os.replace
def replace(source, target):
    _replace(source, target)
    os.kill(os.getpid(), int(os.environ["SOL_PI_AXI_TEST_SIGNAL"]))
os.replace = replace
from sol_pi_axi import cli
sys.argv = ["sol-pi-axi", *sys.argv[1:]]
sys.exit(cli.main())
'''


class HeldRunTestCase(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        self.hold = self.tree.root / "hold"

    def start_held(self, *args, ignore_sigint: bool = False) -> tuple[subprocess.Popen, Path]:
        """Start `sol-pi-axi <args>` with the hook holding it; returns the process and the
        temporary file the hook reported, once the run is held."""
        command = [str(venv_script()), *[str(arg) for arg in args]]
        if ignore_sigint:
            command = [sys.executable, "-c", IGNORE_SIGINT_THEN_EXEC, *command]
        process = subprocess.Popen(
            command, cwd=self.tree.root,
            env=cli_environ(self.tree, **{HOLD_ENV: str(self.hold)}), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self._reap, process)
        deadline = time.monotonic() + HOLD_TIMEOUT
        while True:
            if self.hold.exists():
                text = self.hold.read_text(encoding="utf-8")
                if text.endswith("\n"):
                    return process, Path(text.strip())
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                self.fail(f"the run ended (exit {process.returncode}) before the hook held it\n"
                          f"stdout:\n{stdout}\nstderr:\n{stderr}")
            if time.monotonic() > deadline:
                self.fail(f"the hook did not hold the run within {HOLD_TIMEOUT}s ({HOLD_ENV})")
            time.sleep(0.01)

    @staticmethod
    def _reap(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.kill()
        process.communicate()

    def finish(self, process: subprocess.Popen) -> subprocess.CompletedProcess:
        try:
            stdout, stderr = process.communicate(timeout=HOLD_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            self.fail("the held run did not end after the signal")
        result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        assert_clean_streams(self, result)
        return result

    def assert_cancelled(self, result, code: int) -> None:
        self.assertEqual(result.returncode, code, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        envelope = decode_envelope(self, result.stdout)
        self.assertEqual(envelope["verb"], "setup")
        self.assertEqual(envelope["outcome"], "cancelled")
        self.assertIs(envelope["ok"], False)
        self.assertEqual(envelope["version"], package_json_version())
        self.assertIsInstance(envelope["error"], str)


class SignalCancelTest(HeldRunTestCase):
    def _cancel_over_an_existing_file(self, signum, *, ignore_sigint: bool = False) -> None:
        self.tree.write_project_file('{"version":1,"actionFusion":true}')
        before = snapshot(self.tree.project, self.tree.agent)
        process, temporary = self.start_held("setup", self.tree.project, "--features", "all",
                                             ignore_sigint=ignore_sigint)
        # Held between write and rename: the temporary file sits beside the untouched target.
        self.assertTrue(temporary.is_file(), temporary)
        self.assertEqual(temporary.parent, self.tree.pi_dir)
        self.assertEqual(self.tree.project_file.read_text(encoding="utf-8"),
                         '{"version":1,"actionFusion":true}')
        os.kill(process.pid, signum)
        result = self.finish(process)
        self.assert_cancelled(result, EXIT_CODES[signum])
        self.assertFalse(temporary.exists(), "the temporary file is removed")
        self.assertEqual(snapshot(self.tree.project, self.tree.agent), before,
                         "no temporary or changed file")

    def test_sigint_while_held_cancels_with_exit_130_changing_nothing(self):
        self._cancel_over_an_existing_file(signal.SIGINT)

    def test_sigterm_while_held_cancels_with_exit_143_changing_nothing(self):
        self._cancel_over_an_existing_file(signal.SIGTERM)

    def test_sighup_while_held_cancels_with_exit_129_changing_nothing(self):
        self._cancel_over_an_existing_file(signal.SIGHUP)

    def test_a_run_started_with_sigint_ignored_is_still_cancelled_by_sigint(self):
        self._cancel_over_an_existing_file(signal.SIGINT, ignore_sigint=True)

    def test_each_signal_in_a_project_without_dot_pi_leaves_none(self):
        self.tree.write_settings({"defaultProvider": "anthropic", "defaultModel": "claude-sonnet-4-5"})
        for signum, code in EXIT_CODES.items():
            with self.subTest(signal=signum.name):
                self.hold.unlink(missing_ok=True)
                agent_before = snapshot(self.tree.agent)
                process, temporary = self.start_held("setup", self.tree.project)
                self.assertTrue(temporary.is_file(), temporary)
                os.kill(process.pid, signum)
                result = self.finish(process)
                self.assert_cancelled(result, code)
                self.assertFalse(temporary.exists())
                self.assertFalse(os.path.lexists(self.tree.pi_dir), "the .pi/ the run created is removed")
                self.assertEqual(snapshot(self.tree.agent), agent_before)

    def test_a_released_hold_completes_the_run_with_the_held_temporary_file_renamed(self):
        self.tree.write_settings({"defaultProvider": "anthropic", "defaultModel": "claude-sonnet-4-5"})
        process, temporary = self.start_held("setup", self.tree.project)
        held_bytes = temporary.read_bytes()
        self.assertFalse(self.tree.project_file.exists(), "nothing is renamed while held")
        self.hold.unlink()
        result = self.finish(process)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(decode_envelope(self, result.stdout)["outcome"], "written")
        self.assertFalse(temporary.exists())
        self.assertEqual(self.tree.project_file.read_bytes(), held_bytes)
        self.assertEqual(sorted(os.listdir(self.tree.pi_dir)), ["sol-pi.json"])


class SignalOutsideTheWorkTest(unittest.TestCase):
    """§S4: a signal that lands before the run's work starts, or while its envelope is being
    printed, never puts a traceback on either stream; a run is cancelled only before anything is
    written, and an envelope already decided is printed once with its own exit code."""

    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        self.hold = self.tree.root / "import-hold"
        shadow = self.tree.root / "shadow"
        (shadow / "toon_format").mkdir(parents=True)
        (shadow / "toon_format" / "__init__.py").write_text(SLOW_TOON_FORMAT, encoding="utf-8")
        self.slow_environ = cli_environ(self.tree, PYTHONPATH=str(shadow),
                                        **{IMPORT_HOLD_ENV: str(self.hold)})

    def signal_while_printing(self, signum, *args) -> subprocess.CompletedProcess:
        """Run `sol-pi-axi <args>` with the envelope's printing held, send `signum`, release the
        hold and return the finished run."""
        self.hold.unlink(missing_ok=True)
        process = subprocess.Popen([str(venv_script()), *[str(arg) for arg in args]],
                                   cwd=self.tree.root, env=self.slow_environ,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        self.addCleanup(HeldRunTestCase._reap, process)
        deadline = time.monotonic() + HOLD_TIMEOUT
        while not (self.hold.exists() and self.hold.read_text(encoding="utf-8").endswith("\n")):
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                self.fail(f"the run ended (exit {process.returncode}) before printing was held\n"
                          f"stdout:\n{stdout}\nstderr:\n{stderr}")
            if time.monotonic() > deadline:
                self.fail(f"printing was not held within {HOLD_TIMEOUT}s ({IMPORT_HOLD_ENV})")
            time.sleep(0.01)
        os.kill(process.pid, signum)
        time.sleep(0.2)  # the handler runs while the import is still held
        self.hold.unlink()
        stdout, stderr = process.communicate(timeout=HOLD_TIMEOUT)
        result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        assert_clean_streams(self, result)
        return result

    def test_a_signal_while_a_usage_error_is_printed_prints_one_usage_envelope_and_exits_2(self):
        for signum in EXIT_CODES:
            with self.subTest(signal=signum.name):
                result = self.signal_while_printing(signum, "bogusverb")
                self.assertEqual(result.returncode, 2, f"{result.stdout}\n{result.stderr}")
                envelope = decode_envelope(self, result.stdout)
                self.assertEqual((envelope["verb"], envelope["outcome"]), ("usage", "usage"))
                self.assertIn("bogusverb", envelope["error"])

    def test_a_signal_while_a_written_run_is_printed_reports_written_and_exits_0(self):
        self.tree.write_settings({"defaultProvider": "anthropic", "defaultModel": "claude-sonnet-4-5"})
        for signum in EXIT_CODES:
            with self.subTest(signal=signum.name):
                shutil.rmtree(self.tree.pi_dir, ignore_errors=True)
                result = self.signal_while_printing(signum, "setup", self.tree.project)
                self.assertEqual(result.returncode, 0, f"{result.stdout}\n{result.stderr}")
                envelope = decode_envelope(self, result.stdout)
                self.assertEqual((envelope["verb"], envelope["outcome"]), ("setup", "written"))
                self.assertTrue(self.tree.project_file.is_file())

    def test_a_signal_while_the_home_view_is_printed_prints_it_and_exits_0(self):
        for signum in EXIT_CODES:
            with self.subTest(signal=signum.name):
                result = self.signal_while_printing(signum)
                self.assertEqual(result.returncode, 0, f"{result.stdout}\n{result.stderr}")
                self.assertEqual(decode_envelope(self, result.stdout)["verb"], "home")

    def test_a_signal_before_the_work_starts_cancels_the_run_writing_nothing(self):
        self.tree.write_settings({"defaultProvider": "anthropic", "defaultModel": "claude-sonnet-4-5"})
        before = snapshot(self.tree.project, self.tree.agent)
        for signum, code in EXIT_CODES.items():
            for fmt in ("toon", "json"):
                with self.subTest(signal=signum.name, format=fmt):
                    result = subprocess.run(
                        [sys.executable, "-c", SIGNAL_IN_PARSE, "setup", str(self.tree.project),
                         "--format", fmt], cwd=self.tree.root,
                        env=cli_environ(self.tree, SOL_PI_AXI_TEST_SIGNAL=str(int(signum))),
                        stdin=subprocess.DEVNULL, capture_output=True, text=True,
                        timeout=60, check=False)
                    assert_clean_streams(self, result)
                    self.assertEqual(result.returncode, code, f"{result.stdout}\n{result.stderr}")
                    if fmt == "json":
                        self.assertEqual(result.stdout.count("\n"), 1, result.stdout)
                        envelope = json.loads(result.stdout)["axi"]
                    else:
                        envelope = decode_envelope(self, result.stdout)
                    self.assertEqual((envelope["verb"], envelope["outcome"], envelope["ok"]),
                                     ("setup", "cancelled", False))
                    self.assertEqual(snapshot(self.tree.project, self.tree.agent), before)

    def test_a_signal_right_after_the_rename_reports_the_written_file(self):
        self.tree.write_settings({"defaultProvider": "anthropic", "defaultModel": "claude-sonnet-4-5"})
        for signum in EXIT_CODES:
            for existing in (False, True):
                with self.subTest(signal=signum.name, existing_dot_pi=existing):
                    shutil.rmtree(self.tree.pi_dir, ignore_errors=True)
                    if existing:
                        self.tree.write_project_file('{"version":1,"actionFusion":true}')
                    result = subprocess.run(
                        [sys.executable, "-c", SIGNAL_AFTER_RENAME, "setup",
                         str(self.tree.project), "--features", "observationPack"],
                        cwd=self.tree.root,
                        env=cli_environ(self.tree, SOL_PI_AXI_TEST_SIGNAL=str(int(signum))),
                        stdin=subprocess.DEVNULL, capture_output=True, text=True,
                        timeout=60, check=False)
                    assert_clean_streams(self, result)
                    self.assertEqual(result.returncode, 0, f"{result.stdout}\n{result.stderr}")
                    envelope = decode_envelope(self, result.stdout)
                    self.assertEqual((envelope["outcome"], envelope["ok"]), ("written", True))
                    self.assertEqual(envelope["config"]["features"], ["observationPack"])
                    self.assertEqual(os.listdir(self.tree.pi_dir), ["sol-pi.json"])
                    written = json.loads(self.tree.project_file.read_text(encoding="utf-8"))
                    self.assertIs(written["observationPack"], True)
                    self.assertIs(written["actionFusion"], False)


if __name__ == "__main__":
    unittest.main()
