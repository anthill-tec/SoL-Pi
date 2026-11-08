# SPDX-License-Identifier: MIT
"""The `sol-pi-axi` command line, driven as a subprocess through the editable install's console
script with a temporary project, agent directory and home (`PI_CODING_AGENT_DIR` set): the version
and help flags (§S1, §S3), the flags of `setup` (§S3), the envelope, usage errors, exit codes,
`help[]` and the home view (§S4), and the agent directory through the command (§S2).

Envelopes are decoded with `toon_format.decode`; no run may put a traceback or a dependency message
on either stream."""

import json
import os
import re
import subprocess
import sys
import unittest

from tests.sol_pi_axi_support import (
    TempTree,
    assert_clean_streams,
    cli_environ,
    decode_envelope,
    default_cache_ratio,
    default_reducer_model,
    default_reducer_provider,
    feature_keys,
    package_json_version,
    run_cli,
    snapshot,
    venv_script,
)

PI_PROVIDER = "anthropic"
PI_MODEL = "claude-sonnet-4-5"
#: Every flag a usage error lists, beside the one verb.
LISTED_FLAGS = ("--features", "--reducer", "--cache-ratio", "--format", "--non-interactive",
                "--help", "--version")
#: The keys every envelope carries.
COMMON_KEYS = {"verb", "ok", "version", "warnings", "help"}


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)

    def sol(self, *args, cwd=None, env=None, stdin=subprocess.DEVNULL, tree=None):
        """Run `sol-pi-axi <args>`; neither stream may carry a traceback or dependency message."""
        result = run_cli(args, tree=tree or self.tree, cwd=cwd, env=env, stdin=stdin)
        assert_clean_streams(self, result)
        return result

    def envelope(self, result) -> dict:
        return decode_envelope(self, result.stdout)

    def with_pi_default(self, tree=None):
        (tree or self.tree).write_settings({"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL})

    def project_values(self, tree=None) -> dict:
        return json.loads((tree or self.tree).project_file.read_text(encoding="utf-8"))

    def assert_features(self, values: dict, enabled) -> None:
        self.assertEqual({key: values[key] for key in feature_keys()},
                         {key: key in enabled for key in feature_keys()})

    def assert_exit(self, result, code: int) -> None:
        self.assertEqual(result.returncode, code, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")


class VersionTest(CliTestCase):
    """§S1, §S3: `-v`, `-V`, `--version` print the bare version and exit 0, before `toon_format` or
    any verb module is imported; anywhere else among the arguments they still print it."""

    def test_each_lone_version_flag_prints_the_bare_version_and_exits_0(self):
        for flag in ("-v", "-V", "--version"):
            with self.subTest(flag=flag):
                result = self.sol(flag)
                self.assert_exit(result, 0)
                self.assertEqual(result.stdout, f"{package_json_version()}\n")
                self.assertEqual(result.stderr, "")

    def test_a_lone_version_flag_prints_the_version_with_toon_format_unimportable(self):
        shadow = self.tree.root / "shadow"
        (shadow / "toon_format").mkdir(parents=True)
        (shadow / "toon_format" / "__init__.py").write_text(
            'raise ImportError("toon_format is unimportable in this test")\n', encoding="utf-8")
        env = cli_environ(self.tree, PYTHONPATH=str(shadow))
        # The premise: with this environment the dependency cannot be imported at all.
        premise = subprocess.run([sys.executable, "-c", "import toon_format"], env=env,
                                 capture_output=True, text=True, timeout=60, check=False)
        self.assertNotEqual(premise.returncode, 0, "the shadow must make toon_format unimportable")
        for flag in ("-v", "-V", "--version"):
            with self.subTest(flag=flag):
                result = self.sol(flag, env=env)
                self.assert_exit(result, 0)
                self.assertEqual(result.stdout, f"{package_json_version()}\n")
                self.assertEqual(result.stderr, "")

    def test_a_lone_version_flag_imports_neither_toon_format_nor_a_verb_module(self):
        loaded_file = self.tree.root / "loaded.json"
        program = (
            "import json, sys\n"
            "from sol_pi_axi.cli import main\n"
            f"sys.argv = ['sol-pi-axi', sys.argv[1]]\n"
            "try:\n"
            "    code = main()\n"
            "except SystemExit as stop:\n"
            "    code = stop.code\n"
            "names = sorted(name for name in sys.modules\n"
            "               if name.split('.')[0] in ('toon_format', 'sol_pi_axi'))\n"
            f"open({str(loaded_file)!r}, 'w').write(json.dumps({{'code': code, 'loaded': names}}))\n"
        )
        for flag in ("-v", "-V", "--version"):
            with self.subTest(flag=flag):
                result = subprocess.run([sys.executable, "-c", program, flag], cwd=self.tree.root,
                                        env=cli_environ(self.tree), capture_output=True, text=True,
                                        timeout=60, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, f"{package_json_version()}\n")
                report = json.loads(loaded_file.read_text(encoding="utf-8"))
                self.assertIn(report["code"], (0, None))
                forbidden = [name for name in report["loaded"]
                             if name.split(".")[0] == "toon_format"
                             or name in ("sol_pi_axi.setup", "sol_pi_axi.config", "sol_pi_axi.write")]
                self.assertEqual(forbidden, [])

    def test_a_version_flag_after_other_arguments_prints_the_version_and_writes_nothing(self):
        missing = self.tree.root / "missing"
        cases = (
            ["setup", missing, "--version"],
            ["setup", self.tree.project, "--features", "all", "-V"],
            ["setup", self.tree.project, "-v", "--cache-ratio", "2"],
            ["frobnicate", "--version"],
        )
        for args in cases:
            with self.subTest(args=args):
                result = self.sol(*args)
                self.assert_exit(result, 0)
                self.assertEqual(result.stdout, f"{package_json_version()}\n")
                self.assertFalse(self.tree.pi_dir.exists())
                self.assertFalse(missing.exists())


class HelpTest(CliTestCase):
    """§S3, §S4: `--help`/`-h` anywhere prints plain-text help (verbs, flags with defaults,
    examples) and exits 0, before anything else."""

    def test_help_anywhere_prints_the_same_plain_text_help_and_exits_0(self):
        cases = (
            ["--help"],
            ["-h"],
            ["setup", "x", "--help"],
            ["setup", "--bogus", "-h"],
            ["frobnicate", "--help"],
            ["--version", "--help"],
            ["--format", "json", "-h"],
            ["setup", self.tree.project, "--features", "Bogus", "--help"],
        )
        texts = []
        for args in cases:
            with self.subTest(args=args):
                result = self.sol(*args)
                self.assert_exit(result, 0)
                text = result.stdout
                self.assertFalse(text.lstrip().startswith("axi"), "help is plain text, not an envelope")
                self.assertFalse(text.lstrip().startswith("{"), "help is plain text, not JSON")
                self.assertIn("setup", text)
                for flag in LISTED_FLAGS:
                    self.assertIn(flag, text)
                self.assertIn("-h", text)
                self.assertIn("toon", text, "the --format default is named")
                self.assertIn("json", text)
                self.assertIn("sol-pi-axi setup", text, "an example is given")
                self.assertNotEqual(text, f"{package_json_version()}\n")
                texts.append(text)
        self.assertEqual(len(set(texts)), 1, "help is the same wherever the flag appears")
        self.assertFalse(self.tree.pi_dir.exists())
        self.assertFalse((self.tree.root / "x").exists())


class SetupFlagsTest(CliTestCase):
    """§S3: `--features`, `--reducer`, `--cache-ratio` override and write; a repeat is `unchanged`;
    `all`, `none` and `--flag=value`; flags before or after the directory; `--non-interactive` has
    no effect; no prompt with standard input a terminal."""

    def test_features_list_enables_the_listed_mechanisms_and_turns_the_others_off(self):
        result = self.sol("setup", self.tree.project, "--features", "observationPack,actionFusion")
        self.assert_exit(result, 0)
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "written")
        values = self.project_values()
        self.assert_features(values, {"observationPack", "actionFusion"})
        # The reducer is off, so the built-in route is written.
        self.assertEqual(values["evidencePreservingReducerProvider"], default_reducer_provider())
        self.assertEqual(values["evidencePreservingReducerModel"], default_reducer_model())
        self.assertCountEqual(envelope["config"]["features"], ["observationPack", "actionFusion"])
        self.assertEqual(len(envelope["config"]["features"]), 2)

    def test_reducer_flag_is_split_at_the_first_slash_and_written(self):
        result = self.sol("setup", self.tree.project, "--reducer", "my-provider/org/model-x")
        self.assert_exit(result, 0)
        values = self.project_values()
        self.assertEqual(values["evidencePreservingReducerProvider"], "my-provider")
        self.assertEqual(values["evidencePreservingReducerModel"], "org/model-x")
        self.assert_features(values, set(feature_keys()))
        self.assertEqual(self.envelope(result)["config"]["reducer"], "my-provider/org/model-x")

    def test_cache_ratio_flag_overrides_the_ratio(self):
        self.with_pi_default()
        result = self.sol("setup", self.tree.project, "--cache-ratio", "3.25")
        self.assert_exit(result, 0)
        self.assertEqual(self.project_values()["cacheWriteReadRatio"], 3.25)
        self.assertEqual(self.envelope(result)["config"]["cacheRatio"], 3.25)
        result = self.sol("setup", self.tree.project, "--cache-ratio", "7")
        self.assert_exit(result, 0)
        self.assertEqual(self.envelope(result)["outcome"], "written")
        self.assertIn(b'\t"cacheWriteReadRatio": 7\n', self.tree.project_file.read_bytes())

    def test_value_flags_over_a_valid_project_file_start_from_its_values(self):
        self.tree.write_project_file('{"version":1,"actionFusion":true,"cacheWriteReadRatio":4}')
        result = self.sol("setup", self.tree.project, "--reducer", "p1/m1")
        self.assert_exit(result, 0)
        values = self.project_values()
        self.assert_features(values, {"actionFusion"})
        self.assertEqual(values["cacheWriteReadRatio"], 4)
        self.assertEqual((values["evidencePreservingReducerProvider"],
                          values["evidencePreservingReducerModel"]), ("p1", "m1"))

    def test_the_same_flags_repeated_are_unchanged_with_bytes_and_modification_time_kept(self):
        args = ("setup", self.tree.project, "--features", "actionFusion", "--reducer", "p/m",
                "--cache-ratio", "2.5")
        first = self.sol(*args)
        self.assert_exit(first, 0)
        self.assertEqual(self.envelope(first)["outcome"], "written")
        before = snapshot(self.tree.project, self.tree.agent)
        second = self.sol(*args)
        self.assert_exit(second, 0)
        envelope = self.envelope(second)
        self.assertEqual(envelope["outcome"], "unchanged")
        self.assertEqual(envelope["help"], [])
        self.assertEqual(snapshot(self.tree.project, self.tree.agent), before)

    def test_features_all_enables_every_mechanism_with_pis_default_route(self):
        self.with_pi_default()
        result = self.sol("setup", self.tree.project, "--features", "all")
        self.assert_exit(result, 0)
        values = self.project_values()
        self.assert_features(values, set(feature_keys()))
        self.assertEqual((values["evidencePreservingReducerProvider"],
                          values["evidencePreservingReducerModel"]), (PI_PROVIDER, PI_MODEL))
        self.assertCountEqual(self.envelope(result)["config"]["features"], feature_keys())

    def test_features_none_turns_every_mechanism_off_with_the_built_in_route(self):
        result = self.sol("setup", self.tree.project, "--features", "none")
        self.assert_exit(result, 0)
        values = self.project_values()
        self.assert_features(values, set())
        self.assertEqual((values["evidencePreservingReducerProvider"],
                          values["evidencePreservingReducerModel"]),
                         (default_reducer_provider(), default_reducer_model()))
        self.assertEqual(self.envelope(result)["config"]["features"], [])

    def test_flag_equals_value_form_sets_every_value_flag(self):
        result = self.sol("setup", self.tree.project, "--features=none", "--reducer=p2/m2",
                          "--cache-ratio=2")
        self.assert_exit(result, 0)
        values = self.project_values()
        self.assert_features(values, set())
        self.assertEqual((values["evidencePreservingReducerProvider"],
                          values["evidencePreservingReducerModel"]), ("p2", "m2"))
        self.assertEqual(values["cacheWriteReadRatio"], 2)
        self.assertEqual(self.envelope(result)["config"]["reducer"], "p2/m2")

    def test_flags_before_and_after_the_directory_give_the_same_file(self):
        after = self.sol("setup", self.tree.project, "--features", "observationPack",
                         "--cache-ratio", "1.5")
        self.assert_exit(after, 0)
        self.assertEqual(self.envelope(after)["outcome"], "written")
        written = self.tree.project_file.read_bytes()
        values = self.project_values()
        self.assert_features(values, {"observationPack"})
        self.assertEqual(values["cacheWriteReadRatio"], 1.5)
        before = self.sol("setup", "--features", "observationPack", "--cache-ratio=1.5",
                          self.tree.project)
        self.assert_exit(before, 0)
        self.assertEqual(self.envelope(before)["outcome"], "unchanged")
        self.assertEqual(self.tree.project_file.read_bytes(), written)

    def test_non_interactive_changes_nothing(self):
        other = TempTree()
        self.addCleanup(other.cleanup)
        for tree in (self.tree, other):
            self.with_pi_default(tree)
        plain = self.sol("setup", self.tree.project)
        flagged = self.sol("setup", other.project, "--non-interactive", tree=other)
        self.assert_exit(plain, 0)
        self.assert_exit(flagged, 0)
        self.assertEqual(other.project_file.read_bytes(), self.tree.project_file.read_bytes())
        first, second = self.envelope(plain), self.envelope(flagged)
        for key in ("outcome", "config", "warnings", "ok"):
            self.assertEqual(second[key], first[key], key)
        self.assertEqual([entry.replace(str(other.project), "<project>") for entry in second["help"]],
                         [entry.replace(str(self.tree.project), "<project>") for entry in first["help"]])
        # A repeat with the flag is unchanged too.
        repeat = self.sol("setup", other.project, "--non-interactive", tree=other)
        self.assertEqual(self.envelope(repeat)["outcome"], "unchanged")

    def _run_with_terminal_stdin(self, *args):
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        try:
            process = subprocess.Popen([str(venv_script()), *[str(arg) for arg in args]],
                                       cwd=self.tree.root, env=cli_environ(self.tree), stdin=slave,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        finally:
            os.close(slave)
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            self.fail("sol-pi-axi waited on its terminal standard input: it prompted")
        result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        assert_clean_streams(self, result)
        return result

    def test_no_prompt_with_standard_input_a_terminal_when_a_value_is_unresolvable(self):
        # The reducer is enabled and neither Pi's settings nor a flag names its route.
        result = self._run_with_terminal_stdin("setup", self.tree.project)
        self.assert_exit(result, 1)
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "failed")
        self.assertTrue(any("--reducer" in entry for entry in envelope["help"]), envelope["help"])
        self.assertFalse(self.tree.pi_dir.exists())

    def test_no_prompt_with_standard_input_a_terminal_when_every_value_resolves(self):
        self.with_pi_default()
        result = self._run_with_terminal_stdin("setup", self.tree.project)
        self.assert_exit(result, 0)
        self.assertEqual(self.envelope(result)["outcome"], "written")
        self.assertTrue(self.tree.project_file.is_file())


class UsageErrorTest(CliTestCase):
    """§S3, §S4: usage errors exit 2 with `verb: usage`, `outcome: usage`, an `error` naming the
    input and listing the valid verbs and flags, checked before anything is read."""

    def assert_usage(self, args, named: str, *, env=None) -> dict:
        before = snapshot(self.tree.project, self.tree.agent, self.tree.home)
        result = self.sol(*args, env=env)
        self.assert_exit(result, 2)
        envelope = self.envelope(result)
        self.assertEqual(envelope["verb"], "usage")
        self.assertEqual(envelope["outcome"], "usage")
        self.assertIs(envelope["ok"], False)
        self.assertEqual(envelope["version"], package_json_version())
        self.assertIsInstance(envelope["help"], list)
        self.assertIsInstance(envelope["warnings"], list)
        error = envelope["error"]
        self.assertIsInstance(error, str)
        self.assertIn(named, error)
        self.assertIn("setup", error, "the valid verbs are listed")
        for flag in LISTED_FLAGS:
            self.assertIn(flag, error, "the valid flags are listed")
        self.assertEqual(snapshot(self.tree.project, self.tree.agent, self.tree.home), before,
                         "a usage error changes nothing")
        return envelope

    def test_an_unknown_verb_is_a_usage_error_naming_it(self):
        self.assert_usage(["frobnicate"], "frobnicate")

    def test_an_unknown_flag_is_a_usage_error_naming_it(self):
        self.assert_usage(["setup", self.tree.project, "--bogus"], "--bogus")
        self.assert_usage(["--bogus"], "--bogus")

    def test_a_repeated_flag_is_a_usage_error_naming_it(self):
        self.assert_usage(["setup", self.tree.project, "--features", "all", "--features", "none"],
                          "--features")
        self.assert_usage(["setup", self.tree.project, "--non-interactive", "--non-interactive"],
                          "--non-interactive")
        self.assert_usage(["setup", self.tree.project, "--format", "toon", "--format=toon"],
                          "--format")

    def test_an_extra_argument_is_a_usage_error_naming_it(self):
        self.assert_usage(["setup", self.tree.project, "surplus"], "surplus")

    def test_setup_without_a_directory_is_a_usage_error(self):
        self.assert_usage(["setup"], "setup")
        self.assert_usage(["setup", "--features", "all"], "setup")

    def test_a_value_flag_on_the_home_view_is_a_usage_error_naming_it(self):
        self.assert_usage(["--features", "all"], "--features")
        self.assert_usage(["--reducer=p/m"], "--reducer")
        self.assert_usage(["--cache-ratio", "2"], "--cache-ratio")
        self.assert_usage(["--non-interactive"], "--non-interactive")

    def test_yes_gets_a_hint_naming_non_interactive(self):
        def mentions(envelope: dict) -> int:
            return (envelope["error"].count("--non-interactive")
                    + sum(entry.count("--non-interactive") for entry in envelope["help"]))

        yes = self.assert_usage(["setup", self.tree.project, "--yes"], "--yes")
        bogus = self.assert_usage(["setup", self.tree.project, "--bogus"], "--bogus")
        self.assertGreater(mentions(yes), mentions(bogus),
                           "--yes gets a hint naming --non-interactive beyond the flag list")

    def test_usage_is_checked_before_anything_is_read(self):
        missing = self.tree.root / "missing"
        self.assert_usage(["setup", missing, "--bogus"], "--bogus")
        self.tree.write_project_file('{"version":2}')
        self.assert_usage(["setup", self.tree.project, "--features", "Bogus"], "--features")
        self.tree.settings_file.write_text("{not json", encoding="utf-8")
        self.assert_usage(["setup", self.tree.project, "surplus"], "surplus")

    def test_every_malformed_flag_value_is_a_usage_error_naming_its_flag(self):
        cases = [
            ("--features", ""),
            ("--features", "a,,b"),
            ("--features", "actionFusion,,observationPack"),
            ("--features", "actionFusion,actionFusion"),
            ("--features", "all,actionFusion"),
            ("--features", "ActionFusion"),
            ("--features", "actionfusion"),
            ("--reducer", "provider/"),
            ("--reducer", "/model"),
            ("--reducer", " p/m"),
            ("--reducer", "no-slash"),
            ("--cache-ratio", ""),
            ("--cache-ratio", "-1"),
            ("--cache-ratio", "1e3"),
            ("--cache-ratio", "0x10"),
            ("--cache-ratio", " 2"),
            ("--cache-ratio", "1" + "0" * 400),
        ]
        self.with_pi_default()
        for flag, value in cases:
            with self.subTest(flag=flag, value=value):
                self.assert_usage(["setup", self.tree.project, flag, value], flag)
                self.assertFalse(self.tree.pi_dir.exists())

    def test_a_malformed_format_answers_a_usage_error_in_toon(self):
        for args in (["--format", "xml"], ["setup", self.tree.project, "--format", "yaml"],
                     ["setup", self.tree.project, "--format"], ["--format=JSON"]):
            with self.subTest(args=args):
                result = self.sol(*args)
                self.assertFalse(result.stdout.lstrip().startswith("{"), "answered in TOON")
                self.assert_usage(args, "--format")
                self.assertFalse(self.tree.pi_dir.exists())

    def test_format_json_is_read_first_and_answers_a_usage_error_in_json(self):
        for args in (["frobnicate", "--format", "json"], ["--format=json", "setup"],
                     ["setup", self.tree.project, "--bogus", "--format", "json"]):
            with self.subTest(args=args):
                result = self.sol(*args)
                self.assert_exit(result, 2)
                self.assertEqual(result.stdout.count("\n"), 1, result.stdout)
                self.assertTrue(result.stdout.endswith("\n"))
                envelope = json.loads(result.stdout)["axi"]
                self.assertEqual((envelope["verb"], envelope["outcome"], envelope["ok"]),
                                 ("usage", "usage", False))


class EnvelopeTest(CliTestCase):
    """§S4: each envelope's keys for its `verb`; `--format json`; `help[]`; exit codes; a relative
    project directory; no traceback even when the configuration module raises."""

    def assert_common(self, envelope: dict, verb: str, ok: bool) -> None:
        self.assertTrue(set(envelope) >= COMMON_KEYS, envelope)
        self.assertEqual(envelope["verb"], verb)
        self.assertIs(envelope["ok"], ok)
        self.assertEqual(envelope["version"], package_json_version())
        self.assertIsInstance(envelope["warnings"], list)
        self.assertIsInstance(envelope["help"], list)
        if ok:
            self.assertNotIn("error", envelope)
        else:
            self.assertIsInstance(envelope["error"], str)
            self.assertTrue(envelope["error"])

    def test_a_written_setup_envelope_has_the_setup_keys_and_the_effective_values(self):
        self.with_pi_default()
        result = self.sol("setup", self.tree.project)
        self.assert_exit(result, 0)
        envelope = self.envelope(result)
        self.assert_common(envelope, "setup", True)
        self.assertEqual(envelope["outcome"], "written")
        self.assertEqual(envelope["path"], str(self.tree.project_file))
        self.assertEqual(set(envelope["config"]), {"features", "reducer", "cacheRatio"})
        self.assertCountEqual(envelope["config"]["features"], feature_keys())
        self.assertEqual(len(envelope["config"]["features"]), len(feature_keys()))
        self.assertEqual(envelope["config"]["reducer"], f"{PI_PROVIDER}/{PI_MODEL}")
        self.assertEqual(envelope["config"]["cacheRatio"], default_cache_ratio())
        self.assertEqual(envelope["context"], {"project": str(self.tree.project),
                                               "agentDir": str(self.tree.agent)})
        self.assertEqual(envelope["warnings"], [])

    def test_written_help_names_starting_pi_in_the_project_and_trusting_it(self):
        self.with_pi_default()
        envelope = self.envelope(self.sol("setup", self.tree.project))
        self.assertEqual(envelope["outcome"], "written")
        steps = envelope["help"]
        self.assertTrue(steps, "written has next steps")
        self.assertTrue(any(str(self.tree.project) in step for step in steps), steps)
        self.assertTrue(any(re.search(r"(^|\s)pi(\s|$)", step) for step in steps),
                        f"a step starts Pi: {steps}")
        self.assertTrue(any("trust" in step.lower() for step in steps), steps)

    def test_an_unchanged_setup_envelope_has_no_help_steps(self):
        self.tree.write_project_file('{"version":1,"actionFusion":true}')
        result = self.sol("setup", self.tree.project)
        self.assert_exit(result, 0)
        envelope = self.envelope(result)
        self.assert_common(envelope, "setup", True)
        self.assertEqual(envelope["outcome"], "unchanged")
        self.assertEqual(envelope["help"], [])
        self.assertEqual(envelope["path"], str(self.tree.project_file))
        self.assertEqual(envelope["config"]["features"], ["actionFusion"])
        self.assertEqual(envelope["config"]["reducer"],
                         f"{default_reducer_provider()}/{default_reducer_model()}")

    def test_a_failed_setup_exits_1_naming_the_path_with_a_null_config(self):
        missing = self.tree.root / "missing"
        result = self.sol("setup", missing)
        self.assert_exit(result, 1)
        envelope = self.envelope(result)
        self.assert_common(envelope, "setup", False)
        self.assertEqual(envelope["outcome"], "failed")
        self.assertIn(str(missing), envelope["error"])
        self.assertIsNone(envelope["config"])
        self.assertTrue(envelope["path"] is None or os.path.isabs(envelope["path"]), envelope["path"])
        self.assertEqual(set(envelope["context"]), {"project", "agentDir"})
        self.assertFalse(missing.exists())

    def test_a_failed_setup_without_a_route_names_the_reducer_flag_in_help(self):
        result = self.sol("setup", self.tree.project)
        self.assert_exit(result, 1)
        envelope = self.envelope(result)
        self.assert_common(envelope, "setup", False)
        self.assertEqual(envelope["outcome"], "failed")
        self.assertTrue(any("--reducer" in step for step in envelope["help"]), envelope["help"])
        self.assertFalse(self.tree.pi_dir.exists())

    def test_an_invalid_project_file_fails_with_exit_1_changing_nothing(self):
        self.tree.write_project_file('{"version":2}')
        before = snapshot(self.tree.project, self.tree.agent)
        result = self.sol("setup", self.tree.project, "--features", "all")
        self.assert_exit(result, 1)
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "failed")
        self.assertIn(str(self.tree.project_file), envelope["error"])
        self.assertEqual(snapshot(self.tree.project, self.tree.agent), before)

    def test_a_leftover_backup_is_named_in_warnings(self):
        self.with_pi_default()
        self.tree.pi_dir.mkdir()
        backup = self.tree.pi_dir / "sol-pi.json.bak"
        backup.write_text("old\n", encoding="utf-8")
        result = self.sol("setup", self.tree.project)
        self.assert_exit(result, 0)
        warnings = self.envelope(result)["warnings"]
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn(str(backup), warnings[0])
        self.assertEqual(backup.read_text(encoding="utf-8"), "old\n")

    def test_a_relative_project_directory_resolves_against_the_working_directory(self):
        self.with_pi_default()
        for cwd, argument in ((self.tree.root, "project"), (self.tree.project, "."),
                              (self.tree.home, "../project")):
            with self.subTest(cwd=cwd, argument=argument):
                result = self.sol("setup", argument, cwd=cwd)
                self.assert_exit(result, 0)
                envelope = self.envelope(result)
                self.assertEqual(envelope["path"], str(self.tree.project_file))
                self.assertEqual(envelope["context"]["project"], str(self.tree.project))
                self.assertTrue(self.tree.project_file.is_file())
        self.assertFalse((self.tree.home / ".pi").exists())

    def test_format_json_is_one_line_parsing_to_the_same_object_as_toon(self):
        self.with_pi_default()
        self.sol("setup", self.tree.project)  # written; the runs below are deterministic
        scenarios = {
            "home": ([], self.tree.project),
            "unchanged": (["setup", self.tree.project], self.tree.root),
            "failed": (["setup", self.tree.root / "missing"], self.tree.root),
            "usage": (["frobnicate"], self.tree.root),
        }
        for name, (args, cwd) in scenarios.items():
            with self.subTest(scenario=name):
                toon = self.sol(*args, cwd=cwd)
                for form in (["--format", "json"], ["--format=json"]):
                    as_json = self.sol(*args, *form, cwd=cwd)
                    self.assertEqual(as_json.returncode, toon.returncode)
                    self.assertTrue(as_json.stdout.endswith("\n"))
                    self.assertEqual(as_json.stdout.count("\n"), 1, as_json.stdout)
                    self.assertEqual(json.loads(as_json.stdout), {"axi": self.envelope(toon)})
                explicit = self.sol(*args, "--format", "toon", cwd=cwd)
                self.assertEqual(explicit.stdout, toon.stdout)

    def test_pi_coding_agent_dir_with_a_tilde_reads_the_agent_file_under_home(self):
        agent = self.tree.home / "agent"
        agent.mkdir()
        (agent / "sol-pi.json").write_text(
            '{"version":1,"observationPack":true,"cacheWriteReadRatio":3}', encoding="utf-8")
        result = self.sol("setup", self.tree.project,
                          env=cli_environ(self.tree, PI_CODING_AGENT_DIR="~/agent"))
        self.assert_exit(result, 0)
        envelope = self.envelope(result)
        self.assertEqual(envelope["context"]["agentDir"], str(agent))
        values = self.project_values()
        self.assert_features(values, {"observationPack"})
        self.assertEqual(values["cacheWriteReadRatio"], 3)

    def test_an_empty_pi_coding_agent_dir_reads_home_pi_agent(self):
        agent = self.tree.home / ".pi" / "agent"
        agent.mkdir(parents=True)
        (agent / "sol-pi.json").write_text('{"version":1,"onlineContextCompact":true}',
                                           encoding="utf-8")
        result = self.sol("setup", self.tree.project, env=cli_environ(self.tree, PI_CODING_AGENT_DIR=""))
        self.assert_exit(result, 0)
        self.assertEqual(self.envelope(result)["context"]["agentDir"], str(agent))
        self.assert_features(self.project_values(), {"onlineContextCompact"})

    def _run_with_raising_configuration(self, *args) -> subprocess.CompletedProcess:
        """Run the command in-process with every function of `sol_pi_axi.config` replaced by one
        raising `InjectedFault`, as an unexpected failure inside the configuration module."""
        program = (
            "import sys, types\n"
            "import sol_pi_axi.config as configuration\n"
            "class InjectedFault(Exception):\n"
            "    pass\n"
            "def fault(*args, **kwargs):\n"
            "    raise InjectedFault('injected by the test')\n"
            "for name, value in list(vars(configuration).items()):\n"
            "    if isinstance(value, types.FunctionType) and value.__module__ == configuration.__name__:\n"
            "        setattr(configuration, name, fault)\n"
            "from sol_pi_axi.cli import main\n"
            "sys.argv = ['sol-pi-axi', *sys.argv[1:]]\n"
            "try:\n"
            "    code = main()\n"
            "except SystemExit as stop:\n"
            "    code = stop.code\n"
            "sys.exit(code)\n"
        )
        result = subprocess.run([sys.executable, "-c", program, *[str(arg) for arg in args]],
                                cwd=self.tree.project, env=cli_environ(self.tree),
                                capture_output=True, text=True, timeout=60, check=False)
        assert_clean_streams(self, result)
        return result

    def test_an_unexpected_exception_in_setup_is_failed_naming_its_type_without_a_traceback(self):
        self.with_pi_default()
        result = self._run_with_raising_configuration("setup", self.tree.project)
        self.assert_exit(result, 1)
        envelope = self.envelope(result)
        self.assert_common(envelope, "setup", False)
        self.assertEqual(envelope["outcome"], "failed")
        self.assertIn("InjectedFault", envelope["error"])
        self.assertFalse(self.tree.pi_dir.exists())

    def test_an_unexpected_exception_in_the_home_view_exits_1_naming_its_type_without_a_traceback(self):
        self.tree.write_project_file('{"version":1}')
        result = self._run_with_raising_configuration()
        self.assert_exit(result, 1)
        envelope = self.envelope(result)
        self.assertIs(envelope["ok"], False)
        self.assertIn("InjectedFault", envelope["error"])


class HomeViewTest(CliTestCase):
    """§S4: with no verb, the home view: `bin` (home as `~`), `description`, and `project` (the
    working directory's `.pi/sol-pi.json`) and `agentConfig`, each with `path` and `state`
    (`absent`; `valid` with `features` and `reducer`; `invalid` with the `reason`); exit 0."""

    def home(self) -> dict:
        result = self.sol(cwd=self.tree.project)
        self.assert_exit(result, 0)
        envelope = self.envelope(result)
        self.assertTrue(set(envelope) >= COMMON_KEYS, envelope)
        self.assertEqual(envelope["verb"], "home")
        self.assertIs(envelope["ok"], True)
        self.assertNotIn("error", envelope)
        self.assertEqual(envelope["version"], package_json_version())
        self.assertIsInstance(envelope["description"], str)
        self.assertTrue(envelope["description"].strip())
        self.assertIsInstance(envelope["bin"], str)
        self.assertTrue(envelope["bin"].endswith("sol-pi-axi"), envelope["bin"])
        self.assertNotIn(str(self.tree.home), envelope["bin"])
        self.assertTrue(any("sol-pi-axi setup" in step for step in envelope["help"]), envelope["help"])
        self.assertEqual(envelope["project"]["path"], str(self.tree.project_file))
        self.assertEqual(envelope["agentConfig"]["path"], str(self.tree.agent_file))
        return envelope

    def test_both_files_absent(self):
        envelope = self.home()
        self.assertEqual(envelope["project"], {"path": str(self.tree.project_file), "state": "absent"})
        self.assertEqual(envelope["agentConfig"], {"path": str(self.tree.agent_file), "state": "absent"})
        self.assertFalse(self.tree.pi_dir.exists(), "the home view writes nothing")

    def test_both_files_valid_show_their_features_and_reducer(self):
        self.tree.write_project_file('{"version":1,"actionFusion":true}')
        self.tree.agent_file.write_text(json.dumps({
            "version": 1, "actionFusion": False, "observationPack": True,
            "evidencePreservingReducer": True, "evidencePreservingReducerProvider": "p9",
            "evidencePreservingReducerModel": "m9", "onlineContextCompact": False,
            "cacheWriteReadRatio": 2}), encoding="utf-8")
        before = snapshot(self.tree.project, self.tree.agent)
        envelope = self.home()
        project, agent = envelope["project"], envelope["agentConfig"]
        self.assertEqual(project["state"], "valid")
        self.assertEqual(project["features"], ["actionFusion"])
        self.assertEqual(project["reducer"], f"{default_reducer_provider()}/{default_reducer_model()}")
        self.assertEqual(agent["state"], "valid")
        self.assertCountEqual(agent["features"], ["observationPack", "evidencePreservingReducer"])
        self.assertEqual(len(agent["features"]), 2)
        self.assertEqual(agent["reducer"], "p9/m9")
        self.assertEqual(snapshot(self.tree.project, self.tree.agent), before)

    def test_both_files_invalid_show_the_reason_and_still_exit_0(self):
        self.tree.write_project_file('{"version":2}')
        self.tree.agent_file.write_text("[1]", encoding="utf-8")
        envelope = self.home()
        for name in ("project", "agentConfig"):
            with self.subTest(file=name):
                state = envelope[name]
                self.assertEqual(state["state"], "invalid")
                self.assertIsInstance(state["reason"], str)
                self.assertTrue(state["reason"].strip())
                self.assertNotIn("features", state)
        self.assertIn("version", envelope["project"]["reason"])

    def test_a_project_file_absent_and_an_agent_file_invalid_exit_0(self):
        self.tree.agent_file.write_text("{not json", encoding="utf-8")
        envelope = self.home()
        self.assertEqual(envelope["project"]["state"], "absent")
        self.assertEqual(envelope["agentConfig"]["state"], "invalid")


if __name__ == "__main__":
    unittest.main()
