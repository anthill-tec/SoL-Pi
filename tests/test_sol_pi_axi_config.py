# SPDX-License-Identifier: MIT
"""`sol_pi_axi.config`: the official Pi layout, the agent directory, reading and validating
`sol-pi.json` with `loadSolPiConfig`'s rules, Pi's default reducer route from `settings.json`, and
the written form."""

import json
import os
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
)


class AgentDirectoryTest(unittest.TestCase):
    """The agent directory is `$PI_CODING_AGENT_DIR` when non-empty (a leading `~` expanded),
    else `~/.pi/agent`."""

    def setUp(self):
        self.config = import_sut("sol_pi_axi.config")
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)

    def _agent_dir(self, environ: dict) -> Path:
        base = {key: value for key, value in os.environ.items() if key != "PI_CODING_AGENT_DIR"}
        base.update(environ)
        with mock.patch.dict(os.environ, base, clear=True):
            return Path(self.config.agent_dir())

    def test_agent_dir_expands_a_leading_tilde_in_pi_coding_agent_dir(self):
        got = self._agent_dir({"HOME": str(self.tree.home), "PI_CODING_AGENT_DIR": "~/agent"})
        self.assertEqual(got, self.tree.home / "agent")

    def test_agent_dir_uses_an_absolute_pi_coding_agent_dir_as_given(self):
        got = self._agent_dir({"HOME": str(self.tree.home), "PI_CODING_AGENT_DIR": str(self.tree.agent)})
        self.assertEqual(got, self.tree.agent)

    def test_agent_dir_falls_back_to_home_pi_agent_when_pi_coding_agent_dir_is_empty(self):
        got = self._agent_dir({"HOME": str(self.tree.home), "PI_CODING_AGENT_DIR": ""})
        self.assertEqual(got, self.tree.home / ".pi" / "agent")

    def test_agent_dir_falls_back_to_home_pi_agent_when_pi_coding_agent_dir_is_unset(self):
        got = self._agent_dir({"HOME": str(self.tree.home)})
        self.assertEqual(got, self.tree.home / ".pi" / "agent")

    def test_project_config_path_is_dot_pi_sol_pi_json_under_the_project(self):
        got = Path(self.config.project_config_path(self.tree.project))
        self.assertEqual(got, self.tree.project / ".pi" / "sol-pi.json")


class ReadConfigTest(unittest.TestCase):
    """`read_config(path)` returns the file's effective values (every key) or raises
    `ConfigError` naming the path."""

    def setUp(self):
        self.config = import_sut("sol_pi_axi.config")
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)

    def _write(self, text: str) -> Path:
        path = self.tree.agent_file
        path.write_text(text, encoding="utf-8")
        return path

    def test_read_config_fills_every_unset_key_with_load_sol_pi_config_defaults(self):
        path = self._write('{"version":1,"actionFusion":true}')
        expected: dict[str, object] = dict.fromkeys(feature_keys(), False)
        expected.update({
            "version": 1,
            "actionFusion": True,
            "evidencePreservingReducerProvider": default_reducer_provider(),
            "evidencePreservingReducerModel": default_reducer_model(),
            "cacheWriteReadRatio": default_cache_ratio(),
        })
        assert_same_json_values(self, self.config.read_config(path), expected)

    def test_read_config_rejects_an_unknown_key_naming_the_path_and_the_key(self):
        path = self._write('{"version":1,"actionFussion":true}')
        with self.assertRaises(self.config.ConfigError) as caught:
            self.config.read_config(path)
        self.assertIn(str(path), str(caught.exception))
        self.assertIn("actionFussion", str(caught.exception))

    def test_read_config_rejects_a_missing_file_naming_the_path(self):
        path = self.tree.agent / "absent.json"
        with self.assertRaises(self.config.ConfigError) as caught:
            self.config.read_config(path)
        self.assertIn(str(path), str(caught.exception))

    def test_read_config_rejects_a_dangling_link_as_an_existing_unreadable_file(self):
        path = self.tree.agent_file
        path.symlink_to(self.tree.agent / "missing-target.json")
        with self.assertRaises(self.config.ConfigError) as caught:
            self.config.read_config(path)
        self.assertIn(str(path), str(caught.exception))
        self.assertFalse((self.tree.agent / "missing-target.json").exists())

    def test_read_config_rejects_a_boolean_ratio_although_python_counts_true_as_one(self):
        path = self._write('{"version":1,"cacheWriteReadRatio":true}')
        with self.assertRaises(self.config.ConfigError):
            self.config.read_config(path)

    def test_read_config_rejects_nan_as_json_parse_does(self):
        path = self._write('{"version":1,"cacheWriteReadRatio":NaN}')
        with self.assertRaises(self.config.ConfigError) as caught:
            self.config.read_config(path)
        self.assertIn(str(path), str(caught.exception))


