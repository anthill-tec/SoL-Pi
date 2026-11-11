# SPDX-License-Identifier: MIT
"""`sol-pi-axi install` (CR-SLP-007 §S2): registering `npm:@anthill-tec/sol-pi@<own version>`
user-wide with `pi install`, writing an absent `<agent dir>/sol-pi.json` with the setup defaults,
replacing earlier SoL-Pi sources, the failure paths, the envelope, and `TESTED_PI_VERSIONS`.

Every run uses a temporary home, project and agent directory and the stub `pi` of
`tests.sol_pi_axi_stub_pi` (it records its arguments and working directory and edits
`settings.json` as Pi 1.5.0's `pi install` and `pi remove` do).

The contract these tests fix for the implementation:

- `sol_pi_axi.pi.TESTED_PI_VERSIONS` is the tested Pi set, equal to `scripts/check-pi-compat.mjs`'s
  `TESTED_PI_VERSIONS`.
- The own version is `sol_pi_axi._version.__version__`, read when the command runs (a test puts a
  module holding `0.1.0.dev3` in its place in `sys.modules` before importing the command).
- The install envelope (under `axi`): `verb: install`, `ok`, `version`, `outcome` (`installed`,
  `unchanged`, `failed`, `cancelled`), `extension` exactly `{source, registered, replaced, pi}`
  (`replaced` lists each replaced source exactly as Pi recorded it in `settings.json`; `pi` is the
  `pi --version` output), `config` exactly `{path, state, features, reducer, cacheRatio}` (`state`
  `written` or `kept`; the values as `setup` reports them), `context` exactly `{agentDir}`,
  `error` on failure, `warnings`, `help`.
- "No pi command" is literal: zero invocations, `pi --version` included; every invocation runs from
  the home directory with `--no-approve`; a local path is passed to `pi remove` absolute, resolved
  against the agent directory.
- A signal before registering is delivered while the arguments are parsed (`cli._parse`), as the
  setup signal tests do."""

import json
import re
import signal
import subprocess
import sys
import unittest

from tests.sol_pi_axi_stub_pi import (
    NPM_PACKAGE,
    PI_MODEL,
    PI_PROVIDER,
    PiCommandTestCase,
    StubPi,
    read_packages,
    stub_environ,
    write_local_package,
)
from tests.sol_pi_axi_support import (
    REPO,
    SIGNAL_IN_PARSE,
    assert_clean_streams,
    cli_environ,
    decode_envelope,
    default_cache_ratio,
    feature_keys,
    import_sut,
    render_js,
    snapshot,
)

SETUP_HELP = "sol-pi-axi setup <project dir>"
EXIT_CODES = {signal.SIGINT: 130, signal.SIGTERM: 143, signal.SIGHUP: 129}
#: Runs `sol-pi-axi <argv[2:]>` in-process with `sol_pi_axi._version` replaced, before anything of
#: the package is imported, by a module whose `__version__` is `argv[1]`.
WITH_VERSION = '''\
import sys, types
version = types.ModuleType("sol_pi_axi._version")
version.__version__ = sys.argv[1]
sys.modules["sol_pi_axi._version"] = version
from sol_pi_axi import cli
sys.argv = ["sol-pi-axi", *sys.argv[2:]]
sys.exit(cli.main())
'''


def tested_pi_versions_of_the_compat_script() -> list[str]:
    text = (REPO / "scripts" / "check-pi-compat.mjs").read_text(encoding="utf-8")
    match = re.search(r"^const TESTED_PI_VERSIONS = (\[[^\]]*\]);$", text, re.MULTILINE)
    if match is None:
        raise AssertionError("TESTED_PI_VERSIONS not found in scripts/check-pi-compat.mjs")
    return json.loads(match.group(1))


class InstallTestCase(PiCommandTestCase):
    def setup_defaults(self) -> dict:
        """CR-SLP-004's setup defaults with Pi's default route: all four mechanisms on."""
        values = {"version": 1, "evidencePreservingReducerProvider": PI_PROVIDER,
                  "evidencePreservingReducerModel": PI_MODEL,
                  "cacheWriteReadRatio": default_cache_ratio()}
        values.update(dict.fromkeys(feature_keys(), True))
        return values

    def assert_failed(self, result) -> dict:
        self.assert_exit(result, 1)
        envelope = self.envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("install", False, "failed"))
        self.assertIsInstance(envelope["error"], str)
        return envelope


