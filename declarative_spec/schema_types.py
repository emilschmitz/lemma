"""SQL type → Rust exec/spec types for the declarative emitter."""

from __future__ import annotations

import re
from functools import lru_cache
from dataclasses import dataclass
from enum import Enum, auto

from declarative_spec.parse import DeclarativeUnsupported

# Rust keywords. A column with one of these names is emitted as a raw identifier.
_RUST_KEYWORDS = frozenset(
    {
        "as",
        "async",
        "await",
        "break",
        "box",
        "const",
        "continue",
        "crate",
        "do",
        "dyn",
        "else",
        "enum",
        "extern",
        "false",
        "fn",
        "for",
        "if",
        "impl",
        "in",
        "let",
        "loop",
        "match",
        "mod",
        "move",
        "mut",
        "pub",
        "ref",
        "return",
        "self",
        "static",
        "struct",
        "super",
        "trait",
        "true",
        "type",
        "unsafe",
        "use",
        "where",
        "while",
        "abstract",
        "become",
        "final",
        "macro",
        "override",
        "priv",
        "typeof",
        "unsized",
        "virtual",
        "yield",
        "try",
        "union",
    }
)


def rust_ident(name: str) -> str:
    """Lowercase identifier safe for Rust field names; raw-escape keywords."""
    s = re.sub(r"[^a-z0-9_]", "_", name.lower())
    if s in _RUST_KEYWORDS:
        return f"r#{s}"
    return s


# Names the emitted spec binds itself: the result, a row, a group key, quantifier variables, row indices.
_GENERATED_NAMES = frozenset({"res", "row", "k", "r", "r2", "ex"})
_GENERATED_INDEX = re.compile(r"^[ij]\d+$")
_VALUE_DEF = re.compile(
    r"^(?:pub(?:\([^)]*\))?\s+)?(?:(?:open|closed|uninterp|const|unsafe|exec|spec|proof|broadcast|axiom|default)\s+)*"
    r"(?:fn|const|static)\s+(\w+)",
    re.M,
)


@lru_cache(maxsize=1)
def ambiguous_verus_names() -> frozenset[str]:
    """Function and constant names that two glob imports of the spec preamble both define.

    The preamble imports the Verus builtin crate and every vstd module by glob. A parameter named
    like a name defined in two of them is rejected as ambiguous (``sub``, ``add``). Read from the
    pinned Verus install; fails loudly when it is missing.
    """
    from declarative_spec.vstd_index import VERUS_HOME, VSTD

    sources: dict[str, set[str]] = {}
    for path in [VERUS_HOME / "builtin" / "src" / "lib.rs", *sorted(VSTD.rglob("*.rs"))]:
        for name in _VALUE_DEF.findall(path.read_text()):
            sources.setdefault(name, set()).add(str(path))
    return frozenset(name for name, files in sources.items() if len(files) >= 2)


def param_ident(name: str) -> str:
    """The Rust parameter for a table or alias: ``rust_ident``, moved off names the spec itself uses."""
    ident = rust_ident(name)
    bare = ident.removeprefix("r#")
    if bare in _GENERATED_NAMES or _GENERATED_INDEX.match(bare) or bare in ambiguous_verus_names():
        return f"{bare}_t"
    return ident


class KeyKind(Enum):
    INT = auto()
    STRING = auto()
    BOOL = auto()


UNSIGNED_SQL = frozenset(
    {
        "ubigint",
        "uinteger",
        "usmallint",
        "utinyint",
        "uint",
    }
)
SIGNED_SQL = frozenset(
    {
        "int",
        "integer",
        "bigint",
        "smallint",
        "tinyint",
        "hugeint",
        "int4",
        "int8",
        "int64",
    }
)
FLOAT_SQL = frozenset(
    {
        "float",
        "double",
        "real",
        "float8",
        "double precision",
    }
)
STRING_SQL = frozenset({"string", "varchar", "text", "char"})
BOOL_SQL = frozenset({"bool", "boolean"})

TYPE_EXCLUSIVE_MAX: dict[str, int | None] = {
    "u64": 2**64,
    "i64": 2**63,
    "i128": 2**127,
    "f64": None,
}


