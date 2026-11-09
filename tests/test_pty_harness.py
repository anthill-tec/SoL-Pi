# SPDX-License-Identifier: MIT
"""The pseudo-terminal harness (`tests.pty_harness`) does what the interactive `sol-pi-axi` tests
rely on, proved with a probe program in the command's place: the pseudo-terminal is the
command's controlling terminal, in a session whose leader is the intermediate process; the
command is in the terminal's foreground process group (or a background one), with standard input
and standard error on the terminal and standard output on its own pipe; Ctrl+C typed on the
terminal delivers `SIGINT`, Ctrl+D on an empty line an empty read, Enter a line; a signal reaches
the command; a run can start with `SIGINT` ignored; and closing the master with a line partly
typed hangs the terminal up without signalling the command (not its session's leader), whose
read ends and whose next write fails with `EIO`."""

import errno
import json
import os
import signal
import sys
import tempfile
import unittest

from tests.pty_harness import PtyRun

#: The probe. `facts` prints, as one JSON line on standard output, what the run looks like from
#: inside; `read` installs handlers that print `signal <name>` and exit 128+n, writes `prompt> ` to
#: standard error, reads once from standard input, prints the read (or its errno), then tries one
#: more write to standard error and prints whether it worked.
PROBE = r'''
import json, os, signal, sys


def out(value):
    os.write(1, (json.dumps(value) + "\n").encode())


def controlling_terminal():
    with open("/proc/self/stat", encoding="utf-8") as handle:
        fields = handle.read().rsplit(")", 1)[1].split()
    tty_nr = int(fields[4])
    return ((tty_nr >> 8) & 0xFFF, (tty_nr & 0xFF) | ((tty_nr >> 12) & 0xFFF00))


def device(fd):
    rdev = os.fstat(fd).st_rdev
    return (os.major(rdev), os.minor(rdev))


mode = sys.argv[1]
if mode == "facts":
    tty = os.open("/dev/tty", os.O_RDWR)
    ctty = controlling_terminal()
    out({"pid": os.getpid(), "pgrp": os.getpgrp(), "sid": os.getsid(0),
         "foreground": os.tcgetpgrp(tty) == os.getpgrp(),
         "stdinTty": os.isatty(0), "stdoutTty": os.isatty(1), "stderrTty": os.isatty(2),
         "stdinIsControlling": os.isatty(0) and device(0) == ctty,
         "stderrIsControlling": os.isatty(2) and device(2) == ctty,
         "sigintIgnored": signal.getsignal(signal.SIGINT) is signal.SIG_IGN,
         "sighupDefault": signal.getsignal(signal.SIGHUP) is signal.SIG_DFL})
    sys.exit(0)


def on_signal(signum, _frame):
    out({"signal": signal.Signals(signum).name})
    os._exit(128 + signum)


for name in ("SIGINT", "SIGTERM", "SIGHUP"):
    signal.signal(getattr(signal, name), on_signal)
os.write(2, b"prompt> ")
try:
    data = os.read(0, 1024)
    out({"read": data.decode()})
except OSError as error:
    out({"readErrno": error.errno})
try:
    os.write(2, b"after\n")
    out({"writeAfter": "ok"})
except OSError as error:
    out({"writeAfter": error.errno})
sys.exit(0)
'''


