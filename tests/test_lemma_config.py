"""lemma.toml / lemma_config: precedence, unknown variables, aliases, dirty tree, the recorded config, and the resolved conflicts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import lemma_config as lc

TOML = """
[run]
max_iterations = 2
join_chain = false
[measure]
official_rounds = 5
duck_memory_limit = "8GB"
[agent]
agent_timeout_sec = 750
[safety]
allow_dirty = false
scope_memory_max = "9G"
[prover]
verus_timeout_sec = 300
"""


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "lemma.toml"
    path.write_text(TOML)
    monkeypatch.setattr(lc, "TOML", path)
    monkeypatch.setattr(lc, "_warned", set())
    lc.clear_cli()
    for name in list(__import__("os").environ):
        if name.startswith("LEMMA_") or name in lc.ALIASES:
            monkeypatch.delenv(name)
    yield path
    lc.clear_cli()


def test_precedence_file_then_env_then_cli(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert lc.resolve("official_rounds").value == 5 and lc.resolve("official_rounds").source == "file"
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "7")
    s = lc.resolve("official_rounds")
    assert (s.value, s.source, s.origin) == (7, "env", "LEMMA_OFFICIAL_ROUNDS")
    lc.set_cli("official_rounds", 9, "--rounds")
    s = lc.resolve("official_rounds")
    assert (s.value, s.source, s.origin) == (9, "cli", "--rounds")


def test_the_env_name_is_one_rule_for_every_section(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, raw, want in (("max_iterations", "4", 4), ("join_chain", "1", True), ("duck_memory_limit", "4GB", "4GB"), ("allow_dirty", "true", True)):
        monkeypatch.setenv(f"LEMMA_{key.upper()}", raw)
        assert lc.get(key) == want
    assert lc.env_name("agent_timeout_sec") == "LEMMA_AGENT_TIMEOUT_SEC"


def test_an_empty_variable_is_unset(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "  ")
    assert lc.resolve("official_rounds").source == "file"


@pytest.mark.parametrize(("key", "raw"), [("official_rounds", "x"), ("join_chain", "maybe"), ("max_iterations", "0"), ("official_rounds", "2.5")])
def test_bad_values_fail_loudly(cfg: Path, monkeypatch: pytest.MonkeyPatch, key: str, raw: str) -> None:
    monkeypatch.setenv(f"LEMMA_{key.upper()}", raw)
    with pytest.raises(lc.ConfigError):
        lc.get(key)


def test_a_bad_cli_value_and_an_unknown_key_fail(cfg: Path) -> None:
    with pytest.raises(lc.ConfigError):
        lc.set_cli("no_such_key", 1)
    with pytest.raises(lc.ConfigError):
        lc.set_cli("join_chain", 1)  # an int is not a bool
    lc.set_cli("max_iterations", 0)
    with pytest.raises(lc.ConfigError):
        lc.get("max_iterations")


def test_unknown_lemma_variables_fail_at_startup_and_name_the_culprits(cfg: Path) -> None:
    env = {"LEMMA_OFFICIAL_ROUND": "5", "LEMMA_BOGUS": "1", "LEMMA_OFFICIAL_ROUNDS": "5", "HOME": "/x"}
    with pytest.raises(lc.ConfigError, match="LEMMA_BOGUS") as err:
        lc.check_environment(env)
    assert "LEMMA_OFFICIAL_ROUND'" in str(err.value) and "LEMMA_OFFICIAL_ROUNDS'" in str(err.value)  # the typo is listed, with its near miss
    lc.check_environment({"LEMMA_OFFICIAL_ROUNDS": "5", "LEMMA_MEASURE_DB": "/db", "PATH": "/bin"})  # known keys and host-set variables pass


def test_dead_settings_are_rejected_with_the_reason(cfg: Path) -> None:
    with pytest.raises(lc.ConfigError, match="no effect in a container run"):
        lc.check_environment({"LEMMA_SERIOUS": "1"})
    with pytest.raises(lc.ConfigError, match="AGENT_WEB_SEARCH"):
        lc.check_environment({"AGENT_WEB_SEARCH": "0"})


def test_an_old_spelling_works_with_a_deprecation_message(cfg: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("AGENT_TIMEOUT_SEC", "123")
    s = lc.resolve("agent_timeout_sec")
    assert (s.value, s.source, s.origin) == (123, "env", "AGENT_TIMEOUT_SEC")
    lc.get("agent_timeout_sec")
    err = capsys.readouterr().err
    assert err.count("DEPRECATED: AGENT_TIMEOUT_SEC") == 1 and "LEMMA_AGENT_TIMEOUT_SEC" in err  # once per name


def test_both_spellings_agree_or_fail(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERUS_VERIFY_TIMEOUT_SEC", "120")
    assert lc.get("verus_timeout_sec") == 120
    monkeypatch.setenv("LEMMA_VERUS_TIMEOUT_SEC", "120")
    assert lc.get("verus_timeout_sec") == 120
    monkeypatch.setenv("LEMMA_VERUS_TIMEOUT_SEC", "400")
    with pytest.raises(lc.ConfigError, match="conflicting spellings"):
        lc.get("verus_timeout_sec")


def test_unknown_or_duplicate_keys_in_the_file_fail(cfg: Path) -> None:
    cfg.write_text("[a]\nx = 1\n[b]\nx = 2\n")
    with pytest.raises(lc.ConfigError, match="unique across sections"):
        lc.schema()
    cfg.write_text("[a]\nx = [1]\n")
    with pytest.raises(lc.ConfigError, match="must be a bool"):
        lc.schema()
    cfg.write_text(TOML)
    with pytest.raises(lc.ConfigError, match="unknown setting"):
        lc.get("nope")


def test_duck_memory_must_stay_below_the_scope_cap(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lc.effective()
    monkeypatch.setenv("LEMMA_DUCK_MEMORY_LIMIT", "9GB")
    with pytest.raises(lc.ConfigError, match="below safety.scope_memory_max"):
        lc.effective()
    monkeypatch.setenv("LEMMA_DUCK_MEMORY_LIMIT", "6GB")
    monkeypatch.setenv("LEMMA_SCOPE_MEMORY_MAX", "6G")
    with pytest.raises(lc.ConfigError):
        lc.effective()


def _repo(tmp_path: Path) -> Path:
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"], ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("1")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=tmp_path, check=True)
    return tmp_path


def test_a_dirty_tracked_file_is_refused_and_untracked_data_is_fine(cfg: Path, tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r") if (tmp_path / "r").mkdir() is None else None
    assert repo is not None
    assert lc.require_clean_tree(repo)["git_dirty"] is False
    (repo / "data.bin").write_text("untracked, e.g. gitignored data")
    assert lc.require_clean_tree(repo)["git_dirty"] is False
    (repo / "a.txt").write_text("2")
    with pytest.raises(lc.ConfigError, match="uncommitted changes in tracked files"):
        lc.require_clean_tree(repo)


def test_allow_dirty_lets_a_dirty_tree_start_and_records_it(cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "r").mkdir()
    repo = _repo(tmp_path / "r")
    (repo / "a.txt").write_text("2")
    monkeypatch.setenv("LEMMA_ALLOW_DIRTY", "1")
    state = lc.require_clean_tree(repo)
    assert state["git_dirty"] is True and len(state["git_sha"]) == 40
    monkeypatch.delenv("LEMMA_ALLOW_DIRTY")
    monkeypatch.setenv("LEMMA_EXPERIMENT_ALLOW_DIRTY", "1")  # the old spelling is the same switch
    assert lc.require_clean_tree(repo)["git_dirty"] is True


def test_the_record_has_every_key_with_value_and_source_plus_git(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "3")
    lc.set_cli("max_iterations", 1, "--max-iterations")
    rec = lc.record()
    assert set(rec["config"]) == set(lc.schema()) and len(rec["git_sha"]) == 40 and isinstance(rec["git_dirty"], bool)
    assert rec["config"]["official_rounds"] == {"section": "measure", "value": 3, "source": "env", "origin": "LEMMA_OFFICIAL_ROUNDS"}
    assert rec["config"]["max_iterations"]["source"] == "cli" and rec["config"]["agent_timeout_sec"]["source"] == "file"
    json.dumps(rec)


def test_forwarding_passes_only_non_file_values_and_keeps_the_origin(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert lc.forwarded_env() == {}
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "3")
    lc.set_cli("max_iterations", 1)
    fwd = lc.forwarded_env()
    assert fwd["LEMMA_OFFICIAL_ROUNDS"] == "3" and fwd["LEMMA_MAX_ITERATIONS"] == "1"
    assert json.loads(fwd["LEMMA_CONFIG_ORIGIN"]) == {"official_rounds": "env", "max_iterations": "cli"}
    lc.clear_cli()
    for k, v in fwd.items():  # what the child sees: same values, the batch's flag reported as cli
        monkeypatch.setenv(k, v)
    assert lc.resolve("max_iterations").source == "cli" and lc.resolve("official_rounds").source == "env"


def test_export_env_makes_children_see_the_effective_values(cfg: Path) -> None:
    env: dict[str, str] = {"AGENT_TIMEOUT_SEC": "5"}
    lc.export_env(env)
    assert env["LEMMA_AGENT_TIMEOUT_SEC"] == "5" and "AGENT_TIMEOUT_SEC" not in env and env["LEMMA_JOIN_CHAIN"] == "false"


def test_export_keeps_the_source_of_every_value(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env: dict[str, str] = {"LEMMA_OFFICIAL_ROUNDS": "3"}
    lc.set_cli("max_iterations", 1, "--max-iterations")
    lc.export_env(env)
    lc.clear_cli()
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    got = {k: lc.resolve(k).source for k in ("official_rounds", "max_iterations", "agent_timeout_sec")}
    assert got == {"official_rounds": "env", "max_iterations": "cli", "agent_timeout_sec": "file"}  # exported, yet reported as they were


# --- the real lemma.toml: every resolved conflict has exactly one value ---


@pytest.fixture
def real(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lc, "TOML", Path(lc.__file__).resolve().parent / "lemma.toml")
    lc.clear_cli()
    for name in list(__import__("os").environ):
        if name.startswith("LEMMA_") or name in lc.ALIASES:
            monkeypatch.delenv(name)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("agent_timeout_sec", 1800), ("max_iterations", 2), ("verus_timeout_sec", 300), ("agent_data_mode", "none"), ("parallel_vstd", "auto"),
        ("duck_memory_limit", "8GB"), ("heavy_min_avail_mb", 4000), ("allow_dirty", False), ("scope_memory_max", "9G"),
    ],
)
def test_each_resolved_conflict_has_one_value(real: None, key: str, value: object) -> None:
    assert lc.get(key) == value


def test_the_real_file_is_valid_and_its_memory_budget_is_consistent(real: None) -> None:
    settings = lc.effective()
    assert len(settings) >= 40 and all(s.source == "file" for s in settings.values())
    lc.check_environment({})


# --- experiment files: the fourth source, and the replicable-run refusals ---

EXP = """
[settings]
official_rounds = 3
[[run]]
model = "sonnet"
query = "q1.sql"
duckdb_path = "data/x.duckdb"
assumption_package = "pkg/x.json"
"""


@pytest.fixture
def exp(cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A committed repo holding experiments/e.toml; returns the repo root."""
    root = tmp_path / "repo"
    (root / "experiments").mkdir(parents=True)
    repo = _repo(root)
    (repo / "experiments" / "e.toml").write_text(EXP)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "exp"], cwd=repo, check=True)
    monkeypatch.setattr(lc, "REQUIRED", ())
    yield repo
    lc.clear_experiment()


