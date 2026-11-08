# SPDX-License-Identifier: MIT
"""§S1 — the `sol-pi-axi` Python package: its distributions (`uv build`), its version (equal to
`package.json`'s, read by `stamp_version.py`), its editable install, `.gitignore`, and that no
`sol_pi_axi` module starts `bun` or `node` or imports Node or Pi code."""

import ast
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

# isort: split
# tomllib is standard library from Python 3.11; a sorter without a target version files it apart.
import tomllib

from tests.sol_pi_axi_support import REPO, TempTree, import_sut, package_json_version

PACKAGE_DIR = REPO / "sol_pi_axi"
_BUILD: dict = {}


def build_distributions() -> tuple[Path, Path]:
    """`uv build` the repository root once per run into a temporary directory: (wheel, sdist).
    A failed build fails every test that needs it, each with uv's own output."""
    if "error" in _BUILD:
        raise AssertionError(_BUILD["error"])
    if "result" not in _BUILD:
        out = Path(tempfile.mkdtemp(prefix="sol-pi-axi-build-"))
        result = subprocess.run(["uv", "build", "--out-dir", str(out)], cwd=REPO,
                                capture_output=True, text=True, timeout=300, check=False)
        wheels = sorted(out.glob("*.whl"))
        sdists = sorted(out.glob("*.tar.gz"))
        if result.returncode != 0 or len(wheels) != 1 or len(sdists) != 1:
            _BUILD["error"] = (f"uv build exit {result.returncode}, wheels {wheels}, sdists {sdists}\n"
                               f"{result.stdout}\n{result.stderr}")
            raise AssertionError(_BUILD["error"])
        _BUILD["result"] = (wheels[0], sdists[0])
        _BUILD["dir"] = out
    return _BUILD["result"]


def tearDownModule():
    """Delete the build and forget it: the installed tool's tests import this module and call
    this teardown, and under `discover -t .` both share one module object, so a cached result
    left behind would name deleted files."""
    directory = _BUILD.get("dir")
    _BUILD.clear()
    if directory is not None:
        shutil.rmtree(directory, ignore_errors=True)


def wheel_metadata(wheel: Path) -> tuple[list[str], str, str]:
    """The wheel's member names, its METADATA text and its entry_points.txt text."""
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        info = [name for name in names if re.fullmatch(r"sol_pi_axi-[^/]+\.dist-info/METADATA", name)]
        if len(info) != 1:
            raise AssertionError(f"expected one dist-info METADATA, got {info}")
        dist_info = info[0].rsplit("/", 1)[0]
        metadata = archive.read(info[0]).decode("utf-8")
        entry_points = archive.read(f"{dist_info}/entry_points.txt").decode("utf-8")
    return names, metadata, entry_points


def metadata_headers(metadata: str, name: str) -> list[str]:
    head = metadata.split("\n\n", 1)[0]
    return [line.split(":", 1)[1].strip() for line in head.splitlines() if line.startswith(f"{name}:")]


