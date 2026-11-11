# SPDX-License-Identifier: MIT
"""CR-SLP-005 §S1: `--interactive` for `sol-pi-axi setup` and `install`, driven end to end on a
pseudo-terminal (`tests.pty_harness`: the terminal controls a session led by an intermediate
process, the command runs in its foreground process group with standard input and standard error
on the terminal and standard output on its own pipe), with a temporary project, agent directory
and home and CR-SLP-007's stub `pi` (`tests.sol_pi_axi_stub_pi`).

The contract these tests fix for the implementation (the prompt module is
`sol_pi_axi.prompt`; see `tests.test_sol_pi_axi_prompt` for its answer grammar):

- Prompts are written to standard error by the command, in this order:
  1. each mechanism, in `sol-pi.example.json`'s order: `<key> (yes/no) [<default>]: ` with the
     default `yes` or `no` — e.g. `actionFusion (yes/no) [yes]: `;
  2. when the reducer is answered on: the suggestions (usable `enabledModels` entries), then
     `reducer <provider>/<model> [<default>]: `, or `reducer <provider>/<model>: ` when there is
     no default;
  3. `cacheWriteReadRatio [<default>]: ` (the default as `--cache-ratio` writes it, `4` for 4);
  4. the result, then the confirmation `proceed (yes/no)...: ` (its default is not fixed here).
- An empty answer takes the default; `yes`/`no` answer a switch; the route and the ratio follow
  `--reducer`'s and `--cache-ratio`'s grammar. An invalid answer writes its rule (for a switch
  naming `yes or no`, for the ratio `digits`) and asks the same prompt again.
- Prompting needs standard input and standard error to be terminals, the process group to be the
  terminal's foreground group, and `PI_NONINTERACTIVE` unset or empty. Otherwise the run adds one
  warning that names `--interactive` and why — `PI_NONINTERACTIVE`, `standard input`,
  `standard error`, or the process group not being the terminal's `foreground` group (`foreground`
  or `background`) — and runs as without `--interactive`.
- A cancel before the confirmation is answered prints `cancelled`, with `error` naming the cause:
  `declined` for a declined confirmation, `SIGINT` for Ctrl+C and `SIGINT`, `end of input` for
  Ctrl+D on an empty line, `SIGTERM`, `SIGHUP` (`SIGHUP` or `terminal` for a closed terminal);
  `help[]` holds the command to run again: an entry starting `sol-pi-axi setup ` or
  `sol-pi-axi install` that names `--interactive`.
- The warnings for the suggestions name `enabledModels`, or the settings file's path."""

import json
import os
import re
import shlex
import signal
import subprocess
import time
import unittest

from tests.pty_harness import PtyRun
from tests.sol_pi_axi_stub_pi import (
    PI_HOLD_ENV,
    PI_MODEL,
    PI_PROVIDER,
    PiCommandTestCase,
    stub_environ,
)
from tests.sol_pi_axi_support import (
    REPO,
    TempTree,
    assert_clean_streams,
    cli_environ,
    decode_envelope,
    default_cache_ratio,
    feature_keys,
    package_json_version,
    render_js,
    run_cli,
    snapshot,
    venv_script,
)

ROUTE = "reducer <provider>/<model>"
RATIO = "cacheWriteReadRatio"
PROCEED = "proceed (yes/no)"
HOLD_TIMEOUT = 30.0
#: `config` once `SetupCancelTest.at_confirmation`'s answers are shown.
SETUP_SHOWN = {"features": ["observationPack", "evidencePreservingReducer", "onlineContextCompact"],
               "reducer": "prov/mod-7", "cacheRatio": 8}
#: `install`'s `config` values before the first answer.
NOTHING_SHOWN = {"features": None, "reducer": None, "cacheRatio": None}


def switch(key: str) -> str:
    return f"{key} (yes/no)"


def prompt_markers() -> list[str]:
    """Text only a prompt writes."""
    return [switch(key) for key in feature_keys()] + [ROUTE, f"{RATIO} [", PROCEED]


def example_order(values: dict) -> dict:
    order = json.loads((REPO / "sol-pi.example.json").read_text(encoding="utf-8"))
    return {key: values[key] for key in order}


class InteractiveTestCase(PiCommandTestCase):
    """A run of `sol-pi-axi` on the pseudo-terminal, from the project directory, with the stub
    `pi` as the only `pi`."""

    def start(self, *args, env: dict | None = None, **options) -> PtyRun:
        run = PtyRun([venv_script(), *[str(arg) for arg in args]],
                     env=env if env is not None else self.environ(), cwd=self.tree.project,
                     **options)
        self.addCleanup(run.close)
        return run

    def ask(self, run: PtyRun, label: str, answer: str) -> None:
        """Wait for the prompt `label` (up to its `: `), then type `answer` and Enter."""
        run.expect(label)
        run.expect(": ")
        run.type(answer)

    def answer_values(self, run: PtyRun, switches=("", "", "", ""), route: str | None = "",
                      ratio: str = "") -> None:
        """Answer the four switches, the route (None: no route prompt) and the ratio."""
        for key, answer in zip(feature_keys(), switches, strict=True):
            self.ask(run, switch(key), answer)
        if route is not None:
            self.ask(run, ROUTE, route)
        self.ask(run, RATIO, ratio)

    def finish(self, run: PtyRun):
        result = run.finish()
        assert_clean_streams(self, result)
        return result

    def assert_code(self, result, code: int) -> None:
        self.assertEqual(result.returncode, code,
                         f"stdout:\n{result.stdout}\nterminal:\n{result.terminal}")

    def assert_no_prompt(self, text: str) -> None:
        for marker in prompt_markers():
            if marker == ROUTE:
                # Only a prompt line starts with it: envelope text names `--reducer <provider>/<model>`.
                self.assertNotRegex(text, rf"(?m)^{re.escape(ROUTE)}",
                                    f"a prompt was written:\n{text}")
                continue
            self.assertNotIn(marker, text, f"a prompt was written:\n{text}")

    def assert_stdout_is_only_the_envelope(self, result) -> dict:
        self.assert_no_prompt(result.stdout)
        return decode_envelope(self, result.stdout)

    def assert_rerun_help(self, envelope: dict, verb: str) -> None:
        prefix = f"sol-pi-axi {verb}"
        self.assertTrue(any(entry.startswith(prefix) and "--interactive" in entry
                            for entry in envelope["help"]),
                        f"help[] runs {prefix} … --interactive again: {envelope['help']}")

    def assert_interactive_warning(self, warnings: list, reason: str) -> None:
        found = [entry for entry in warnings if "--interactive" in entry]
        self.assertEqual(len(found), 1, f"one warning names --interactive: {warnings}")
        self.assertRegex(found[0], reason)

    def setup_defaults(self) -> dict:
        values = {"version": 1, "evidencePreservingReducerProvider": PI_PROVIDER,
                  "evidencePreservingReducerModel": PI_MODEL,
                  "cacheWriteReadRatio": default_cache_ratio()}
        values.update(dict.fromkeys(feature_keys(), True))
        return values

    def project_values(self) -> dict:
        return json.loads(self.tree.project_file.read_text(encoding="utf-8"))

    def agent_values(self) -> dict:
        return json.loads(self.tree.agent_file.read_text(encoding="utf-8"))