def test_experiment_sits_between_file_and_env_and_records_its_origin(exp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = lc.use_experiment("experiments/e.toml", 0, root=exp)
    assert run["model"] == "claude-sonnet-5-5"  # alias resolved
    s = lc.resolve("official_rounds")
    assert (s.value, s.source, s.origin) == (3, "experiment", "experiments/e.toml")
    assert lc._experiment["values"]["agent_model"] == "claude-sonnet-5-5" and lc._experiment["values"]["duckdb_path"] == str(exp / "data/x.duckdb")
    assert lc.resolve("max_iterations").source == "file"
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "7")
    assert lc.resolve("official_rounds").source == "env"
    lc.set_cli("official_rounds", 9)
    assert lc.resolve("official_rounds").source == "cli"
    monkeypatch.delenv("LEMMA_OFFICIAL_ROUNDS")
    lc.clear_cli()
    assert lc.effective_dict()["official_rounds"]["source"] == "experiment" and "LEMMA_OFFICIAL_ROUNDS" not in lc.forwarded_env()  # the child loads the file itself


def test_experiment_unknown_or_ill_typed_keys_fail(exp: Path) -> None:
    f = exp / "experiments" / "bad.toml"
    for body, msg in (
        ('[settings]\nofficial_roundz = 3\n[[run]]\nmodel="a"\nquery="q"\nduckdb_path="d"\nassumption_package="p"\n', "unknown setting"),
        ('[settings]\nofficial_rounds = "x"\n[[run]]\nmodel="a"\nquery="q"\nduckdb_path="d"\nassumption_package="p"\n', "must be a int"),
        ('[[run]]\nmodel="a"\nquery="q"\n', "exactly the string keys"),
        ('[settings]\nofficial_rounds = 3\n', "no \\[\\[run\\]\\]"),
    ):
        f.write_text(body)
        with pytest.raises(lc.ConfigError, match=msg):
            lc.load_experiment(f, exp)


