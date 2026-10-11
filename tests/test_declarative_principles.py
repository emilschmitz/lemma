"""`LEMMA_EXAMPLES=principles`: the container agent gets no benchmark query as an example, only seven small technique examples.

* Each principles body is verified by Verus (memory-guarded, rlimit as the repo default) against the spec its SQL emits over the invented
  `events` / `items` / `users` schema, mutated bodies are rejected, and the compiled program returns the same rows as DuckDB on a tiny synthetic table.
* LEAKAGE: in principles mode no mounted example (nor INDEX.md) contains a table or column name of the TPC-H, SSB or SEC schemas, the prompt, the lemma index
  and the error hints name no benchmark query and cite no example outside the principles set, and the default (full) mode is unchanged.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import duckdb
import pytest

from declarative_spec import principles as P
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.bench import load_speed_bar, rows_from_stdout_general, rows_match_error
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.pipeline import run_declarative_metrics, verify_assembled
from declarative_spec.prompt import build_declarative_prompt, mount_examples
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from declarative_spec.trusted_sets import current as current_trusted_set

ROOT = Path(__file__).resolve().parents[1]
VERUS = Path("/home/emil/tools/verus/verus")
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
BY_FILE = {p.file: p for p in P.PRINCIPLES}


def _flags(monkeypatch: pytest.MonkeyPatch, principle: P.Principle) -> None:
    for key, val in {**P.BASE_ENV, **principle.env}.items():
        monkeypatch.setenv(key, val)
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))


def _spec(principle: P.Principle) -> str:
    return emit_declarative_spec(principle.sql, P.SCHEMA, P.catalog())


def _verify(principle: P.Principle, monkeypatch: pytest.MonkeyPatch, mutate: tuple[str, str] | None = None) -> tuple[bool, str]:
    _flags(monkeypatch, principle)
    text = (P.FIXTURES / principle.file).read_text()
    if mutate is not None:
        assert mutate[0] in text, mutate[0]
        text = text.replace(*mutate, 1)
    program = assemble_declarative_program(_spec(principle), extract_agent_edit(text), helpers=extract_agent_helpers(text))
    return verify_assembled(program, timeout_sec=600)


# ---- the set itself ----------------------------------------------------------------------------------------------------


def test_the_set_is_seven_files_and_each_is_on_disk() -> None:
    assert len(P.PRINCIPLES) == 7 and len({p.file for p in P.PRINCIPLES}) == 7
    assert {f.name for f in P.FIXTURES.glob("*.rs")} == set(P.names())


def test_the_flag_defaults_to_full_and_a_bad_value_is_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(P.ENV, raising=False)
    assert P.mode() == "full" and not P.principles_only()
    monkeypatch.setenv(P.ENV, "principles")
    assert P.principles_only()
    monkeypatch.setenv(P.ENV, "everything")
    with pytest.raises(ValueError, match="examples must be one of"):
        P.mode()


# ---- Verus --------------------------------------------------------------------------------------------------------------


@needs_verus
@pytest.mark.parametrize("name", sorted(BY_FILE))
def test_principle_verifies(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify(BY_FILE[name], monkeypatch)
    assert ok and re.search(r"verification results:: \d+ verified, 0 errors", out), out[-2500:]


_MUTATIONS = {
    "scan_filter_sum_count.rs": ("let hit = q > 2 && c <= 5000;", "let hit = q > 2 && c <= 5001;"),
    "group_by_dict_key.rs": ("let hit = events.ev_day[i] >= 30;", "let hit = events.ev_day[i] >= 31;"),
    "join_unique_lookup.rs": ("if shelf < 20 {", "if shelf < 21 {"),
    "star_join_group_by.rs": ("if users.us_level[rb] >= 3 {", "if users.us_level[rb] >= 2 {"),
    "top_n_with_ties.rs": ("res[p].ev_qty >= a\n", "res[p].ev_qty <= a\n"),
    "parallel_scan_sum.rs": ("if d >= 100 {\n                            acc = acc + (v as i128);", "if d >= 101 {\n                            acc = acc + (v as i128);"),
    "null_skipping_aggregate.rs": ("            if valid {\n                cn = cn + 1;", "            if !valid {\n                cn = cn + 1;"),
}


@needs_verus
@pytest.mark.parametrize("name", sorted(_MUTATIONS))
def test_a_wrong_body_is_rejected(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify(BY_FILE[name], monkeypatch, _MUTATIONS[name])
    assert not ok and re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out), out[-1500:]


# ---- the compiled program returns DuckDB's rows -------------------------------------------------------------------------

_USERS = [(1, "north", 1), (2, "south", 3), (3, "north", 3), (4, "east", 9), (5, "south", 2)]
_ITEMS = [(3, "toys", 5), (5, "food", 25), (7, "toys", 19), (11, "tools", 20), (13, "food", 3), (17, "tools", 40)]
# (user, item, kind, qty, cost, day, score): item 99 and user 9 have no dimension row; four rows tie at qty 9; boundaries at cost 50.00, day 3 / 30 / 100; NULL scores
_EVENTS = [
    (1, 3, "view", 4, "12.50", 31, 5),
    (2, 5, "buy", 2, "50.00", 30, None),
    (3, 7, "buy", 9, "50.01", 100, 7),
    (4, 11, "like", 9, "49.99", 99, 3),
    (5, 13, "view", 9, "5.00", 101, None),
    (1, 99, "buy", 6, "10.00", 200, 2),
    (2, 17, "share", 1, "75.25", 3, 8),
    (3, 3, "buy", 3, "20.00", 4, 9),
    (4, 5, "view", 7, "30.00", 150, None),
    (5, 7, "like", 3, "40.00", 30, 1),
    (2, 11, "buy", 9, "45.00", 120, 6),
    (9, 13, "view", 5, "8.00", 50, 4),
    (3, 17, "buy", 2, "60.00", 3, None),
    (4, 13, "share", 8, "50.00", 250, 10),
]


def _tiny_db(path: Path) -> Path:
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE events (ev_user BIGINT, ev_item BIGINT, ev_kind VARCHAR, ev_qty BIGINT, ev_cost DECIMAL(12,2), ev_day BIGINT, ev_score BIGINT)"
    )
    con.execute("CREATE TABLE items (it_id BIGINT, it_group VARCHAR, it_shelf BIGINT)")
    con.execute("CREATE TABLE users (us_id BIGINT, us_region VARCHAR, us_level BIGINT)")
    con.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)", _EVENTS)
    con.executemany("INSERT INTO items VALUES (?, ?, ?)", _ITEMS)
    con.executemany("INSERT INTO users VALUES (?, ?, ?)", _USERS)
    con.close()
    return path


def test_the_synthetic_table_fits_the_catalog() -> None:
    """The caps the bodies were proved under (row caps, cell caps, distinct caps, unique keys) hold for the host-check data."""
    cat = P.catalog()
    rows = {"events": _EVENTS, "items": _ITEMS, "users": _USERS}
    for table, data in rows.items():
        assert len(data) <= cat.tables[table].max_rows
    assert len({r[0] for r in _ITEMS}) == len(_ITEMS) and len({r[0] for r in _USERS}) == len(_USERS)
    assert len({r[2] for r in _EVENTS}) <= cat.tables["events"].columns["ev_kind"].max_distinct
    assert len({r[1] for r in _ITEMS}) <= cat.tables["items"].columns["it_group"].max_distinct


@needs_verus
@pytest.mark.parametrize("name", sorted(BY_FILE))
def test_principle_returns_the_rows_duckdb_returns(name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from research_loop.decl_query_measure import write_query_measure

    principle = BY_FILE[name]
    _flags(monkeypatch, principle)
    db = _tiny_db(tmp_path / "tiny.duckdb")
    prepared = write_query_measure(sql=principle.sql, schema=P.SCHEMA, catalog=P.catalog(), db_path=db, dest=tmp_path / "data")
    assert prepared["rows"], "the synthetic table must give the query a non-empty answer"
    # the prepared data (column files, dictionary sizes, expected rows) is what `run_runquery` loads; the speed verdict is switched off (a 14-row table is not a timing)
    monkeypatch.setenv("LEMMA_SPEED_BAR_MULT", "0.000001")
    bins, bar = load_speed_bar(tmp_path / "data")
    metrics = run_declarative_metrics(
        spec_rs=_spec(principle), agent_source=(P.FIXTURES / name).read_text(), work_dir=tmp_path / "run", column_bins=bins, speed_bar=bar
    )
    assert metrics["proof_verified"], str(metrics.get("compiler_error"))[-2500:]
    assert metrics["status"] == "SUCCESS", metrics.get("compiler_error")
    got = rows_from_stdout_general(metrics["stdout"])
    err = rows_match_error(got, prepared["rows"], prepared["kinds"], prepared["order_cols"], prepared["limited"], prepared["tie_rows"])
    assert err is None, (err, got, prepared["rows"])


# ---- leakage: examples ---------------------------------------------------------------------------------------------------

# The TPC-H schema from the specification (the assumption package tpch_sf1 lists the same names; it is not tracked in every checkout).
_TPCH = {
    "part": "p_partkey p_name p_mfgr p_brand p_type p_size p_container p_retailprice p_comment",
    "supplier": "s_suppkey s_name s_address s_nationkey s_phone s_acctbal s_comment",
    "partsupp": "ps_partkey ps_suppkey ps_availqty ps_supplycost ps_comment",
    "customer": "c_custkey c_name c_address c_nationkey c_phone c_acctbal c_mktsegment c_comment",
    "orders": "o_orderkey o_custkey o_orderstatus o_totalprice o_orderdate o_orderpriority o_clerk o_shippriority o_comment",
    "lineitem": "l_orderkey l_partkey l_suppkey l_linenumber l_quantity l_extendedprice l_discount l_tax l_returnflag l_linestatus l_shipdate l_commitdate l_receiptdate l_shipinstruct l_shipmode l_comment",
    "nation": "n_nationkey n_name n_regionkey n_comment",
    "region": "r_regionkey r_name r_comment",
}


def _package_tables(name: str) -> dict[str, list[str]]:
    from research_loop.assumption_packages import REGISTRY_DIR

    path = REGISTRY_DIR / f"{name}.json"
    if not path.is_file():  # an untracked package of the main checkout, when this is a worktree
        path = Path(os.environ.get("LEMMA_MAIN_CHECKOUT", "/home/emil/projects/lemma-db")) / "research_loop" / "assumption_packages" / "registry" / f"{name}.json"
    if not path.is_file():
        return {}
    return {t: list(v.get("columns", {})) for t, v in json.loads(path.read_text())["tables"].items()}


def benchmark_names() -> set[str]:
    """Every table and column name of the TPC-H, SSB and SEC schemas (lowercase)."""
    from research_loop.scripts.sqlsmith_trusted_coverage import _load_sec_schema_sql

    names: set[str] = set()
    for table, cols in _load_sec_schema_sql().items():
        names |= {table, *cols}
    for table, cols in _TPCH.items():
        names |= {table, *cols.split()}
    for package in ("tpch_sf1", "ssb_sf1"):
        for table, cols in _package_tables(package).items():
            names |= {table, *cols}
    return {n.lower() for n in names}


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)}


def test_the_name_list_covers_all_three_benchmarks() -> None:
    names = benchmark_names()
    assert {"lineitem", "l_shipdate", "p_brand", "lo_revenue", "d_year", "c_nation", "adsh", "uom", "ddate", "stmt"} <= names
    assert len(names) > 150


def test_no_mounted_example_names_a_benchmark_table_or_column(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(P.ENV, "principles")
    mount_examples(tmp_path)
    mounted = sorted(f for f in (tmp_path / "examples").rglob("*") if f.is_file())
    assert {f.name for f in mounted} == {*P.names(), "INDEX.md"}
    names = benchmark_names()
    for f in mounted:
        leaked = _tokens(f.read_text()) & names
        assert not leaked, (f.name, sorted(leaked))
        assert not _QUERY_NAMES.findall(f.read_text()), (f.name, _QUERY_NAMES.findall(f.read_text()))  # no "SSB Q4.1" / "TPC-H Q1" labels in INDEX.md or a header


def test_the_principles_schema_shares_no_name_with_a_benchmark() -> None:
    mine = {t.lower() for t in P.SCHEMA} | {c.lower() for cols in P.SCHEMA.values() for c in cols}
    assert not mine & benchmark_names()


def test_mounting_over_another_mount_is_an_error_not_a_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "tpch_q3_join_group_topk.rs").write_text("// a full-set file\n")
    monkeypatch.setenv(P.ENV, "principles")
    with pytest.raises(RuntimeError, match="not in the principles set"):
        mount_examples(tmp_path)
    assert (tmp_path / "examples" / "tpch_q3_join_group_topk.rs").is_file()  # nothing was deleted


def test_the_full_mode_still_mounts_the_whole_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(P.ENV, raising=False)
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    mount_examples(tmp_path)
    mounted = {str(f.relative_to(tmp_path / "examples")) for f in (tmp_path / "examples").rglob("*.rs")}
    assert len(mounted) > 40 and "tpch_q3_join_group_topk.rs" in mounted and "hard/dict_parallel_q1.rs" in mounted
    assert not set(P.names()) & mounted  # the principles files are only mounted in principles mode


# ---- leakage: prompt, lemma index, hints --------------------------------------------------------------------------------

_QUERY_NAMES = re.compile(r"TPC-?H|\bSSB\b|\bGenDB\b|\bEDGAR\b|\bQ\d{1,3}(?:\.\d)?\b|\bQ\d-class\b|\bsf1\b", re.I)
# names that are not ordinary English words: a prompt sentence using one is naming a benchmark table or column
_DISTINCTIVE = {n for n in benchmark_names() if "_" in n} | {
    "lineitem", "lineorder", "partsupp", "adsh", "ddate", "qtrs", "uom", "cik", "stmt", "rfile", "plabel", "tlabel", "afs", "sic", "prevrpt", "coreg", "crdr",
}
# SEC names that are short or plain words but are not used as such in a prompt (a hit means an example sentence still carries a SEC table or column)
_SEC_EXTRA = {"pre", "num", "uom", "tag", "plabel", "adsh"}
_PROBES = {
    "grouped_topn": "SELECT it_group, SUM(ev_qty) AS q FROM events, items WHERE ev_item = it_id GROUP BY it_group ORDER BY q DESC LIMIT 2",
    "distinct": "SELECT it_group, COUNT(DISTINCT ev_user) AS u FROM events, items WHERE ev_item = it_id GROUP BY it_group",
    "float": "SELECT SUM(ev_ratio) AS r FROM events WHERE ev_day > 3",
    "projection_join": "SELECT ev_user, it_group FROM events, items WHERE ev_item = it_id",
    "two_string_keys": "SELECT ev_kind, it_group, COUNT(*) AS n FROM events, items WHERE ev_item = it_id GROUP BY ev_kind, it_group",
    "plain_count": "SELECT ev_user, COUNT(*) AS n FROM events GROUP BY ev_user",
}


def _probe_catalog():
    """The principles catalog plus a capped DOUBLE column, so a float query emits (only the prompt probes use it)."""
    import dataclasses

    from research_loop.table_assumptions import ColumnAssumption

    cat = P.catalog()
    events = cat.tables["events"]
    events = dataclasses.replace(events, columns={**events.columns, "ev_ratio": ColumnAssumption(max_value_exclusive=1000)})
    return dataclasses.replace(cat, tables={**cat.tables, "events": events})


def _prompt_specs(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[str, str]]:
    """name -> (sql, emitted spec) for the seven principles and the probes that reach prompt sections the seven do not."""
    schema = {**P.SCHEMA, "events": {**P.SCHEMA["events"], "ev_ratio": "double"}}
    out: dict[str, tuple[str, str]] = {}
    for p in P.PRINCIPLES:
        for k, v in {**P.BASE_ENV, **p.env}.items():
            monkeypatch.setenv(k, v)
        out[p.file] = (p.sql, emit_declarative_spec(p.sql, schema, _probe_catalog()))
        monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "off")
    for k, v in P.BASE_ENV.items():
        monkeypatch.setenv(k, v)
    for name, sql in _PROBES.items():
        out[name] = (sql, emit_declarative_spec(sql, schema, _probe_catalog()))
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "on")
    out["parallel_group"] = (_PROBES["plain_count"], emit_declarative_spec(_PROBES["plain_count"], schema, _probe_catalog()))
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "off")
    return out


def _agent_texts(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    from declarative_spec.pipeline import PARALLEL_HINT_PRINCIPLES

    monkeypatch.setenv(P.ENV, "principles")
    texts: dict[str, str] = {"parallel hint": PARALLEL_HINT_PRINCIPLES}
    for name, (sql, spec) in _prompt_specs(monkeypatch).items():
        texts[f"prompt[{name}]"] = build_declarative_prompt(sql=sql, spec_path="s.rs", edit_path="e.rs", lemma_index="", spec_text=spec)
        texts[f"prompt[{name}] with dictionary sizes"] = build_declarative_prompt(
            sql=sql, spec_path="s.rs", edit_path="e.rs", lemma_index="", spec_text=spec, dict_sizes={"events.ev_kind": 6, "items.it_group": 4}
        )
        texts[f"lemma index[{name}]"] = current_trusted_set().index_markdown(spec)
    return texts


def test_principles_prompts_and_lemma_index_name_no_benchmark_query(monkeypatch: pytest.MonkeyPatch) -> None:
    for where, text in _agent_texts(monkeypatch).items():
        found = _QUERY_NAMES.findall(text)
        assert not found, (where, found, [ln for ln in text.splitlines() if _QUERY_NAMES.search(ln)][:3])
        leaked = (_tokens(text) & _DISTINCTIVE) | (_tokens(text) & _SEC_EXTRA)
        assert not leaked, (where, sorted(leaked))


def test_principles_prompts_cite_only_principles_files(monkeypatch: pytest.MonkeyPatch) -> None:
    allowed = {*P.names(), "INDEX.md"}
    for where, text in _agent_texts(monkeypatch).items():
        cited = set(re.findall(r"context/ro/examples/([\w/]+\.(?:rs|md))", text))
        assert cited <= allowed, (where, sorted(cited - allowed))
        # the other file names an example sentence can carry without the directory prefix
        bare = {m for m in re.findall(r"`((?:hard/)?[\w]+\.rs)`", text) if m.startswith(("dict_", "parallel_", "tpch_", "float_", "hard/", "projection_", "group_", "join_", "ungrouped_"))}
        assert bare <= allowed, (where, sorted(bare - allowed))


def test_the_principles_prompt_points_at_the_index_and_the_seven_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(P.ENV, "principles")
    sql, spec = _prompt_specs(monkeypatch)["star_join_group_by.rs"]
    text = build_declarative_prompt(sql=sql, spec_path="s.rs", edit_path="e.rs", lemma_index="", spec_text=spec)
    assert "context/ro/examples/INDEX.md" in text and "seven small" in text
    assert "join_unique_lookup.rs" in text and "star_join_group_by.rs" in text  # the chain section and the closing-lemma section name the matching principle


def test_the_full_prompt_is_unchanged_in_default_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(P.ENV, raising=False)
    for k, v in P.BASE_ENV.items():
        monkeypatch.setenv(k, v)
    spec = emit_declarative_spec(BY_FILE["group_by_dict_key.rs"].sql, P.SCHEMA, P.catalog())
    text = build_declarative_prompt(sql="select 1", spec_path="s.rs", edit_path="e.rs", lemma_index="", spec_text=spec)
    assert "dict_group_count_dense.rs" in text and "seven small" not in text
    from declarative_spec import prompt as prompt_mod

    assert prompt_mod._hygiene_text() is prompt_mod._PROOF_HYGIENE and prompt_mod._speed_text() is prompt_mod._SPEED and prompt_mod._do_not_text() is prompt_mod._DO_NOT
    assert "key_at(pre, i0)" in text and "uom = 'pure'" in text
    assert "context/ro/examples/INDEX.md" in text


def test_the_flag_reaches_the_container_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts import container_batch as cb

    monkeypatch.delenv(P.ENV, raising=False)
    assert not any(c.startswith("--setenv=LEMMA_EXAMPLES") for c in cb.command("claude-sonnet-5-5", Path("/q.sql")))
    monkeypatch.setenv(P.ENV, "principles")
    assert "--setenv=LEMMA_EXAMPLES=principles" in cb.command("claude-sonnet-5-5", Path("/q.sql"))