# --- setup ---------------------------------------------------------------------------------------

class InteractiveSetupTest(InteractiveTestCase):
    """§S1 `setup --interactive` at a terminal."""

    def test_setup_prompts_writes_the_answers_and_the_pipe_holds_only_the_envelope(self):
        self.with_pi_default()
        run = self.start("setup", self.tree.project, "--interactive")
        self.answer_values(run, switches=("no", "yes", "yes", "no"), route="prov/mod-9",
                           ratio="8")
        self.ask(run, PROCEED, "yes")
        result = self.finish(run)
        self.assert_code(result, 0)
        envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("setup", True, "written"))
        self.assertEqual(envelope["path"], str(self.tree.project_file))
        self.assertEqual(envelope["config"], {
            "features": ["observationPack", "evidencePreservingReducer"],
            "reducer": "prov/mod-9", "cacheRatio": 8})
        values = self.project_values()
        self.assertEqual({key: values[key] for key in feature_keys()},
                         {"actionFusion": False, "observationPack": True,
                          "evidencePreservingReducer": True, "onlineContextCompact": False})
        self.assertEqual((values["evidencePreservingReducerProvider"],
                          values["evidencePreservingReducerModel"],
                          values["cacheWriteReadRatio"]), ("prov", "mod-9", 8))
        for marker in prompt_markers():
            self.assertIn(marker, result.terminal, "the prompts were written to the terminal")
        terminal = result.terminal
        shown = terminal[terminal.rindex(f"{RATIO} ["):terminal.index(PROCEED)]
        self.assertIn("prov/mod-9", shown, "the result is shown before the confirmation")

    def test_value_flags_become_the_prompt_defaults(self):
        self.with_pi_default()
        run = self.start("setup", self.tree.project, "--interactive", "--features",
                         "observationPack,evidencePreservingReducer", "--reducer", "prov/mod-1",
                         "--cache-ratio", "4")
        self.answer_values(run)
        self.ask(run, PROCEED, "yes")
        result = self.finish(run)
        self.assert_code(result, 0)
        terminal = result.terminal
        self.assertIn("actionFusion (yes/no) [no]", terminal)
        self.assertIn("observationPack (yes/no) [yes]", terminal)
        self.assertIn("evidencePreservingReducer (yes/no) [yes]", terminal)
        self.assertIn("onlineContextCompact (yes/no) [no]", terminal)
        self.assertIn(f"{ROUTE} [prov/mod-1]", terminal)
        self.assertIn(f"{RATIO} [4]", terminal)
        values = self.project_values()
        self.assertEqual({key: values[key] for key in feature_keys()},
                         {key: key in ("observationPack", "evidencePreservingReducer")
                          for key in feature_keys()})
        self.assertEqual((values["evidencePreservingReducerProvider"],
                          values["evidencePreservingReducerModel"],
                          values["cacheWriteReadRatio"]), ("prov", "mod-1", 4))

    def test_the_defaults_without_flags_are_the_base_values(self):
        self.with_pi_default()
        run = self.start("setup", self.tree.project, "--interactive")
        self.answer_values(run)
        self.ask(run, PROCEED, "yes")
        result = self.finish(run)
        self.assert_code(result, 0)
        self.assertIn(f"{ROUTE} [{PI_PROVIDER}/{PI_MODEL}]", result.terminal)
        self.assertEqual(self.tree.project_file.read_bytes(),
                         render_js(example_order(self.setup_defaults())))

    def test_confirming_the_base_values_is_unchanged_and_writes_nothing(self):
        self.with_pi_default()
        values = dict(self.setup_defaults(), actionFusion=False, cacheWriteReadRatio=3)
        self.tree.write_project_file(render_js(example_order(values)).decode("utf-8"))
        before = snapshot(self.tree.project, self.tree.agent)
        run = self.start("setup", self.tree.project, "--interactive")
        self.answer_values(run)
        self.ask(run, PROCEED, "yes")
        result = self.finish(run)
        self.assert_code(result, 0)
        envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual((envelope["ok"], envelope["outcome"]), (True, "unchanged"))
        self.assertIn("actionFusion (yes/no) [no]", result.terminal, "the base values are the "
                      "defaults")
        self.assertEqual(snapshot(self.tree.project, self.tree.agent), before)

    def test_invalid_answers_repeat_their_prompt_with_the_rule(self):
        self.with_pi_default()
        run = self.start("setup", self.tree.project, "--interactive")
        self.ask(run, switch("actionFusion"), "maybe")
        run.expect("yes or no")
        self.ask(run, switch("actionFusion"), "no")
        self.ask(run, switch("observationPack"), "")
        self.ask(run, switch("evidencePreservingReducer"), "")
        self.ask(run, switch("onlineContextCompact"), "")
        self.ask(run, ROUTE, "noslash")
        self.ask(run, ROUTE, "prov/mod-2")
        self.ask(run, RATIO, "-1")
        run.expect("digits")
        self.ask(run, RATIO, "abc")
        run.expect("digits")
        self.ask(run, RATIO, "2.5")
        self.ask(run, PROCEED, "yes")
        result = self.finish(run)
        self.assert_code(result, 0)
        self.assertEqual(result.terminal.count(switch("actionFusion")), 2, result.terminal)
        self.assertEqual(result.terminal.count(f"{RATIO} ["), 3, result.terminal)
        values = self.project_values()
        self.assertEqual((values["actionFusion"], values["evidencePreservingReducerProvider"],
                          values["evidencePreservingReducerModel"],
                          values["cacheWriteReadRatio"]), (False, "prov", "mod-2", 2.5))

    def test_answering_the_reducer_no_skips_the_reducer_prompt(self):
        self.with_pi_default()
        run = self.start("setup", self.tree.project, "--interactive")
        self.answer_values(run, switches=("", "", "no", ""), route=None)
        self.ask(run, PROCEED, "yes")
        result = self.finish(run)
        self.assert_code(result, 0)
        self.assertNotIn(ROUTE, result.terminal)
        self.assertIs(self.project_values()["evidencePreservingReducer"], False)

    def test_with_no_pi_default_the_reducer_prompt_has_no_default_and_a_typed_route_is_written(self):
        self.tree.write_settings({})
        run = self.start("setup", self.tree.project, "--interactive")
        for key in feature_keys():
            self.ask(run, switch(key), "")
        run.expect(f"{ROUTE}: ")
        run.type("typed/model-x")
        self.ask(run, RATIO, "")
        self.ask(run, PROCEED, "yes")
        result = self.finish(run)
        self.assert_code(result, 0)
        self.assertNotIn(f"{ROUTE} [", result.terminal, "the reducer prompt has no default")
        values = self.project_values()
        self.assertEqual((values["evidencePreservingReducerProvider"],
                          values["evidencePreservingReducerModel"]), ("typed", "model-x"))

    def test_with_no_pi_default_an_empty_reducer_answer_fails_and_writes_nothing(self):
        self.tree.write_settings({})
        before = snapshot(self.tree.project, self.tree.agent)
        run = self.start("setup", self.tree.project, "--interactive")
        for key in feature_keys():
            self.ask(run, switch(key), "")
        run.expect(f"{ROUTE}: ")
        run.type("")
        result = self.finish(run)
        self.assert_code(result, 1)
        envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("setup", False, "failed"))
        self.assertTrue(any("--reducer" in entry for entry in envelope["help"]),
                        envelope["help"])
        self.assertEqual(snapshot(self.tree.project, self.tree.agent), before)


