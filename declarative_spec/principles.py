"""The principles example set (`LEMMA_EXAMPLES=principles`): small verified bodies on an INVENTED schema, one technique each.

The full set (`LEMMA_EXAMPLES` unset or `full`) mounts every registered fixture, among them bodies for the benchmark queries themselves.
With `LEMMA_EXAMPLES=principles` the agent gets no benchmark query as an example: only the files below, on an invented
event-log schema (`events`, `items`, `users`) whose names appear in no TPC-H, SSB or SEC table. Each file is a `run_query` body that Verus
verified against the spec this module's `sql` emits over this module's `SCHEMA` and `catalog()`, and that the compiled program turns into
the same rows as DuckDB (tests/test_declarative_principles.py).
"""

from __future__ import annotations

import lemma_config
import re
from dataclasses import dataclass, field
from pathlib import Path

from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

ENV = lemma_config.env_name("examples")
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "declarative_proofs" / "principles"

SCHEMA: dict[str, dict[str, str]] = {
    "events": {
        "ev_user": "bigint",
        "ev_item": "bigint",
        "ev_kind": "varchar",
        "ev_qty": "bigint",
        "ev_cost": "decimal(12,2)",
        "ev_day": "bigint",
        "ev_score": "bigint",
    },
    "items": {"it_id": "bigint", "it_group": "varchar", "it_shelf": "bigint"},
    "users": {"us_id": "bigint", "us_region": "varchar", "us_level": "bigint"},
}


def catalog() -> CatalogAssumptions:
    """Caps for the invented tables (tiny, so the host check can load them; the bodies do not depend on the numbers)."""
    col = ColumnAssumption
    return CatalogAssumptions(
        max_rows=16,
        tables={
            "events": TableAssumptions(
                max_rows=16,
                columns={
                    "ev_user": col(max_value_exclusive=1000),
                    "ev_item": col(max_value_exclusive=1000),
                    "ev_kind": col(max_string_len=8, max_distinct=6),
                    "ev_qty": col(max_value_exclusive=1000),
                    "ev_cost": col(max_value_exclusive=10**6, scale=2),
                    "ev_day": col(max_value_exclusive=400),
                    "ev_score": col(max_value_exclusive=1000, nullable=True),
                },
            ),
            "items": TableAssumptions(
                max_rows=8,
                unique_keys=(("it_id",),),
                columns={
                    "it_id": col(max_value_exclusive=1000),
                    "it_group": col(max_string_len=8, max_distinct=4),
                    "it_shelf": col(max_value_exclusive=50),
                },
            ),
            "users": TableAssumptions(
                max_rows=8,
                unique_keys=(("us_id",),),
                columns={
                    "us_id": col(max_value_exclusive=1000),
                    "us_region": col(max_string_len=8, max_distinct=4),
                    "us_level": col(max_value_exclusive=10),
                },
            ),
        },
    )


@dataclass(frozen=True)
class Principle:
    file: str  # under tests/fixtures/declarative_proofs/principles/
    sql: str
    teaches: str  # one line for INDEX.md
    env: dict[str, str] = field(default_factory=dict)  # extra flags the spec is emitted under (besides the ones every principle uses)


# Flags every principle is emitted and verified under (the container run's flags).
BASE_ENV = {"LEMMA_STRING_ENCODING": "dict", "LEMMA_JOIN_CHAIN": "1"}

PRINCIPLES: tuple[Principle, ...] = (
    Principle(
        "scan_filter_sum_count.rs",
        "SELECT COUNT(*) AS n, SUM(ev_qty) AS q, SUM(ev_cost) AS c FROM events WHERE ev_qty > 2 AND ev_cost <= 50.00",
        "filtered scan, COUNT and SUM over an integer and a DECIMAL (scaled integer) column; suffix-fold invariants, `i128` accumulators bounded by the cell caps, SUM of no rows is NULL",
    ),
    Principle(
        "group_by_dict_key.rs",
        "SELECT ev_kind, COUNT(*) AS n, SUM(ev_qty) AS q FROM events WHERE ev_day >= 30 GROUP BY ev_kind",
        "GROUP BY a dictionary-coded string key: one dense slot per code, every slot equals the host fold for its key, emit the nonzero slots with a ghost index",
    ),
    Principle(
        "join_unique_lookup.rs",
        "SELECT COUNT(*) AS n, SUM(ev_qty) AS q FROM events, items WHERE ev_item = it_id AND it_shelf < 20",
        "equi-join on a UNIQUE key as a lookup: index the dimension table once (`key + offset -> row + 1`), scan the fact table and probe it; the host's per-row chain lemma replaces counting matches (LEMMA_JOIN_CHAIN=1)",
    ),
    Principle(
        "star_join_group_by.rs",
        "SELECT it_group, SUM(ev_qty) AS q FROM events, items, users WHERE ev_item = it_id AND ev_user = us_id AND us_level >= 3 GROUP BY it_group",
        "fact table plus TWO unique-key dimensions, GROUP BY a dimension's dictionary string; two probe indexes, dense slots over the group codes, the host's grouped-result closing lemmas (LEMMA_JOIN_CHAIN=1)",
    ),
    Principle(
        "top_n_with_ties.rs",
        "SELECT ev_qty, ev_user FROM events WHERE ev_qty > 1 ORDER BY ev_qty DESC LIMIT 3",
        "ORDER BY ... LIMIT: a sorted streaming top-N (insert before the first smaller row, pop the overflow), with the spec's tie rule for omitted rows that tie the last kept one",
    ),
    Principle(
        "parallel_scan_sum.rs",
        "SELECT SUM(ev_qty) AS q FROM events WHERE ev_day >= 100",
        "PARALLEL scan with vstd threads: split the rows across 8 workers over a shared `Arc`, per-worker partial folds that telescope, merge in order (LEMMA_PARALLEL_VSTD=on)",
        {"LEMMA_PARALLEL_VSTD": "on"},
    ),
    Principle(
        "null_skipping_aggregate.rs",
        "SELECT COUNT(*) AS m, COUNT(ev_score) AS n, SUM(ev_score) AS s FROM events WHERE ev_day > 3",
        "NULL-skipping aggregates over a nullable column (validity vector): COUNT(*) vs COUNT(col), SUM over no valid cell is NULL",
    ),
)

