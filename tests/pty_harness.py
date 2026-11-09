# SPDX-License-Identifier: MIT
"""The pseudo-terminal harness for the interactive `sol-pi-axi` tests (CR-SLP-005 §S1, §S2).

A run is laid out as a terminal session is:

- an intermediate process, the *leader*, starts a new session (`setsid`) and makes the
  pseudo-terminal its controlling terminal (`TIOCSCTTY`);
- the command runs in a child of the leader, in a process group of its own, which the leader makes
  the terminal's foreground group (`tcsetpgrp`) — unless the run is started in the background,
  where the leader's group stays in the foreground;
- the command's standard input and standard error are the terminal (standard input can be
  `/dev/null` instead, standard error a pipe), its standard output a pipe of its own, so the
  envelope never mixes with what is written to the terminal;
- the leader ignores `SIGHUP`, so closing the master hangs the terminal up without ending the
  leader: the kernel signals only the session's leader, and the command — not its session's
  leader — sees the hang-up as its terminal failing (an empty read, `EIO` on a write).

The test drives the master side: it types answers (Enter is a carriage return, as a keyboard
sends it), sends Ctrl+C and Ctrl+D as keystrokes, sends signals to the command, and closes the
master. The leader reports the command's process id and its exit code (`waitstatus_to_exitcode`:
a negative number for a death by signal) over a pipe of its own.

Linux only (`TIOCSCTTY`, `/proc`), where CI runs.

Not a test module (its name does not match `test_*.py`)."""

from __future__ import annotations

import contextlib
import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

#: The keystrokes a keyboard sends for Ctrl+C, Ctrl+D and Enter.
CTRL_C = b"\x03"
CTRL_D = b"\x04"
ENTER = b"\r"
#: How long a step waits for the command by default, in seconds.
TIMEOUT = 30.0

#: The leader's program. `argv[1]` is its JSON configuration: the slave, standard-output,
#: standard-error (or null) and report descriptors, `stdin` (`tty` or `devnull`), `background`,
#: `ignore_sigint`, the command's `argv` and `env`.
_LEADER = r'''
import fcntl, json, os, signal, sys, termios

config = json.loads(sys.argv[1])
report = config["report"]


def say(text):
    os.write(report, (text + "\n").encode("utf-8", "replace"))


try:
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    slave = config["slave"]
    fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
    gate_read, gate_write = os.pipe()
    pid = os.fork()
except BaseException as error:
    say(f"error leader: {error!r}")
    os._exit(126)

if pid == 0:
    try:
        os.close(gate_write)
        os.setpgid(0, 0)
        os.read(gate_read, 1)
        os.close(gate_read)
        stdin = slave if config["stdin"] == "tty" else os.open(os.devnull, os.O_RDONLY)
        stderr = slave if config["stderr"] is None else config["stderr"]
        os.dup2(stdin, 0)
        os.dup2(config["stdout"], 1)
        os.dup2(stderr, 2)
        for fd in {slave, config["stdout"], stdin, stderr}:
            if fd > 2:
                os.close(fd)
        os.set_inheritable(report, False)
        signal.signal(signal.SIGHUP, signal.SIG_DFL)
        signal.signal(signal.SIGINT,
                      signal.SIG_IGN if config["ignore_sigint"] else signal.SIG_DFL)
        os.execve(config["argv"][0], config["argv"], config["env"])
    except BaseException as error:
        say(f"error exec: {error!r}")
    os._exit(127)

os.close(gate_read)
try:
    os.setpgid(pid, pid)
except OSError:
    pass  # the child has set it already
if not config["background"]:
    try:
        os.tcsetpgrp(slave, pid)
    except OSError as error:
        say(f"error tcsetpgrp: {error!r}")
os.write(gate_write, b"g")
os.close(gate_write)
say(f"pid {pid}")
for fd in {slave, config["stdout"], *([config["stderr"]] if config["stderr"] is not None else [])}:
    os.close(fd)
_, status = os.waitpid(pid, 0)
say(f"exit {os.waitstatus_to_exitcode(status)}")
'''


