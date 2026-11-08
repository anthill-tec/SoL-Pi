# SPDX-License-Identifier: MIT
"""The golden written files (`tests/fixtures/sol-pi-config/written.json` lists each with its fixed
inputs): `run_setup` writes exactly their bytes, `sol-pi-axi setup` writes them from the flags,
and `render_config` renders exactly them.
`tests/sol-pi-config-conformance.test.ts` accepts each through `loadSolPiConfig` and
`scripts/check-sol-pi-config.mjs`."""

import json
import os
import re
import unittest

from tests.sol_pi_axi_support import (
    FIXTURES,
    TempTree,
    assert_clean_streams,
    cli_environ,
    decode_envelope,
    feature_keys,
    import_sut,
    run_cli,
)

GOLDENS = json.loads((FIXTURES / "written.json").read_text(encoding="utf-8"))["cases"]


def api_inputs(args: list[str]) -> dict:
    """The fixed flag inputs as `run_setup` keyword arguments: `--features` as the enabled names
    (`all`, `none`, or a comma list), `--reducer` split at the first `/`, `--cache-ratio` as a
    number."""
    kwargs = {}
    pairs = dict(zip(args[::2], args[1::2], strict=True))
    if "--features" in pairs:
        value = pairs["--features"]
        kwargs["features"] = (feature_keys() if value == "all" else [] if value == "none"
                              else value.split(","))
    if "--reducer" in pairs:
        provider, model = pairs["--reducer"].split("/", 1)
        kwargs["reducer"] = (provider, model)
    if "--cache-ratio" in pairs:
        kwargs["cache_ratio"] = float(pairs["--cache-ratio"])
    return kwargs


class WrittenFormGoldenTest(unittest.TestCase):
    """One test per golden file, named after it."""

    def setUp(self):
        self.setup_module = import_sut("sol_pi_axi.setup")
        self.config = import_sut("sol_pi_axi.config")
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)


def _make_test(case: dict):
    def test(self):
        golden = (FIXTURES / case["file"]).read_bytes()
        if case["piSettings"] is not None:
            self.tree.write_settings(case["piSettings"])
        kwargs = api_inputs(case["args"])

        result = self.setup_module.run_setup(self.tree.project, agent_dir=self.tree.agent, **kwargs)

        self.assertEqual(result.outcome, "written")
        self.assertEqual(self.tree.project_file.read_bytes(), golden)
        self.assertEqual(self.config.render_config(result.config), golden)
        again = self.setup_module.run_setup(self.tree.project, agent_dir=self.tree.agent, **kwargs)
        self.assertEqual(again.outcome, "unchanged")
        self.assertEqual(self.tree.project_file.read_bytes(), golden)

    test.__doc__ = f"{case['name']}: {case['note']}"
    return test


class CommandLineGoldenTest(unittest.TestCase):
    """The real command line, flags to bytes: `sol-pi-axi setup <project> <args>` writes exactly
    each golden file's bytes."""

    def test_the_command_line_writes_every_golden_files_bytes(self):
        for case in GOLDENS:
            with self.subTest(case=case["name"]):
                tree = TempTree()
                self.addCleanup(tree.cleanup)
                if case["piSettings"] is not None:
                    tree.write_settings(case["piSettings"])
                result = run_cli(["setup", tree.project, *case["args"]], tree=tree,
                                 env=cli_environ(tree))
                assert_clean_streams(self, result)
                self.assertEqual(result.returncode, 0, f"{result.stdout}\n{result.stderr}")
                self.assertEqual(decode_envelope(self, result.stdout)["outcome"], "written")
                self.assertEqual(tree.project_file.read_bytes(),
                                 (FIXTURES / case["file"]).read_bytes())


for _case in GOLDENS:
    _slug = re.sub(r"[^0-9a-z]+", "_", _case["name"].lower()).strip("_")
    setattr(WrittenFormGoldenTest, f"test_setup_writes_the_golden_{_slug}_bytes", _make_test(_case))


if __name__ == "__main__":
    unittest.main()
