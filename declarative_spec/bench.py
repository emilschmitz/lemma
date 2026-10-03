"""Column-file speed bar for a declarative binary. No database client lives here."""

from __future__ import annotations

import json
from pathlib import Path


def rows_from_stdout(stdout: str) -> list[tuple[int, int]]:
    rows: list[tuple[int, int]] = []
    for line in stdout.splitlines():
        if not line.startswith("ROW "):
            continue
        parts = line.split()
        if len(parts) != 3:
            continue
        rows.append((int(parts[1]), int(parts[2])))
    return sorted(rows)


def load_speed_bar(data_dir: Path) -> tuple[dict[str, str], dict] | None:
    expect_path = data_dir / "expect.json"
    if not expect_path.is_file():
        return None
    bins: dict[str, str] = {}
    for path in sorted(data_dir.glob("cols_*.bin")):
        suffix = path.name[len("cols_") : -len(".bin")]
        bins[suffix] = str(path)
    if not bins:
        raise FileNotFoundError(f"no column file in {data_dir}")
    bar = json.loads(expect_path.read_text(encoding="utf-8"))
    return bins, bar