class SuggestionsTest(InteractiveTestCase):
    """§S1: the reducer prompt suggests the usable agent `enabledModels` entries."""

    USABLE = ("openai/gpt-5.1", "google/gemini-3-pro")
    UNUSABLE = ("anthropic/*", "openai/gpt-5:high", "x/[abc]", "y/{p,q}", "z/m?", "nosuch")

    def run_to_the_end(self, *flags, route: str = "") -> tuple:
        run = self.start("setup", self.tree.project, "--interactive", *flags)
        for key in feature_keys():
            self.ask(run, switch(key), "")
        run.expect(ROUTE)
        run.expect(": ")
        shown = run.terminal()
        run.type(route)
        self.ask(run, RATIO, "")
        self.ask(run, PROCEED, "yes")
        result = self.finish(run)
        return result, shown

    def test_the_reducer_prompt_lists_usable_entries_and_none_with_a_glob_or_colon_suffix(self):
        self.tree.write_settings({"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL,
                                  "enabledModels": [*self.USABLE, *self.UNUSABLE]})
        result, shown = self.run_to_the_end(route="google/gemini-3-pro")
        self.assert_code(result, 0)
        before_route = shown[shown.index(switch("onlineContextCompact")):]
        for entry in self.USABLE:
            self.assertIn(entry, before_route, "suggested before the reducer prompt")
        for entry in self.UNUSABLE:
            self.assertNotIn(entry, result.terminal, f"{entry!r} is not suggested")
        values = self.project_values()
        self.assertEqual((values["evidencePreservingReducerProvider"],
                          values["evidencePreservingReducerModel"]),
                         ("google", "gemini-3-pro"))

    def test_the_reducer_prompt_lists_a_model_id_with_a_colon(self):
        colon_id = "amazon-bedrock/anthropic.claude-v2:1"
        self.tree.write_settings({"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL,
                                  "enabledModels": [colon_id, "x/y:xhigh"]})
        result, shown = self.run_to_the_end()
        self.assert_code(result, 0)
        before_route = shown[shown.index(switch("onlineContextCompact")):]
        self.assertIn(colon_id, before_route, "suggested before the reducer prompt")
        self.assertNotIn("x/y:xhigh", result.terminal, "a thinking-level suffix is not suggested")

    def test_a_non_array_enabled_models_gives_no_suggestions_and_a_warning(self):
        self.tree.write_settings({"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL,
                                  "enabledModels": "openai/gpt-5.1"})
        result, _ = self.run_to_the_end()
        self.assert_code(result, 0)
        self.assertNotIn("openai/gpt-5.1", result.terminal)
        envelope = decode_envelope(self, result.stdout)
        self.assertEqual(envelope["outcome"], "written")
        self.assertTrue(any("enabledModels" in entry for entry in envelope["warnings"]),
                        envelope["warnings"])

    def test_non_string_entries_give_no_suggestions_and_a_warning(self):
        self.tree.write_settings({"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL,
                                  "enabledModels": [42, True, None, {"model": "x/y"}]})
        result, _ = self.run_to_the_end()
        self.assert_code(result, 0)
        self.assertNotIn("x/y", result.terminal)
        envelope = decode_envelope(self, result.stdout)
        self.assertTrue(any("enabledModels" in entry for entry in envelope["warnings"]),
                        envelope["warnings"])

    def test_a_malformed_settings_file_with_reducer_given_warns_and_prompts(self):
        self.tree.settings_file.write_text("{not json", encoding="utf-8")
        result, _ = self.run_to_the_end("--reducer", "prov/mod-3")
        self.assert_code(result, 0)
        envelope = decode_envelope(self, result.stdout)
        self.assertEqual((envelope["ok"], envelope["outcome"]), (True, "written"))
        self.assertTrue(any(str(self.tree.settings_file) in entry
                            for entry in envelope["warnings"]), envelope["warnings"])
        values = self.project_values()
        self.assertEqual((values["evidencePreservingReducerProvider"],
                          values["evidencePreservingReducerModel"]), ("prov", "mod-3"))


