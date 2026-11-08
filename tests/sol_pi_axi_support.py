# SPDX-License-Identifier: MIT
"""Shared helpers for the `sol_pi_axi` tests: repository paths, values read from the repository
(never duplicated here), the guarded import of the package under test, and file-tree snapshots.

Not a test module (its name does not match `test_*.py`)."""

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "sol-pi-config"


def import_sut(name: str):
    """Import a `sol_pi_axi` module inside a test, so a module that does not exist yet fails that
    test with its ModuleNotFoundError rather than the whole module's collection."""
    return importlib.import_module(name)


def package_json_version() -> str:
    return json.loads((REPO / "package.json").read_text(encoding="utf-8"))["version"]


def example_key_order() -> list[str]:
    """Every configuration key, in `sol-pi.example.json`'s order."""
    return list(json.loads((REPO / "sol-pi.example.json").read_text(encoding="utf-8")))


def feature_keys() -> list[str]:
    """The four mechanism keys: the example's boolean-valued keys, in its order."""
    example = json.loads((REPO / "sol-pi.example.json").read_text(encoding="utf-8"))
    return [key for key, value in example.items() if isinstance(value, bool)]


def _ts_joined_constant(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"export const {name} = \[([^\]]*)\]\.join\(\"-\"\);", text)
    if match is None:
        raise AssertionError(f"{name} not found in {path}")
    return "-".join(json.loads(f"[{match.group(1)}]"))


_REDUCER_CONFIG = REPO / "src" / "sol-pi" / "extensions" / "evidence-preserving-reducer" / "config.ts"


def default_reducer_provider() -> str:
    """`DEFAULT_REDUCER_PROVIDER`, read from the TypeScript source."""
    return _ts_joined_constant(_REDUCER_CONFIG, "DEFAULT_REDUCER_PROVIDER")


def default_reducer_model() -> str:
    """`DEFAULT_REDUCER_MODEL`, read from the TypeScript source."""
    return _ts_joined_constant(_REDUCER_CONFIG, "DEFAULT_REDUCER_MODEL")


def default_cache_ratio() -> float:
    """`DEFAULT_CACHE_WRITE_READ_RATIO`, read from the TypeScript source."""
    text = (REPO / "src" / "sol-pi" / "config.ts").read_text(encoding="utf-8")
    match = re.search(r"export const DEFAULT_CACHE_WRITE_READ_RATIO = ([0-9.]+);", text)
    if match is None:
        raise AssertionError("DEFAULT_CACHE_WRITE_READ_RATIO not found in src/sol-pi/config.ts")
    return float(match.group(1))


def render_js(values: dict) -> bytes:
    """`JSON.stringify(values, null, "\\t") + "\\n"` for a flat object of strings, booleans and
    numbers, keys in `values`' order — the written form."""
    return (json.dumps(values, indent="\t", ensure_ascii=False) + "\n").encode("utf-8")


def assert_same_json_values(test, actual: dict, expected: dict) -> None:
    """Equal values with JavaScript's types: a boolean must be a `bool`, a number an `int` or
    `float` that is not a `bool`, and a string a `str` (Python counts `True == 1`)."""
    test.assertIsInstance(actual, dict)
    test.assertEqual(sorted(actual), sorted(expected), "effective keys")
    for key, want in expected.items():
        got = actual[key]
        if isinstance(want, bool):
            test.assertIs(type(got), bool, f"{key} must be a boolean, got {got!r}")
            test.assertIs(got, want, key)
        elif isinstance(want, (int, float)):
            test.assertIn(type(got), (int, float), f"{key} must be a number, got {got!r}")
            test.assertEqual(got, want, key)
        else:
            test.assertIs(type(got), str, f"{key} must be a string, got {got!r}")
            test.assertEqual(got, want, key)


def snapshot(*roots: Path) -> dict:
    """Every path under `roots` (the roots included): its kind, bytes or link target, mode and
    modification time — to prove a run changed nothing."""
    state = {}
    for root in roots:
        if not os.path.lexists(root):
            state[str(root)] = None
            continue
        paths = [Path(root)]
        if Path(root).is_dir() and not Path(root).is_symlink():
            for dirpath, dirnames, filenames in os.walk(root):
                paths.extend(Path(dirpath) / name for name in dirnames + filenames)
        for path in paths:
            info = os.lstat(path)
            if path.is_symlink():
                state[str(path)] = ("link", os.readlink(path))
            elif path.is_dir():
                state[str(path)] = ("dir", info.st_mode)
            else:
                state[str(path)] = ("file", path.read_bytes(), info.st_mode, info.st_mtime_ns)
    return state