class FreshInstallTest(InstallTestCase):
    """§S2: an agent directory with no SoL-Pi registration and no `sol-pi.json`, whose
    `settings.json` names Pi's default route."""

    def test_install_registers_the_own_version_and_writes_the_setup_defaults(self):
        self.with_pi_default()
        result = self.sol("install")
        self.assert_exit(result, 0)
        self.assertEqual(self.pi.commands(), [["install", self.own_source()]])
        self.assertEqual(self.packages(), [self.own_source()])
        self.assertEqual(self.tree.agent_file.read_bytes(),
                         render_js({key: self.setup_defaults()[key] for key in
                                    json.loads((REPO / "sol-pi.example.json").read_text())}))
        envelope = self.envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("install", True, "installed"))
        self.assertEqual(envelope["version"], self.own_version())
        self.assertNotIn("error", envelope)

    def test_the_installed_envelope_reports_extension_config_and_context(self):
        self.with_pi_default()
        envelope = self.envelope(self.sol("install"))
        self.assertEqual(envelope["extension"], {"source": self.own_source(), "registered": True,
                                                 "replaced": [], "pi": "1.5.0"})
        self.assertEqual(envelope["config"], {
            "path": str(self.tree.agent_file), "state": "written", "features": feature_keys(),
            "reducer": f"{PI_PROVIDER}/{PI_MODEL}", "cacheRatio": default_cache_ratio()})
        self.assertEqual(envelope["context"], {"agentDir": str(self.tree.agent)})
        self.assertEqual(envelope["warnings"], [])
        self.assertIn(SETUP_HELP, envelope["help"])

    def test_the_configuration_is_written_only_after_pi_install_registered_the_source(self):
        self.with_pi_default()
        self.assert_exit(self.sol("install"), 0)
        installs = [call for call in self.pi.calls() if "install" in call["argv"]]
        self.assertEqual(len(installs), 1, self.pi.calls())
        self.assertIs(installs[0]["agentConfigExisted"], False,
                      "sol-pi.json existed before pi install ran")
        self.assertTrue(self.tree.agent_file.is_file())

    def test_a_second_run_registers_nothing_writes_nothing_and_is_unchanged(self):
        self.with_pi_default()
        self.assert_exit(self.sol("install"), 0)
        before = snapshot(self.tree.agent_file)
        self.pi.clear()
        result = self.sol("install")
        self.assert_exit(result, 0)
        self.assertEqual(self.pi.commands(), [], "a second run ran pi install or pi remove")
        self.assertEqual(snapshot(self.tree.agent_file), before)
        envelope = self.envelope(result)
        self.assertEqual((envelope["ok"], envelope["outcome"]), (True, "unchanged"))
        self.assertEqual(envelope["extension"]["registered"], True)
        self.assertEqual(envelope["extension"]["replaced"], [])
        self.assertEqual(envelope["config"]["state"], "kept")
        self.assertEqual(self.packages(), [self.own_source()])

    def test_every_pi_command_runs_from_home_with_no_approve(self):
        write_local_package(self.tree.root / "checkout", "sol-pi")
        self.with_pi_default(["npm:sol-pi", "../checkout"])
        self.assert_exit(self.sol("install"), 0)
        self.assertEqual(len(self.pi.commands()), 3, self.pi.calls())
        self.assert_every_pi_call_from_home_with_no_approve()

    def test_value_flags_set_the_written_values_in_an_empty_agent_directory(self):
        result = self.sol("install", "--features", "observationPack,evidencePreservingReducer",
                          "--reducer", "prov/mod-1", "--cache-ratio", "4")
        self.assert_exit(result, 0)
        written = json.loads(self.tree.agent_file.read_text(encoding="utf-8"))
        self.assertEqual({key: written[key] for key in feature_keys()},
                         {key: key in ("observationPack", "evidencePreservingReducer")
                          for key in feature_keys()})
        self.assertEqual((written["evidencePreservingReducerProvider"],
                          written["evidencePreservingReducerModel"], written["cacheWriteReadRatio"]),
                         ("prov", "mod-1", 4))
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "installed")
        self.assertEqual(envelope["config"]["reducer"], "prov/mod-1")
        self.assertEqual(envelope["config"]["cacheRatio"], 4)

    def test_non_interactive_and_format_json_are_accepted(self):
        self.with_pi_default()
        result = self.sol("install", "--non-interactive", "--format", "json")
        self.assert_exit(result, 0)
        self.assertEqual(result.stdout.count("\n"), 1, result.stdout)
        envelope = json.loads(result.stdout)["axi"]
        self.assertEqual((envelope["verb"], envelope["outcome"]), ("install", "installed"))


