"""Global column value bounds for Lemma (all queries, host-injected via ValidCols).

Powers of two — loose enough for OLAP benchmarks (SSB, TPC-H SF1), tight enough
for the verifier to prove casts, products, and i64 aggregation paths.
"""
from __future__ import annotations

# Max rows in one ColsNative table (also matches practical in-memory caps).
LEMMA_MAX_ROWS = 2**31

# NativeU32 cells: keys, dates (YYYYMMDD), quantities, discounts, etc.
LEMMA_MAX_NATIVE_U32 = 2**31

# NativeU64 money / wide metric cells (per row, before aggregation).
LEMMA_MAX_MONEY_U64 = 2**40

# Per-cell string length (nation names, brands, regions, …).
LEMMA_MAX_STRING_LEN = 128


def emit_bound_constants() -> str:
    return f"""// === Lemma global input bounds (all queries) ===
const LemmaMaxRows: int := {LEMMA_MAX_ROWS}
const LemmaMaxNativeU32: int := {LEMMA_MAX_NATIVE_U32}
const LemmaMaxMoneyU64: int := {LEMMA_MAX_MONEY_U64}
const LemmaMaxStringLen: int := {LEMMA_MAX_STRING_LEN}
"""


def _col_dafny_type(col_type: str) -> str:
    t = col_type.lower()
    if t in ("bigint", "int64", "int8"):
        return "NativeU64"
    if t in ("int", "integer", "int4", "int32"):
        return "NativeU32"
    if t in ("string", "varchar", "text"):
        return "string"
    raise ValueError(f"unsupported column type: {col_type!r}")


def emit_bound_lemmas() -> str:
    return """lemma LemmaMaxMoneyFitsI64()
  ensures LemmaMaxMoneyU64 < 9223372036854775808
{
}

lemma MoneyU64FitsI64(v: NativeU64)
  requires (v as int) < LemmaMaxMoneyU64
  ensures (v as int) < 9223372036854775808
{
  LemmaMaxMoneyFitsI64();
}
"""


def emit_valid_cols_accessor_lemmas(schema_dict: dict[str, str]) -> str:
    """Per-column lemmas: instantiate ValidCols at index i (schema-generated)."""
    blocks: list[str] = []
    for col, col_type in schema_dict.items():
        dt = _col_dafny_type(col_type)
        if dt == "NativeU32":
            bound = "LemmaMaxNativeU32"
        elif dt == "NativeU64":
            bound = "LemmaMaxMoneyU64"
        else:
            bound = "LemmaMaxStringLen"
            blocks.append(
                f"lemma ValidCols_Get{col}(cols: Cols, i: int)\n"
                f"  requires ValidCols(cols)\n"
                f"  requires 0 <= i < cols.n()\n"
                f"  ensures |cols.Get{col}(i)| <= {bound}\n"
                f"{{\n"
                f"}}\n"
            )
            continue
        cmp = "<" if dt != "string" else "<="
        expr = f"(cols.Get{col}(i) as int) {cmp} {bound}"
        blocks.append(
            f"lemma ValidCols_Get{col}(cols: Cols, i: int)\n"
            f"  requires ValidCols(cols)\n"
            f"  requires 0 <= i < cols.n()\n"
            f"  ensures {expr}\n"
            f"{{\n"
            f"}}\n"
        )
    return "\n".join(blocks)


def emit_valid_cols_predicate(schema_dict: dict[str, str]) -> str:
    """Columnar ValidCols: row count + per-column cell bounds."""
    lines = [
        "predicate ValidCols(cols: Cols)",
        "{",
        "  0 <= cols.n() <= LemmaMaxRows",
    ]
    for col, col_type in schema_dict.items():
        dt = _col_dafny_type(col_type)
        idx = "i"
        if dt == "NativeU32":
            lines.append(
                f"  && (forall {idx} :: 0 <= {idx} < cols.n() ==>"
                f" (cols.Get{col}({idx}) as int) < LemmaMaxNativeU32)"
            )
        elif dt == "NativeU64":
            lines.append(
                f"  && (forall {idx} :: 0 <= {idx} < cols.n() ==>"
                f" (cols.Get{col}({idx}) as int) < LemmaMaxMoneyU64)"
            )
        else:
            lines.append(
                f"  && (forall {idx} :: 0 <= {idx} < cols.n() ==>"
                f" |cols.Get{col}({idx})| <= LemmaMaxStringLen)"
            )
    lines.append("}")
    return "\n".join(lines)