class DistributionTest(unittest.TestCase):
    """`uv build`: the wheel holds only `sol_pi_axi/` and metadata, with the console script,
    `Requires-Python: >=3.14` and one requirement `toon-format==1.2.0`; the sdist holds only
    `pyproject.toml`, `README.md`, `LICENSE`, `sol_pi_axi/`, and the `PKG-INFO` and `.gitignore`
    hatchling always adds."""

    def test_wheel_holds_only_the_sol_pi_axi_package_and_its_metadata(self):
        wheel, _ = build_distributions()
        names, _, _ = wheel_metadata(wheel)
        stray = [name for name in names
                 if not name.startswith("sol_pi_axi/")
                 and not re.match(r"sol_pi_axi-[^/]+\.dist-info/", name)]
        self.assertEqual(stray, [])
        self.assertIn("sol_pi_axi/__init__.py", names)
        self.assertIn("sol_pi_axi/_version.py", names)

    def test_wheel_declares_the_sol_pi_axi_console_script(self):
        wheel, _ = build_distributions()
        _, _, entry_points = wheel_metadata(wheel)
        section = entry_points.split("[console_scripts]", 1)
        self.assertEqual(len(section), 2, entry_points)
        scripts = [line.replace(" ", "") for line in section[1].splitlines()
                   if line.strip() and not line.startswith("[")]
        self.assertEqual(scripts, ["sol-pi-axi=sol_pi_axi.cli:main"])

    def test_wheel_requires_python_3_14_and_exactly_toon_format_1_2_0_at_runtime(self):
        wheel, _ = build_distributions()
        _, metadata, _ = wheel_metadata(wheel)
        self.assertEqual(metadata_headers(metadata, "Name"), ["sol-pi-axi"])
        self.assertEqual(metadata_headers(metadata, "Version"), [package_json_version()])
        self.assertEqual(metadata_headers(metadata, "Requires-Python"), [">=3.14"])
        requires = metadata_headers(metadata, "Requires-Dist")
        runtime = [req for req in requires if "extra ==" not in req]
        self.assertEqual(runtime, ["toon-format==1.2.0"])

    def test_wheel_has_a_dev_extra_with_xmlrunner_and_coverage(self):
        wheel, _ = build_distributions()
        _, metadata, _ = wheel_metadata(wheel)
        self.assertIn("dev", metadata_headers(metadata, "Provides-Extra"))
        dev = [re.split(r"[ ;<>=!~\[]", req, maxsplit=1)[0]
               for req in metadata_headers(metadata, "Requires-Dist") if "extra == 'dev'" in req
               or 'extra == "dev"' in req]
        self.assertEqual(sorted(dev), ["coverage", "unittest-xml-reporting"])

    def test_wheel_is_mit_licensed_with_the_license_file(self):
        wheel, _ = build_distributions()
        names, metadata, _ = wheel_metadata(wheel)
        licenses = metadata_headers(metadata, "License-Expression") + metadata_headers(metadata, "License")
        self.assertEqual(licenses, ["MIT"])
        self.assertTrue(any(re.fullmatch(r"sol_pi_axi-[^/]+\.dist-info/licenses/LICENSE", name)
                            for name in names), names)
        self.assertEqual(metadata_headers(metadata, "Description-Content-Type"), ["text/markdown"])

    def test_sdist_holds_only_pyproject_readme_license_the_package_and_hatchlings_additions(self):
        _, sdist = build_distributions()
        with tarfile.open(sdist) as archive:
            members = [member.name for member in archive.getmembers() if not member.isdir()]
        prefix = f"sol_pi_axi-{package_json_version()}/"
        self.assertTrue(all(name.startswith(prefix) for name in members), members)
        relative = sorted(name[len(prefix):] for name in members)
        # PKG-INFO and .gitignore: hatchling adds both to every sdist, and §S1 allows them.
        allowed = {"pyproject.toml", "README.md", "LICENSE", "PKG-INFO", ".gitignore"}
        stray = [name for name in relative if name not in allowed and not name.startswith("sol_pi_axi/")]
        self.assertEqual(stray, [])
        for required in ("pyproject.toml", "README.md", "LICENSE",
                         "sol_pi_axi/__init__.py", "sol_pi_axi/_version.py"):
            self.assertIn(required, relative)


class ProjectMetadataTest(unittest.TestCase):
    """`pyproject.toml` and `sol_pi_axi/_version.py` as §S1 declares them."""

    def _pyproject(self) -> dict:
        return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))

    def test_pyproject_declares_the_distribution_hatchling_and_the_dynamic_version_file(self):
        pyproject = self._pyproject()
        project = pyproject["project"]
        self.assertEqual(project["name"], "sol-pi-axi")
        self.assertEqual(project["requires-python"], ">=3.14")
        self.assertEqual(project["readme"], "README.md")
        self.assertEqual(project["dependencies"], ["toon-format==1.2.0"])
        self.assertEqual(project["scripts"], {"sol-pi-axi": "sol_pi_axi.cli:main"})
        self.assertIn("version", project["dynamic"])
        self.assertNotIn("version", project)
        self.assertEqual(pyproject["build-system"]["build-backend"], "hatchling.build")
        self.assertEqual(pyproject["tool"]["hatch"]["version"]["path"], "sol_pi_axi/_version.py")

    def test_version_file_is_one_literal_with_no_imports_equal_to_package_json(self):
        source = (PACKAGE_DIR / "_version.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertFalse([node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))])
        self.assertRegex(source, rf'(?m)^__version__ = "{re.escape(package_json_version())}"$')

    def test_dunder_version_equals_package_json_version(self):
        version = import_sut("sol_pi_axi._version")
        self.assertEqual(version.__version__, package_json_version())

    def test_stamp_version_reads_the_pypi_version_source(self):
        result = subprocess.run([sys.executable, ".github/scripts/stamp_version.py", "read", "pypi:."],
                                cwd=REPO, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout, f"pypi:.\t{package_json_version()}\n")

    def test_the_tests_import_the_package_from_an_editable_install_of_this_checkout(self):
        package = import_sut("sol_pi_axi")
        self.assertIsNotNone(package.__file__)
        self.assertEqual(Path(str(package.__file__)).resolve(), PACKAGE_DIR / "__init__.py")
        distribution = importlib.metadata.distribution("sol-pi-axi")
        self.assertEqual(distribution.version, package_json_version())
        direct_url = json.loads(distribution.read_text("direct_url.json") or "{}")
        self.assertEqual(direct_url.get("dir_info"), {"editable": True})
        self.assertEqual(Path(direct_url["url"].removeprefix("file://")).resolve(), REPO)

    def test_gitignore_ignores_the_venv_and_egg_info(self):
        lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".venv/", lines)
        self.assertIn("*.egg-info/", lines)