class ReplacingTest(InstallTestCase):
    """§S2: earlier SoL-Pi sources are replaced; unrelated packages and a project's own
    `.pi/settings.json` are untouched."""

    def test_the_same_package_at_another_version_is_replaced_in_place_by_pi_install_alone(self):
        old = f"npm:{NPM_PACKAGE}@0.0.9"
        self.with_pi_default([old, "npm:pi-unrelated@1.0.0"])
        result = self.sol("install")
        self.assert_exit(result, 0)
        self.assertEqual(self.pi.commands(), [["install", self.own_source()]], "no pi remove")
        self.assertEqual(self.packages(), [self.own_source(), "npm:pi-unrelated@1.0.0"])
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "installed")
        self.assertEqual(envelope["extension"]["replaced"], [old])
        self.assertTrue(any(old in warning for warning in envelope["warnings"]), envelope["warnings"])

    def test_other_sol_pi_sources_are_removed_after_pi_install_with_a_local_path_absolute(self):
        write_local_package(self.tree.root / "checkout", "sol-pi")
        write_local_package(self.tree.root / "other-local", "other-package")
        earlier = ["npm:sol-pi", "git:github.com/NVlabs/SoL-Pi", "https://github.com/anthill-tec/SoL-Pi",
                   "../checkout"]
        self.with_pi_default(["npm:sol-pi", "npm:pi-unrelated@1.0.0", "git:github.com/NVlabs/SoL-Pi",
                              "https://github.com/anthill-tec/SoL-Pi", "../checkout", "../other-local"])
        project_settings = '{\n  "packages": ["npm:sol-pi"]\n}\n'
        self.tree.pi_dir.mkdir()
        (self.tree.pi_dir / "settings.json").write_text(project_settings, encoding="utf-8")
        project_before = snapshot(self.tree.pi_dir)

        result = self.sol("install")
        self.assert_exit(result, 0)
        commands = self.pi.commands()
        self.assertEqual(commands[0], ["install", self.own_source()], commands)
        removed = [argv[1] for argv in commands[1:] if argv[0] == "remove"]
        self.assertEqual(len(commands), 5, commands)
        self.assertCountEqual(removed, ["npm:sol-pi", "git:github.com/NVlabs/SoL-Pi",
                                        "https://github.com/anthill-tec/SoL-Pi",
                                        str(self.tree.root / "checkout")])
        self.assertEqual(self.packages(),
                         ["npm:pi-unrelated@1.0.0", "../other-local", self.own_source()])
        self.assertEqual(snapshot(self.tree.pi_dir), project_before, "the project's settings changed")

        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "installed")
        self.assertCountEqual(envelope["extension"]["replaced"], earlier)
        self.assertEqual(len(envelope["extension"]["replaced"]), 4)
        for source in earlier:
            with self.subTest(source=source):
                self.assertTrue(any(source in warning for warning in envelope["warnings"]),
                                envelope["warnings"])
        self.assertFalse(any("pi-unrelated" in warning for warning in envelope["warnings"]))

    def test_a_local_path_whose_package_is_the_scoped_name_is_replaced(self):
        write_local_package(self.tree.root / "scoped", NPM_PACKAGE)
        self.with_pi_default(["../scoped"])
        result = self.sol("install")
        self.assert_exit(result, 0)
        self.assertEqual(self.pi.commands(), [["install", self.own_source()],
                                              ["remove", str(self.tree.root / "scoped")]])
        self.assertEqual(self.envelope(result)["extension"]["replaced"], ["../scoped"])
        self.assertEqual(self.packages(), [self.own_source()])


