# SPDX-License-Identifier: MIT
"""§S2 signals through the `sol-pi-axi` command line: with the writing module's test-only hook
holding a `setup` run between write and rename, `SIGINT`, `SIGTERM` and `SIGHUP` each leave no
temporary or changed file, print a `cancelled` envelope and exit 130, 143 and 129; a project
without `.pi/` still has none; a run started with `SIGINT` ignored is still cancelled by it.

The hold is reached through `HOLD_ENV` (see `tests.sol_pi_axi_support`): the run writes the
temporary file's path and a newline to the named file, then waits until that file is removed."""

import os
import signal
import subprocess
import time
import unittest
from pathlib import Path

from tests.sol_pi_axi_support import (
    HOLD_ENV,
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


class HeldRunTestCase(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        self.hold = self.tree.root / "hold"

    def start_held(self, *args, ignore_sigint: bool = False) -> tuple[subprocess.Popen, Path]:
        """Start `sol-pi-axi <args>` with the hook holding it; returns the process and the
        temporary file the hook reported, once the run is held."""
        preexec = (lambda: signal.signal(signal.SIGINT, signal.SIG_IGN)) if ignore_sigint else None
        process = subprocess.Popen(
            [str(venv_script()), *[str(arg) for arg in args]], cwd=self.tree.root,
            env=cli_environ(self.tree, **{HOLD_ENV: str(self.hold)}), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=preexec)
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


if __name__ == "__main__":
    unittest.main()