class BeforeAnyPromptTest(InteractiveTestCase):
    """§S1: the checks the verb makes before writing or registering run before any prompt."""

    def assert_failed_without_prompting(self, run: PtyRun, verb: str) -> dict:
        result = self.finish(run)
        self.assert_code(result, 1)
        self.assert_no_prompt(result.terminal)
        envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         (verb, False, "failed"))
        return envelope

    def test_an_invalid_project_file_fails_before_any_prompt(self):
        self.with_pi_default()
        self.tree.write_project_file('{"version": 2}')
        before = snapshot(self.tree.project, self.tree.agent)
        envelope = self.assert_failed_without_prompting(
            self.start("setup", self.tree.project, "--interactive"), "setup")
        self.assertIn(str(self.tree.project_file), envelope["error"])
        self.assertEqual(snapshot(self.tree.project, self.tree.agent), before)

    def test_a_malformed_settings_file_the_plain_run_reads_fails_setup_before_any_prompt(self):
        self.tree.settings_file.write_text("{not json", encoding="utf-8")
        envelope = self.assert_failed_without_prompting(
            self.start("setup", self.tree.project, "--interactive"), "setup")
        self.assertIn(str(self.tree.settings_file), envelope["error"])
        self.assertFalse(self.tree.pi_dir.exists())

    def test_no_pi_fails_install_before_any_prompt(self):
        self.with_pi_default()
        empty = self.tree.root / "empty-bin"
        empty.mkdir()
        env = stub_environ(cli_environ(self.tree), empty)
        envelope = self.assert_failed_without_prompting(self.start("install", "--interactive",
                                                                   env=env), "install")
        self.assertIn("pi", envelope["error"])
        self.assertFalse(self.tree.agent_file.exists())

    def test_install_runs_pi_version_and_reads_the_records_before_the_first_prompt(self):
        self.with_pi_default()
        run = self.start("install", "--interactive")
        run.expect(switch("actionFusion"))
        calls = self.pi.calls()
        self.assertEqual(len(calls), 1, calls)
        self.assertIn("--version", calls[0]["argv"])
        run.ctrl_c()
        self.finish(run)


# --- install -------------------------------------------------------------------------------------

class InteractiveInstallTest(InteractiveTestCase):
    """§S1 `install --interactive` at a terminal."""

    def test_install_in_an_empty_agent_directory_prompts_registers_writes_and_checks_last(self):
        self.with_pi_default()
        run = self.start("install", "--interactive")
        self.answer_values(run, switches=("yes", "no", "yes", "yes"), route="prov/mod-5",
                           ratio="6")
        run.expect(PROCEED)
        self.assertEqual(self.pi.commands(), [], "no pi install or pi remove before the "
                         "confirmation")
        run.expect(": ")
        run.type("yes")
        result = self.finish(run)
        self.assert_code(result, 0)
        envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("install", True, "installed"))
        self.assertEqual(self.pi.commands(), [["install", self.own_source()]])
        self.assertEqual(self.packages(), [self.own_source()])
        values = self.agent_values()
        self.assertEqual({key: values[key] for key in feature_keys()},
                         {"actionFusion": True, "observationPack": False,
                          "evidencePreservingReducer": True, "onlineContextCompact": True})
        self.assertEqual((values["evidencePreservingReducerProvider"],
                          values["evidencePreservingReducerModel"],
                          values["cacheWriteReadRatio"]), ("prov", "mod-5", 6))
        self.assertEqual(envelope["config"]["state"], "written")
        # The load check runs last, as without --interactive.
        self.assertIsInstance(envelope["verify"], dict)
        self.assertIs(envelope["verify"]["ok"], True)
        argvs = [call["argv"] for call in self.pi.calls()]
        self.assertIn("--mode", argvs[-1], f"the check is the last pi command: {argvs}")
        self.assertEqual(len(self.pi.rpc_calls()), 1)

    def test_install_with_an_agent_file_present_prompts_for_nothing_and_adds_no_warning(self):
        self.with_pi_default()
        self.tree.agent_file.write_bytes(render_js(example_order(self.setup_defaults())))
        before = self.tree.agent_file.read_bytes()
        run = self.start("install", "--interactive")
        result = self.finish(run)
        self.assert_code(result, 0)
        self.assert_no_prompt(result.terminal)
        envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual((envelope["ok"], envelope["outcome"]), (True, "installed"))
        self.assertEqual(envelope["warnings"], [], "no interactive-mode warning")
        self.assertEqual(self.packages(), [self.own_source()])
        self.assertEqual(self.tree.agent_file.read_bytes(), before)

    def test_value_flags_become_the_install_prompt_defaults(self):
        self.with_pi_default()
        run = self.start("install", "--interactive", "--features", "actionFusion",
                         "--cache-ratio", "3")
        for key in feature_keys():
            self.ask(run, switch(key), "")
        self.ask(run, RATIO, "")
        self.ask(run, PROCEED, "yes")
        result = self.finish(run)
        self.assert_code(result, 0)
        self.assertIn("actionFusion (yes/no) [yes]", result.terminal)
        self.assertIn("observationPack (yes/no) [no]", result.terminal)
        self.assertIn(f"{RATIO} [3]", result.terminal)
        values = self.agent_values()
        self.assertEqual({key: values[key] for key in feature_keys()},
                         {key: key == "actionFusion" for key in feature_keys()})
        self.assertEqual(values["cacheWriteReadRatio"], 3)

    def test_with_no_pi_default_an_empty_reducer_answer_fails_with_no_pi_install_or_remove(self):
        self.tree.write_settings({"packages": ["npm:sol-pi"]})
        before = snapshot(self.tree.agent, self.tree.home)
        run = self.start("install", "--interactive")
        for key in feature_keys():
            self.ask(run, switch(key), "")
        run.expect(f"{ROUTE}: ")
        run.type("")
        result = self.finish(run)
        self.assert_code(result, 1)
        envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("install", False, "failed"))
        self.assertTrue(any("--reducer" in entry for entry in envelope["help"]),
                        envelope["help"])
        self.assertEqual(self.pi.commands(), [], "no pi install or pi remove ran")
        self.assertEqual(snapshot(self.tree.agent, self.tree.home), before)


