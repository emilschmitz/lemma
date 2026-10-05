"""Host-only workspace paths that must be invisible inside the agent container.

The agent container bind-mounts the whole run workspace read-write. Some files the host drives write
there are for the host only: the exported raw column data (``decl_data/cols_*.bin``), the reference
engine's expected result and timing bar (``decl_data/expect.json``, ``bar.json``). Every path listed
here is shadowed by an empty read-only tmpfs mounted over it, so the host still reads and writes the
real directory (it is the same host path, nothing moved) while the agent sees an empty directory.
"""

from __future__ import annotations

from pathlib import Path

# Relative to the workspace root. Directories only (a tmpfs shadows a directory).
HOST_ONLY_DIRS: tuple[str, ...] = ("decl_data",)


def shadow_mount_args(workspace: Path) -> list[str]:
    """``docker run`` args that shadow each host-only dir under ``/workspace``.

    The mountpoint is created host-side first, as the host user: otherwise docker creates it as root
    inside the bind mount and the host's later write into it fails. Must come after the workspace bind mount.
    """
    args: list[str] = []
    for rel in HOST_ONLY_DIRS:
        (workspace / rel).mkdir(parents=True, exist_ok=True)
        args += [
            "--mount",
            f"type=tmpfs,destination=/workspace/{rel},tmpfs-size=4096,tmpfs-mode=0555,readonly",
        ]
    return args
