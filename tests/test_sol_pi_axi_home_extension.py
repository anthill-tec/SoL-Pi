# SPDX-License-Identifier: MIT
"""The home view's `extension` (CR-SLP-007 §S4): exactly `{state: absent}`, or
`{state: registered, source}` with the source as Pi recorded it in `settings.json`; a warning, and `sol-pi-axi install` in `help[]`, when the registered source is
not `npm:@anthill-tec/sol-pi@<own version>`. The home view reads `<agent dir>/settings.json`; it
runs no `pi` command and writes nothing."""

import unittest

from tests.sol_pi_axi_stub_pi import NPM_PACKAGE, PiCommandTestCase
from tests.sol_pi_axi_support import snapshot

INSTALL_HELP = "sol-pi-axi install"


class HomeExtensionTest(PiCommandTestCase):
    def home(self) -> dict:
        before = snapshot(self.tree.agent, self.tree.project)
        result = self.sol()
        self.assert_exit(result, 0)
        envelope = self.envelope(result)
        self.assertEqual((envelope["verb"], envelope["ok"]), ("home", True))
        self.assertEqual(snapshot(self.tree.agent, self.tree.project), before, "the home view wrote")
        self.assertEqual(self.pi.commands(), [], "the home view ran pi install or pi remove")
        return envelope

    def test_no_registration_is_absent(self):
        self.tree.write_settings({"packages": ["npm:pi-unrelated@1.0.0"]})
        envelope = self.home()
        self.assertEqual(envelope["extension"], {"state": "absent"})

    def test_no_settings_file_is_absent(self):
        envelope = self.home()
        self.assertEqual(envelope["extension"], {"state": "absent"})

    def test_registered_at_the_own_version_has_no_warning_and_no_install_step(self):
        self.tree.write_settings({"packages": ["npm:pi-unrelated@1.0.0", self.own_source()]})
        envelope = self.home()
        self.assertEqual(envelope["extension"], {"state": "registered", "source": self.own_source()})
        self.assertEqual(envelope["warnings"], [])
        self.assertNotIn(INSTALL_HELP, envelope["help"])

    def test_registered_at_another_version_warns_and_adds_the_install_step(self):
        old = f"npm:{NPM_PACKAGE}@0.0.9"
        self.tree.write_settings({"packages": [old]})
        envelope = self.home()
        self.assertEqual(envelope["extension"], {"state": "registered", "source": old})
        self.assertEqual(len([w for w in envelope["warnings"] if old in w]), 1, envelope["warnings"])
        self.assertIn(INSTALL_HELP, envelope["help"])

    def test_an_earlier_sol_pi_source_registered_warns_and_adds_the_install_step(self):
        self.tree.write_settings({"packages": ["npm:sol-pi"]})
        envelope = self.home()
        self.assertEqual(envelope["extension"], {"state": "registered", "source": "npm:sol-pi"})
        self.assertTrue(any("npm:sol-pi" in warning for warning in envelope["warnings"]),
                        envelope["warnings"])
        self.assertIn(INSTALL_HELP, envelope["help"])


if __name__ == "__main__":
    unittest.main()