# --- when it does not prompt ---------------------------------------------------------------------

class NotATerminalTest(InteractiveTestCase):
    """§S1: without a terminal to prompt on, a warning saying why and the plain run's outcome."""

    def reference(self, *args, settings: dict) -> tuple:
        """The same run without `--interactive`, in a tree of its own: `(exit, envelope,
        written bytes or None)`."""
        other = TempTree()
        self.addCleanup(other.cleanup)
        other.write_settings(settings)
        result = run_cli([arg if arg != "<project>" else other.project for arg in args],
                         tree=other, cwd=other.project,
                         env=stub_environ(cli_environ(other), self.pi.bin_dir))
        written = other.project_file.read_bytes() if other.project_file.exists() else None
        return result.returncode, decode_envelope(self, result.stdout), written

    def assert_like_the_plain_run(self, result, reason: str, *, settings: dict) -> None:
        code, plain, written = self.reference("setup", "<project>", settings=settings)
        self.assert_code(result, code)
        self.assert_no_prompt(result.terminal)
        self.assert_no_prompt(result.stderr)
        envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual((envelope["ok"], envelope["outcome"]), (plain["ok"], plain["outcome"]))
        self.assertEqual(envelope.get("config"), plain.get("config"))
        mine = self.tree.project_file.read_bytes() if self.tree.project_file.exists() else None
        self.assertEqual(mine, written)
        self.assertEqual(len(envelope["warnings"]), len(plain["warnings"]) + 1,
                         envelope["warnings"])
        self.assert_interactive_warning(envelope["warnings"], reason)

    def settings(self) -> dict:
        return {"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL}

    def test_pi_noninteractive_set_warns_and_runs_as_without_interactive(self):
        self.tree.write_settings(self.settings())
        run = self.start("setup", self.tree.project, "--interactive",
                         env=self.environ(PI_NONINTERACTIVE="1"))
        self.assert_like_the_plain_run(self.finish(run), "PI_NONINTERACTIVE",
                                       settings=self.settings())

    def test_pi_noninteractive_set_with_no_route_fails_as_without_interactive(self):
        self.tree.write_settings({})
        run = self.start("setup", self.tree.project, "--interactive",
                         env=self.environ(PI_NONINTERACTIVE="1"))
        result = self.finish(run)
        self.assert_like_the_plain_run(result, "PI_NONINTERACTIVE", settings={})
        self.assert_code(result, 1)

    def test_standard_input_not_a_terminal_warns_and_runs_as_without_interactive(self):
        self.tree.write_settings(self.settings())
        run = self.start("setup", self.tree.project, "--interactive", stdin="devnull")
        self.assert_like_the_plain_run(self.finish(run), "standard input",
                                       settings=self.settings())

    def test_standard_error_not_a_terminal_warns_and_runs_as_without_interactive(self):
        self.tree.write_settings(self.settings())
        run = self.start("setup", self.tree.project, "--interactive", stderr="pipe")
        self.assert_like_the_plain_run(self.finish(run), "standard error",
                                       settings=self.settings())

    def test_a_background_process_group_warns_and_runs_as_without_interactive(self):
        self.tree.write_settings(self.settings())
        run = self.start("setup", self.tree.project, "--interactive", background=True)
        self.assert_like_the_plain_run(self.finish(run), "foreground|background",
                                       settings=self.settings())

    def test_an_empty_pi_noninteractive_prompts(self):
        self.with_pi_default()
        run = self.start("setup", self.tree.project, "--interactive",
                         env=self.environ(PI_NONINTERACTIVE=""))
        self.answer_values(run, switches=("no", "", "", ""))
        self.ask(run, PROCEED, "yes")
        result = self.finish(run)
        self.assert_code(result, 0)
        envelope = decode_envelope(self, result.stdout)
        self.assertEqual(envelope["outcome"], "written")
        self.assertEqual([entry for entry in envelope["warnings"] if "--interactive" in entry], [])
        self.assertIs(self.project_values()["actionFusion"], False)

    def test_install_with_pi_noninteractive_set_warns_and_installs_as_without_interactive(self):
        self.with_pi_default()
        run = self.start("install", "--interactive", env=self.environ(PI_NONINTERACTIVE="1"))
        result = self.finish(run)
        self.assert_code(result, 0)
        self.assert_no_prompt(result.terminal)
        envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual((envelope["ok"], envelope["outcome"]), (True, "installed"))
        self.assert_interactive_warning(envelope["warnings"], "PI_NONINTERACTIVE")
        self.assertEqual(self.agent_values(), self.setup_defaults())

    def test_install_without_any_terminal_warns_and_installs(self):
        self.with_pi_default()
        result = self.sol("install", "--interactive")
        self.assert_exit(result, 0)
        envelope = self.envelope(result)
        self.assertEqual((envelope["ok"], envelope["outcome"]), (True, "installed"))
        self.assert_no_prompt(result.stderr)
        self.assert_interactive_warning(envelope["warnings"], "standard input|standard error")


# --- cancelling ----------------------------------------------------------------------------------

class SetupCancelTest(InteractiveTestCase):
    """§S1: a cancel before the confirmation is answered writes nothing and leaves no temporary
    file; `setup`'s `cancelled` envelope has `path` the target and `config` the values shown so
    far (`null` before the first answer)."""

    def setUp(self):
        super().setUp()
        self.with_pi_default()
        self.before = snapshot(self.tree.project, self.tree.agent, self.tree.home)

    def at_first_prompt(self, **options) -> PtyRun:
        run = self.start("setup", self.tree.project, "--interactive", **options)
        run.expect(switch("actionFusion"))
        run.expect(": ")
        return run

    def at_confirmation(self) -> PtyRun:
        run = self.start("setup", self.tree.project, "--interactive")
        self.answer_values(run, switches=("no", "yes", "yes", "yes"), route="prov/mod-7",
                           ratio="8")
        run.expect(PROCEED)
        run.expect(": ")
        return run

    def assert_cancelled(self, run: PtyRun, code: int, cause: str, config) -> dict:
        result = self.finish(run)
        self.assert_code(result, code)
        envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("setup", False, "cancelled"))
        self.assertEqual(envelope["version"], package_json_version())
        self.assertEqual(envelope["path"], str(self.tree.project_file))
        self.assertEqual(envelope["config"], config)
        self.assertRegex(envelope["error"], cause)
        self.assert_rerun_help(envelope, "setup")
        self.assertEqual(snapshot(self.tree.project, self.tree.agent, self.tree.home),
                         self.before, "nothing written, no temporary file")
        return envelope

    def test_declining_the_confirmation_exits_130(self):
        run = self.at_confirmation()
        run.type("no")
        self.assert_cancelled(run, 130, "declined", SETUP_SHOWN)

    def test_ctrl_c_at_the_confirmation_exits_130(self):
        run = self.at_confirmation()
        run.ctrl_c()
        self.assert_cancelled(run, 130, "SIGINT", SETUP_SHOWN)

    def test_ctrl_c_at_a_prompt_exits_130(self):
        run = self.at_first_prompt()
        run.ctrl_c()
        self.assert_cancelled(run, 130, "SIGINT", None)

    def test_ctrl_d_on_an_empty_line_exits_130(self):
        run = self.at_first_prompt()
        run.ctrl_d()
        self.assert_cancelled(run, 130, "end of input", None)

    def test_sigint_at_a_prompt_exits_130(self):
        run = self.at_first_prompt()
        run.send_signal(signal.SIGINT)
        self.assert_cancelled(run, 130, "SIGINT", None)

    def test_sigterm_at_a_prompt_exits_143(self):
        run = self.at_first_prompt()
        run.send_signal(signal.SIGTERM)
        self.assert_cancelled(run, 143, "SIGTERM", None)

    def test_sighup_at_a_prompt_exits_129(self):
        run = self.at_first_prompt()
        run.send_signal(signal.SIGHUP)
        self.assert_cancelled(run, 129, "SIGHUP", None)

    def test_closing_the_terminal_with_a_prompt_partly_answered_exits_exactly_129(self):
        run = self.at_first_prompt()
        run.type_partial("ye")
        run.hang_up()
        self.assert_cancelled(run, 129, "SIGHUP|terminal", None)

    def test_ctrl_c_with_sigint_ignored_at_start_exits_130(self):
        run = self.at_first_prompt(ignore_sigint=True)
        run.ctrl_c()
        self.assert_cancelled(run, 130, "SIGINT", None)


