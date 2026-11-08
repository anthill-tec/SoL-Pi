# SPDX-License-Identifier: MIT
"""`sol_pi_axi.write.write_file(path, data, *, hook=None)`: a temporary file in the target's
directory renamed over the target; through a symbolic link the target is replaced and the link
kept; an existing file's mode kept, a new file `0o666` less the umask; equal bytes not rewritten;
an optional test-only hook called with the temporary file's path between write and rename."""

import os
import stat
import unittest
from pathlib import Path

from tests.sol_pi_axi_support import TempTree, import_sut


class HookStop(Exception):
    """Raised by a test hook to fail a write between write and rename."""


class WriteFileTest(unittest.TestCase):
    def setUp(self):
        self.write = import_sut("sol_pi_axi.write")
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        self.dir = self.tree.root / "target"
        self.dir.mkdir()
        self.target = self.dir / "sol-pi.json"

    def _with_umask(self, mask: int):
        previous = os.umask(mask)
        self.addCleanup(os.umask, previous)

    def test_write_file_creates_a_new_file_with_the_bytes_and_reports_written(self):
        outcome = self.write.write_file(self.target, b'{"version": 1}\n')
        self.assertEqual(outcome, "written")
        self.assertEqual(self.target.read_bytes(), b'{"version": 1}\n')
        self.assertEqual(sorted(os.listdir(self.dir)), ["sol-pi.json"])

    def test_write_file_gives_a_new_file_0644_under_umask_022(self):
        self._with_umask(0o022)
        self.write.write_file(self.target, b"x\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.target).st_mode), 0o644)

    def test_write_file_gives_a_new_file_0666_less_any_umask(self):
        self._with_umask(0o027)
        self.write.write_file(self.target, b"x\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.target).st_mode), 0o640)

    def test_write_file_keeps_an_existing_files_mode(self):
        self._with_umask(0o022)
        self.target.write_bytes(b"old\n")
        os.chmod(self.target, 0o600)
        self.write.write_file(self.target, b"new\n")
        self.assertEqual(self.target.read_bytes(), b"new\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.target).st_mode), 0o600)

    def test_write_file_replaces_the_target_by_rename_not_in_place(self):
        self.target.write_bytes(b"old\n")
        before = os.stat(self.target).st_ino
        outcome = self.write.write_file(self.target, b"new\n")
        self.assertEqual(outcome, "written")
        self.assertNotEqual(os.stat(self.target).st_ino, before)
        self.assertEqual(self.target.read_bytes(), b"new\n")

    def test_write_file_leaves_equal_bytes_untouched_and_reports_unchanged(self):
        self.target.write_bytes(b"same\n")
        os.utime(self.target, ns=(1_000_000_000, 1_000_000_000))
        before = os.stat(self.target)
        calls = []
        outcome = self.write.write_file(self.target, b"same\n", hook=calls.append)
        after = os.stat(self.target)
        self.assertEqual(outcome, "unchanged")
        self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(after.st_ino, before.st_ino)
        self.assertEqual(calls, [], "no temporary file is written for equal bytes")
        self.assertEqual(sorted(os.listdir(self.dir)), ["sol-pi.json"])

    def test_write_file_calls_the_hook_once_with_a_complete_temporary_file_in_the_target_directory(self):
        self.target.write_bytes(b"old\n")
        seen = []

        def hook(temporary):
            temporary = Path(temporary)
            seen.append((temporary, temporary.read_bytes(), self.target.read_bytes()))

        self.write.write_file(self.target, b"new\n", hook=hook)
        self.assertEqual(len(seen), 1)
        temporary, temporary_bytes, target_bytes = seen[0]
        self.assertEqual(temporary.parent, self.dir)
        self.assertNotEqual(temporary.name, "sol-pi.json")
        self.assertEqual(temporary_bytes, b"new\n", "the hook runs after the write")
        self.assertEqual(target_bytes, b"old\n", "the hook runs before the rename")
        self.assertFalse(temporary.exists(), "the temporary file was renamed away")
        self.assertEqual(sorted(os.listdir(self.dir)), ["sol-pi.json"])

    def test_write_file_removes_the_temporary_file_and_keeps_the_target_when_the_hook_raises(self):
        self.target.write_bytes(b"old\n")
        os.utime(self.target, ns=(1_000_000_000, 1_000_000_000))

        def hook(_temporary):
            raise HookStop

        with self.assertRaises(HookStop):
            self.write.write_file(self.target, b"new\n", hook=hook)
        self.assertEqual(self.target.read_bytes(), b"old\n")
        self.assertEqual(os.stat(self.target).st_mtime_ns, 1_000_000_000)
        self.assertEqual(sorted(os.listdir(self.dir)), ["sol-pi.json"])

    def test_write_file_creates_nothing_when_the_hook_raises_for_a_new_file(self):
        def hook(_temporary):
            raise HookStop

        with self.assertRaises(HookStop):
            self.write.write_file(self.target, b"new\n", hook=hook)
        self.assertEqual(os.listdir(self.dir), [])

    def test_write_file_through_a_symbolic_link_replaces_the_target_and_keeps_the_link(self):
        real_dir = self.tree.root / "real"
        real_dir.mkdir()
        real = real_dir / "config.json"
        real.write_bytes(b"old\n")
        os.chmod(real, 0o640)
        self.target.symlink_to(real)
        seen = []

        outcome = self.write.write_file(self.target, b"new\n", hook=lambda t: seen.append(Path(t)))

        self.assertEqual(outcome, "written")
        self.assertTrue(self.target.is_symlink(), "the link is kept")
        self.assertEqual(os.readlink(self.target), str(real))
        self.assertEqual(real.read_bytes(), b"new\n")
        self.assertEqual(stat.S_IMODE(os.stat(real).st_mode), 0o640)
        self.assertEqual(seen[0].parent, real_dir, "the temporary file sits beside the link's target")
        self.assertEqual(sorted(os.listdir(real_dir)), ["config.json"])
        self.assertEqual(sorted(os.listdir(self.dir)), ["sol-pi.json"])

    def test_write_file_through_a_symbolic_link_with_equal_bytes_is_unchanged(self):
        real = self.tree.root / "real.json"
        real.write_bytes(b"same\n")
        self.target.symlink_to(real)
        self.assertEqual(self.write.write_file(self.target, b"same\n"), "unchanged")
        self.assertTrue(self.target.is_symlink())


if __name__ == "__main__":
    unittest.main()
