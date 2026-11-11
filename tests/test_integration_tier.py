# SPDX-License-Identifier: MIT
"""The `integration` tier of the Python tests (`tests/integration/test_integration.py`) is a
hand-kept list of test modules. A `tests/test_*.py` module belongs to it when it imports
`subprocess` or `pty`, uses `tests/pty_harness.py` or `tests/sol_pi_axi_stub_pi.py`, or calls
`run_cli` or `venv_script` from `tests/sol_pi_axi_support.py`.

The rule reads a module's syntax tree, not its raw text: an import or a call counts, a docstring,
comment or string that merely names one does not. So this module — which starts no process and is
therefore deliberately not in the tier — holds its fixture sources as strings without matching the
rule itself."""

import ast
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
TIER_FILE = TESTS / "integration" / "test_integration.py"
TIER_NAME = "tests/integration/test_integration.py"

#: Standard-library modules whose import starts a process or a pseudo-terminal.
PROCESS_MODULES = frozenset({"subprocess", "pty"})
#: The test-support modules that start one: the pseudo-terminal harness and the stub `pi`.
HARNESS_MODULES = frozenset({"pty_harness", "sol_pi_axi_stub_pi"})
#: The helpers of `tests/sol_pi_axi_support.py` that run the `sol-pi-axi` console script.
PROCESS_HELPERS = frozenset({"run_cli", "venv_script"})


def _imported_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        return [module, *(f"{module}.{alias.name}" if module else alias.name for alias in node.names)]
    return []


def _called_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def starts_a_process(source: str) -> bool:
    """Whether a test module's source starts a process or a pseudo-terminal, by the tier's rule."""
    for node in ast.walk(ast.parse(source)):
        for name in _imported_names(node):
            parts = [part for part in name.split(".") if part]
            if parts and (parts[0] in PROCESS_MODULES or HARNESS_MODULES.intersection(parts)):
                return True
        if _called_name(node) in PROCESS_HELPERS:
            return True
    return False


def listed_modules(tier_source: str) -> tuple[str, ...]:
    """The `INTEGRATION` tuple of the tier file, read from its source without importing it."""
    for node in ast.parse(tier_source).body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "INTEGRATION" for target in node.targets)):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError(f"{TIER_NAME} declares no INTEGRATION list")


def tier_mismatches(modules: dict[str, str], listed) -> list[str]:
    """Every disagreement between the rule and the list: a selected module missing from the list, a
    listed module that does not exist, a listed module the rule does not select."""
    listed_set = set(listed)
    missing = [f"{name} starts a process but is missing from {TIER_NAME}"
               for name, source in modules.items()
               if starts_a_process(source) and name not in listed_set]
    extra = []
    for name in listed_set:
        if name not in modules:
            extra.append(f"{name} is listed in {TIER_NAME} but does not exist")
        elif not starts_a_process(modules[name]):
            extra.append(f"{name} is listed in {TIER_NAME} but starts no process")
    return sorted(missing + extra)


def code(*lines: str) -> str:
    return "\n".join(lines) + "\n"