def test_replicable_passes_on_a_clean_committed_tree(exp: Path) -> None:
    lc.use_experiment("experiments/e.toml", 0, root=exp)
    assert lc.require_replicable(exp) == lc._git(exp, "rev-parse", "HEAD")
    assert lc.experiment_record()["path"] == "experiments/e.toml"


def test_replicable_refuses_env_and_cli_overrides_and_names_the_keys(exp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lc.use_experiment("experiments/e.toml", 0, root=exp)
    monkeypatch.setenv("LEMMA_MAX_ITERATIONS", "4")
    with pytest.raises(lc.ConfigError, match="max_iterations"):
        lc.require_replicable(exp)
    monkeypatch.delenv("LEMMA_MAX_ITERATIONS")
    lc.set_cli("agent_timeout_sec", 5, "--t")
    with pytest.raises(lc.ConfigError, match="agent_timeout_sec"):
        lc.require_replicable(exp)


def test_replicable_refuses_untracked_and_modified_files(exp: Path) -> None:
    lc.use_experiment("experiments/e.toml", 0, root=exp)
    (exp / "stray.txt").write_text("x")
    with pytest.raises(lc.ConfigError, match="not clean.*stray.txt"):
        lc.require_replicable(exp)
    (exp / "stray.txt").unlink()
    (exp / "a.txt").write_text("changed")
    with pytest.raises(lc.ConfigError, match="not clean"):
        lc.require_replicable(exp)


def test_replicable_refuses_an_uncommitted_or_modified_experiment_file(exp: Path) -> None:
    (exp / "experiments" / "new.toml").write_text(EXP)
    lc.use_experiment("experiments/new.toml", 0, root=exp)
    with pytest.raises(lc.ConfigError, match="not committed"):
        lc.require_replicable(exp)
    lc.use_experiment("experiments/e.toml", 0, root=exp)
    (exp / "experiments" / "e.toml").write_text(EXP.replace("= 3", "= 4"))
    lc.use_experiment("experiments/e.toml", 0, root=exp)  # loaded with the edited blob...
    with pytest.raises(lc.ConfigError, match="differs from its committed version"):
        lc.require_replicable(exp)


def test_replicable_refuses_when_head_moved_from_the_pin(exp: Path) -> None:
    pin = lc._git(exp, "rev-parse", "HEAD")
    lc.use_experiment("experiments/e.toml", 0, pin, exp)
    lc.require_replicable(exp)
    (exp / "a.txt").write_text("2")
    subprocess.run(["git", "commit", "-qam", "later"], cwd=exp, check=True)
    with pytest.raises(lc.ConfigError, match="pinned at"):
        lc.require_replicable(exp)
