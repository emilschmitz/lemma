"""Query templates in container runs: an experiment run names binding rules + seed; drive draws and records the per-round bindings."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import duckdb
import pytest

import lemma_config as lc
from declarative_spec import drive, templates
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

ROOT = Path(__file__).resolve().parents[1]
SQL = "-- params: lo BIGINT\nSELECT COUNT(*) AS c, SUM(x) AS s FROM t WHERE x > $lo"
RULES = {"tq": {"lo": {"kind": "int_range", "lo": "0", "hi": "9"}}}
EXP = """
[settings]
assumptions = true
official_rounds = 3
templates = true
[[run]]
model = "sonnet"
query = "tq.sql"
duckdb_path = "d.duckdb"
assumption_package = "p.json"
bindings_rules = "rules.json"
bindings_seed = {seed}
"""
EXP_PLAIN = EXP.split("bindings_rules")[0]  # the same run without the template keys


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for name in list(__import__("os").environ):
        if name.startswith("LEMMA_") and name not in ("LEMMA_ASSUMPTION_PACKAGE",):
            monkeypatch.delenv(name)
    root = tmp_path / "repo"
    (root / "configs" / "experiments").mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "tq.sql").write_text(SQL)
    (root / "p.json").write_text("{}")
    (root / "rules.json").write_text(json.dumps(RULES))
    (root / "configs" / "experiments" / "e.toml").write_text(EXP.format(seed=7))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "x")
    monkeypatch.setattr(lc, "REQUIRED", ())
    yield root
    lc.clear_experiment()


def _use(root: Path) -> None:
    lc.use_experiment("configs/experiments/e.toml", 0, root=root)


def test_same_seed_gives_the_same_bindings_and_another_seed_others(repo: Path) -> None:
    _use(repo)
    a = drive.template_bindings(SQL)
    assert a == drive.template_bindings(SQL)
    assert a["seed"] == 7 and a["rules"] == "rules.json" and a["rule_set"] == "tq"
    assert len(a["bindings"]) == 4  # official_rounds (3) + 1
    (repo / "configs" / "experiments" / "e.toml").write_text(EXP.format(seed=8))
    _use(repo)
    b = drive.template_bindings(SQL)
    assert b["bindings"] != a["bindings"] and b["seed"] == 8


def test_fixed_constant_sql_has_no_bindings(repo: Path) -> None:
    _use(repo)
    assert drive.template_bindings("SELECT COUNT(*) FROM t WHERE x > 3") is None


def test_a_params_header_without_rules_is_refused(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    lc.clear_experiment()  # a dev run: no experiment, so no rules
    with pytest.raises(ValueError, match="names no bindings_rules and bindings_seed"):
        drive.template_bindings(SQL)
    (repo / "configs" / "experiments" / "e.toml").write_text(EXP_PLAIN)
    _use(repo)
    with pytest.raises(ValueError, match="names no bindings_rules and bindings_seed"):
        drive.template_bindings(SQL)


def test_rules_without_an_entry_for_the_query_stem_are_refused(repo: Path) -> None:
    (repo / "rules.json").write_text(json.dumps({"other": RULES["tq"]}))
    _use(repo)
    with pytest.raises(ValueError, match="no rules for 'tq'"):
        drive.template_bindings(SQL)


def test_rules_and_seed_go_together_and_the_seed_is_an_integer(repo: Path) -> None:
    f = repo / "configs" / "experiments" / "bad.toml"
    base = 'model="a"\nquery="q"\nduckdb_path="d"\nassumption_package="p"\n'
    for body, msg in (
        (f"[settings]\nassumptions = true\n[[run]]\n{base}bindings_rules=\"r.json\"\n", "go together"),
        (f"[settings]\nassumptions = true\n[[run]]\n{base}bindings_seed=1\n", "go together"),
        (f"[settings]\nassumptions = true\n[[run]]\n{base}bindings_rules=\"r.json\"\nbindings_seed=\"1\"\n", "an integer"),
        (f"[settings]\nassumptions = true\n[[run]]\n{base}bindings_rules=\"r.json\"\nbindings_seed=true\n", "an integer"),
        (f"[settings]\nassumptions = true\n[[run]]\n{base}bindings_rules=\"/abs/r.json\"\nbindings_seed=1\n", "repo-relative"),
    ):
        f.write_text(body)
        with pytest.raises(lc.ConfigError, match=msg):
            lc.load_experiment(f, repo)


def test_an_untracked_or_modified_rules_file_makes_the_run_not_replicable(repo: Path) -> None:
    _git(repo, "rm", "-q", "--cached", "rules.json")
    _git(repo, "commit", "-qm", "untrack")
    _use(repo)
    with pytest.raises(lc.ConfigError, match="rules.json .*not tracked at HEAD"):
        lc.require_replicable(repo)
    _git(repo, "add", "rules.json")
    _git(repo, "commit", "-qm", "track")
    (repo / "rules.json").write_text(json.dumps({"tq": {"lo": {"kind": "int_range", "lo": "0", "hi": "99"}}}))
    _use(repo)
    with pytest.raises(lc.ConfigError, match="rules.json .*differs from its committed version"):
        lc.require_replicable(repo)


def test_the_run_without_template_keys_is_unchanged(repo: Path) -> None:
    (repo / "configs" / "experiments" / "e.toml").write_text(EXP_PLAIN)
    _use(repo)
    assert lc.experiment_bindings() is None


def _db(path: Path) -> Path:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (x BIGINT)")
    con.execute("INSERT INTO t SELECT i FROM range(1, 11) r(i)")
    con.close()
    return path


def test_drive_prepare_writes_template_bindings_to_expect_json_and_the_manifest(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    _use(repo)
    monkeypatch.setenv("LEMMA_MEASURE_DB", str(_db(tmp_path / "t.duckdb")))
    run_dir = tmp_path / "run"
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": "r"}))
    cat = CatalogAssumptions(max_rows=100, tables={"t": TableAssumptions(max_rows=100, columns={"x": ColumnAssumption(max_value_exclusive=1000)})})
    bins, bar = drive._maybe_large_table(sql_query=SQL, catalog=cat, workspace=workspace, schema={"t": {"x": "bigint"}})
    expected = drive.template_bindings(SQL)
    expect = json.loads((workspace / "decl_data" / "expect.json").read_text())
    assert expect["template_bindings"] == expected["bindings"] and len(expect["template_bindings"]) == 4
    assert bar["template_bindings"] == expected["bindings"] and bins is not None
    assert expect["binding_args"] == templates.binary_args(templates.parse_template(SQL), expected["bindings"][0])
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["template_bindings"] == expected and manifest["run_id"] == "r"


def test_drive_prepare_refuses_a_template_without_rules_before_any_data_is_written(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    lc.clear_experiment()
    monkeypatch.setenv("LEMMA_MEASURE_DB", str(_db(tmp_path / "t.duckdb")))
    workspace = tmp_path / "run" / "workspace"
    workspace.mkdir(parents=True)
    cat = CatalogAssumptions(max_rows=100, tables={"t": TableAssumptions(max_rows=100, columns={"x": ColumnAssumption(max_value_exclusive=1000)})})
    with pytest.raises(ValueError, match="names no bindings_rules"):
        drive._maybe_large_table(sql_query=SQL, catalog=cat, workspace=workspace, schema={"t": {"x": "bigint"}})
    assert not (workspace / "decl_data").exists()


def test_the_smoke_experiment_names_tracked_files_and_passes_the_file_checks() -> None:
    f = ROOT / "configs" / "experiments" / "tpch_sf10_templates_smoke.toml"
    settings, runs = lc.load_experiment(f, ROOT)
    assert settings["templates"] is True and len(runs) == 1
    assert runs[0]["bindings_seed"] == 1 and runs[0]["bindings_rules"] == "configs/query_templates/tpch/substitution.json"
    for key in ("query", "assumption_package", "bindings_rules"):
        rel = runs[0][key]
        assert subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True).returncode == 0, rel


def test_the_smoke_experiment_draws_valid_q06_bindings(monkeypatch: pytest.MonkeyPatch) -> None:
    f = ROOT / "configs" / "experiments" / "tpch_sf10_templates_smoke.toml"
    _, runs = lc.load_experiment(f, ROOT)
    rules = json.loads((ROOT / runs[0]["bindings_rules"]).read_text())[Path(runs[0]["query"]).stem]
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    t = templates.parse_template((ROOT / runs[0]["query"]).read_text())
    a = templates.generate_bindings(t, rules, 6, runs[0]["bindings_seed"])
    assert a == templates.generate_bindings(t, rules, 6, 1) and a != templates.generate_bindings(t, rules, 6, 2)
