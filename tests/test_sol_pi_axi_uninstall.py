# SPDX-License-Identifier: MIT
"""`sol-pi-axi uninstall` (CR-SLP-007 §S3): removing every SoL-Pi source §S2 recognises with
`pi remove` (a local path passed absolute, resolved against the agent directory), deleting no
configuration file, the envelope (`verb: uninstall`; `outcome` `removed`, `unchanged`, `failed`
or `cancelled`; `removed`, each source exactly as Pi recorded it; `context` `{agentDir}`), and the
real-Pi round trip of §S2: a local-path source registered by the development dependency's
`pi install` (through `$PI_BIN`, offline) is recognised and removed from another working
directory.

Stub runs use `tests.sol_pi_axi_stub_pi`'s stub `pi` as the only `pi` on `PATH`."""

import os
import shutil
import subprocess
import unittest

from tests.sol_pi_axi_stub_pi import (
    NPM_PACKAGE,
    PiCommandTestCase,
    read_packages,
    write_local_package,
)
from tests.sol_pi_axi_support import cli_environ, development_pi, snapshot


class UninstallTestCase(PiCommandTestCase):
    def assert_envelope(self, result, outcome: str, code: int) -> dict:
        self.assert_exit(result, code)
        envelope = self.envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"], envelope["outcome"]),
                         ("uninstall", code == 0, outcome))
        self.assertEqual(envelope["version"], self.own_version())
        self.assertEqual(envelope["context"], {"agentDir": str(self.tree.agent)})
        self.assertIsInstance(envelope["warnings"], list)
        self.assertIsInstance(envelope["help"], list)
        return envelope


class UninstallStubTest(UninstallTestCase):
    def test_every_recognised_source_is_removed_with_local_paths_absolute(self):
        write_local_package(self.tree.root / "checkout", "sol-pi")
        write_local_package(self.tree.root / "scoped", NPM_PACKAGE)
        write_local_package(self.tree.root / "other-local", "other-package")
        recognised = [self.own_source(), "npm:sol-pi", "git:github.com/NVlabs/SoL-Pi",
                      "https://github.com/anthill-tec/SoL-Pi", "../checkout", "../scoped"]
        self.tree.write_settings({"packages": [
            self.own_source(), "npm:sol-pi", "npm:pi-unrelated@1.0.0", "git:github.com/NVlabs/SoL-Pi",
            "https://github.com/anthill-tec/SoL-Pi", "../checkout", "../scoped", "../other-local"]})

        envelope = self.assert_envelope(self.sol("uninstall"), "removed", 0)
        commands = self.pi.commands()
        self.assertTrue(all(argv[0] == "remove" for argv in commands), commands)
        self.assertCountEqual([argv[1] for argv in commands], [
            self.own_source(), "npm:sol-pi", "git:github.com/NVlabs/SoL-Pi",
            "https://github.com/anthill-tec/SoL-Pi", str(self.tree.root / "checkout"),
            str(self.tree.root / "scoped")])
        self.assertEqual(len(commands), 6)
        self.assertCountEqual(envelope["removed"], recognised)
        self.assertEqual(len(envelope["removed"]), 6)
        self.assertEqual(self.packages(), ["npm:pi-unrelated@1.0.0", "../other-local"])
        self.assert_every_pi_call_from_home_with_no_approve()

    def test_an_unprefixed_scp_source_is_a_local_path_as_pi_parses_it(self):
        # Pi 1.5.0's parseSource reads `git@host:owner/repo` without `git:` as a local path
        # (isLocalPath), stored relative to the agent directory: it is SoL-Pi only when that
        # directory's package.json names it, and is then removed by its absolute path.
        scp = "git@github.com:anthill-tec/SoL-Pi"
        prefixed = "git:git@github.com:anthill-tec/SoL-Pi.git"
        self.tree.write_settings({"packages": [scp, prefixed]})
        envelope = self.assert_envelope(self.sol("uninstall"), "removed", 0)
        self.assertEqual(self.pi.commands(), [["remove", prefixed]])
        self.assertEqual(envelope["removed"], [prefixed])
        self.assertEqual(self.packages(), [scp])

        write_local_package(self.tree.agent / scp, "sol-pi")
        envelope = self.assert_envelope(self.sol("uninstall"), "removed", 0)
        self.assertEqual(self.pi.commands()[1:], [["remove", str(self.tree.agent / scp)]])
        self.assertEqual(envelope["removed"], [scp])
        self.assertEqual(self.packages(), [])

    def test_another_version_of_the_scoped_package_is_removed(self):
        old = f"npm:{NPM_PACKAGE}@0.0.9"
        self.tree.write_settings({"packages": [old]})
        envelope = self.assert_envelope(self.sol("uninstall"), "removed", 0)
        self.assertEqual(self.pi.commands(), [["remove", old]])
        self.assertEqual(envelope["removed"], [old])
        self.assertEqual(self.packages(), [])

    def test_with_no_sol_pi_source_no_pi_command_runs_and_it_is_unchanged(self):
        for settings in (None, {"packages": ["npm:pi-unrelated@1.0.0"]}):
            with self.subTest(settings=settings):
                self.tree.settings_file.unlink(missing_ok=True)
                if settings is not None:
                    self.tree.write_settings(settings)
                before = snapshot(self.tree.agent)
                envelope = self.assert_envelope(self.sol("uninstall"), "unchanged", 0)
                self.assertEqual(envelope["removed"], [])
                self.assertEqual(self.pi.calls(), [], "a pi command ran")
                self.assertEqual(snapshot(self.tree.agent), before)

    def test_no_configuration_file_is_deleted_and_the_agent_file_is_named(self):
        self.tree.write_settings({"packages": [self.own_source()]})
        self.tree.agent_file.write_text('{"version":1}', encoding="utf-8")
        self.tree.write_project_file('{"version":1}')
        before = snapshot(self.tree.agent_file, self.tree.project_file)
        envelope = self.assert_envelope(self.sol("uninstall"), "removed", 0)
        self.assertEqual(snapshot(self.tree.agent_file, self.tree.project_file), before)
        self.assertTrue(any(str(self.tree.agent_file) in warning for warning in envelope["warnings"]),
                        envelope["warnings"])

    def test_the_agent_file_is_named_with_nothing_to_remove_and_not_named_when_absent(self):
        self.tree.agent_file.write_text('{"version":1}', encoding="utf-8")
        envelope = self.assert_envelope(self.sol("uninstall"), "unchanged", 0)
        self.assertTrue(any(str(self.tree.agent_file) in warning for warning in envelope["warnings"]),
                        envelope["warnings"])
        self.tree.agent_file.unlink()
        envelope = self.assert_envelope(self.sol("uninstall"), "unchanged", 0)
        self.assertFalse(any("sol-pi.json" in warning for warning in envelope["warnings"]),
                         envelope["warnings"])

    def test_a_value_flag_is_a_usage_error(self):
        self.tree.write_settings({"packages": ["npm:pi-unrelated@1.0.0"]})
        # Without the flag the same run is a valid uninstall: the flag alone makes it a usage error.
        self.assert_envelope(self.sol("uninstall"), "unchanged", 0)
        for flag, value in (("--features", "all"), ("--reducer", "prov/mod"), ("--cache-ratio", "3")):
            with self.subTest(flag=flag):
                result = self.sol("uninstall", flag, value)
                self.assert_exit(result, 2)
                envelope = self.envelope(result)
                self.assertEqual((envelope["verb"], envelope["outcome"]), ("usage", "usage"))
                self.assertIn(flag, envelope["error"])
                self.assertEqual(self.pi.calls(), [])
                self.assertEqual(self.packages(), ["npm:pi-unrelated@1.0.0"])

    def test_a_failed_pi_remove_fails_the_run_naming_the_command_and_code(self):
        self.tree.write_settings({"packages": ["npm:sol-pi"]})
        self.pi.configure(remove_exit=4)
        result = self.sol("uninstall")
        envelope = self.assert_envelope(result, "failed", 1)
        self.assertIn("remove", envelope["error"])
        self.assertIn("npm:sol-pi", envelope["error"])
        self.assertRegex(envelope["error"], r"\b4\b")
        self.assertIn("stub pi: remove npm:sol-pi failed", result.stderr)
        self.assertEqual(self.packages(), ["npm:sol-pi"])


