"""ORDER BY ... LIMIT with a sort-key tie across the cut: the row check accepts any choice among the tied rows, nothing else."""

import duckdb

from declarative_spec.bench import rows_match_error
from research_loop.decl_query_measure import _tie_group

OUT = [("a", "String"), ("b", "i64")]
KINDS = ["str", "int"]


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t(a VARCHAR, b BIGINT, c BIGINT)")
    con.execute("INSERT INTO t VALUES ('x',1,1),('x',2,2),('y',3,3),('y',3,4),('y',3,5),('z',9,6)")
    return con


def _hex(s: str) -> str:
    return s.encode().hex()


def test_tie_across_the_cut_is_found_and_other_choices_pass() -> None:
    con = _con()
    rows = [["x", 1], ["x", 2], ["y", 3]]
    tie = _tie_group(con, "SELECT a, b FROM t ORDER BY b LIMIT 3", rows, OUT, None, KINDS)
    assert tie is not None and tie["k"] == 1 and len(tie["pool"]) == 3 and tie["key_cols"] == [1]
    got = [[_hex("x"), "1"], [_hex("x"), "2"], [_hex("y"), "3"]]
    assert rows_match_error(got, rows, KINDS, tie) is None


def test_a_wrong_row_before_the_cut_or_a_row_outside_the_group_fails() -> None:
    con = _con()
    rows = [["x", 1], ["x", 2], ["y", 3]]
    tie = _tie_group(con, "SELECT a, b FROM t ORDER BY b LIMIT 3", rows, OUT, None, KINDS)
    assert rows_match_error([[_hex("x"), "1"], [_hex("z"), "9"], [_hex("y"), "3"]], rows, KINDS, tie)
    assert rows_match_error([[_hex("x"), "1"], [_hex("x"), "2"], [_hex("z"), "9"]], rows, KINDS, tie)


def test_no_tie_no_limit_or_unmapped_order_key_stays_exact() -> None:
    con = _con()
    assert _tie_group(con, "SELECT a, b FROM t ORDER BY b LIMIT 2", [["x", 1], ["x", 2]], OUT, None, KINDS) is None
    assert _tie_group(con, "SELECT a, b FROM t ORDER BY b", [["x", 1]], OUT, None, KINDS) is None
    assert _tie_group(con, "SELECT a, b FROM t ORDER BY c LIMIT 3", [["x", 1], ["x", 2], ["y", 3]], OUT, None, KINDS) is None


def test_qualified_order_term_never_maps_to_an_alias() -> None:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE u(x BIGINT, y BIGINT, n VARCHAR)")
    con.execute("INSERT INTO u VALUES (1,5,'a'),(2,5,'b'),(3,5,'c')")
    out = [("x", "i64"), ("n", "String")]
    # `u.x` is the table column (unique), the alias x = y+0 ties: the true result is fully determined, so no tie may be reported
    rows = [[5, "a"], [5, "b"]]
    assert _tie_group(con, "SELECT y+0 AS x, n FROM u ORDER BY u.x LIMIT 2", rows, out, None, ["int", "str"]) is None


def test_desc_multi_key_ties_only_in_the_last_group_and_group_size_is_pinned() -> None:
    con = _con()
    rows = [["z", 9], ["y", 3], ["y", 3]]
    tie = _tie_group(con, "SELECT a, b FROM t ORDER BY b DESC, a DESC LIMIT 3", rows, OUT, None, KINDS)
    assert tie is not None and tie["k"] == 2 and len(tie["pool"]) == 3 and tie["key_cols"] == [1, 0]
    assert rows_match_error([[_hex("z"), "9"], [_hex("y"), "3"], [_hex("y"), "3"]], rows, KINDS, tie) is None
    assert rows_match_error([[_hex("z"), "9"], [_hex("y"), "3"], [_hex("x"), "2"]], rows, KINDS, tie)