class PiDefaultRouteTest(unittest.TestCase):
    """`pi_default_route(agent_dir)` reads `<agent dir>/settings.json`: missing means no Pi default
    (`None`); invalid JSON or a non-object root raises `ConfigError` naming the file;
    `defaultProvider`/`defaultModel` count only when both are non-empty strings without
    whitespace."""

    def setUp(self):
        self.config = import_sut("sol_pi_axi.config")
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)

    def _route(self):
        return self.config.pi_default_route(self.tree.agent)

    def test_pi_default_route_returns_provider_and_model_when_both_are_set(self):
        self.tree.write_settings({"defaultProvider": "anthropic", "defaultModel": "claude-sonnet-4-5",
                                  "theme": "dark"})
        self.assertEqual(tuple(self._route()), ("anthropic", "claude-sonnet-4-5"))

    def test_pi_default_route_is_none_when_settings_json_is_missing(self):
        self.assertIsNone(self._route())

    def test_pi_default_route_rejects_malformed_settings_json_naming_the_file(self):
        self.tree.settings_file.write_text("{", encoding="utf-8")
        with self.assertRaises(self.config.ConfigError) as caught:
            self._route()
        self.assertIn(str(self.tree.settings_file), str(caught.exception))

    def test_pi_default_route_rejects_nan_in_settings_json_as_invalid_json(self):
        self.tree.settings_file.write_text(
            '{"defaultProvider":"anthropic","defaultModel":"claude-sonnet-4-5","x":NaN}', encoding="utf-8")
        with self.assertRaises(self.config.ConfigError) as caught:
            self._route()
        self.assertIn(str(self.tree.settings_file), str(caught.exception))

    def test_pi_default_route_rejects_an_array_root_naming_the_file(self):
        self.tree.write_settings([{"defaultProvider": "anthropic", "defaultModel": "claude-sonnet-4-5"}])
        with self.assertRaises(self.config.ConfigError) as caught:
            self._route()
        self.assertIn(str(self.tree.settings_file), str(caught.exception))

    def test_pi_default_route_rejects_a_null_or_string_root(self):
        for root in (None, "anthropic"):
            with self.subTest(root=root):
                self.tree.write_settings(root)
                with self.assertRaises(self.config.ConfigError):
                    self._route()

    def test_pi_default_route_is_none_for_a_non_string_empty_or_whitespace_value(self):
        for provider, model in [
            (123, "claude-sonnet-4-5"),
            ("anthropic", ["claude"]),
            ("", "claude-sonnet-4-5"),
            ("anthropic", ""),
            (" anthropic", "claude-sonnet-4-5"),
            ("anthropic", "claude sonnet"),
            ("anthropic", "claude-sonnet-4-5\t"),
            ("anthropic", None),
        ]:
            with self.subTest(provider=provider, model=model):
                self.tree.write_settings({"defaultProvider": provider, "defaultModel": model})
                self.assertIsNone(self._route())

    def test_pi_default_route_is_none_when_only_one_of_provider_and_model_is_set(self):
        for settings in ({"defaultProvider": "anthropic"}, {"defaultModel": "claude-sonnet-4-5"}):
            with self.subTest(settings=settings):
                self.tree.write_settings(settings)
                self.assertIsNone(self._route())


class RenderConfigTest(unittest.TestCase):
    """`render_config(values)` gives the written form: every key in `sol-pi.example.json`'s
    order, tab indentation, a final newline."""

    def setUp(self):
        self.config = import_sut("sol_pi_axi.config")

    def _values(self) -> dict:
        return {
            "version": 1,
            "actionFusion": True,
            "observationPack": False,
            "evidencePreservingReducer": True,
            "evidencePreservingReducerProvider": "anthropic",
            "evidencePreservingReducerModel": "claude-sonnet-4-5",
            "onlineContextCompact": True,
            "cacheWriteReadRatio": 3.25,
        }

    def test_render_config_orders_keys_as_the_example_whatever_the_input_order(self):
        values = self._values()
        shuffled = dict(reversed(list(values.items())))
        text = self.config.render_config(shuffled).decode("utf-8")
        self.assertEqual(list(json.loads(text)), example_key_order())

    def test_render_config_writes_tab_indented_json_with_a_final_newline(self):
        rendered = self.config.render_config(self._values())
        expected = (
            b'{\n\t"version": 1,\n\t"actionFusion": true,\n\t"observationPack": false,\n'
            b'\t"evidencePreservingReducer": true,\n\t"evidencePreservingReducerProvider": "anthropic",\n'
            b'\t"evidencePreservingReducerModel": "claude-sonnet-4-5",\n\t"onlineContextCompact": true,\n'
            b'\t"cacheWriteReadRatio": 3.25\n}\n'
        )
        self.assertEqual(rendered, expected)
        self.assertFalse(rendered.endswith(b"\n\n"))

    def test_render_config_output_is_read_back_unchanged(self):
        values = self._values()
        rendered = self.config.render_config(values)
        self.assertEqual(json.loads(rendered), values)


if __name__ == "__main__":
    unittest.main()
