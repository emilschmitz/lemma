"""Build a plain Rust file against the python wheel's DuckDB C API (prototype link): ``build_rust_with_duckdb.py FILE.rs OUT_BINARY [WORKDIR]``.

Used by the profiling tool ``cold_profile.rs``. Same link as ``zero_copy_oneshot.python_wheel_link``: symlink the wheel's ``_duckdb`` extension as libduckdb.so and link libpython.
Run it through ``scripts/ram/heavy.sh`` (a compile is not heavy, but the profiling runs of the binary are).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research_loop.scripts import zero_copy_oneshot as zo  # noqa: E402


def main() -> int:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    work = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/tmp/claude-1000/pin_lib")
    lib, extra = zo.python_wheel_link(work)
    cmd = ["rustc", "-O", "--edition", "2021", str(src), "-o", str(out), "-L", str(lib), "-C", f"link-arg=-Wl,-rpath,{lib}", *extra]
    cmd += sys.argv[4:]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