@dataclass(frozen=True)
class ColumnTypeInfo:
    sql_type: str
    exec_rust: str
    spec_as: str  # e.g. "int" or "real"
    key_kind: KeyKind | None
    signed: bool
    is_float: bool
    is_hugeint: bool
    cell_exclusive_cap: int | None  # integer types only
    scale: int = 0  # DECIMAL: the stored integer is value * 10**scale
    is_date: bool = False  # DATE: the stored integer is days since 1970-01-01
    precision: int | None = None  # DECIMAL: |stored integer| < 10**precision


def _normalize_sql_type(sql_type: str) -> str:
    return " ".join(sql_type.strip().lower().split())


_DECIMAL = re.compile(r"^(?:decimal|numeric)(?:\((\d+)(?:,\s*(\d+))?\))?$")


def _classify_decimal(norm: str, precision: int, scale: int) -> ColumnTypeInfo:
    if not 1 <= precision <= 38 or not 0 <= scale <= precision:
        raise DeclarativeUnsupported(f"unsupported DECIMAL({precision},{scale})")
    wide = precision > 18
    return ColumnTypeInfo(
        sql_type=f"decimal({precision},{scale})",
        exec_rust="i128" if wide else "i64",
        spec_as="int",
        key_kind=KeyKind.INT,
        signed=True,
        is_float=False,
        is_hugeint=wide,
        cell_exclusive_cap=10**precision,
        scale=scale,
        precision=precision,
    )


def classify_sql_type(sql_type: str) -> ColumnTypeInfo:
    norm = _normalize_sql_type(sql_type)
    decimal = _DECIMAL.match(norm)
    if decimal is not None:
        # A bare DECIMAL is DuckDB's DECIMAL(18,3); DECIMAL(p) has scale 0.
        precision = int(decimal.group(1) or 18)
        scale = int(decimal.group(2) or (0 if decimal.group(1) else 3))
        return _classify_decimal(norm, precision, scale)
    if norm == "date":
        return ColumnTypeInfo(
            sql_type="date",
            exec_rust="i32",
            spec_as="int",
            key_kind=KeyKind.INT,
            signed=True,
            is_float=False,
            is_hugeint=False,
            cell_exclusive_cap=2**31,
            is_date=True,
        )
    if norm in UNSIGNED_SQL:
        return ColumnTypeInfo(
            sql_type=norm,
            exec_rust="u64",
            spec_as="int",
            key_kind=KeyKind.INT,
            signed=False,
            is_float=False,
            is_hugeint=False,
            cell_exclusive_cap=2**64,
        )
    if norm in SIGNED_SQL:
        huge = norm == "hugeint"
        exec_ty = "i128" if huge else "i64"
        cap = 2**127 if huge else 2**63
        return ColumnTypeInfo(
            sql_type=norm,
            exec_rust=exec_ty,
            spec_as="int",
            key_kind=KeyKind.INT,
            signed=True,
            is_float=False,
            is_hugeint=huge,
            cell_exclusive_cap=cap,
        )
    if norm in FLOAT_SQL:
        return ColumnTypeInfo(
            sql_type=norm,
            exec_rust="f64",
            spec_as="real",
            key_kind=None,
            signed=True,
            is_float=True,
            is_hugeint=False,
            cell_exclusive_cap=None,
        )
    if norm in STRING_SQL:
        return ColumnTypeInfo(
            sql_type=norm,
            exec_rust="String",
            spec_as="Seq<char>",
            key_kind=KeyKind.STRING,
            signed=False,
            is_float=False,
            is_hugeint=False,
            cell_exclusive_cap=None,
        )
    if norm in BOOL_SQL:
        return ColumnTypeInfo(
            sql_type=norm,
            exec_rust="bool",
            spec_as="bool",
            key_kind=KeyKind.BOOL,
            signed=False,
            is_float=False,
            is_hugeint=False,
            cell_exclusive_cap=None,
        )
    raise DeclarativeUnsupported(f"unsupported SQL type: {sql_type!r}")


def map_type_for_aggregate(key_kind: KeyKind, value_exec: str) -> str:
    if key_kind == KeyKind.STRING:
        return f"StringHashMap<{value_exec}>"
    return f"HashMapWithView<{key_rust_type(key_kind)}, {value_exec}>"


