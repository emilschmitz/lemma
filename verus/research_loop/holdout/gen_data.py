#!/usr/bin/env python3
"""Generate holdout benchmark .tbl files under holdout/data/."""

from __future__ import annotations

import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOLDOUT_DATA = Path(__file__).resolve().parent / "data"
TPCH_LINEITEM = ROOT / "data" / "tpch-sf1" / "lineitem.tbl"
TPCH_ORDERS = ROOT / "data" / "tpch-sf1" / "orders.tbl"
SSB_FLAT = ROOT / "ssb-dbgen" / "lineorder_flat.tbl"

SCAN_SKEW_ROWS = 500_000
SCAN_SKEW_1M_ROWS = 1_000_000
ZIPF_LEFT_ROWS = 200_000
ZIPF_RIGHT_ROWS = 50_000
STR_FILTER_ROWS = 100_000
TPCH_SLICE_ROWS = 200_000
TPCH_1M_ROWS = 1_000_000
SSB_FLAT_ROWS = 500_000


def _skip(path: Path) -> bool:
    if path.is_file():
        print(f"skip {path.name} (exists)")
        return True
    return False


def _zipf_key(rng: random.Random, n_keys: int, alpha: float = 1.2) -> int:
    """Sample Zipf key in [0, n_keys) with exponent alpha."""
    u = rng.random()
    raw = int((u ** (-1.0 / (alpha - 1.0))) if alpha > 1.0 else rng.randint(0, n_keys - 1))
    return min(raw, n_keys - 1)


def gen_scan_skew(path: Path, rows: int) -> None:
    if _skip(path):
        return
    rng = random.Random(42)
    lines = ["EVENT_DATE|REGION|AMOUNT\n"]
    for i in range(rows):
        year = 1990 + (i * 20) // rows
        month = 1 + (i % 12)
        day = 1 + (i % 28)
        event_date = year * 10_000 + month * 100 + day
        region = i % 12
        amount = (rng.randint(1, 999) * 100) + (i % 97)
        lines.append(f"{event_date}|{region}|{amount}\n")
    path.write_text("".join(lines), encoding="utf-8")
    print(f"wrote {path.name}: {rows:,} rows")


def gen_zipf_join(left_path: Path, right_path: Path) -> None:
    if left_path.is_file() and right_path.is_file():
        print(f"skip {left_path.name}, {right_path.name} (exist)")
        return
    rng = random.Random(99)
    n_distinct = 8_000
    left_lines = ["KEY|REGION|AMOUNT\n"]
    for _ in range(ZIPF_LEFT_ROWS):
        key = _zipf_key(rng, n_distinct)
        region = rng.randint(0, 4)
        amount = rng.randint(10, 50_000)
        left_lines.append(f"{key}|{region}|{amount}\n")
    right_keys: set[int] = set()
    right_lines = ["KEY|REGION\n"]
    for _ in range(ZIPF_RIGHT_ROWS):
        key = _zipf_key(rng, n_distinct)
        region = rng.randint(0, 4)
        right_keys.add(key)
        right_lines.append(f"{key}|{region}\n")
    left_path.write_text("".join(left_lines), encoding="utf-8")
    right_path.write_text("".join(right_lines), encoding="utf-8")
    print(
        f"wrote {left_path.name}: {ZIPF_LEFT_ROWS:,} rows, "
        f"{right_path.name}: {ZIPF_RIGHT_ROWS:,} rows "
        f"(~{len(right_keys):,} distinct right keys)"
    )


def gen_str_filter(path: Path) -> None:
    if _skip(path):
        return
    rng = random.Random(7)
    forms = ["10-K", "10-Q", "8-K", "DEF 14A", "S-1", "424B2", "13F-HR", "NPORT-P"]
    lines = ["FORM_TYPE|CIK|AMOUNT|ACTIVE\n"]
    for _ in range(STR_FILTER_ROWS):
        form = forms[rng.randint(0, len(forms) - 1)]
        cik = f"{rng.randint(0, 999999):06d}"
        amount = rng.randint(100, 9_999_999)
        active = rng.randint(0, 1)
        lines.append(f"{form}|{cik}|{amount}|{active}\n")
    path.write_text("".join(lines), encoding="utf-8")
    print(f"wrote {path.name}: {STR_FILTER_ROWS:,} rows")


def gen_tpch_slice(
    lineitem_out: Path,
    orders_out: Path,
    *,
    max_lineitem_rows: int,
) -> None:
    if lineitem_out.is_file() and orders_out.is_file():
        print(f"skip {lineitem_out.name}, {orders_out.name} (exist)")
        return
    if not TPCH_LINEITEM.is_file():
        raise FileNotFoundError(f"missing {TPCH_LINEITEM}")
    if not TPCH_ORDERS.is_file():
        raise FileNotFoundError(f"missing {TPCH_ORDERS}")

    order_keys: set[str] = set()
    with TPCH_LINEITEM.open(encoding="utf-8") as fin, lineitem_out.open(
        "w", encoding="utf-8"
    ) as fout:
        hdr = fin.readline()
        fout.write(hdr)
        for i, line in enumerate(fin):
            if i >= max_lineitem_rows:
                break
            fout.write(line)
            parts = line.rstrip("\n").split("|")
            if parts:
                order_keys.add(parts[0])

    with TPCH_ORDERS.open(encoding="utf-8") as fin, orders_out.open(
        "w", encoding="utf-8"
    ) as fout:
        hdr = fin.readline()
        fout.write(hdr)
        kept = 0
        for line in fin:
            parts = line.rstrip("\n").split("|")
            if parts and parts[0] in order_keys:
                fout.write(line)
                kept += 1

    print(
        f"wrote {lineitem_out.name}: {max_lineitem_rows:,} rows, "
        f"{orders_out.name}: {kept:,} matching orders"
    )


def gen_ssb_flat_500k(path: Path) -> None:
    if _skip(path):
        return
    if not SSB_FLAT.is_file():
        raise FileNotFoundError(f"missing {SSB_FLAT}")
    with SSB_FLAT.open(encoding="utf-8") as fin, path.open("w", encoding="utf-8") as fout:
        hdr = fin.readline()
        fout.write(hdr)
        for i, line in enumerate(fin):
            if i >= SSB_FLAT_ROWS:
                break
            fout.write(line)
    print(f"wrote {path.name}: {SSB_FLAT_ROWS:,} rows from {SSB_FLAT.name}")


def main() -> None:
    HOLDOUT_DATA.mkdir(parents=True, exist_ok=True)
    gen_scan_skew(HOLDOUT_DATA / "scan_skew.tbl", SCAN_SKEW_ROWS)
    gen_scan_skew(HOLDOUT_DATA / "scan_skew_1m.tbl", SCAN_SKEW_1M_ROWS)
    gen_zipf_join(HOLDOUT_DATA / "zipf_left.tbl", HOLDOUT_DATA / "zipf_right.tbl")
    gen_str_filter(HOLDOUT_DATA / "str_filter.tbl")
    gen_tpch_slice(
        HOLDOUT_DATA / "lineitem_slice.tbl",
        HOLDOUT_DATA / "orders_slice.tbl",
        max_lineitem_rows=TPCH_SLICE_ROWS,
    )
    gen_tpch_slice(
        HOLDOUT_DATA / "lineitem_1m.tbl",
        HOLDOUT_DATA / "orders_1m.tbl",
        max_lineitem_rows=TPCH_1M_ROWS,
    )
    gen_ssb_flat_500k(HOLDOUT_DATA / "ssb_flat_500k.tbl")
    print(f"holdout data in {HOLDOUT_DATA}")


if __name__ == "__main__":
    main()
