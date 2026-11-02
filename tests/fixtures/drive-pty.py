"""Drive a command under a pty: send one input line each time output goes idle.

usage: drive-pty.py '<json list of input lines>' cmd [args...]
Prints captured output, then 'EXIT=<code>' (or 'EXIT=timeout').
"""
import json, os, pty, select, sys, time

inputs = json.loads(sys.argv[1])
pid, fd = pty.fork()
if pid == 0:
    os.execvp(sys.argv[2], sys.argv[2:])
out = b""
deadline = time.time() + 40
last = time.time()
code = None
while time.time() < deadline:
    r, _, _ = select.select([fd], [], [], 0.2)
    if r:
        try:
            data = os.read(fd, 4096)
        except OSError:
            data = b""
        if not data:
            break
        out += data
        # fish queries terminal capabilities and stalls ~10s without an answer.
        if b"\x1b[0c" in data or b"\x1b[c" in data:
            os.write(fd, b"\x1b[?62;c")
        last = time.time()
    elif inputs and time.time() - last > 0.4:
        os.write(fd, (inputs.pop(0) + "\n").encode())
        last = time.time()
else:
    os.kill(pid, 9)
    code = "timeout"
if code is None:
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
sys.stdout.write(out.decode(errors="replace"))
print(f"\nEXIT={code}")
