"""A realistic default for the absolute float epsilon (`LEMMA_FLOAT_ABS_EPS`).

The epsilon states how far a float aggregate may sit from the exact real value, and is the tolerance of the timed
row check against DuckDB. A huge value (the old `1e20`) accepts any float and checks nothing. The default is
relative 1e-9 of the largest float sum the catalog allows (rows times the largest float magnitude cap), with a
floor of 1e-9, written as a plain decimal.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from declarative_spec.schema_types import classify_sql_type
from research_loop.table_assumptions import CatalogAssumptions, column_assumption_exclusive

REL = Fraction(1, 10**9)
FLOOR = Fraction(1, 10**9)


def _float_columns(schema: dict) -> list[tuple[str | None, str]]:
    first = next(iter(schema.values()), None)
    if isinstance(first, str):  # flat schema: one projected table
        return [(None, c) for c, ty in schema.items() if classify_sql_type(str(ty)).is_float]
    return [(t, c) for t, cols in schema.items() for c, ty in cols.items() if classify_sql_type(str(ty)).is_float]


def default_float_abs_eps(catalog: CatalogAssumptions | None, schema: dict) -> str:
    """Plain decimal string: 1e-9 * (largest rows) * (largest float cap), at least 1e-9."""
    biggest = Fraction(0)
    if catalog is not None:
        for table, column in _float_columns(schema):
            tables = (
                list(catalog.tables.items())
                if table is None
                else [(n, ta) for n, ta in catalog.tables.items() if n.casefold() == table.casefold()]
            )
            for _name, ta in tables:
                cap = column_assumption_exclusive(column, ta)
                rows = ta.max_rows if ta.max_rows is not None else catalog.max_rows
                if cap is not None and rows is not None:
                    biggest = max(biggest, Fraction(rows * cap))
    eps = max(FLOOR, REL * biggest)
    return format(Decimal(eps.numerator) / Decimal(eps.denominator), "f")
