"""ORDER BY keys that tie at a LIMIT cut: DuckDB and the proved binary may keep different tied rows; both are valid SQL answers.

Found on arena r1_q01 (2026-10-06): 67 verified, 0 errors eleven times, every run rejected for 'result rows differ' with equal sort keys at every position."""

from __future__ import annotations

from declarative_spec.bench import order_info, rows_match_error

KINDS = ["str", "int", "str"]


def _hex(s: str) -> str:
    return s.encode().hex()


def _got(rows: list[tuple[str, int, str]]) -> list[list[str]]:
    return [[_hex(a), str(b), _hex(c)] for a, b, c in rows]


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
    assert rows_match_error(_got(other), EXPECT, KINDS, [0, 1], True) is None


def test_it_still_refuses_a_wrong_row_a_wrong_key_or_a_missing_limit_flag() -> None:
    cols = [0, 1]
    wrong_head = [("a", 1, "x"), ("a", 1, "WRONG"), ("b", 2, "p"), ("b", 2, "q")]
    assert rows_match_error(_got(wrong_head), EXPECT, KINDS, cols, True) is not None  # an earlier tie group must match as a multiset
    wrong_key = [("a", 1, "x"), ("a", 1, "y"), ("b", 3, "p"), ("b", 2, "q")]
    assert rows_match_error(_got(wrong_key), EXPECT, KINDS, cols, True) is not None  # the sort keys must agree position by position
    other = [("a", 1, "y"), ("a", 1, "x"), ("b", 2, "q"), ("b", 2, "zz")]
    assert rows_match_error(_got(other), EXPECT, KINDS, cols, False) is not None  # no LIMIT: the strict check
    assert rows_match_error(_got(other), EXPECT, KINDS, None, True) is not None  # ORDER BY keys unknown: the strict check


def test_the_cut_is_only_assumed_when_the_result_is_full() -> None:
    """A result shorter than its LIMIT was not cut: its last tie group must match exactly (drive.py sets `limited` only when len(rows) == LIMIT)."""
    from declarative_spec import drive

    assert order_info("SELECT name FROM t ORDER BY name LIMIT 7")["limit"] == 7
    src = open(drive.__file__).read()
    assert 'info.get("limit") == len(prepared["rows"])' in src
