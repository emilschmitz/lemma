"""ORDER BY keys that tie at a LIMIT cut: DuckDB and the proved binary may keep different tied rows; both are valid SQL answers.

Found on arena r1_q01 (2026-10-06): 67 verified, 0 errors eleven times, every run rejected for 'result rows differ' with equal sort keys at every position."""

from __future__ import annotations

from declarative_spec.bench import order_info, rows_match_error

KINDS = ["str", "int", "str"]


def _hex(s: str) -> str:
    return s.encode().hex()


def _got(rows: list[tuple[str, int, str]]) -> list[list[str]]:
    return [[_hex(a), str(b), _hex(c)] for a, b, c in rows]


TIES = [["b", 2, "p"], ["b", 2, "q"], ["b", 2, "zz"]]  # every (b, 2) row DuckDB has without the LIMIT
EXPECT = [("a", 1, "x"), ("a", 1, "y"), ("b", 2, "p"), ("b", 2, "q")]  # the cut falls inside the last (b, 2) tie group of a longer answer


def test_order_info_maps_order_by_items_to_output_positions() -> None:
    assert order_info("SELECT name, line, label FROM t ORDER BY name, line LIMIT 4") == {"order_cols": [0, 1], "limited": True, "limit": 4}
    assert order_info("SELECT s.name AS n, t.line FROM t s JOIN u t ON 1=1 ORDER BY t.line, n LIMIT 5")["order_cols"] == [1, 0]
    assert order_info("SELECT name, line FROM t ORDER BY 2 DESC LIMIT 5")["order_cols"] == [1]
    assert order_info("SELECT name, line FROM t ORDER BY name") == {"order_cols": None, "limited": False}  # no LIMIT: nothing is cut
    assert order_info("SELECT name, line FROM t ORDER BY line + 1 LIMIT 3") == {"order_cols": None, "limited": True, "limit": 3}  # an expression of its own: stay strict


def test_a_different_choice_inside_the_group_the_limit_cuts_is_accepted() -> None:
    other = [("a", 1, "y"), ("a", 1, "x"), ("b", 2, "q"), ("b", 2, "zz")]  # tied head group reordered; the cut group keeps another member
    assert rows_match_error(_got(other), EXPECT, KINDS) is not None  # the strict check refuses it
    assert rows_match_error(_got(other), EXPECT, KINDS, [0, 1], True, TIES) is None


def test_it_still_refuses_a_wrong_row_a_wrong_key_or_a_missing_limit_flag() -> None:
    cols = [0, 1]
    wrong_head = [("a", 1, "x"), ("a", 1, "WRONG"), ("b", 2, "p"), ("b", 2, "q")]
    assert rows_match_error(_got(wrong_head), EXPECT, KINDS, cols, True, TIES) is not None  # an earlier tie group must match as a multiset
    wrong_key = [("a", 1, "x"), ("a", 1, "y"), ("b", 3, "p"), ("b", 2, "q")]
    assert rows_match_error(_got(wrong_key), EXPECT, KINDS, cols, True, TIES) is not None  # the sort keys must agree position by position
    other = [("a", 1, "y"), ("a", 1, "x"), ("b", 2, "q"), ("b", 2, "zz")]
    assert rows_match_error(_got(other), EXPECT, KINDS, cols, False, TIES) is not None  # no LIMIT: the strict check
    assert rows_match_error(_got(other), EXPECT, KINDS, None, True, TIES) is not None  # ORDER BY keys unknown: the strict check


def test_the_cut_is_only_assumed_when_the_result_is_full() -> None:
    """A result shorter than its LIMIT was not cut: its last tie group must match exactly."""
    from declarative_spec.bench import cut_applies

    info = order_info("SELECT name FROM t ORDER BY name LIMIT 7")
    assert info["limit"] == 7 and cut_applies(info, 7) and not cut_applies(info, 6)
    assert not cut_applies(order_info("SELECT name FROM t ORDER BY name"), 7)


def test_the_last_group_must_be_members_of_the_full_tie_group_each_used_once() -> None:
    cols = [0, 1]
    not_a_member = [("a", 1, "x"), ("a", 1, "y"), ("b", 2, "p"), ("b", 2, "NOT IN DUCKDB")]
    assert rows_match_error(_got(not_a_member), EXPECT, KINDS, cols, True, TIES) is not None
    twice = [("a", 1, "x"), ("a", 1, "y"), ("b", 2, "zz"), ("b", 2, "zz")]  # one DuckDB row cannot be returned twice
    assert rows_match_error(_got(twice), EXPECT, KINDS, cols, True, TIES) is not None
    assert rows_match_error(_got([("b", 2, "q"), ("b", 2, "zz")]), [("b", 2, "p"), ("b", 2, "q")], KINDS, cols, True, TIES) is None  # a single-group result is still checked
    assert rows_match_error(_got([("b", 2, "q"), ("b", 2, "bad")]), [("b", 2, "p"), ("b", 2, "q")], KINDS, cols, True, TIES) is not None
    assert rows_match_error(_got([("b", 2, "q"), ("b", 2, "zz")]), [("b", 2, "p"), ("b", 2, "q")], KINDS, cols, True, None) is not None  # no tie rows computed: strict


def test_an_output_alias_wins_over_an_underlying_column_of_the_same_name() -> None:
    assert order_info("SELECT a AS b, b AS a FROM t ORDER BY a LIMIT 3")["order_cols"] == [1]  # `a` is the SECOND output column's alias
    assert order_info("SELECT x AS c, c AS x FROM t ORDER BY c LIMIT 3")["order_cols"] == [0]


def test_the_tie_group_is_computed_from_duckdb_without_the_limit() -> None:
    import duckdb

    from research_loop.decl_query_measure import _tie_group_rows

    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES ('a', 1, 'x'), ('b', 2, 'p'), ('b', 2, 'q'), ('b', 2, 'zz'), ('c', 3, 'w')) v(name, line, label)")
    sql = "SELECT name, line, label FROM t ORDER BY name, line LIMIT 3"
    rows = [["a", 1, "x"], ["b", 2, "p"], ["b", 2, "q"]]
    fields = [("name", "String"), ("line", "i64"), ("label", "String")]
    got = _tie_group_rows(con, sql, rows, fields, None)
    assert sorted(map(tuple, got)) == [("b", 2, "p"), ("b", 2, "q"), ("b", 2, "zz")]
    assert _tie_group_rows(con, sql, rows[:2], fields, None) is None  # fewer rows than the LIMIT: nothing was cut
    assert _tie_group_rows(con, "SELECT name FROM t ORDER BY name", rows, fields, None) is None