class UninstallRealPiTest(UninstallTestCase):
    """§S2 with the real Pi: Pi stores a local path relative to the agent directory and resolves
    a `pi remove` argument against the working directory.

    The agent directory is nested three levels below the root while home sits one level below
    it, so the relative path Pi records names a different place when resolved against home: Pi
    itself fails the removal unless the argument is the absolute path."""

    def setUp(self):
        super().setUp()
        self.tree.agent = self.tree.root / "deep" / "er" / "agent"
        self.tree.agent.mkdir(parents=True)

    def test_a_local_path_registered_by_real_pi_is_removed_from_another_working_directory(self):
        pi = development_pi()
        self.assertTrue(pi.exists(), f"the development dependency's pi is missing: {pi}")
        node = shutil.which("node")
        self.assertIsNotNone(node, "node is not on PATH")
        checkout = write_local_package(self.tree.root / "checkout", "sol-pi")
        environ = cli_environ(self.tree, PATH=os.path.dirname(str(node)), PI_OFFLINE="1",
                              PI_BIN=str(pi))

        registered = subprocess.run([str(pi), "install", str(checkout), "--no-approve"],
                                    cwd=self.tree.home, env=environ, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(registered.returncode, 0, registered.stderr)
        self.assertEqual(read_packages(self.tree.agent), ["../../../checkout"], "Pi's own record")

        elsewhere = self.tree.root / "elsewhere" / "deeper"
        elsewhere.mkdir(parents=True)
        result = self.sol("uninstall", cwd=elsewhere, env=environ)
        envelope = self.assert_envelope(result, "removed", 0)
        self.assertEqual(envelope["removed"], ["../../../checkout"])
        self.assertEqual(read_packages(self.tree.agent), [])
        self.assertTrue((checkout / "package.json").is_file(), "the checkout itself was touched")


if __name__ == "__main__":
    unittest.main()
