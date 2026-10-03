"""Local Verus check for assembled declarative programs."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

VERUS_CANDIDATES = (
    Path("/home/emil/tools/verus/verus"),
    Path("verus"),
)


def _verus_binary() -> str:
    for p in VERUS_CANDIDATES:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return "verus"


def verify_assembled(rs_source: str, *, timeout_sec: int = 180) -> tuple[bool, str]:
    verus = _verus_binary()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
        f.write(rs_source)
        path = f.name
    try:
        proc = subprocess.run(
            [verus, path],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, combined
    except subprocess.TimeoutExpired as e:
        def _text(chunk: str | bytes | None) -> str:
            if chunk is None:
                return ""
            if isinstance(chunk, bytes):
                return chunk.decode("utf-8", errors="replace")
            return chunk

        out = _text(e.stdout) + _text(e.stderr)
        return False, out or f"timeout after {timeout_sec}s"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