class FailureTest(InstallTestCase):
    """§S2 failure paths: a failure before registering changes nothing; a failed `pi` command
    fails the run, naming the command and its exit code, Pi's output on standard error."""

    def test_a_failed_pi_install_removes_nothing_and_leaves_the_earlier_source_registered(self):
        self.with_pi_default(["npm:sol-pi"])
        self.pi.configure(install_exit=1)
        envelope = self.assert_failed(self.sol("install"))
        self.assertEqual(self.pi.commands(), [["install", self.own_source()]], "no pi remove")
        self.assertEqual(self.packages(), ["npm:sol-pi"])
        self.assertIs(envelope["extension"]["registered"], False)
        self.assertFalse(self.tree.agent_file.exists())

    def test_pi_install_exiting_3_names_the_command_and_code_with_pis_output_on_stderr(self):
        self.with_pi_default()
        self.pi.configure(install_exit=3)
        result = self.sol("install")
        envelope = self.assert_failed(result)
        self.assertIn("install", envelope["error"])
        self.assertIn(self.own_source(), envelope["error"])
        self.assertRegex(envelope["error"], r"\b3\b")
        self.assertIn(f"stub pi: install {self.own_source()} failed", result.stderr)
        self.assertNotIn("stub pi:", result.stdout)
        self.assertFalse(self.tree.agent_file.exists(), "a configuration file was written")
        self.assertIs(envelope["extension"]["registered"], False)

    def test_a_pi_record_in_another_directory_fails_naming_the_directory_read(self):
        self.with_pi_default()
        elsewhere = self.tree.root / "other-agent"
        self.pi.configure(settings_dir=elsewhere)
        envelope = self.assert_failed(self.sol("install"))
        self.assertIn(str(self.tree.agent), envelope["error"])
        self.assertEqual(read_packages(elsewhere), [self.own_source()], "the stub registered it")
        self.assertIs(envelope["extension"]["registered"], False)
        self.assertFalse(self.tree.agent_file.exists())

    def test_a_dev_version_fails_before_any_pi_command_naming_it(self):
        self.with_pi_default()
        before = snapshot(self.tree.agent, self.tree.home, self.tree.project)
        result = subprocess.run([sys.executable, "-c", WITH_VERSION, "0.1.0.dev3", "install"],
                                cwd=self.tree.project, env=self.environ(), stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=60, check=False)
        assert_clean_streams(self, result)
        envelope = self.assert_failed(result)
        self.assertIn("0.1.0.dev3", envelope["error"])
        self.assertIn("pi install <checkout path>", envelope["help"])
        self.assertEqual(self.pi.calls(), [], "a pi command ran")
        self.assertEqual(snapshot(self.tree.agent, self.tree.home, self.tree.project), before)

    def test_no_reducer_default_and_no_reducer_flag_fails_before_any_pi_command(self):
        before = snapshot(self.tree.agent, self.tree.home)
        envelope = self.assert_failed(self.sol("install"))
        self.assertIn("--reducer", envelope["error"] + " ".join(envelope["help"]))
        self.assertEqual(self.pi.calls(), [], "a pi command ran")
        self.assertEqual(snapshot(self.tree.agent, self.tree.home), before)

    def test_no_pi_on_path_and_no_pi_bin_exits_1_naming_both(self):
        self.with_pi_default()
        empty = self.tree.root / "empty-bin"
        empty.mkdir()
        before = snapshot(self.tree.agent)
        result = self.sol("install", env=stub_environ(cli_environ(self.tree), empty))
        envelope = self.assert_failed(result)
        self.assertIn("PI_BIN", envelope["error"])
        self.assertIn("PATH", envelope["error"])
        self.assertEqual(snapshot(self.tree.agent), before)
        self.assertEqual(self.pi.calls(), [])

    def test_pi_bin_is_used_when_set(self):
        self.with_pi_default()
        chosen = StubPi(self.tree.root, "chosen-bin")
        environ = stub_environ(cli_environ(self.tree), self.pi.bin_dir)
        environ["PI_BIN"] = str(chosen.path)
        result = self.sol("install", env=environ)
        self.assert_exit(result, 0)
        self.assertEqual(chosen.commands(), [["install", self.own_source()]])
        self.assertEqual(self.pi.calls(), [], "the pi on PATH ran though $PI_BIN was set")
        self.assert_every_pi_call_from_home_with_no_approve(chosen)


class ExistingConfigurationTest(InstallTestCase):
    """§S2: an existing `<agent dir>/sol-pi.json` is left untouched."""

    def test_a_valid_file_is_kept_byte_for_byte_with_value_flags_named_in_warnings(self):
        self.tree.agent_file.write_text('{"version":1,"observationPack":true}', encoding="utf-8")
        before = snapshot(self.tree.agent_file)
        result = self.sol("install", "--features", "none", "--cache-ratio", "3")
        self.assert_exit(result, 0)
        self.assertEqual(snapshot(self.tree.agent_file), before)
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "installed")
        self.assertEqual(envelope["config"]["state"], "kept")
        self.assertEqual(envelope["config"]["features"], ["observationPack"])
        self.assertEqual(envelope["config"]["cacheRatio"], default_cache_ratio())
        for flag in ("--features", "--cache-ratio"):
            with self.subTest(flag=flag):
                self.assertTrue(any(flag in warning for warning in envelope["warnings"]),
                                envelope["warnings"])
        self.assertEqual(self.pi.commands(), [["install", self.own_source()]])

    def test_an_invalid_file_is_kept_and_named_in_warnings(self):
        self.with_pi_default()
        self.tree.agent_file.write_text('{"version":2}', encoding="utf-8")
        before = snapshot(self.tree.agent_file)
        result = self.sol("install")
        self.assert_exit(result, 0)
        self.assertEqual(snapshot(self.tree.agent_file), before)
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "installed")
        self.assertEqual(envelope["config"]["state"], "kept")
        self.assertTrue(any(str(self.tree.agent_file) in warning for warning in envelope["warnings"]),
                        envelope["warnings"])
        self.assertEqual(self.packages(), [self.own_source()])


