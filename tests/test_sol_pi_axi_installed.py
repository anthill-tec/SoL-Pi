# SPDX-License-Identifier: MIT
"""§S1 — the wheel installed with `uv tool install` into a temporary `UV_TOOL_DIR` and
`UV_TOOL_BIN_DIR` (both under a temporary home): `--version` prints `package.json`'s version,
`setup <temporary project>` writes the file and prints a decodable envelope, no arguments prints a
decodable home view; and the installed script's `--version` is fast — the median of five runs at
most twice the median of five `<same interpreter> -c pass` runs."""

import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests import test_sol_pi_axi_package as package_tests
from tests.sol_pi_axi_support import (
    TempTree,
    assert_clean_streams,
    cli_environ,
    decode_envelope,
    package_json_version,
    run_cli,
)

_INSTALL: dict = {}


def installed_tool() -> tuple[Path, Path]:
    """`uv tool install` the built wheel once per run: (the temporary home, the installed
    `sol-pi-axi` in `UV_TOOL_BIN_DIR`). A failed install fails every test that needs it."""
    if "error" in _INSTALL:
        raise AssertionError(_INSTALL["error"])
    if "result" not in _INSTALL:
        wheel, _ = package_tests.build_distributions()
        root = Path(os.path.realpath(tempfile.mkdtemp(prefix="sol-pi-axi-tool-")))
        _INSTALL["dir"] = root
        home = root / "home"
        tool_dir = home / ".local" / "share" / "uv" / "tools"
        bin_dir = home / ".local" / "bin"
        environ = dict(os.environ, UV_TOOL_DIR=str(tool_dir), UV_TOOL_BIN_DIR=str(bin_dir))
        environ.pop("VIRTUAL_ENV", None)
        result = subprocess.run(["uv", "tool", "install", "--python", sys.executable, str(wheel)],
                                env=environ, capture_output=True, text=True, timeout=300,
                                check=False)
        script = bin_dir / "sol-pi-axi"
        if result.returncode != 0 or not os.path.lexists(script):
            _INSTALL["error"] = (f"uv tool install exit {result.returncode}, script {script}\n"
                                 f"{result.stdout}\n{result.stderr}")
            raise AssertionError(_INSTALL["error"])
        _INSTALL["result"] = (home, script)
    return _INSTALL["result"]


def tearDownModule():
    if "dir" in _INSTALL:
        shutil.rmtree(_INSTALL["dir"], ignore_errors=True)
    package_tests.tearDownModule()


class InstalledToolTest(unittest.TestCase):
    def setUp(self):
        self.home, self.script = installed_tool()
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)

    def environ(self) -> dict:
        return cli_environ(self.tree, HOME=str(self.home))

    def run_tool(self, *args, cwd=None):
        result = run_cli(args, tree=self.tree, cwd=cwd, env=self.environ(), script=self.script)
        assert_clean_streams(self, result)
        return result

    def test_installed_version_prints_package_json_version(self):
        result = self.run_tool("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"{package_json_version()}\n")

    def test_installed_setup_writes_the_file_and_prints_a_decodable_envelope(self):
        self.tree.write_settings({"defaultProvider": "anthropic", "defaultModel": "claude-sonnet-4-5"})
        result = self.run_tool("setup", self.tree.project)
        self.assertEqual(result.returncode, 0, f"{result.stdout}\n{result.stderr}")
        envelope = decode_envelope(self, result.stdout)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("setup", True, "written"))
        self.assertEqual(envelope["path"], str(self.tree.project_file))
        self.assertEqual(envelope["version"], package_json_version())
        self.assertTrue(self.tree.project_file.is_file())
        self.assertIn(b'"evidencePreservingReducerProvider": "anthropic"',
                      self.tree.project_file.read_bytes())

    def test_installed_without_arguments_prints_a_decodable_home_view_with_bin_under_tilde(self):
        result = self.run_tool(cwd=self.tree.project)
        self.assertEqual(result.returncode, 0, f"{result.stdout}\n{result.stderr}")
        envelope = decode_envelope(self, result.stdout)
        self.assertEqual((envelope["verb"], envelope["ok"]), ("home", True))
        self.assertTrue(envelope["bin"].startswith("~/"), envelope["bin"])
        self.assertTrue(envelope["bin"].endswith("sol-pi-axi"), envelope["bin"])
        self.assertNotIn(str(self.home), envelope["bin"])
        self.assertEqual(envelope["project"], {"path": str(self.tree.project_file), "state": "absent"})

    def test_installed_version_median_is_at_most_twice_a_bare_interpreter_start(self):
        shebang = Path(os.path.realpath(self.script)).read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(shebang.startswith("#!"), shebang)
        interpreter = shebang[2:].strip().split()[0]
        environ = self.environ()

        def timed(command: list[str], expected_stdout: str) -> float:
            started = time.perf_counter()
            result = subprocess.run(command, env=environ, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=60, check=False)
            elapsed = time.perf_counter() - started
            self.assertEqual((result.returncode, result.stdout), (0, expected_stdout), result.stderr)
            return elapsed

        version = f"{package_json_version()}\n"
        # One untimed run of each warms the file cache.
        timed([str(self.script), "--version"], version)
        timed([interpreter, "-c", "pass"], "")
        script_runs = [timed([str(self.script), "--version"], version) for _ in range(5)]
        bare_runs = [timed([interpreter, "-c", "pass"], "") for _ in range(5)]
        script_median = statistics.median(script_runs)
        bare_median = statistics.median(bare_runs)
        self.assertLessEqual(script_median, 2 * bare_median,
                             f"script {script_runs} vs bare {bare_runs}")


if __name__ == "__main__":
    unittest.main()
