# SPDX-License-Identifier: MIT
"""The `integration` tier of the Python tests: the modules that start a real process or a
pseudo-terminal — the `sol-pi-axi` console script, the Pi stubs, a real Pi under Node, `uv`, the
pseudo-terminal harness.

The Python Crucible client declares a tier by its discovery invocation, so this directory is that
declaration:

    python3 ~/.crucible/clients/python-crucible.py integration --agent <id> --start-dir tests/integration

This directory carries no `__init__.py`, so the full-suite discovery (`regression`, and the
release workflow's `unittest discover -s tests`) never descends into it and runs each module once.
Each module is loaded exactly as that full-suite discovery loads it (top-level directory `tests`),
so a test keeps one name on every tier.
"""

import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent

#: The test modules of the tier, by file name under `tests/`.
INTEGRATION = (
    "test_pty_harness.py",
    "test_sol_pi_axi_cli.py",
    "test_sol_pi_axi_home_extension.py",
    "test_sol_pi_axi_install.py",
    "test_sol_pi_axi_installed.py",
    "test_sol_pi_axi_interactive.py",
    "test_sol_pi_axi_package.py",
    "test_sol_pi_axi_signals.py",
    "test_sol_pi_axi_uninstall.py",
    "test_sol_pi_axi_verify.py",
    "test_sol_pi_axi_written_form.py",
)


def load_tests(loader, standard_tests, pattern):
    missing = [name for name in INTEGRATION if not (TESTS / name).is_file()]
    if missing:
        raise FileNotFoundError(f"integration tier names missing test modules: {', '.join(missing)}")
    suite = unittest.TestSuite()
    for name in INTEGRATION:
        suite.addTests(unittest.TestLoader().discover(str(TESTS), pattern=name, top_level_dir=str(TESTS)))
    return suite