# The principle that stands in for a full-set example a prompt or lemma-index sentence used to cite (None: the sentence has no principles counterpart and is dropped).
STAND_IN: dict[str, str | None] = {
    "parallel_ungrouped_sum.rs": "parallel_scan_sum.rs",
    "dict_group_count_dense.rs": "group_by_dict_key.rs",
    "dict_string_filter_minmax.rs": "scan_filter_sum_count.rs",
}


def mode() -> str:
    return lemma_config.get("examples")


# Every prompt section has a kind; the examples mode decides which kinds are emitted (declarative_spec/prompt.py tags each section).
TASK, RULES, TOOLS, LIMITS, HARDWARE, RECIPE, EXAMPLE_POINTER = "task", "rules", "tools", "limits", "hardware", "recipe", "example-pointer"
KINDS = (TASK, RULES, TOOLS, LIMITS, HARDWARE, RECIPE, EXAMPLE_POINTER)
_PLAIN_KINDS = (TASK, RULES, TOOLS, LIMITS, HARDWARE)


def kinds_emitted() -> tuple[str, ...]:
    """full: everything (as before). principles: everything, the recipes and pointers being their principles variants (the section
    builders choose those). none: no technique recipe and no pointer to an example, only the task, rules, tools, limits and hardware."""
    return _PLAIN_KINDS if mode() == "none" else KINDS


def examples_none() -> bool:
    """`LEMMA_EXAMPLES=none`: no example file is mounted and no prompt, lemma-index or hint text names one."""
    return mode() == "none"


def principles_only() -> bool:
    """True when no benchmark-shaped example may be cited: `principles`, and also `none` (which then drops every citation, see ``scrub``)."""
    return mode() in ("principles", "none")


# Our example directory, however a sentence spells it. Verus's own `verus/examples` is documentation and stays.
_EXAMPLE_REF = re.compile(r"context/ro/examples|(?<![\w/])examples/(?:INDEX|\w+\.rs|hard/)|\.helpers\.rs")


def scrub(text: str) -> str:
    """In `none` mode, drop every line that names an example file (`.../examples/...`); otherwise the text unchanged."""
    if not examples_none():
        return text
    return "\n".join(ln for ln in text.split("\n") if not _EXAMPLE_REF.search(ln))


def names() -> list[str]:
    return [p.file for p in PRINCIPLES]


def example_ref(full_set_file: str) -> str | None:
    """The file a sentence should cite: `full_set_file` in the full set, its principles stand-in (or None) in principles mode."""
    return full_set_file if not principles_only() else STAND_IN.get(Path(full_set_file).name)


def cite(full_set_file: str, *, lead: str = "") -> str:
    """`lead` + a back-quoted `context/ro/examples/<file>` path for the sentence, or "" when principles mode has no stand-in."""
    ref = example_ref(full_set_file)
    return "" if ref is None or examples_none() else f"{lead}`context/ro/examples/{ref}`"


def index_markdown() -> str:
    rows = [f"| {p.teaches} | `{p.file}` | {len((FIXTURES / p.file).read_text().splitlines())} |" for p in PRINCIPLES]
    return "\n".join(
        [
            "# Worked examples: seven small techniques",
            "",
            "These are NOT examples of your query. Each file is a `run_query` body (plus helpers) that Verus verified against a tiny spec on an unrelated",
            "event-log schema (`events`, `items`, `users`); it teaches ONE technique. Your tables, columns, caps and SQL differ: read the files whose technique",
            "your spec needs, then combine and adapt them (rename, redo the arithmetic for YOUR caps, change the filter). The header comment of each file says what to take.",
            "A query usually needs several of them at once; each file's header says what to take.",
            "",
            "| technique | file | lines |",
            "|---|---|---|",
            *rows,
            "",
        ]
    )


def mount(dest: Path) -> None:
    """Write the principles set and its INDEX.md to `dest` (the `context/ro/examples` directory) and fail loudly when anything else is in it.

    Nothing is deleted: a directory that already holds other files (a full-set mount from an earlier run) is an error, not something this quietly cleans up."""
    dest.mkdir(parents=True, exist_ok=True)
    wanted = {*names(), "INDEX.md"}
    stale = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file() and str(p.relative_to(dest)) not in wanted)
    if stale:
        raise RuntimeError(f"{dest} holds files that are not in the principles set ({stale[:5]}...): mount into a fresh workspace")
    for name in names():
        (dest / name).write_text((FIXTURES / name).read_text())
    (dest / "INDEX.md").write_text(index_markdown())