class InstallCancelTest(InteractiveTestCase):
    """§S1: `install`'s `cancelled` envelope before the confirmation: `config` in CR-SLP-007's
    shape with `state` `null`, `extension` the registration as the run left it, `verify` `null`;
    no `pi install` or `pi remove`, nothing written."""

    def setUp(self):
        super().setUp()
        self.with_pi_default()

    def at_first_prompt(self) -> PtyRun:
        run = self.start("install", "--interactive")
        run.expect(switch("actionFusion"))
        run.expect(": ")
        return run

    def assert_cancelled(self, run: PtyRun, code: int, cause: str, *, config: dict,
                         registered: bool, before: dict) -> dict:
        result = self.finish(run)
        self.assert_code(result, code)
        envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("install", False, "cancelled"))
        self.assertRegex(envelope["error"], cause)
        self.assertEqual(envelope["config"], {"path": str(self.tree.agent_file), "state": None,
                                              **config})
        self.assertEqual(envelope["extension"], {"source": self.own_source(),
                                                 "registered": registered, "replaced": [],
                                                 "pi": "1.5.0"})
        self.assertIn("verify", envelope)
        self.assertIsNone(envelope["verify"])
        self.assert_rerun_help(envelope, "install")
        self.assertEqual(self.pi.commands(), [], "no pi install or pi remove ran")
        self.assertEqual(snapshot(self.tree.agent, self.tree.home), before,
                         "nothing written or registered, no temporary file")
        return envelope

    def test_ctrl_c_at_a_prompt_exits_130(self):
        before = snapshot(self.tree.agent, self.tree.home)
        run = self.at_first_prompt()
        run.ctrl_c()
        self.assert_cancelled(run, 130, "SIGINT", config=NOTHING_SHOWN, registered=False,
                              before=before)

    def test_ctrl_d_on_an_empty_line_exits_130(self):
        before = snapshot(self.tree.agent, self.tree.home)
        run = self.at_first_prompt()
        run.ctrl_d()
        self.assert_cancelled(run, 130, "end of input", config=NOTHING_SHOWN,
                              registered=False, before=before)

    def test_sigterm_at_a_prompt_exits_143(self):
        before = snapshot(self.tree.agent, self.tree.home)
        run = self.at_first_prompt()
        run.send_signal(signal.SIGTERM)
        self.assert_cancelled(run, 143, "SIGTERM", config=NOTHING_SHOWN, registered=False,
                              before=before)

    def test_sighup_at_a_prompt_exits_129(self):
        before = snapshot(self.tree.agent, self.tree.home)
        run = self.at_first_prompt()
        run.send_signal(signal.SIGHUP)
        self.assert_cancelled(run, 129, "SIGHUP", config=NOTHING_SHOWN, registered=False,
                              before=before)

    def test_closing_the_terminal_with_a_prompt_partly_answered_exits_exactly_129(self):
        before = snapshot(self.tree.agent, self.tree.home)
        run = self.at_first_prompt()
        run.type_partial("n")
        run.hang_up()
        self.assert_cancelled(run, 129, "SIGHUP|terminal", config=NOTHING_SHOWN,
                              registered=False, before=before)

    def test_declining_the_confirmation_exits_130_with_the_values_shown(self):
        before = snapshot(self.tree.agent, self.tree.home)
        run = self.start("install", "--interactive")
        self.answer_values(run, switches=("yes", "yes", "yes", "no"), route="prov/mod-4",
                           ratio="5")
        self.ask(run, PROCEED, "no")
        self.assert_cancelled(run, 130, "declined",
                              config={"features": ["actionFusion", "observationPack",
                                                   "evidencePreservingReducer"],
                                      "reducer": "prov/mod-4", "cacheRatio": 5},
                              registered=False, before=before)

    def test_a_cancel_with_sol_pi_already_registered_reports_it_registered(self):
        self.with_pi_default([self.own_source()])
        before = snapshot(self.tree.agent, self.tree.home)
        run = self.at_first_prompt()
        run.ctrl_c()
        self.assert_cancelled(run, 130, "SIGINT", config=NOTHING_SHOWN, registered=True,
                              before=before)
        self.assertFalse(self.tree.agent_file.exists())


