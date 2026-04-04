"""Atomic file write utilities."""

import os
import tempfile
from pathlib import Path


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Write bytes to a file atomically via tempfile + rename."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    fd_closed = False
    try:
        os.write(fd, content)
        os.close(fd)
        fd_closed = True
        os.replace(tmp, path)
    except BaseException:
        if not fd_closed:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    """Write text to a file atomically (UTF-8 encoded)."""
    atomic_write_bytes(path, text.encode("utf-8"))
