"""The generated spec carries the query as a comment directly above ``run_query``."""

import pytest

from declarative_spec.emit import with_sql_comment
from declarative_spec.parse import DeclarativeUnsupported

SPEC = "verus! {\n// AGENT_HELPERS_END\npub fn run_query(t: &Cols_t) -> (res: u64)\n{\n}\n}\n"


def test_sql_lines_sit_verbatim_above_run_query():
    sql = "SELECT sum(x)\nFROM t\nWHERE x > 5"
    out = with_sql_comment(SPEC, sql)
    head, _, _ = out.partition("pub fn run_query(")
    assert head.endswith("// SQL (the query this spec states):\n//     SELECT sum(x)\n//     FROM t\n//     WHERE x > 5\n")
    assert out.count("pub fn run_query(") == 1 and out.replace(head, "") == SPEC.partition("// AGENT_HELPERS_END\n")[2]


def test_every_added_line_is_a_comment_and_nothing_else_changes():
    sql = "  select a, b from t where s = 'x;y' \n  order by a  "
    out = with_sql_comment(SPEC, sql)
    added = [line for line in out.splitlines() if line not in SPEC.splitlines()]
    assert added and all(line.startswith("//") for line in added)
    assert [line for line in out.splitlines() if not line.startswith("// SQL") and not line.startswith("//     ")] == SPEC.splitlines()


@pytest.mark.parametrize("marker", ["AGENT_EDIT_START", "HOST_LEMMAS_END"])
def test_sql_that_mentions_a_region_marker_is_refused(marker):
    with pytest.raises(DeclarativeUnsupported):
        with_sql_comment(SPEC, f"SELECT 1 -- {marker}")