@dataclass
class PtyResult:
    """A finished run: the exit code, standard output (the pipe), standard error (the pipe, or
    the terminal's transcript when standard error was the terminal) and the terminal's
    transcript."""

    returncode: int
    stdout: str
    stderr: str
    terminal: str


class _Collector(threading.Thread):
    """Reads a descriptor to its end (end of file, or `EIO` once a terminal has no slave left)."""

    def __init__(self, fd: int, condition: threading.Condition):
        super().__init__(daemon=True)
        self.fd = fd
        self.condition = condition
        self.data = bytearray()
        self.done = False
        self.stopping = False

    def run(self) -> None:
        try:
            while not self.stopping:
                ready, _, _ = select.select([self.fd], [], [], 0.05)
                if not ready:
                    continue
                try:
                    chunk = os.read(self.fd, 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                with self.condition:
                    self.data.extend(chunk)
                    self.condition.notify_all()
        finally:
            with self.condition:
                self.done = True
                self.condition.notify_all()

    def text(self) -> str:
        return bytes(self.data).decode("utf-8", "replace")

    def stop(self) -> None:
        self.stopping = True
        self.join(TIMEOUT)


class PtyRun:
    """One command run on a pseudo-terminal (see the module docstring). Call `close` when done
    (a test registers it with `addCleanup`); it kills whatever is left of the run."""

    def __init__(self, argv, *, env: dict, cwd, stdin: str = "tty", stderr: str = "tty",
                 ignore_sigint: bool = False, background: bool = False,
                 timeout: float = TIMEOUT):
        if stdin not in ("tty", "devnull"):
            raise ValueError(f"stdin must be tty or devnull, got {stdin!r}")
        if stderr not in ("tty", "pipe"):
            raise ValueError(f"stderr must be tty or pipe, got {stderr!r}")
        self.timeout = timeout
        self.pid = 0
        self._master_open = True
        self._mark = 0
        self._closed = False
        self._condition = threading.Condition()
        self.master, slave = os.openpty()
        stdout_read, stdout_write = os.pipe()
        report_read, report_write = os.pipe()
        stderr_read = stderr_write = None
        if stderr == "pipe":
            stderr_read, stderr_write = os.pipe()
        config = {"slave": slave, "stdout": stdout_write, "stderr": stderr_write,
                  "report": report_write, "stdin": stdin, "background": background,
                  "ignore_sigint": ignore_sigint, "argv": [str(arg) for arg in argv],
                  "env": {str(key): str(value) for key, value in env.items()}}
        passed = [slave, stdout_write, report_write]
        if stderr_write is not None:
            passed.append(stderr_write)
        try:
            self.leader = subprocess.Popen(
                [sys.executable, "-c", _LEADER, json.dumps(config)], cwd=str(cwd),
                pass_fds=passed, start_new_session=True, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            for fd in passed:
                os.close(fd)
        self.leader_pid = self.leader.pid
        self._terminal = _Collector(self.master, self._condition)
        self._stdout = _Collector(stdout_read, self._condition)
        self._report = _Collector(report_read, self._condition)
        self._stderr = (_Collector(stderr_read, self._condition)
                        if stderr_read is not None else None)
        for collector in self._collectors():
            collector.start()
        self.pid = self._await_pid()

    # --- the leader's report ------------------------------------------------------------------

    def _collectors(self) -> list[_Collector]:
        return [c for c in (self._terminal, self._stdout, self._report, self._stderr)
                if c is not None]

    def _report_lines(self) -> list[str]:
        return self._report.text().splitlines()

    def _reported(self, word: str) -> str | None:
        for line in self._report_lines():
            if line.startswith(word + " "):
                return line[len(word) + 1:]
        return None

    def _await_pid(self) -> int:
        deadline = time.monotonic() + self.timeout
        with self._condition:
            while True:
                error = self._reported("error")
                if error is not None:
                    self.close()
                    raise AssertionError(f"the pseudo-terminal leader failed: {error}")
                pid = self._reported("pid")
                if pid is not None:
                    return int(pid)
                if self._report.done:
                    self.close()
                    raise AssertionError("the pseudo-terminal leader ended without starting "
                                         "the command")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.close()
                    raise AssertionError(f"the command did not start within {self.timeout}s")
                self._condition.wait(min(remaining, 0.1))

    @property
    def returncode(self) -> int | None:
        """The command's exit code once it has ended, else None."""
        with self._condition:
            code = self._reported("exit")
        return None if code is None else int(code)

    # --- what the run shows -------------------------------------------------------------------

    def terminal(self) -> str:
        """Everything written to the terminal so far (the echo of typed keys included)."""
        with self._condition:
            return self._terminal.text()

    def stdout(self) -> str:
        with self._condition:
            return self._stdout.text()

    def _describe(self) -> str:
        return (f"exit: {self._reported('exit')}\n--- terminal ---\n{self._terminal.text()}\n"
                f"--- stdout ---\n{self._stdout.text()}"
                + (f"\n--- stderr ---\n{self._stderr.text()}" if self._stderr is not None else ""))

    def expect(self, text: str, timeout: float | None = None) -> None:
        """Wait until the terminal shows `text` after the previous match; the next `expect`
        searches after this one. Fails at once when the command has ended without showing it."""
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        with self._condition:
            while True:
                transcript = self._terminal.text()
                index = transcript.find(text, self._mark)
                if index >= 0:
                    self._mark = index + len(text)
                    return
                if self._terminal.done or (self._reported("exit") is not None
                                           and self._stdout.done):
                    raise AssertionError(f"the command ended before the terminal showed "
                                         f"{text!r}\n{self._describe()}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(f"the terminal did not show {text!r} within the "
                                         f"timeout\n{self._describe()}")
                self._condition.wait(min(remaining, 0.1))

    # --- driving it ---------------------------------------------------------------------------

    def keys(self, data: bytes) -> None:
        """Write `data` to the master, as keystrokes."""
        if not self._master_open:
            raise AssertionError("the master is closed (the terminal was hung up)")
        os.write(self.master, data)

    def type(self, answer: str) -> None:
        """Type `answer` and press Enter."""
        self.keys(answer.encode("utf-8") + ENTER)

    def type_partial(self, text: str) -> None:
        """Type `text` without pressing Enter."""
        self.keys(text.encode("utf-8"))

    def ctrl_c(self) -> None:
        self.keys(CTRL_C)

    def ctrl_d(self) -> None:
        self.keys(CTRL_D)

    def send_signal(self, signum: int) -> None:
        """Send `signum` to the command's process alone (not its group)."""
        os.kill(self.pid, signum)

    def hang_up(self) -> None:
        """Close the master: the terminal hangs up."""
        self._terminal.stop()
        self._master_open = False
        os.close(self.master)

    def finish(self, timeout: float | None = None) -> PtyResult:
        """Wait for the command to end and its output to be read; the run's result."""
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        with self._condition:
            while self._reported("exit") is None:
                if self._report.done:
                    raise AssertionError(f"the leader ended without reporting the command's "
                                         f"exit\n{self._describe()}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(f"the command did not end within the timeout (waiting "
                                         f"on its terminal, or stopped?)\n{self._describe()}")
                self._condition.wait(min(remaining, 0.1))
        self.leader.wait(max(deadline - time.monotonic(), 1.0))
        for collector in (self._stdout, self._stderr, self._terminal):
            if collector is not None:
                collector.join(max(deadline - time.monotonic(), 1.0))
        terminal = self.terminal()
        stderr = self._stderr.text() if self._stderr is not None else terminal
        return PtyResult(int(self._reported("exit") or "0"), self.stdout(), stderr, terminal)

    def close(self) -> None:
        """Kill whatever is left of the run (the command's process group and the leader) and
        release the descriptors."""
        if self._closed:
            return
        self._closed = True
        if self.pid and self._reported("exit") is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(self.pid, signal.SIGKILL)
        if self.leader.poll() is None:
            self.leader.kill()
        self.leader.wait(TIMEOUT)
        for collector in self._collectors():
            collector.stop()
            if collector is self._terminal and not self._master_open:
                continue
            with contextlib.suppress(OSError):
                os.close(collector.fd)
        self._master_open = False