class IntegrationTierRuleTest(unittest.TestCase):
    def test_a_module_importing_subprocess_or_pty_is_selected(self):
        self.assertIs(starts_a_process(code("import subprocess")), True)
        self.assertIs(starts_a_process(code("import os, pty")), True)
        self.assertIs(starts_a_process(code("from subprocess import run, PIPE")), True)
        self.assertIs(starts_a_process(code("def f():", "    import pty", "    return pty")), True)

    def test_a_module_using_the_pty_harness_or_the_stub_pi_is_selected(self):
        self.assertIs(starts_a_process(code("from tests.pty_harness import PtyRun")), True)
        self.assertIs(starts_a_process(code("from tests.sol_pi_axi_stub_pi import PiCommandTestCase")), True)
        self.assertIs(starts_a_process(code("from tests import sol_pi_axi_stub_pi")), True)
        self.assertIs(starts_a_process(code("import tests.pty_harness as harness")), True)

    def test_a_module_calling_run_cli_or_venv_script_is_selected(self):
        self.assertIs(starts_a_process(code("from tests.sol_pi_axi_support import run_cli",
                                            "result = run_cli(['--version'], tree=tree)")), True)
        self.assertIs(starts_a_process(code("from tests.sol_pi_axi_support import venv_script",
                                            "script = str(venv_script())")), True)
        self.assertIs(starts_a_process(code("from tests import sol_pi_axi_support as support",
                                            "support.run_cli([])")), True)

    def test_a_module_only_importing_the_support_helpers_or_naming_the_rule_in_text_is_not_selected(self):
        source = code(
            '"""Runs `sol-pi-axi` the way `tests.pty_harness` and the stub pi would, with subprocess."""',
            "import json",
            "import os",
            "from tests.sol_pi_axi_support import TempTree, import_sut, run_cli",
            "# subprocess.run(['pi']) and venv_script() are only mentioned here",
            "TEXT = 'import subprocess; run_cli([])'",
            "cli = import_sut('sol_pi_axi.cli')",
        )
        self.assertIs(starts_a_process(source), False)

    def test_the_tier_list_is_read_from_the_integration_tuple(self):
        source = code('"""Tier."""', "OTHER = ('test_x.py',)",
                      "INTEGRATION = (", "    'test_a.py',", "    'test_b.py',", ")")
        self.assertEqual(listed_modules(source), ("test_a.py", "test_b.py"))

    def test_a_tier_file_without_an_integration_tuple_fails_naming_the_file(self):
        with self.assertRaises(AssertionError) as raised:
            listed_modules(code("OTHER = ('test_a.py',)"))
        self.assertEqual(str(raised.exception), f"{TIER_NAME} declares no INTEGRATION list")

    def test_nothing_is_reported_when_the_list_holds_exactly_the_selected_modules(self):
        modules = {"test_spawns.py": code("import subprocess"), "test_pure.py": code("import json")}
        self.assertEqual(tier_mismatches(modules, ("test_spawns.py",)), [])

    def test_a_process_starting_module_left_out_of_the_list_is_named(self):
        modules = {
            "test_spawns.py": code("import subprocess"),
            "test_terminal.py": code("from tests.pty_harness import PtyRun"),
            "test_pure.py": code("import json"),
        }
        self.assertEqual(tier_mismatches(modules, ("test_terminal.py",)), [
            f"test_spawns.py starts a process but is missing from {TIER_NAME}",
        ])

    def test_a_listed_module_that_starts_no_process_is_named(self):
        modules = {"test_spawns.py": code("import pty"), "test_pure.py": code("import json")}
        self.assertEqual(tier_mismatches(modules, ("test_spawns.py", "test_pure.py")), [
            f"test_pure.py is listed in {TIER_NAME} but starts no process",
        ])

    def test_a_listed_module_that_does_not_exist_is_named(self):
        modules = {"test_spawns.py": code("import subprocess")}
        self.assertEqual(tier_mismatches(modules, ("test_spawns.py", "test_gone.py")), [
            f"test_gone.py is listed in {TIER_NAME} but does not exist",
        ])

    def test_every_disagreement_is_named_at_once(self):
        modules = {
            "test_a.py": code("import subprocess"),
            "test_b.py": code("from tests.sol_pi_axi_support import venv_script", "venv_script()"),
            "test_c.py": code("import json"),
        }
        self.assertEqual(tier_mismatches(modules, ("test_c.py", "test_d.py")), [
            f"test_a.py starts a process but is missing from {TIER_NAME}",
            f"test_b.py starts a process but is missing from {TIER_NAME}",
            f"test_c.py is listed in {TIER_NAME} but starts no process",
            f"test_d.py is listed in {TIER_NAME} but does not exist",
        ])


class IntegrationTierListTest(unittest.TestCase):
    def test_this_module_starts_no_process_so_it_is_not_in_the_tier(self):
        self.assertIs(starts_a_process(Path(__file__).read_text(encoding="utf-8")), False)
        self.assertNotIn(Path(__file__).name, listed_modules(TIER_FILE.read_text(encoding="utf-8")))

    def test_the_integration_tier_lists_exactly_the_test_modules_that_start_a_process(self):
        modules = {path.name: path.read_text(encoding="utf-8") for path in sorted(TESTS.glob("test_*.py"))}
        listed = listed_modules(TIER_FILE.read_text(encoding="utf-8"))
        mismatches = tier_mismatches(modules, listed)
        self.assertEqual(mismatches, [], "\n".join(mismatches))


if __name__ == "__main__":
    unittest.main()