#: The environment variable naming the signal tests' hold file (the writing module's test-only
#: hook, reached through the command line). When it is non-empty, a `setup` run that is about to
#: rename its temporary file over the target first writes the temporary file's absolute path and
#: a newline to the named file, then waits — polling, the temporary file still in place — until
#: the named file no longer exists, and only then renames. Unset or empty, nothing is held.
HOLD_ENV = "SOL_PI_AXI_TEST_HOLD"

#: Text that must never reach either stream of a `sol-pi-axi` run: a traceback or a dependency
#: (import) message.
FORBIDDEN_OUTPUT = ("Traceback", "No module named", "ModuleNotFoundError", "ImportError")


def venv_script() -> Path:
    """The `sol-pi-axi` console script of the editable install the tests run under."""
    script = Path(sys.executable).parent / "sol-pi-axi"
    if not script.is_file():
        raise AssertionError(f"no sol-pi-axi console script beside {sys.executable}")
    return script


def cli_environ(tree: "TempTree", **extra: str) -> dict:
    """A clean environment for a `sol-pi-axi` run: `PATH`, the tree's home as `HOME`, its agent
    directory as `PI_CODING_AGENT_DIR`, a UTF-8 locale, coverage's own variables, then `extra`."""
    environ = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tree.home),
        "PI_CODING_AGENT_DIR": str(tree.agent),
        "LANG": "C.UTF-8",
    }
    environ.update({key: value for key, value in os.environ.items() if key.startswith("COVERAGE")})
    environ.update(extra)
    return environ


def run_cli(args, *, tree: "TempTree", cwd=None, env=None, stdin=subprocess.DEVNULL,
            script=None, timeout: float = 60) -> subprocess.CompletedProcess:
    """Run the `sol-pi-axi` console script (the editable install's unless `script` is given) as a
    subprocess, capturing both streams as text."""
    command = [str(script if script is not None else venv_script()), *[str(arg) for arg in args]]
    return subprocess.run(command, cwd=str(cwd if cwd is not None else tree.root),
                          env=env if env is not None else cli_environ(tree), stdin=stdin,
                          capture_output=True, text=True, timeout=timeout, check=False)


def assert_clean_streams(test, result) -> None:
    """Neither stream carries a traceback or a dependency message."""
    for name, text in (("stdout", result.stdout), ("stderr", result.stderr)):
        for marker in FORBIDDEN_OUTPUT:
            test.assertNotIn(marker, text or "", f"{marker!r} on {name}:\n{text}")


def decode_envelope(test, stdout: str) -> dict:
    """The `axi` object of a TOON envelope, decoded with `toon_format.decode`; the whole of
    standard output must be that one envelope."""
    toon_format = importlib.import_module("toon_format")
    try:
        decoded = toon_format.decode(stdout)
    except Exception as error:  # noqa: BLE001 — any decode failure is the assertion
        raise test.failureException(
            f"stdout is not a TOON envelope ({type(error).__name__}: {error}):\n{stdout}") from None
    test.assertIsInstance(decoded, dict, stdout)
    test.assertEqual(list(decoded), ["axi"], f"the envelope's root must be axi:\n{stdout}")
    test.assertIsInstance(decoded["axi"], dict, stdout)
    return decoded["axi"]


class TempTree:
    """A temporary root holding `home/`, `project/` and `agent/` (the agent directory);
    `project/.pi/` is not created."""

    def __init__(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="sol-pi-axi-test-")))
        self.home = self.root / "home"
        self.project = self.root / "project"
        self.agent = self.root / "agent"
        for path in (self.home, self.project, self.agent):
            path.mkdir()

    @property
    def pi_dir(self) -> Path:
        return self.project / ".pi"

    @property
    def project_file(self) -> Path:
        return self.project / ".pi" / "sol-pi.json"

    @property
    def agent_file(self) -> Path:
        return self.agent / "sol-pi.json"

    @property
    def settings_file(self) -> Path:
        return self.agent / "settings.json"

    def write_settings(self, value) -> None:
        self.settings_file.write_text(json.dumps(value), encoding="utf-8")

    def write_project_file(self, text: str) -> None:
        self.pi_dir.mkdir(exist_ok=True)
        self.project_file.write_text(text, encoding="utf-8")

    def cleanup(self) -> None:
        for dirpath, dirnames, _ in os.walk(self.root):
            for name in dirnames:
                path = Path(dirpath) / name
                if not path.is_symlink():
                    # Owner-only access is enough for rmtree to clear a directory a test made
                    # read-only.
                    os.chmod(path, 0o700)
        shutil.rmtree(self.root, ignore_errors=True)
