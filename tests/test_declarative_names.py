"""Names: tables, aliases and columns that collide with Rust keywords, vstd names or generated names."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.schema_types import ambiguous_verus_names, param_ident
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

GUARD = Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")

SCHEMA = {
    "sub": {"adsh": "varchar", "form": "varchar", "fy": "integer", "cik": "integer"},
    "tag": {"tag": "varchar", "abstract": "integer", "custom": "integer", "crdr": "varchar", "doc": "varchar"},
}
CATALOG = CatalogAssumptions(
    max_rows=64, tables={t: TableAssumptions(max_rows=64) for t in SCHEMA}
)


def _emit(sql: str) -> str:
    return emit_declarative_spec(sql, SCHEMA, CATALOG, float_abs_eps="1e20")


def _typechecks(spec: str) -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    program = assemble_declarative_program(spec, "    Vec::new()")
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(program)
    proc = subprocess.run(
        [str(GUARD), handle.name, "--no-verify", "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]


def test_the_ambiguous_vstd_names_come_from_the_install() -> None:
    names = ambiguous_verus_names()
    assert {"sub", "add"} <= names
    assert "num" not in names  # a module name lives in another namespace


@pytest.mark.parametrize("name", ["sub", "add", "res", "row", "k", "r", "r2", "i0", "i1", "j0", "ex"])
def test_param_is_moved_off_a_name_the_spec_or_vstd_defines(name: str) -> None:
    assert param_ident(name) == f"{name}_t"


@pytest.mark.parametrize("name", ["num", "tag", "n", "s", "form", "type"])
def test_other_names_keep_their_spelling(name: str) -> None:
    assert param_ident(name) in (name, f"r#{name}")


@pytest.mark.parametrize("alias", ["res", "k", "i0", "row", "r", "add"])
def test_an_alias_that_collides_with_a_generated_name_typechecks(alias: str) -> None:
    spec = _emit(f"SELECT form, COUNT(*) AS c FROM sub {alias} WHERE {alias}.fy > 3 GROUP BY form")
    assert f"{alias}_t: &Cols_sub" in spec
    _typechecks(spec)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT fy, COUNT(*) AS c FROM sub WHERE form = '10-K' GROUP BY fy",  # table named sub
        "SELECT sub.fy, COUNT(*) AS c FROM sub JOIN tag ON sub.adsh = tag.tag GROUP BY sub.fy",
    ],
)
def test_a_table_named_like_a_vstd_function_typechecks(sql: str) -> None:
    _typechecks(_emit(sql))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS n FROM tag WHERE tag = 'x'",  # column named like its table
        "SELECT crdr, COUNT(*) AS n FROM tag WHERE tag LIKE 'A%' AND abstract = 0 GROUP BY crdr",
        "SELECT tag, abstract FROM tag WHERE abstract > 0 ORDER BY tag LIMIT 5",
        "SELECT SUM(CASE WHEN abstract = 0 THEN 1 ELSE 0 END) AS z FROM tag",  # keyword column in CASE
    ],
)
def test_keyword_and_table_named_columns_typecheck(sql: str) -> None:
    _typechecks(_emit(sql))


def test_like_in_a_plain_projection_defines_spec_like() -> None:
    spec = _emit("SELECT crdr, doc FROM tag WHERE crdr LIKE 'D%' ORDER BY crdr LIMIT 10")
    assert "spec fn spec_like(" in spec
    _typechecks(spec)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT fy, AVG(cik) AS a FROM sub GROUP BY fy HAVING AVG(cik) > 5",
        "SELECT fy, AVG(cik) AS a FROM sub GROUP BY fy HAVING 5 < AVG(cik) AND COUNT(*) > 2",
    ],
)
def test_having_an_integer_average_against_an_integer_literal_typechecks(sql: str) -> None:
    spec = _emit(sql)
    assert "5real" in spec
    _typechecks(spec)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS n FROM sub WHERE fy > (SELECT AVG(fy) FROM sub)",
        "SELECT fy, COUNT(*) AS n FROM sub WHERE cik > (SELECT AVG(cik) FROM sub WHERE form = 'x') GROUP BY fy",
        "SELECT COUNT(*) AS n FROM sub WHERE fy = (SELECT COUNT(*) FROM sub)",
    ],
)
def test_an_uncorrelated_scalar_subquery_in_the_where_of_an_aggregate_typechecks(sql: str) -> None:
    spec = _emit(sql)
    assert "sq_1(" in spec
    _typechecks(spec)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS n FROM sub s WHERE s.cik > (SELECT SUM(w.cik) FROM sub w WHERE w.fy = s.fy)",
        "SELECT s.form, COUNT(*) AS n FROM sub s WHERE s.fy > (SELECT AVG(w.fy) FROM sub w WHERE w.cik = s.cik) GROUP BY s.form",
    ],
)
def test_a_correlated_scalar_subquery_in_an_aggregate_is_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="correlated scalar subquery"):
        _emit(sql)


def test_a_with_name_used_inside_a_subquery_is_refused_not_a_crash() -> None:
    sql = (
        "WITH r AS (SELECT fy, COUNT(*) AS c FROM sub GROUP BY fy) "
        "SELECT fy FROM r WHERE c = (SELECT MAX(c) FROM r)"
    )
    with pytest.raises(DeclarativeUnsupported):
        _emit(sql)


@pytest.mark.parametrize(
    ("sql", "inner_cmp"),
    [
        (
            "SELECT COUNT(*) AS c FROM sub a WHERE EXISTS (SELECT 1 FROM sub b WHERE b.cik = a.cik AND b.fy <> a.fy)",
            "(a.cik@[e0] as int) == (a.cik@[i0] as int)",
        ),
        (
            "SELECT a.form, COUNT(*) AS c FROM sub a WHERE NOT EXISTS "
            "(SELECT 1 FROM sub b WHERE b.fy > a.fy AND b.cik = a.cik) GROUP BY a.form",
            "(a.fy@[e0] as int) > (a.fy@[i0] as int)",
        ),
        (
            # the inner alias shadows the outer one: both sides are the inner row
            "SELECT COUNT(*) AS c FROM sub a WHERE EXISTS (SELECT 1 FROM sub a WHERE a.cik = a.fy)",
            "(a.cik@[e0] as int) == (a.fy@[e0] as int)",
        ),
    ],
)
def test_a_correlated_self_subquery_binds_inner_and_outer_rows_apart(sql: str, inner_cmp: str) -> None:
    spec = _emit(sql)
    assert inner_cmp in spec
    _typechecks(spec)


def test_exists_star_is_exists_one() -> None:
    spec = _emit("SELECT COUNT(*) AS c FROM sub a WHERE EXISTS (SELECT * FROM tag t WHERE t.tag = a.adsh)")
    assert "exists|e0: int|" in spec
    _typechecks(spec)


SELF = {"nation": {"k": "integer", "reg": "integer", "nm": "varchar"}}
SELF_CAT = CatalogAssumptions(max_rows=64, tables={"nation": TableAssumptions(max_rows=64)})


@pytest.mark.parametrize(
    ("sql", "want"),
    [
        ("SELECT b.nm, COUNT(*) AS c FROM nation a, nation b WHERE a.reg = b.reg GROUP BY b.nm", "b.nm@[i1]"),
        ("SELECT a.nm, COUNT(*) AS c FROM nation a, nation b WHERE a.reg = b.reg GROUP BY a.nm", "a.nm@[i0]"),
        ("SELECT a.nm, SUM(b.k) AS s FROM nation a, nation b WHERE a.reg = b.reg GROUP BY a.nm", "b.k@[i1]"),
    ],
)
def test_group_key_and_aggregate_bind_to_the_alias_they_name(sql: str, want: str) -> None:
    spec = emit_declarative_spec(sql, SELF, SELF_CAT)
    assert want in spec
    if "SUM" not in sql:
        key_fn = spec.split("pub open spec fn key_at")[1].split("} else")[0]
        assert want in key_fn


def test_self_join_passes_one_loaded_struct_per_parameter() -> None:
    spec = emit_declarative_spec(
        "SELECT b.nm, COUNT(*) AS c FROM nation a, nation b WHERE a.reg = b.reg GROUP BY b.nm", SELF, SELF_CAT
    )
    program = assemble_declarative_program(spec, "    Vec::new()")
    assert "run_query(&cols_nation, &cols_nation)" in program