class RerunCommandTest(InteractiveTestCase):
    """§S1: the `cancelled` envelope's command to run again carries over every value flag given,
    in `--features`, `--reducer`, `--cache-ratio`, `--format` order whatever order they were
    given in, each value shell-quoted, then `--interactive`; a flag not given stays absent."""

    #: A route `--reducer` accepts (no whitespace) that the shell must have quoted.
    ODD_REDUCER = "pro'v/m$od;x"

    def setUp(self):
        super().setUp()
        self.with_pi_default()

    def cancelled_help(self, *args, fmt: str = "toon") -> list:
        run = self.start(*args)
        run.expect(switch("actionFusion"))
        run.expect(": ")
        run.ctrl_c()
        result = self.finish(run)
        self.assert_code(result, 130)
        if fmt == "json":
            self.assert_no_prompt(result.stdout)
            envelope = json.loads(result.stdout)["axi"]
        else:
            envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual(envelope["outcome"], "cancelled")
        return envelope["help"]

    def test_setup_without_value_flags_runs_the_same_command_again(self):
        self.assertEqual(self.cancelled_help("setup", self.tree.project, "--interactive"),
                         [f"sol-pi-axi setup {shlex.quote(str(self.tree.project))} --interactive"])

    def test_setup_carries_over_every_value_flag_quoted_in_a_stable_order(self):
        help_steps = self.cancelled_help("setup", self.tree.project, "--cache-ratio", "4.5",
                                         "--interactive", f"--reducer={self.ODD_REDUCER}",
                                         "--features", "observationPack,evidencePreservingReducer")
        self.assertEqual(help_steps, [(
            f"sol-pi-axi setup {shlex.quote(str(self.tree.project))} "
            "--features observationPack,evidencePreservingReducer "
            f"--reducer {shlex.quote(self.ODD_REDUCER)} --cache-ratio 4.5 --interactive")])
        self.assertIn("--reducer 'pro'\"'\"'v/m$od;x'", help_steps[0])

    def test_setup_in_a_directory_needing_quotes_keeps_it_quoted_before_the_flags(self):
        project = self.tree.root / "my proj's"
        project.mkdir()
        help_steps = self.cancelled_help("setup", project, "--interactive", "--reducer",
                                         "prov/mod-1")
        self.assertEqual(help_steps, [(f"sol-pi-axi setup {shlex.quote(str(project))} "
                                       "--reducer prov/mod-1 --interactive")])

    def test_install_without_value_flags_runs_the_same_command_again(self):
        self.assertEqual(self.cancelled_help("install", "--interactive"),
                         ["sol-pi-axi install --interactive"])

    def test_install_carries_over_every_value_flag_quoted_in_a_stable_order(self):
        help_steps = self.cancelled_help("install", "--format=json", "--interactive",
                                         "--cache-ratio", "3", "--reducer", self.ODD_REDUCER,
                                         "--features", "none", fmt="json")
        self.assertEqual(help_steps, [(
            f"sol-pi-axi install --features none --reducer {shlex.quote(self.ODD_REDUCER)} "
            "--cache-ratio 3 --format json --interactive")])

    def test_install_with_some_value_flags_names_only_those(self):
        help_steps = self.cancelled_help("install", "--interactive", "--features", "actionFusion")
        self.assertEqual(help_steps, ["sol-pi-axi install --features actionFusion --interactive"])
        self.assertNotIn("--non-interactive", help_steps[0])