def key_rust_type(kind: KeyKind) -> str:
    if kind == KeyKind.INT:
        return "i64"
    if kind == KeyKind.STRING:
        return "String"
    if kind == KeyKind.BOOL:
        return "bool"
    raise DeclarativeUnsupported("unsupported group key kind")


def composite_key_rust(kinds: list[KeyKind]) -> str:
    if len(kinds) == 1:
        return key_rust_type(kinds[0])
    inner = ", ".join(key_rust_type(k) for k in kinds)
    return f"({inner})"


@dataclass(frozen=True)
class SchemaModel:
    """Normalized schema: table name → column → ColumnTypeInfo."""

    tables: dict[str, dict[str, ColumnTypeInfo]]
    original_table_names: dict[str, str]  # lowered → original spelling
    original_column_names: dict[tuple[str, str], str]  # (table lower, col lower) → original

    @staticmethod
    def from_caller(schema: dict[str, str] | dict[str, dict[str, str]], from_table: str) -> SchemaModel:
        if not schema:
            raise DeclarativeUnsupported("empty schema")
        first_val = next(iter(schema.values()))
        tables: dict[str, dict[str, ColumnTypeInfo]] = {}
        orig_tables: dict[str, str] = {}
        orig_cols: dict[tuple[str, str], str] = {}

        if isinstance(first_val, str):
            tbl = from_table
            cols: dict[str, ColumnTypeInfo] = {}
            for col_name, sql_ty in schema.items():  # type: ignore[union-attr]
                info = classify_sql_type(str(sql_ty))
                cols[col_name.casefold()] = info
                orig_cols[(tbl.casefold(), col_name.casefold())] = col_name
            tables[tbl.casefold()] = cols
            orig_tables[tbl.casefold()] = tbl
        else:
            for tbl_name, col_map in schema.items():  # type: ignore[union-attr]
                if isinstance(col_map, str):
                    raise DeclarativeUnsupported("schema mixes a flat column map with table maps")
                cols = {}
                for col_name, sql_ty in col_map.items():
                    info = classify_sql_type(str(sql_ty))
                    cols[col_name.casefold()] = info
                    orig_cols[(tbl_name.casefold(), col_name.casefold())] = col_name
                tables[tbl_name.casefold()] = cols
                orig_tables[tbl_name.casefold()] = tbl_name

        return SchemaModel(tables=tables, original_table_names=orig_tables, original_column_names=orig_cols)

    def table_names(self) -> list[str]:
        return [self.original_table_names[k] for k in self.tables]

    def lookup_table(self, name: str) -> tuple[str, dict[str, ColumnTypeInfo]]:
        key = name.casefold()
        if key not in self.tables:
            raise DeclarativeUnsupported(f"unknown table {name!r}")
        return self.original_table_names[key], self.tables[key]

    def lookup_column(self, table: str, column: str) -> tuple[str, ColumnTypeInfo]:
        _, cols = self.lookup_table(table)
        ckey = column.casefold()
        if ckey not in cols:
            raise DeclarativeUnsupported(f"unknown column {table}.{column}")
        orig = self.original_column_names.get((table.casefold(), ckey), column)
        return orig, cols[ckey]

    def resolve_column(self, qual: str | None, bare: str, involved_tables: list[str]) -> tuple[str, str, ColumnTypeInfo]:
        if qual:
            t_orig, _ = self.lookup_table(qual)
            c_orig, info = self.lookup_column(qual, bare)
            return t_orig, c_orig, info
        hits: list[tuple[str, str, ColumnTypeInfo]] = []
        for t in involved_tables:
            tkey = t.casefold()
            cols = self.tables.get(tkey)
            if cols is None:
                continue
            ckey = bare.casefold()
            if ckey in cols:
                t_orig = self.original_table_names[tkey]
                c_orig = self.original_column_names.get((tkey, ckey), bare)
                hits.append((t_orig, c_orig, cols[ckey]))
        if len(hits) == 1:
            return hits[0]
        if len(hits) == 0:
            raise DeclarativeUnsupported(f"column {bare!r} not found")
        raise DeclarativeUnsupported(f"column {bare!r} is ambiguous across tables")