class PiVersionTest(InstallTestCase):
    """§S2: a `pi --version` outside `TESTED_PI_VERSIONS` is a warning, not a failure."""

    def test_tested_pi_versions_equal_the_compat_scripts_list(self):
        pi = import_sut("sol_pi_axi.pi")
        self.assertEqual(list(pi.TESTED_PI_VERSIONS), tested_pi_versions_of_the_compat_script())

    def test_an_untested_pi_version_is_a_warning_and_the_run_installs(self):
        self.with_pi_default()
        self.pi.configure(version="9.9.9")
        result = self.sol("install")
        self.assert_exit(result, 0)
        envelope = self.envelope(result)
        self.assertEqual(envelope["outcome"], "installed")
        self.assertEqual(envelope["extension"]["pi"], "9.9.9")
        self.assertEqual(len([w for w in envelope["warnings"] if "9.9.9" in w]), 1, envelope["warnings"])
        self.assertEqual(self.packages(), [self.own_source()])

    def test_every_tested_pi_version_installs_without_a_warning(self):
        for version in tested_pi_versions_of_the_compat_script():
            with self.subTest(version=version):
                self.tree.write_settings({"defaultProvider": PI_PROVIDER, "defaultModel": PI_MODEL})
                self.tree.agent_file.unlink(missing_ok=True)
                self.pi.configure(version=version)
                envelope = self.envelope(self.sol("install"))
                self.assertEqual(envelope["outcome"], "installed")
                self.assertEqual(envelope["extension"]["pi"], version)
                self.assertEqual(envelope["warnings"], [])


class InstallSignalTest(InstallTestCase):
    """§S2: `SIGINT`, `SIGTERM`, `SIGHUP` before registering cancel the run with no `pi` command
    and nothing written."""

    def test_each_signal_before_registering_cancels_with_its_exit_code(self):
        self.with_pi_default()
        before = snapshot(self.tree.agent, self.tree.home, self.tree.project)
        for signum, code in EXIT_CODES.items():
            with self.subTest(signal=signum.name):
                result = subprocess.run(
                    [sys.executable, "-c", SIGNAL_IN_PARSE, "install"], cwd=self.tree.project,
                    env=self.environ(SOL_PI_AXI_TEST_SIGNAL=str(int(signum))),
                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False)
                assert_clean_streams(self, result)
                self.assert_exit(result, code)
                envelope = decode_envelope(self, result.stdout)
                self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                                 ("install", False, "cancelled"))
                self.assertEqual(self.pi.calls(), [], "a pi command ran")
                self.assertEqual(snapshot(self.tree.agent, self.tree.home, self.tree.project), before)


class InstallUsageTest(InstallTestCase):
    """§S2: unknown input as CR-SLP-004 §S4; the help text and the valid-verb lists name the verbs."""

    def test_an_extra_argument_is_a_usage_error_naming_it(self):
        self.with_pi_default()
        result = self.sol("install", "surplus")
        self.assert_exit(result, 2)
        envelope = self.envelope(result)
        self.assertEqual((envelope["verb"], envelope["outcome"]), ("usage", "usage"))
        self.assertIn("surplus", envelope["error"])
        self.assertEqual(self.pi.calls(), [])
        self.assertFalse(self.tree.agent_file.exists())

    def test_an_unknown_verb_lists_install_and_uninstall_among_the_valid_verbs(self):
        envelope = self.envelope(self.sol("frobnicate"))
        self.assertEqual(envelope["verb"], "usage")
        self.assertRegex(envelope["error"], r"\binstall\b")
        self.assertRegex(envelope["error"], r"\buninstall\b")

    def test_the_help_text_describes_install_and_uninstall(self):
        result = self.sol("--help")
        self.assert_exit(result, 0)
        self.assertRegex(result.stdout, r"(?m)^\s+install\b")
        self.assertRegex(result.stdout, r"(?m)^\s+uninstall\b")


if __name__ == "__main__":
    unittest.main()