class InstallAfterConfirmationTest(InteractiveTestCase):
    """§S1: after the confirmation, signals follow CR-SLP-007 §S2: `SIGTERM` while the stub's
    `pi install` is held exits 143 with `extension` reporting the registration."""

    def test_sigterm_while_pi_install_is_held_exits_143_reporting_the_registration(self):
        self.with_pi_default()
        hold = self.tree.root / "pi-hold"
        self.addCleanup(hold.unlink, missing_ok=True)
        run = self.start("install", "--interactive", env=self.environ(**{PI_HOLD_ENV: str(hold)}))
        self.answer_values(run)
        self.ask(run, PROCEED, "yes")
        deadline = time.monotonic() + HOLD_TIMEOUT
        while not (hold.exists() and hold.read_text(encoding="utf-8").endswith("\n")):
            if run.returncode is not None:
                self.fail(f"the run ended (exit {run.returncode}) before pi install was held\n"
                          f"{run.stdout()}\n{run.terminal()}")
            if time.monotonic() > deadline:
                self.fail("the stub pi install was not held within the timeout")
            time.sleep(0.01)
        run.send_signal(signal.SIGTERM)
        result = self.finish(run)
        self.assert_code(result, 143)
        envelope = self.assert_stdout_is_only_the_envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("install", False, "cancelled"))
        self.assertIn(self.own_source(), self.packages(), "premise: the held stub recorded it")
        self.assertEqual(envelope["extension"]["source"], self.own_source())
        self.assertIs(envelope["extension"]["registered"], True,
                      "extension reports the registration the run left")
        self.assertFalse(self.tree.agent_file.exists(), "the agent file is written after pi")
        leftovers = sorted(name for name in os.listdir(self.tree.agent)
                           if name not in ("settings.json", "npm"))
        self.assertEqual(leftovers, [], "no temporary file")


class StubPiHoldTest(PiCommandTestCase):
    """The stub `pi`'s `pi install` hold (support for the test above): held once `settings.json`
    records the source, released when the hold file is removed."""

    def test_pi_install_is_held_after_recording_until_the_hold_file_is_removed(self):
        hold = self.tree.root / "pi-hold"
        env = self.environ(**{PI_HOLD_ENV: str(hold)})
        process = subprocess.Popen([str(self.pi.path), "install", self.own_source(),
                                    "--no-approve"], cwd=self.tree.home, env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        deadline = time.monotonic() + HOLD_TIMEOUT
        while not (hold.exists() and hold.read_text(encoding="utf-8").endswith("\n")):
            self.assertIsNone(process.poll(), "the stub ended before holding")
            self.assertLess(time.monotonic(), deadline, "the stub did not hold")
            time.sleep(0.01)
        self.assertEqual(int(hold.read_text(encoding="utf-8")), process.pid)
        self.assertEqual(self.packages(), [self.own_source()], "recorded before the hold")
        with self.assertRaises(subprocess.TimeoutExpired, msg="still held"):
            process.wait(timeout=0.2)
        hold.unlink()
        stdout, _ = process.communicate(timeout=HOLD_TIMEOUT)
        self.assertEqual(process.returncode, 0)
        self.assertIn(f"Installed {self.own_source()}", stdout)


# --- usage, help and the --yes hint --------------------------------------------------------------

class InteractiveUsageTest(PiCommandTestCase):
    """§S1: `--interactive` is a flag of `setup` and `install` only, and never with
    `--non-interactive`; `--help` and the `--yes` hint name it."""

    def assert_usage(self, args: list, *named: str) -> dict:
        before = snapshot(self.tree.project, self.tree.agent, self.tree.home)
        result = self.sol(*args)
        self.assert_exit(result, 2)
        envelope = self.envelope(result)
        self.assertEqual((envelope["ok"], envelope["outcome"]), (False, "usage"))
        reason = envelope["error"].split(";")[0]
        for name in named:
            self.assertIn(name, reason, envelope["error"])
        self.assertNotIn("unknown flag", reason, "--interactive is a known flag")
        self.assertEqual(snapshot(self.tree.project, self.tree.agent, self.tree.home), before)
        return envelope

    def test_interactive_with_non_interactive_is_a_usage_error_for_setup_and_install(self):
        self.with_pi_default()
        self.assert_usage(["setup", self.tree.project, "--interactive", "--non-interactive"],
                          "--interactive", "--non-interactive")
        self.assert_usage(["install", "--non-interactive", "--interactive"],
                          "--interactive", "--non-interactive")
        self.assertEqual(self.pi.calls(), [])

    def test_interactive_on_the_home_view_uninstall_and_verify_is_a_usage_error(self):
        for args in (["--interactive"], ["uninstall", "--interactive"],
                     ["verify", "--interactive"]):
            with self.subTest(args=args):
                self.assert_usage(args, "--interactive")
        self.assertEqual(self.pi.calls(), [])

    def test_a_usage_error_lists_interactive_among_the_valid_flags(self):
        result = self.sol("setup", self.tree.project, "--bogus")
        self.assert_exit(result, 2)
        self.assertIn("--interactive", self.envelope(result)["error"])

    def test_help_names_interactive_and_no_longer_says_the_command_never_prompts(self):
        result = self.sol("--help")
        self.assert_exit(result, 0)
        self.assertRegex(result.stdout, r"(?m)^\s+--interactive\b", "a flag line for it")
        self.assertNotRegex(" ".join(result.stdout.split()), r"(?i)never\s+prompts")

    def test_the_yes_hint_names_interactive_and_non_interactive(self):
        result = self.sol("setup", self.tree.project, "--yes")
        self.assert_exit(result, 2)
        envelope = self.envelope(result)
        hint = " ".join([envelope["error"].split("; valid verbs")[0], *envelope["help"]])
        self.assertRegex(hint, r"(?<![\w-])--interactive\b")
        self.assertIn("--non-interactive", hint)
        self.assertNotRegex(" ".join(hint.split()), r"(?i)never\s+prompts")

    def test_no_source_of_the_command_says_it_never_prompts(self):
        for path in sorted((REPO / "sol_pi_axi").glob("*.py")):
            with self.subTest(path=path.name):
                text = " ".join(path.read_text(encoding="utf-8").split())
                self.assertNotRegex(re.sub(r'"\s*"', "", text), r"(?i)never\s+prompts")


if __name__ == "__main__":
    unittest.main()
