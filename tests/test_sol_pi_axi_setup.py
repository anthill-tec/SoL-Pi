# SPDX-License-Identifier: MIT
"""`sol_pi_axi.setup.run_setup`: the configuration core of `sol-pi-axi setup <project dir>`,
driven through its module API (the CLI, its flags and envelope are tested elsewhere).

`run_setup(project_dir, *, agent_dir=None, features=None, reducer=None, cache_ratio=None,
hook=None)` writes at most `<project>/.pi/sol-pi.json` and returns a result with `outcome`
(`"written"` or `"unchanged"`), `path`, `config` (the eight effective values) and `warnings`; a
failed run raises `sol_pi_axi.config.ConfigError` naming the path, with `flag` naming the flag
that fixes it when one does."""

import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

from tests.sol_pi_axi_support import (
    TempTree,
    assert_same_json_values,
    default_cache_ratio,
    default_reducer_model,
    default_reducer_provider,
    example_key_order,
    feature_keys,
    import_sut,
    render_js,
    snapshot,
)

PI_PROVIDER = "anthropic"
PI_MODEL = "claude-sonnet-4-5"


class HookStop(Exception):
    """Raised by a test hook to fail a run between write and rename."""


def values(enabled, provider, model, ratio=None) -> dict:
    """The eight effective values in `sol-pi.example.json`'s order."""
    value = {
        "version": 1,
        "evidencePreservingReducerProvider": provider,
        "evidencePreservingReducerModel": model,
        "cacheWriteReadRatio": default_cache_ratio() if ratio is None else ratio,
    }
    for key in feature_keys():
        value[key] = key in enabled
    return {key: value[key] for key in example_key_order()}


class SetupTestCase(unittest.TestCase):
    def setUp(self):
        self.setup_module = import_sut("sol_pi_axi.setup")
        self.config = import_sut("sol_pi_axi.config")
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)

    def run_setup(self, project=None, **kwargs):
        kwargs.setdefault("agent_dir", self.tree.agent)
        return self.setup_module.run_setup(self.tree.project if project is None else project, **kwargs)

    def assert_fails_changing_nothing(self, named: Path | None, project=None, **kwargs):
        before = snapshot(self.tree.project, self.tree.agent)
        with self.assertRaises(self.config.ConfigError) as caught:
            self.run_setup(project, **kwargs)
        if named is not None:
            self.assertIn(str(named), str(caught.exception))
        self.assertEqual(snapshot(self.tree.project, self.tree.agent), before, "no file changed")
        return caught.exception


