# SPDX-License-Identifier: MIT
"""CR-SLP-005 §S1, the pieces of `--interactive` below the command line: the prompts' answer
grammar (`sol_pi_axi.prompt`) and the reducer prompt's suggestions from the agent
`settings.json`'s `enabledModels` (`sol_pi_axi.config`).

The contract these tests fix for the implementation:

- `sol_pi_axi.prompt.parse_switch(answer) -> bool`: `yes` is True, `no` False; anything else
  raises `ValueError` whose message states the rule (`yes or no`).
- `sol_pi_axi.prompt.parse_route(answer) -> (provider, model)`: `--reducer`'s grammar — split at
  the first `/`, both parts non-empty without whitespace; otherwise `ValueError` naming
  `<provider>/<model>`.
- `sol_pi_axi.prompt.parse_ratio(answer) -> float`: `--cache-ratio`'s grammar — digits with an
  optional decimal fraction; otherwise `ValueError` naming the rule (`digits`).
- An empty answer is the prompt's default; it is handled by the prompt, not by these parsers.
- `sol_pi_axi.config.enabled_model_suggestions(agent_dir) -> (suggestions, warnings)`: the
  `enabledModels` entries of `<agent_dir>/settings.json` that are valid `--reducer` values without
  any of `*?[]{}` or a thinking-level suffix (`:` then one of Pi's levels `off`, `minimal`,
  `low`, `medium`, `high`, `xhigh`, `max`), in the file's order — any other `:` is part of the
  model id; it never raises. A missing or malformed
  file, a root that is not an object, a non-array `enabledModels`, or entries none of which is
  usable give no suggestions and one warning — naming the file for the first three, naming
  `enabledModels` for the last two."""

import unittest

from tests.sol_pi_axi_support import TempTree, import_sut


class AnswerGrammarTest(unittest.TestCase):
    def prompt(self):
        return import_sut("sol_pi_axi.prompt")

    def test_a_switch_answer_is_yes_or_no(self):
        prompt = self.prompt()
        self.assertIs(prompt.parse_switch("yes"), True)
        self.assertIs(prompt.parse_switch("no"), False)

    def test_any_other_switch_answer_is_refused_with_the_rule(self):
        prompt = self.prompt()
        for answer in ("maybe", "yess", "1", "true", "nope"):
            with self.subTest(answer=answer):
                with self.assertRaises(ValueError) as caught:
                    prompt.parse_switch(answer)
                self.assertIn("yes or no", str(caught.exception))

    def test_a_route_answer_is_split_at_the_first_slash(self):
        prompt = self.prompt()
        self.assertEqual(prompt.parse_route("anthropic/claude-sonnet-4-5"),
                         ("anthropic", "claude-sonnet-4-5"))
        self.assertEqual(prompt.parse_route("openrouter/meta/llama-4"),
                         ("openrouter", "meta/llama-4"))

    def test_a_route_answer_outside_the_reducer_grammar_is_refused_with_the_rule(self):
        prompt = self.prompt()
        for answer in ("noslash", "/model", "provider/", "pro vider/model", "provider/mo del",
                       "provider/model\u00a0"):
            with self.subTest(answer=answer):
                with self.assertRaises(ValueError) as caught:
                    prompt.parse_route(answer)
                self.assertIn("<provider>/<model>", str(caught.exception))

    def test_a_ratio_answer_is_digits_with_an_optional_fraction(self):
        prompt = self.prompt()
        self.assertEqual(prompt.parse_ratio("8"), 8.0)
        self.assertEqual(prompt.parse_ratio("12.5"), 12.5)
        self.assertEqual(prompt.parse_ratio("0"), 0.0)

    def test_a_ratio_answer_outside_the_cache_ratio_grammar_is_refused_with_the_rule(self):
        prompt = self.prompt()
        for answer in ("-1", "abc", "1e3", "1.", ".5", "+2", "inf", "NaN", "1,5"):
            with self.subTest(answer=answer):
                with self.assertRaises(ValueError) as caught:
                    prompt.parse_ratio(answer)
                self.assertIn("digits", str(caught.exception))


class EnabledModelSuggestionsTest(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)

    def suggestions(self):
        config = import_sut("sol_pi_axi.config")
        return config.enabled_model_suggestions(self.tree.agent)

    def test_usable_entries_are_suggested_in_order_without_globs_or_a_colon_suffix(self):
        self.tree.write_settings({"enabledModels": [
            "openai/gpt-5.1", "anthropic/*", "google/gemini-3-pro", "openai/gpt-5:high",
            "nosuch", "a b/c", "x/[abc]", "y/{p,q}", "z/m?", "/m", "p/", "xai/grok-4"]})
        suggestions, warnings = self.suggestions()
        self.assertEqual(suggestions, ["openai/gpt-5.1", "google/gemini-3-pro", "xai/grok-4"])
        self.assertIsInstance(warnings, list)

    def test_a_colon_that_is_not_a_thinking_level_suffix_is_part_of_the_model_id(self):
        self.tree.write_settings({"enabledModels": [
            "x/y:high", "amazon-bedrock/anthropic.claude-v2:1", "x/y:off", "x/y:minimal",
            "x/m-v1:0", "x/y:low", "x/y:medium", "x/y:xhigh", "x/y:max"]})
        suggestions, warnings = self.suggestions()
        self.assertEqual(suggestions, ["amazon-bedrock/anthropic.claude-v2:1", "x/m-v1:0"])
        self.assertEqual(warnings, [])

    def test_each_thinking_level_suffix_keeps_an_entry_out(self):
        for level in ("off", "minimal", "low", "medium", "high", "xhigh", "max"):
            with self.subTest(level=level):
                self.tree.write_settings({"enabledModels": [f"x/y:{level}", "x/m-v1:0"]})
                suggestions, _ = self.suggestions()
                self.assertEqual(suggestions, ["x/m-v1:0"])

    def test_a_non_array_enabled_models_gives_no_suggestions_and_a_warning(self):
        self.tree.write_settings({"enabledModels": "openai/gpt-5.1"})
        suggestions, warnings = self.suggestions()
        self.assertEqual(suggestions, [])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("enabledModels", warnings[0])

    def test_non_string_entries_give_no_suggestions_and_a_warning(self):
        self.tree.write_settings({"enabledModels": [42, True, None, {"model": "x/y"}]})
        suggestions, warnings = self.suggestions()
        self.assertEqual(suggestions, [])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("enabledModels", warnings[0])

    def test_only_unusable_entries_give_no_suggestions_and_a_warning(self):
        self.tree.write_settings({"enabledModels": ["anthropic/*", "openai/gpt-5:high"]})
        suggestions, warnings = self.suggestions()
        self.assertEqual(suggestions, [])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("enabledModels", warnings[0])

    def test_a_malformed_settings_file_gives_no_suggestions_and_a_warning_naming_it(self):
        self.tree.settings_file.write_text("{not json", encoding="utf-8")
        suggestions, warnings = self.suggestions()
        self.assertEqual(suggestions, [])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn(str(self.tree.settings_file), warnings[0])

    def test_a_settings_root_that_is_not_an_object_gives_a_warning_naming_the_file(self):
        self.tree.write_settings(["openai/gpt-5.1"])
        suggestions, warnings = self.suggestions()
        self.assertEqual(suggestions, [])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn(str(self.tree.settings_file), warnings[0])

    def test_a_missing_settings_file_gives_no_suggestions_and_a_warning_naming_it(self):
        suggestions, warnings = self.suggestions()
        self.assertEqual(suggestions, [])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn(str(self.tree.settings_file), warnings[0])


if __name__ == "__main__":
    unittest.main()
