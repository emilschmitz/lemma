"""SEC margin assumption package.

Forty-five upper bounds and schema keys. Each one is a domain fact the
SEC EDGAR 2022–2024 database already sits under, with room for several more
years of filings. Caps were checked on 2026-10-02 against
``sec_edgar.duckdb`` (num 39,401,761, pre 9,600,799, sub 86,135, tag 1,070,662).

Measured maxima that set the tight caps: ``num.value`` 1.884e17 (about 2^57.4),
``pre.line`` 482, ``pre.report`` 324, ``sub.cik`` 2,042,694, ``sub.sic`` 8,900,
``sub.fy`` 2,025, ``sub.nciks`` 33, ``num.coreg`` 96 characters, ``tag`` names
204 characters, ``tag.doc`` 13,227 characters. The old global string cap of
4096 is false because of ``tag.doc``. The global string cap is 2^16.

``num.value`` is loaded by truncating the DOUBLE toward zero into ``u64``, so
negatives become 0. The positive maximum still requires ``< 2^62``. A 99th
percentile near 2.5e10 is real, and only 48,300 rows have absolute value above
1e12, but that is not a cell cap: the maximum is far above it. The absolute
sum of ``value`` does not fit in ``u64`` (the measured tail alone can pass
2^64), so this package does not state one.

A count of pairs of tables at the global row cap fits in ``u64``
(2^31 * 2^31 = 2^62). A two-table sum of ``value`` fits in ``i128``
(2^62 * 2^62 = 2^124). A three-table or four-table nested sum of ``value``
does not fit in ``i128`` under these caps. That is left unstated rather than
given a false total.

Join caps (``JOIN_CAPS``, outside the 45) are data assumptions of the same kind: ``num JOIN pre ON (adsh, tag, version)``
has at most 2^36 joined tuples. They are not proved. ``check.py`` measures ``COUNT(*)`` of each declared join and fails
naming the join and the measured count; the emitted spec requires the cap and ``main`` asserts it on the loaded data.
On the development machine only the synthetic SEC data (1.25M joined tuples) has been checked: the real EDGAR join
count is unverified until the preflight (``check.py``) runs on the real database.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    JoinCap,
    TableAssumptions,
)

# Published SEC-EDGAR 2022–2024 counts. The caps below are strictly larger.
SEC_NUM_ROWS = 39_401_761
SEC_PRE_ROWS = 9_600_799
SEC_SUB_ROWS = 86_135
SEC_TAG_ROWS = 1_070_662
# Recorded exclusive maximum of num.value.
SEC_NUM_VALUE_EXCLUSIVE = 188_446_126_794_000_002

NUM_ROWS = 2**31
PRE_ROWS = 2**28
SUB_ROWS = 2**20
TAG_ROWS = 2**24
ANY_TABLE_ROWS = 2**31
VALUE_EXCLUSIVE = 2**62
# DECIMAL variant of the database (``make_decimal_variant.py``): num.value is DECIMAL(38, 4),
# a stored i128 equal to value * 10**4. The EDGAR documentation (aqfs.pdf) gives the field
# as 4 decimals; the local slice has at most 2.
DEC_VALUE_SCALE = 4
# The same real-world fact, num.value < 2^62, in stored units. Derived, never loosened:
# 2^62 * 10^4 (about 2^75.3) is the exclusive stored cap. The measured maximum 1.884e17 stores
# as 1.884e21 (about 2^70.7), under it. A two-table sum of it is below 2^31 * 2^75.3 = 2^106.3,
# which fits i128; the three-table product does not (same as the DOUBLE package, one level down).
DEC_VALUE_EXCLUSIVE = VALUE_EXCLUSIVE * 10**DEC_VALUE_SCALE
# tag.doc measured 13227. 2^16 is about 5x that, and covers the other text columns.
STRING_LEN = 2**16
U32_EXCLUSIVE = 2**31
CIK_EXCLUSIVE = 2**24
SIC_EXCLUSIVE = 2**14
FY_EXCLUSIVE = 2**12
NCIKS_EXCLUSIVE = 2**8
LINE_EXCLUSIVE = 2**13
REPORT_EXCLUSIVE = 2**12
COREG_LEN = 256
AFS_LEN = 16


@dataclass(frozen=True)
class MarginAssumption:
    """One named fact in this package. ``n`` is 1..45."""

    n: int
    statement: str


# Order is the package. Replacing a fact means editing that slot, not appending.
ASSUMPTIONS: tuple[MarginAssumption, ...] = (
    MarginAssumption(1, "num has at most 2^31 rows"),
    MarginAssumption(2, "pre has at most 2^28 rows"),
    MarginAssumption(3, "sub has at most 2^20 rows"),
    MarginAssumption(4, "tag has at most 2^24 rows"),
    MarginAssumption(5, "every table has at most 2^31 rows"),
    MarginAssumption(6, "a 3-table query still has at most 2^31 rows per table"),
    MarginAssumption(7, "a 4-table query still has at most 2^31 rows per table"),
    MarginAssumption(8, "sub.adsh is unique"),
    MarginAssumption(9, "(tag.tag, tag.version) is unique"),
    MarginAssumption(10, "(pre.adsh, pre.report, pre.line) is unique"),
    MarginAssumption(11, "num.value < 2^62"),
    MarginAssumption(12, "num.ddate < 2^28"),
    MarginAssumption(13, "num.qtrs < 2^16"),
    MarginAssumption(14, "sub.cik < 2^24"),
    MarginAssumption(15, "sub.sic < 2^14"),
    MarginAssumption(16, "sub.fy < 2^12"),
    MarginAssumption(17, "sub.period < 2^28"),
    MarginAssumption(18, "sub.filed < 2^28"),
    MarginAssumption(19, "sub.nciks < 2^8"),
    MarginAssumption(20, "sub.prevrpt < 16"),
    MarginAssumption(21, "sub.wksi < 16"),
    MarginAssumption(22, "pre.line < 2^13"),
    MarginAssumption(23, "pre.report < 2^12"),
    MarginAssumption(24, "pre.inpth < 16"),
    MarginAssumption(25, "pre.negating < 16"),
    MarginAssumption(26, "tag.custom < 16"),
    MarginAssumption(27, "tag.abstract < 16"),
    MarginAssumption(28, "every string has length at most 2^16"),
    MarginAssumption(29, "every u32 cell is < 2^31"),
    MarginAssumption(30, "every u64 cell is < 2^62"),
    MarginAssumption(31, "every adsh has length at most 32"),
    MarginAssumption(32, "every tag name has length at most 512"),
    MarginAssumption(33, "every version has length at most 64"),
    MarginAssumption(34, "num.uom has length at most 64"),
    MarginAssumption(35, "sub.form has length at most 16"),
    MarginAssumption(36, "sub.fp has length at most 8"),
    MarginAssumption(37, "pre.stmt has length at most 8"),
    MarginAssumption(38, "sub.countryba has length at most 8"),
    MarginAssumption(39, "sub.name has length at most 256"),
    MarginAssumption(40, "num.coreg has length at most 256"),
    MarginAssumption(41, "tag.datatype has length at most 32"),
    MarginAssumption(42, "tag.iord has length at most 4"),
    MarginAssumption(43, "tag.crdr has length at most 4"),
    MarginAssumption(44, "pre.rfile has length at most 4"),
    MarginAssumption(45, "sub.afs has length at most 16"),
)


# Join caps: data assumptions on the number of joined tuples of a pair of tables, in the spirit of the row caps.
# They are separate from the 45 above (that count is fixed). Each one is MEASURED by ``check.py``
# (``COUNT(*)`` of exactly that join) and required of the loaded data by the emitted spec.
#
# num JOIN pre ON (adsh, tag, version): 2^36 joined tuples. Derivation: num has 39.4M rows (about 2^25.2 on the
# 2022-2024 data) and a num fact matches the presentation lines of its filing that show the same concept: a handful
# of statements times a few lines, about 2^3 to 2^5 on typical filings, with a few thousand for the largest
# filings that present one concept in many reports. 2^25.2 rows x 2^11 fan-out = 2^36.2, so 2^36 holds with the
# stated margin only if the average fan-out stays below about 2^10.8. ON THIS MACHINE ONLY THE SYNTHETIC DATA HAS
# BEEN CHECKED; the real EDGAR join count is unverified until ``check.py`` runs on the real database.
JOIN_CAPS: tuple[JoinCap, ...] = (
    JoinCap("num", "pre", (("adsh", "adsh"), ("tag", "tag"), ("version", "version")), 2**36),
)


def _col(exclusive: int, scale: int = 0) -> ColumnAssumption:
    return ColumnAssumption(max_value_exclusive=exclusive, scale=scale)


def _strlen(n: int, distinct: int | None = None, nullable: bool = False) -> ColumnAssumption:
    return ColumnAssumption(max_string_len=n, max_distinct=distinct, nullable=nullable)


# Columns that hold NULL cells in the real EDGAR database (counts measured on sec_edgar_dec.duckdb, 2026-10-04):
# num.coreg 38,909,249 / num.footnote 39,329,996 of 39.4M; pre.stmt 1,073 / pre.plabel 1,332 of 9.6M; sub.sic 1,215,
# countryba 87, stprba 9,355, cityba 87, countryinc 7,967, period 7, fy 4,662, fp 4,665, afs 695, fye 106 of 86,135;
# tag.crdr 119,636, tlabel 6, doc 146,328 of 1.07M. These are declared ``nullable``: loaded with a validity vector and
# queried with SQL's three-valued logic. Every other column is declared (by omission) to hold no NULL, and
# ``check.py`` measures that.
NULLABLE_COLUMNS: frozenset[tuple[str, str]] = frozenset(
    {
        ("num", "coreg"), ("num", "footnote"),
        ("pre", "stmt"), ("pre", "plabel"),
        ("sub", "sic"), ("sub", "countryba"), ("sub", "stprba"), ("sub", "cityba"), ("sub", "countryinc"),
        ("sub", "period"), ("sub", "fy"), ("sub", "fp"), ("sub", "afs"), ("sub", "fye"),
        ("tag", "crdr"), ("tag", "tlabel"), ("tag", "doc"),
    }
)


def _with_nullable(catalog: CatalogAssumptions) -> CatalogAssumptions:
    """``catalog`` with ``nullable=True`` on every column of ``NULLABLE_COLUMNS`` (a column with no entry gets one)."""
    import dataclasses

    tables = dict(catalog.tables)
    for table, column in sorted(NULLABLE_COLUMNS):
        ta = tables[table]
        old = ta.columns.get(column, ColumnAssumption())
        cols = {**ta.columns, column: dataclasses.replace(old, nullable=True)}
        tables[table] = dataclasses.replace(ta, columns=cols)
    return dataclasses.replace(catalog, tables=tables)


# Distinct-value caps of the low-cardinality string columns (data assumptions, outside the 45): they pick the
# dictionary code width when strings are dictionary-encoded (LEMMA_STRING_ENCODING=dict): u8 up to 256, u16 up to 65536.
# `check.py` MEASURES each (COUNT(DISTINCT col)) and fails naming the column and the measured count. Derived from
# the EDGAR Financial Statement Data Sets documentation with a wide margin; ON THIS MACHINE ONLY THE SYNTHETIC DATA
# HAS BEEN CHECKED ON THE SYNTHETIC DATA (num.uom 3, pre.stmt 7, pre.rfile 2, sub.form 4, sub.fp 5, sub.afs 1, tag.iord 1,
# tag.crdr 1, tag.datatype 1, sub.countryba 1). MEASURED ON THE REAL DATABASE (read-only, 2026-10-04, sec_edgar_dec.duckdb):
# num.uom 201, pre.stmt 8, pre.rfile 2, sub.form 49, sub.fp 4, sub.afs 3, sub.countryba 78, tag.iord 2, tag.crdr 2,
# tag.datatype 13: every cap below holds with margin.
#   pre.stmt 16 (BS IS CF EQ CI UN CP SI), pre.rfile 8 (H, X), sub.form 256 (about 60 form types), sub.fp 32
#   (FY Q1-Q4 H1 H2 M9 T1-T3 ...), sub.afs 16 (LAF ACC SRA NON ...), tag.iord 4 (I, D), tag.crdr 4 (C, D),
#   tag.datatype 64 (about 10), sub.countryba 512 (ISO codes, about 250 and a few historical), num.uom 4096 (EDGAR
#   has hundreds of units; u16 codes).
DISTINCT_CAPS: dict[tuple[str, str], int] = {
    ("num", "uom"): 4096,
    ("pre", "stmt"): 16,
    ("pre", "rfile"): 8,
    ("sub", "form"): 256,
    ("sub", "fp"): 32,
    ("sub", "afs"): 16,
    ("sub", "countryba"): 512,
    ("tag", "iord"): 4,
    ("tag", "crdr"): 4,
    ("tag", "datatype"): 64,
}


def sec_margin_catalog(value_scale: int = 0) -> CatalogAssumptions:
    """The ``sec_margin`` package as a catalog the transpiler already accepts.

    ``value_scale`` > 0 is the DECIMAL variant: ``num.value`` is DECIMAL(38, value_scale) and
    its cap is the same fact in stored units.
    """
    if len(ASSUMPTIONS) != 45:
        raise RuntimeError(f"sec_margin must list 45 assumptions, got {len(ASSUMPTIONS)}")
    return _with_nullable(_sec_margin_base(value_scale))


def _sec_margin_base(value_scale: int) -> CatalogAssumptions:
    return CatalogAssumptions(
        max_rows=ANY_TABLE_ROWS,
        max_rows_cube=ANY_TABLE_ROWS,
        max_rows_4=ANY_TABLE_ROWS,
        max_cell_u64=VALUE_EXCLUSIVE,  # u64 cells only; the DECIMAL value is an i128 cell
        max_native_u32=U32_EXCLUSIVE,
        max_string_len=STRING_LEN,
        join_caps=JOIN_CAPS,
        tables={
            "num": TableAssumptions(
                max_rows=NUM_ROWS,
                columns={
                    "value": (
                        _col(VALUE_EXCLUSIVE * 10**value_scale, value_scale)
                    ),
                    "ddate": _col(2**28),
                    "qtrs": _col(2**16),  # real EDGAR max is 3604 (checked 2026-10-04 on the full 39.4M-row table); 2^8 was false
                    "adsh": _strlen(32),
                    "tag": _strlen(512),
                    "version": _strlen(64),
                    "uom": _strlen(64, DISTINCT_CAPS[("num", "uom")]),
                    "coreg": _strlen(COREG_LEN),
                },
            ),
            "pre": TableAssumptions(
                max_rows=PRE_ROWS,
                unique_keys=(("adsh", "report", "line"),),
                columns={
                    "line": _col(LINE_EXCLUSIVE),
                    "report": _col(REPORT_EXCLUSIVE),
                    "inpth": _col(16),
                    "negating": _col(16),
                    "adsh": _strlen(32),
                    "tag": _strlen(512),
                    "version": _strlen(64),
                    "stmt": _strlen(8, DISTINCT_CAPS[("pre", "stmt")]),
                    "rfile": _strlen(4, DISTINCT_CAPS[("pre", "rfile")]),
                },
            ),
            "sub": TableAssumptions(
                max_rows=SUB_ROWS,
                one_row_per_adsh=True,
                unique_keys=(("adsh",),),
                columns={
                    "cik": _col(CIK_EXCLUSIVE),
                    "sic": _col(SIC_EXCLUSIVE),
                    "fy": _col(FY_EXCLUSIVE),
                    "period": _col(2**28),
                    "filed": _col(2**28),
                    "nciks": _col(NCIKS_EXCLUSIVE),
                    "prevrpt": _col(16),
                    "wksi": _col(16),
                    "adsh": _strlen(32),
                    "form": _strlen(16, DISTINCT_CAPS[("sub", "form")]),
                    "fp": _strlen(8, DISTINCT_CAPS[("sub", "fp")]),
                    "countryba": _strlen(8, DISTINCT_CAPS[("sub", "countryba")]),
                    "name": _strlen(256),
                    "afs": _strlen(AFS_LEN, DISTINCT_CAPS[("sub", "afs")]),
                },
            ),
            "tag": TableAssumptions(
                max_rows=TAG_ROWS,
                unique_keys=(("tag", "version"),),
                columns={
                    "custom": _col(16),
                    "abstract": _col(16),
                    "tag": _strlen(512),
                    "version": _strlen(64),
                    "datatype": _strlen(32, DISTINCT_CAPS[("tag", "datatype")]),
                    "iord": _strlen(4, DISTINCT_CAPS[("tag", "iord")]),
                    "crdr": _strlen(4, DISTINCT_CAPS[("tag", "crdr")]),
                    "doc": _strlen(STRING_LEN),
                },
            ),
        },
    )


def sec_margin_dec_catalog() -> CatalogAssumptions:
    """``sec_margin`` for the DECIMAL(38, ``DEC_VALUE_SCALE``) variant of ``num.value``."""
    return sec_margin_catalog(DEC_VALUE_SCALE)