class PtyHarnessTest(unittest.TestCase):
    def setUp(self):
        self.cwd = tempfile.mkdtemp(prefix="pty-harness-test-")
        self.addCleanup(os.rmdir, self.cwd)

    def start(self, mode: str, **options) -> PtyRun:
        run = PtyRun([sys.executable, "-c", PROBE, mode],
                     env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"},
                     cwd=self.cwd, **options)
        self.addCleanup(run.close)
        return run

    def records(self, stdout: str) -> list[dict]:
        return [json.loads(line) for line in stdout.splitlines() if line.strip()]

    def facts(self, **options) -> tuple[PtyRun, dict]:
        run = self.start("facts", **options)
        result = run.finish()
        self.assertEqual(result.returncode, 0, result)
        records = self.records(result.stdout)
        self.assertEqual(len(records), 1, result.stdout)
        return run, records[0]

    def test_the_terminal_controls_a_session_led_by_the_intermediate_process(self):
        run, facts = self.facts()
        self.assertEqual(facts["pid"], run.pid)
        self.assertEqual(facts["sid"], run.leader_pid, "the leader leads the session")
        self.assertNotEqual(facts["sid"], facts["pid"], "the command is not the session's leader")
        self.assertTrue(facts["stdinIsControlling"], "standard input is the controlling terminal")
        self.assertTrue(facts["stderrIsControlling"], "standard error is the controlling terminal")

    def test_the_command_is_in_the_foreground_group_with_stdout_on_a_pipe(self):
        _, facts = self.facts()
        self.assertTrue(facts["foreground"])
        self.assertEqual(facts["pgrp"], facts["pid"], "the command leads its own process group")
        self.assertEqual((facts["stdinTty"], facts["stdoutTty"], facts["stderrTty"]),
                         (True, False, True))
        self.assertIs(facts["sigintIgnored"], False)
        self.assertIs(facts["sighupDefault"], True, "the leader's ignored SIGHUP is not inherited")

    def test_a_background_run_is_not_in_the_foreground_group(self):
        _, facts = self.facts(background=True)
        self.assertIs(facts["foreground"], False)
        self.assertEqual((facts["stdinTty"], facts["stderrTty"]), (True, True))
        self.assertTrue(facts["stdinIsControlling"])

    def test_standard_input_can_be_dev_null_and_standard_error_a_pipe(self):
        _, facts = self.facts(stdin="devnull")
        self.assertEqual((facts["stdinTty"], facts["stderrTty"], facts["foreground"]),
                         (False, True, True))
        _, facts = self.facts(stderr="pipe")
        self.assertEqual((facts["stdinTty"], facts["stderrTty"], facts["foreground"]),
                         (True, False, True))

    def test_a_run_can_start_with_sigint_ignored(self):
        _, facts = self.facts(ignore_sigint=True)
        self.assertIs(facts["sigintIgnored"], True)

    def test_a_typed_answer_is_read_as_a_line(self):
        run = self.start("read")
        run.expect("prompt> ")
        run.type("hello")
        result = run.finish()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.records(result.stdout)[0], {"read": "hello\n"})
        self.assertNotIn("prompt> ", result.stdout, "the prompt went to the terminal")
        self.assertIn("prompt> ", result.terminal)

    def test_ctrl_c_typed_on_the_terminal_delivers_sigint(self):
        run = self.start("read")
        run.expect("prompt> ")
        run.ctrl_c()
        result = run.finish()
        self.assertEqual(self.records(result.stdout), [{"signal": "SIGINT"}])
        self.assertEqual(result.returncode, 128 + signal.SIGINT)

    def test_ctrl_d_on_an_empty_line_is_an_empty_read(self):
        run = self.start("read")
        run.expect("prompt> ")
        run.ctrl_d()
        result = run.finish()
        self.assertEqual(self.records(result.stdout)[0], {"read": ""})
        self.assertEqual(result.returncode, 0)

    def test_a_signal_sent_to_the_command_reaches_it(self):
        run = self.start("read")
        run.expect("prompt> ")
        run.send_signal(signal.SIGTERM)
        result = run.finish()
        self.assertEqual(self.records(result.stdout), [{"signal": "SIGTERM"}])
        self.assertEqual(result.returncode, 128 + signal.SIGTERM)

    def test_closing_the_master_mid_line_ends_the_read_and_fails_the_next_write_without_sighup(self):
        run = self.start("read")
        run.expect("prompt> ")
        run.type_partial("par")
        run.hang_up()
        result = run.finish()
        records = self.records(result.stdout)
        self.assertNotIn({"signal": "SIGHUP"}, records,
                         "the command, not its session's leader, is not sent SIGHUP")
        self.assertEqual(len(records), 2, result.stdout)
        self.assertIn(records[0], ({"read": ""}, {"readErrno": errno.EIO}))
        self.assertEqual(records[1], {"writeAfter": errno.EIO})
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