class SetupBaseValuesTest(SetupTestCase):
    """Base values: a valid project file's effective values; else the agent file's; else the
    setup defaults (all four mechanisms, ratio 12.5, the reducer on Pi's default route)."""

    def test_no_configuration_anywhere_writes_the_setup_defaults_with_pis_default_route(self):
        self.tree.write_settings({"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL})
        result = self.run_setup()
        expected = values(feature_keys(), PI_PROVIDER, PI_MODEL)
        self.assertEqual(result.outcome, "written")
        self.assertEqual(Path(result.path), self.tree.project_file)
        self.assertTrue(Path(result.path).is_absolute())
        assert_same_json_values(self, result.config, expected)
        self.assertEqual(self.tree.project_file.read_bytes(), render_js(expected))

    def test_a_second_run_is_unchanged_with_bytes_and_modification_time_kept(self):
        self.tree.write_settings({"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL})
        self.run_setup()
        os.utime(self.tree.project_file, ns=(1_000_000_000, 1_000_000_000))
        before = snapshot(self.tree.project)
        result = self.run_setup()
        self.assertEqual(result.outcome, "unchanged")
        self.assertEqual(snapshot(self.tree.project), before)

    def test_a_valid_partial_project_file_without_value_flags_is_left_byte_for_byte(self):
        text = '{"version":1,"actionFusion":true}'
        self.tree.write_project_file(text)
        os.utime(self.tree.project_file, ns=(1_000_000_000, 1_000_000_000))
        self.tree.agent_file.write_text("{ not json", encoding="utf-8")  # never read
        before = snapshot(self.tree.project, self.tree.agent)

        result = self.run_setup()

        self.assertEqual(result.outcome, "unchanged")
        self.assertEqual(self.tree.project_file.read_bytes(), text.encode())
        self.assertEqual(snapshot(self.tree.project, self.tree.agent), before)
        assert_same_json_values(self, result.config, values(
            ["actionFusion"], default_reducer_provider(), default_reducer_model()))

    def test_without_a_project_file_the_agent_files_values_are_written(self):
        self.tree.agent_file.write_text(json.dumps({
            "version": 1, "observationPack": True, "evidencePreservingReducer": True,
            "evidencePreservingReducerProvider": " openrouter ", "evidencePreservingReducerModel": "qwen3",
            "cacheWriteReadRatio": 2.5,
        }), encoding="utf-8")
        self.tree.settings_file.write_text("{", encoding="utf-8")  # read only for the setup defaults
        result = self.run_setup()
        expected = values(["observationPack", "evidencePreservingReducer"], "openrouter", "qwen3", 2.5)
        self.assertEqual(result.outcome, "written")
        self.assertEqual(self.tree.project_file.read_bytes(), render_js(expected))

    def test_a_value_flag_over_a_valid_project_file_starts_from_its_effective_values(self):
        self.tree.write_project_file('{"version":1,"actionFusion":true,"cacheWriteReadRatio":2}')
        self.tree.agent_file.write_text('{"version":1,"observationPack":true}', encoding="utf-8")
        self.tree.settings_file.write_text("{", encoding="utf-8")
        result = self.run_setup(cache_ratio=4.5)
        expected = values(["actionFusion"], default_reducer_provider(), default_reducer_model(), 4.5)
        self.assertEqual(result.outcome, "written")
        self.assertEqual(self.tree.project_file.read_bytes(), render_js(expected))

    def test_value_flags_override_and_a_repeat_is_unchanged(self):
        kwargs = {"features": ["onlineContextCompact", "evidencePreservingReducer"],
                  "reducer": ("openrouter", "qwen/qwen3-coder"), "cache_ratio": 7.0}
        first = self.run_setup(**kwargs)
        expected = values(["onlineContextCompact", "evidencePreservingReducer"],
                          "openrouter", "qwen/qwen3-coder", 7.0)
        self.assertEqual(first.outcome, "written")
        self.assertEqual(json.loads(self.tree.project_file.read_bytes()), expected)
        os.utime(self.tree.project_file, ns=(1_000_000_000, 1_000_000_000))
        before = snapshot(self.tree.project)
        second = self.run_setup(**kwargs)
        self.assertEqual(second.outcome, "unchanged")
        self.assertEqual(snapshot(self.tree.project), before)

    def test_pi_coding_agent_dir_with_a_tilde_reads_the_agent_file_under_home(self):
        agent = self.tree.home / "agent"
        agent.mkdir()
        (agent / "sol-pi.json").write_text('{"version":1,"observationPack":true}', encoding="utf-8")
        environ = {key: value for key, value in os.environ.items() if key != "PI_CODING_AGENT_DIR"}
        environ.update(HOME=str(self.tree.home), PI_CODING_AGENT_DIR="~/agent")
        with mock.patch.dict(os.environ, environ, clear=True):
            self.setup_module.run_setup(self.tree.project)
        self.assertEqual(json.loads(self.tree.project_file.read_bytes()), values(
            ["observationPack"], default_reducer_provider(), default_reducer_model()))

    def test_an_empty_pi_coding_agent_dir_reads_the_agent_file_under_home_pi_agent(self):
        agent = self.tree.home / ".pi" / "agent"
        agent.mkdir(parents=True)
        (agent / "sol-pi.json").write_text('{"version":1,"onlineContextCompact":true}', encoding="utf-8")
        environ = dict(os.environ)
        environ.update(HOME=str(self.tree.home), PI_CODING_AGENT_DIR="")
        with mock.patch.dict(os.environ, environ, clear=True):
            self.setup_module.run_setup(self.tree.project)
        self.assertEqual(json.loads(self.tree.project_file.read_bytes()), values(
            ["onlineContextCompact"], default_reducer_provider(), default_reducer_model()))


class SetupInvalidInputTest(SetupTestCase):
    """An invalid file the run needs fails it, untouched; Pi settings rules for the setup
    defaults."""

    def test_an_invalid_project_file_fails_naming_it_and_the_agent_file_is_not_used(self):
        self.tree.write_project_file('{"version":2}')
        self.tree.agent_file.write_text('{"version":1}', encoding="utf-8")
        self.assert_fails_changing_nothing(self.tree.project_file)

    def test_an_invalid_project_file_fails_even_with_a_value_flag(self):
        self.tree.write_project_file('{"version":1,"cacheWriteReadRatio":NaN}')
        self.assert_fails_changing_nothing(self.tree.project_file, cache_ratio=3.0)

    def test_an_invalid_agent_file_without_a_project_file_fails_naming_it_and_creates_no_pi_dir(self):
        self.tree.agent_file.write_text('{"version":1,"actionFusion":"yes"}', encoding="utf-8")
        self.tree.write_settings({"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL})
        self.assert_fails_changing_nothing(self.tree.agent_file)
        self.assertFalse(self.tree.pi_dir.exists())

    def test_malformed_settings_json_with_the_setup_defaults_fails_naming_it(self):
        self.tree.settings_file.write_text("{", encoding="utf-8")
        self.assert_fails_changing_nothing(self.tree.settings_file)
        self.assertFalse(self.tree.pi_dir.exists())

    def test_malformed_settings_json_is_not_read_when_the_setup_defaults_need_no_pi_route(self):
        # Read only when the setup defaults enable the reducer and no --reducer is given.
        cases = {
            "reducer off": ({"features": ["actionFusion"]}, values(
                ["actionFusion"], default_reducer_provider(), default_reducer_model())),
            "--reducer given": ({"reducer": ("openrouter", "qwen3")}, values(
                feature_keys(), "openrouter", "qwen3")),
        }
        for name, (kwargs, expected) in cases.items():
            with self.subTest(case=name):
                shutil.rmtree(self.tree.pi_dir, ignore_errors=True)
                self.tree.settings_file.write_text("{", encoding="utf-8")
                result = self.run_setup(**kwargs)
                self.assertEqual(result.outcome, "written")
                self.assertEqual(self.tree.project_file.read_bytes(), render_js(expected))

    def test_a_settings_json_with_an_array_root_fails(self):
        self.tree.write_settings([{"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL}])
        self.assert_fails_changing_nothing(self.tree.settings_file)

    def test_no_pi_default_and_no_reducer_fails_naming_the_reducer_flag_and_creates_no_pi_dir(self):
        error = self.assert_fails_changing_nothing(None)
        self.assertEqual(error.flag, "--reducer")
        self.assertFalse(self.tree.pi_dir.exists())

    def test_a_pi_default_with_whitespace_counts_as_none_and_fails_naming_the_reducer_flag(self):
        self.tree.write_settings({"defaultProvider": PI_PROVIDER, "defaultModel": "claude sonnet"})
        error = self.assert_fails_changing_nothing(None)
        self.assertEqual(error.flag, "--reducer")

    def test_no_pi_default_with_the_reducer_disabled_writes_the_built_in_route(self):
        result = self.run_setup(features=["actionFusion"])
        expected = values(["actionFusion"], default_reducer_provider(), default_reducer_model())
        self.assertEqual(result.outcome, "written")
        self.assertEqual(self.tree.project_file.read_bytes(), render_js(expected))

    def test_no_pi_default_with_a_reducer_given_writes_that_route(self):
        self.run_setup(reducer=("openrouter", "qwen/qwen3-coder"))
        self.assertEqual(json.loads(self.tree.project_file.read_bytes()),
                         values(feature_keys(), "openrouter", "qwen/qwen3-coder"))


class SetupPathsTest(SetupTestCase):
    """Target-path failures each fail the run naming the path, changing nothing; `.pi/` is
    created when missing and removed when a run that created it fails."""

    def setUp(self):
        super().setUp()
        self.tree.write_settings({"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL})

    def test_a_project_path_that_does_not_exist_fails_naming_it(self):
        missing = self.tree.root / "absent"
        self.assert_fails_changing_nothing(missing, project=missing)
        self.assertFalse(os.path.lexists(missing))

    def test_a_project_path_that_is_a_file_fails_naming_it(self):
        file = self.tree.root / "a-file"
        file.write_bytes(b"data")
        self.assert_fails_changing_nothing(file, project=file)
        self.assertEqual(file.read_bytes(), b"data")

    def test_a_dot_pi_that_is_a_file_fails_naming_it(self):
        self.tree.pi_dir.write_bytes(b"not a directory")
        self.assert_fails_changing_nothing(self.tree.pi_dir)

    def test_a_sol_pi_json_that_is_a_directory_fails_naming_it(self):
        self.tree.project_file.mkdir(parents=True)
        self.assert_fails_changing_nothing(self.tree.project_file)
        self.assertTrue(self.tree.project_file.is_dir())

    def test_a_dangling_sol_pi_json_link_is_an_unreadable_file_and_fails_naming_it(self):
        self.tree.pi_dir.mkdir()
        self.tree.project_file.symlink_to(self.tree.pi_dir / "missing.json")
        self.assert_fails_changing_nothing(self.tree.project_file)
        self.assertFalse(os.path.lexists(self.tree.pi_dir / "missing.json"))

    def test_a_read_only_dot_pi_fails_naming_it(self):
        self.tree.pi_dir.mkdir()
        os.chmod(self.tree.pi_dir, 0o500)
        self.assert_fails_changing_nothing(self.tree.pi_dir)
        self.assertEqual(os.listdir(self.tree.pi_dir), [])

    def test_a_written_run_leaves_only_sol_pi_json_in_a_dot_pi_it_created(self):
        self.run_setup()
        self.assertEqual(os.listdir(self.tree.pi_dir), ["sol-pi.json"])

    def test_a_leftover_backup_is_kept_and_named_in_warnings(self):
        self.tree.pi_dir.mkdir()
        backup = self.tree.pi_dir / "sol-pi.json.bak"
        backup.write_bytes(b'{"version":1}\n')
        result = self.run_setup()
        self.assertEqual(result.outcome, "written")
        self.assertEqual(backup.read_bytes(), b'{"version":1}\n')
        self.assertEqual(sorted(os.listdir(self.tree.pi_dir)), ["sol-pi.json", "sol-pi.json.bak"])
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("sol-pi.json.bak", result.warnings[0])

    def test_a_run_without_a_backup_has_no_warnings(self):
        self.assertEqual(list(self.run_setup().warnings), [])

    def test_a_failure_between_write_and_rename_removes_the_dot_pi_the_run_created(self):
        def hook(_temporary):
            raise HookStop

        with self.assertRaises(HookStop):
            self.run_setup(hook=hook)
        self.assertFalse(os.path.lexists(self.tree.pi_dir))
        self.assertEqual(os.listdir(self.tree.project), [])

    def test_a_failure_between_write_and_rename_keeps_an_existing_dot_pi_and_file(self):
        self.tree.write_project_file('{"version":1}')
        before = snapshot(self.tree.project)

        def hook(_temporary):
            raise HookStop

        with self.assertRaises(HookStop):
            self.run_setup(features=["actionFusion"], hook=hook)
        self.assertEqual(snapshot(self.tree.project), before)


if __name__ == "__main__":
    unittest.main()