#: Commands that start Bun or Node, which no module may name as a command.
_NODE_COMMANDS = {"bun", "bunx", "node", "nodejs", "npm", "npx", "pnpm", "yarn", "tsx", "deno"}
#: Every command the PATH trap catches: the Node commands and Pi's own launcher, a Node program.
_TRAPPED_COMMANDS = _NODE_COMMANDS | {"pi"}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


class NoNodeOrPiCodeTest(unittest.TestCase):
    """No `sol_pi_axi` module starts `bun` or `node` or imports Node or Pi code."""

    def _modules(self) -> list[Path]:
        modules = sorted(PACKAGE_DIR.rglob("*.py"))
        self.assertIn(PACKAGE_DIR / "__init__.py", modules)
        return modules

    def test_every_module_imports_only_the_standard_library_toon_format_and_itself(self):
        allowed = set(sys.stdlib_module_names) | {"toon_format", "sol_pi_axi"}
        found = {}
        for path in self._modules():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    if name.split(".")[0] not in allowed:
                        found.setdefault(str(path.relative_to(REPO)), []).append(name)
        self.assertEqual(found, {})

    def test_no_module_names_a_node_command_or_node_and_pi_sources(self):
        found = []
        for path in self._modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str) \
                        or id(node) in docstrings:
                    continue
                words = node.value.split()
                command = os.path.basename(words[0]) if words else ""
                if command in _NODE_COMMANDS or re.search(
                        r"node_modules|@earendil-works|src/sol-pi|\.(?:ts|mjs|cjs|js)\b", node.value):
                    found.append((str(path.relative_to(REPO)), node.value))
        self.assertEqual(found, [])

    def test_importing_every_module_and_running_setup_starts_no_node_command(self):
        tree = TempTree()
        self.addCleanup(tree.cleanup)
        fake_bin = tree.root / "bin"
        fake_bin.mkdir()
        marker = tree.root / "started"
        for command in sorted(_TRAPPED_COMMANDS):
            script = fake_bin / command
            script.write_text(f'#!/bin/sh\necho "{command} $*" >> "{marker}"\n', encoding="utf-8")
            script.chmod(0o700)
        tree.write_settings({"defaultProvider": "anthropic", "defaultModel": "claude-sonnet-4-5"})
        program = (
            "import importlib, pkgutil, sys\n"
            "import sol_pi_axi\n"
            "for info in pkgutil.walk_packages(sol_pi_axi.__path__, 'sol_pi_axi.'):\n"
            "    if not info.name.endswith('.__main__'):  # importing it would run the command\n"
            "        importlib.import_module(info.name)\n"
            "from sol_pi_axi.setup import run_setup\n"
            "print(run_setup(sys.argv[1], agent_dir=sys.argv[2]).outcome)\n"
        )
        environ = {"PATH": str(fake_bin), "HOME": str(tree.home), "PI_CODING_AGENT_DIR": str(tree.agent)}
        result = subprocess.run([sys.executable, "-c", program, str(tree.project), str(tree.agent)],
                                cwd=REPO, env=environ, capture_output=True, text=True, timeout=60,
                                check=False)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "written"), result.stderr)
        self.assertFalse(marker.exists(), marker.read_text() if marker.exists() else "")
        self.assertTrue(tree.project_file.is_file())


if __name__ == "__main__":
    unittest.main()
