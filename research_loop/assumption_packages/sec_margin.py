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
"""

from __future__ import annotations

from dataclasses import dataclass

from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
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
    MarginAssumption(13, "num.qtrs < 2^8"),
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


def _col(exclusive: int) -> ColumnAssumption:
    return ColumnAssumption(max_value_exclusive=exclusive)


def _strlen(n: int) -> ColumnAssumption:
    return ColumnAssumption(max_string_len=n)


def sec_margin_catalog() -> CatalogAssumptions:
    """The ``sec_margin`` package as a catalog the transpiler already accepts."""
    if len(ASSUMPTIONS) != 45:
        raise RuntimeError(f"sec_margin must list 45 assumptions, got {len(ASSUMPTIONS)}")
    return CatalogAssumptions(
        max_rows=ANY_TABLE_ROWS,
        max_rows_cube=ANY_TABLE_ROWS,
        max_rows_4=ANY_TABLE_ROWS,
        max_cell_u64=VALUE_EXCLUSIVE,
        max_native_u32=U32_EXCLUSIVE,
        max_string_len=STRING_LEN,
        tables={
            "num": TableAssumptions(
                max_rows=NUM_ROWS,
                columns={
                    "value": _col(VALUE_EXCLUSIVE),
                    "ddate": _col(2**28),
                    "qtrs": _col(2**8),
                    "adsh": _strlen(32),
                    "tag": _strlen(512),
                    "version": _strlen(64),
                    "uom": _strlen(64),
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
                    "stmt": _strlen(8),
                    "rfile": _strlen(4),
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
                    "form": _strlen(16),
                    "fp": _strlen(8),
                    "countryba": _strlen(8),
                    "name": _strlen(256),
                    "afs": _strlen(AFS_LEN),
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
                    "datatype": _strlen(32),
                    "iord": _strlen(4),
                    "crdr": _strlen(4),
                    "doc": _strlen(STRING_LEN),
                },
            ),
        },
    )
