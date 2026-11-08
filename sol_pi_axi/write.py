# SPDX-License-Identifier: MIT
"""Atomic file writing: a temporary file in the target's directory, renamed over the target."""

import os
import secrets
import stat
from collections.abc import Callable
from pathlib import Path

#: A test-only callback, given the temporary file's path between write and rename.
WriteHook = Callable[[Path], object]
#: A callback run right after the rename, with `SIGINT`, `SIGTERM` and `SIGHUP` blocked.
RenameHook = Callable[[], object]

_BLOCKED_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP")


def _rename_with_signals_blocked(temporary: Path, target: Path, on_rename: RenameHook) -> None:
    """Rename and run `on_rename` with the signals blocked, so a signal arriving in between is
    delivered only after `on_rename` has recorded the rename."""
    import signal

    signals = {getattr(signal, name) for name in _BLOCKED_SIGNALS if hasattr(signal, name)}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, ())
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK, signals)
        os.replace(temporary, target)
        on_rename()
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def write_file(path: str | os.PathLike[str], data: bytes, *, hook: WriteHook | None = None,
               on_rename: RenameHook | None = None) -> str:
    """Write `data` to `path`; returns `"written"`, or `"unchanged"` when the file already holds
    exactly `data` (it is then not touched).

    Through a symbolic link the link's target is replaced and the link kept. An existing file's
    mode is kept; a new file gets `0o666` less the umask. `hook`, when given, is called with the
    temporary file's path after the write and before the rename; if it raises, the temporary file
    is removed, the target is left as it was, and the exception propagates. `on_rename`, when
    given, is called right after the rename; `SIGINT`, `SIGTERM` and `SIGHUP` are blocked from
    just before the rename until it returns, so no signal handler runs between the two."""
    target = Path(os.path.realpath(path)) if os.path.islink(path) else Path(path)
    mode = None
    try:
        info = os.stat(target)
    except FileNotFoundError:
        info = None
    if info is not None and stat.S_ISREG(info.st_mode):
        if target.read_bytes() == data:
            return "unchanged"
        mode = stat.S_IMODE(info.st_mode)

    temporary = target.parent / f".{target.name}.{secrets.token_hex(6)}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        try:
            if mode is not None:
                os.fchmod(fd, mode)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        if hook is not None:
            hook(temporary)
        if on_rename is None:
            os.replace(temporary, target)
        else:
            _rename_with_signals_blocked(temporary, target, on_rename)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return "written"
