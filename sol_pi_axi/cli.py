# SPDX-License-Identifier: MIT
"""The `sol-pi-axi` console-script entry point.

The argument parsing, envelope and home view arrive with the command line; until then the entry
point only reports that it is not available."""

import sys


def main() -> int:
    """Run `sol-pi-axi`; returns the exit code."""
    sys.stderr.write("sol-pi-axi: the command line is not available yet\n")
    return 1
