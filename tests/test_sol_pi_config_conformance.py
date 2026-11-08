# SPDX-License-Identifier: MIT
"""The shared conformance table (`tests/fixtures/sol-pi-config/cases.json`) run against
`sol_pi_axi.config.read_config`: each case's file gets its verdict and, when valid, exactly its
effective values. `tests/sol-pi-config-conformance.test.ts` runs the same table through
`loadSolPiConfig` and `scripts/check-sol-pi-config.mjs`."""

import json
import re
import unittest

from tests.sol_pi_axi_support import FIXTURES, assert_same_json_values, import_sut

CASES = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))["cases"]


class SolPiConfigConformanceTest(unittest.TestCase):
    """One test per conformance case, named after the case and its verdict."""

    def setUp(self):
        self.config = import_sut("sol_pi_axi.config")


def _make_test(case: dict):
    def test(self):
        path = FIXTURES / case["file"]
        if case["valid"]:
            assert_same_json_values(self, self.config.read_config(path), case["effective"])
        else:
            with self.assertRaises(self.config.ConfigError) as caught:
                self.config.read_config(path)
            self.assertIn(str(path), str(caught.exception))

    test.__doc__ = f"{case['name']}: {case['note']}"
    return test


for _case in CASES:
    _slug = re.sub(r"[^0-9a-z]+", "_", _case["name"].lower()).strip("_")
    _verdict = "is_valid" if _case["valid"] else "is_rejected"
    setattr(SolPiConfigConformanceTest, f"test_case_{_slug}_{_verdict}", _make_test(_case))


if __name__ == "__main__":
    unittest.main()
