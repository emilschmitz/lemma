"""Menu profiles: every axis, the style group, the trusted_set registry, loud failures, recording."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from research_loop import menu_profile as mp
from research_loop.spec_styles import DECLARATIVE, ENV_VALUE, IMPERATIVE
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions
from research_loop.trust_configs import get_config

_AXIS_ENV = [
    "LEMMA_MENU", "LEMMA_SPEC_STYLE", "LEMMA_TRUSTED_SET", "LEMMA_ASSUMPTION_PACKAGE",
    "LEMMA_SPEED_BAR_MULT", "LEMMA_AGENT_MODEL", "LEMMA_MENU_ALLOW_OVERRIDE", "LEMMA_TRUST_CONFIG",
    "LEMMA_FAST_TRUSTEDS", "LEMMA_ENABLE_PARALLEL", "LEMMA_ENABLE_VECTOR_SCAN",
    "LEMMA_ENABLE_SPILL_HASH", "LEMMA_FOLD_SLOT_AXIOMATIC", "LEMMA_EXACT_SUM",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch):
    mp.deactivate_menu()
    for key in _AXIS_ENV:
        monkeypatch.delenv(key, raising=False)
    yield
    mp.deactivate_menu()


# --- every profile activates and sets its env ---


@pytest.mark.parametrize("name", sorted(mp.PROFILES))
def test_every_profile_activates_and_sets_its_env_then_restores(name: str) -> None:
    profile = mp.PROFILES[name]
    resolved = mp.activate_menu(name)
    assert resolved.style == profile.style and resolved.trusted_set == profile.trusted_set
    assert os.environ["LEMMA_MENU"] == name
    assert os.environ["LEMMA_SPEC_STYLE"] == ENV_VALUE[profile.style]
    assert os.environ["LEMMA_TRUSTED_SET"] == profile.trusted_set
    trust = get_config(mp.TRUSTED_SETS[profile.trusted_set].trust)
    for key, val in trust.env.items():
        if key != "LEMMA_SPEC_STYLE":
            assert os.environ[key] == val
    mp.deactivate_menu()
    assert "LEMMA_MENU" not in os.environ and "LEMMA_SPEC_STYLE" not in os.environ


def test_profiles_pair_rocketship_with_product_flags_and_declarative_with_its_own() -> None:
    mp.activate_menu("rocketship")
    assert os.environ["LEMMA_TRUST_CONFIG"] == "product" and os.environ["LEMMA_FAST_TRUSTEDS"] == "0"
    mp.deactivate_menu()
    mp.activate_menu("fast")
    assert os.environ["LEMMA_FAST_TRUSTEDS"] == "1"
    mp.deactivate_menu()
    mp.activate_menu("adversary_imperativespec0")
    assert os.environ["LEMMA_EXACT_SUM"] == "1"
    mp.deactivate_menu()
    mp.activate_menu("adversary_declarative0")
    assert os.environ["LEMMA_SPEED_BAR_MULT"] == "1.0"
    assert os.environ["LEMMA_SPEC_STYLE"] == ENV_VALUE[DECLARATIVE]


# --- the style group moves together ---


def test_style_group_selects_different_existing_functions_per_style() -> None:
    imp = mp.style_group_for(mp.resolve_menu("rocketship"))
    dec = mp.style_group_for(mp.resolve_menu("adversary_declarative0"))
    assert imp.emitter.__name__ == "transpile_sql_to_verus"
    assert dec.emitter.__name__ == "emit_declarative_spec"
    assert imp.assembler.__name__ == "assemble_verified_program"
    assert dec.assembler.__name__ == "assemble_declarative_program"
    assert imp.admission.__name__ == "admit_runquery_body"
    assert dec.admission.__name__ == "admit_declarative_body"
    assert imp.workspace.prompt.__name__ == "build_agent_prompt"
    assert dec.workspace.prompt.__name__ == "build_declarative_prompt"
    assert dec.workspace.mount.__name__ == "mount_verus_docs"
    assert imp.workspace.mount.__name__ == "_mount_none"
    assert imp.measure is not dec.measure


def test_admission_rules_differ_per_style() -> None:
    imp = mp.style_group_for(mp.resolve_menu("rocketship")).admission
    dec = mp.style_group_for(mp.resolve_menu("adversary_declarative0")).admission
    assert dec("").violations == ["empty agent body"]
    assert imp is not dec


# --- unknown and incompatible selections fail loudly ---


def test_unknown_menu_fails_loudly() -> None:
    with pytest.raises(ValueError, match="unknown menu 'nope'"):
        mp.activate_menu("nope")


def test_recursive_is_rejected_as_renamed_and_unknown_style_too() -> None:
    from research_loop.spec_styles import check_style, style_from_env

    with pytest.raises(ValueError, match="renamed to 'imperative'"):
        check_style("recursive")
    with pytest.raises(ValueError, match="unknown style"):
        check_style("sideways")
    with pytest.raises(ValueError, match="unknown LEMMA_SPEC_STYLE"):
        style_from_env("sideways")


@pytest.mark.parametrize(
    ("menu", "trusted"),
    [("adversary_declarative0", "fast"), ("adversary_declarative0", "rocketship"), ("rocketship", "declarative_default")],
)
def test_trusted_set_of_the_wrong_style_fails_even_with_allow_override(menu: str, trusted: str) -> None:
    with pytest.raises(ValueError, match="belongs to the"):
        mp.resolve_menu(menu, flags={"trusted_set": trusted}, allow_override=True)


def test_unknown_trusted_set_fails() -> None:
    with pytest.raises(ValueError, match="unknown trusted_set 'nope'"):
        mp.resolve_menu("rocketship", flags={"trusted_set": "nope"}, allow_override=True)


# --- each axis switchable alone, on top of a profile ---


def test_catalog_axis_alone_needs_no_override_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "sec_margin_dec")
    resolved = mp.resolve_menu("adversary_declarative0")
    assert resolved.values["assumption_package"] == "sec_margin_dec"
    assert resolved.sources["assumption_package"] == "override LEMMA_ASSUMPTION_PACKAGE"
    assert resolved.sources["style"] == "profile"


def test_trusted_set_axis_alone_within_the_style() -> None:
    with pytest.raises(ValueError, match="contradicts the profile value"):
        mp.resolve_menu("rocketship", flags={"trusted_set": "fast"})
    resolved = mp.resolve_menu("rocketship", flags={"trusted_set": "fast"}, allow_override=True)
    assert resolved.trusted_set == "fast" and resolved.style == IMPERATIVE
    assert resolved.sources["trusted_set"] == "override --trusted-set"
    assert resolved.sources["agent"] == "profile"


def test_agent_axis_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="contradicts the profile value"):
        mp.resolve_menu("rocketship", flags={"agent": "claude-haiku-4-5-20251001"})
    resolved = mp.resolve_menu("rocketship", flags={"agent": "claude-haiku-4-5-20251001"}, allow_override=True)
    assert resolved.values["agent"] == "claude-haiku-4-5-20251001" and resolved.trusted_set == "rocketship"
    same = mp.resolve_menu("adversary_declarative0", flags={"agent": "claude-haiku-4-5-20251001"})
    assert same.sources["agent"].startswith("profile (confirmed by")


def test_speed_bar_axis_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_SPEED_BAR_MULT", "2.0")
    with pytest.raises(ValueError, match="contradicts the profile value"):
        mp.resolve_menu("adversary_declarative0")
    monkeypatch.setenv("LEMMA_MENU_ALLOW_OVERRIDE", "1")
    resolved = mp.resolve_menu("adversary_declarative0")
    assert resolved.values["speed_bar_mult"] == "2.0"
    assert resolved.values["trusted_set"] == "declarative_default"


def test_style_override_contradicting_the_profile_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_SPEC_STYLE", ENV_VALUE[IMPERATIVE])
    with pytest.raises(ValueError):
        mp.resolve_menu("adversary_declarative0", allow_override=True)  # style flips -> wrong trusted set
    with pytest.raises(ValueError, match="contradicts the profile value"):
        mp.resolve_menu("adversary_declarative0")


def test_conflicting_overrides_of_one_axis_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "a")
    with pytest.raises(ValueError, match="conflicting overrides"):
        mp.resolve_menu("rocketship", flags={"assumption_package": "b"})


# --- the resolved selection is correct, printed and recorded ---


def test_resolved_summary_lists_every_axis_with_its_source(capsys: pytest.CaptureFixture[str]) -> None:
    os.environ["LEMMA_ASSUMPTION_PACKAGE"] = "prove_loop"
    mp.activate_menu("adversary_declarative0")
    out = capsys.readouterr().out
    for axis in mp.AXES:
        assert axis in out
    assert "declarative_default" in out and "[profile]" in out
    assert "prove_loop" in out and "[override LEMMA_ASSUMPTION_PACKAGE]" in out
    os.environ.pop("LEMMA_ASSUMPTION_PACKAGE")


def test_resolved_selection_is_written_into_the_run_manifest(tmp_path: Path) -> None:
    from research_loop.run_artifacts import begin_run

    mp.activate_menu("adversary_declarative0")
    run = begin_run(query_id=1, sql_query="SELECT 1", root=tmp_path)
    manifest = json.loads((run.path / "manifest.json").read_text())
    axes = manifest["menu"]["axes"]
    assert manifest["menu"]["menu"] == "adversary_declarative0"
    assert axes["style"] == {"value": DECLARATIVE, "source": "profile"}
    assert axes["trusted_set"]["value"] == "declarative_default"
    assert manifest["env"]["LEMMA_MENU"] == "adversary_declarative0"


def test_manifest_menu_is_null_without_a_profile(tmp_path: Path) -> None:
    from research_loop.run_artifacts import begin_run

    run = begin_run(query_id=2, sql_query="SELECT 1", root=tmp_path)
    assert json.loads((run.path / "manifest.json").read_text())["menu"] is None


# --- the production loop picks the profile up from LEMMA_MENU ---


def test_production_loop_picks_up_lemma_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    from db_extension.optimizer import run_optimization_loop

    recorded: list[dict] = []

    def _fake_drive(**kwargs):
        recorded.append(kwargs)
        return {"status": "FAILED", "error": "stopped", "history": []}

    monkeypatch.setattr("declarative_spec.drive.run_declarative_optimization_loop", _fake_drive)
    monkeypatch.setenv("LEMMA_MENU", "adversary_declarative0")  # no LEMMA_SPEC_STYLE set
    result = run_optimization_loop(
        "SELECT k, COUNT(*) AS cnt FROM t GROUP BY k", schema={"t": {"k": "bigint"}}, use_mock=True,
        max_iterations=1,
    )
    assert recorded and result["error"] == "stopped"
    assert mp.active_menu().menu == "adversary_declarative0"


def test_production_loop_rejects_a_menu_that_contradicts_an_explicit_style(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from db_extension.optimizer import run_optimization_loop

    monkeypatch.setenv("LEMMA_MENU", "rocketship")
    monkeypatch.setenv("LEMMA_SPEC_STYLE", "declarative")
    with pytest.raises(ValueError, match="contradicts the profile value"):
        run_optimization_loop("SELECT 1", use_mock=True, max_iterations=1)


# --- trusted_set is a real selectable piece: spec text and lemma index move together ---

_ALT_LEMMAS = "// ALT_TRUSTED_MARKER\nproof fn lemma_alt_only() {}"
_ALT_INDEX = "# ALT index\n- `lemma_alt_only()`\n"


@pytest.fixture
def alt_trusted_set(monkeypatch: pytest.MonkeyPatch):
    from declarative_spec import trusted_sets as ts

    monkeypatch.setitem(ts.TRUSTED_SETS, "alt", ts.TrustedSet("alt", lambda: _ALT_LEMMAS, lambda: _ALT_INDEX))
    monkeypatch.setitem(
        mp.TRUSTED_SETS, "alt", mp.TrustedSetEntry(DECLARATIVE, "adversary_declarative0", lambda: ts.get("alt"))
    )
    monkeypatch.setitem(
        mp.PROFILES, "alt_menu", mp.MenuProfile("alt_menu", DECLARATIVE, "alt", "claude-haiku-4-5-20251001")
    )


def _spec() -> str:
    from declarative_spec.emit import emit_declarative_spec

    catalog = CatalogAssumptions(tables={"t": TableAssumptions(max_rows=64)})
    return emit_declarative_spec("SELECT k, COUNT(*) AS cnt FROM t GROUP BY k", {"t": {"k": "ubigint"}}, catalog)


def test_default_trusted_set_spec_and_index_are_unchanged() -> None:
    from declarative_spec.lemma_index import lemma_index_markdown
    from declarative_spec.trusted_sets import current

    spec = _spec()
    assert "lemma_u64_add_fits" in spec and "ALT_TRUSTED_MARKER" not in spec
    assert current().index_markdown() == lemma_index_markdown()


def test_swapping_the_trusted_set_changes_spec_text_and_lemma_index_together(alt_trusted_set) -> None:
    from declarative_spec.admit import host_names
    from declarative_spec.trusted_sets import current

    mp.activate_menu("alt_menu")
    spec = _spec()
    host = spec.split("// HOST_LEMMAS_START")[1].split("// HOST_LEMMAS_END")[0]
    assert "ALT_TRUSTED_MARKER" in host and "lemma_u64_add_fits" not in host
    assert current().index_markdown() == _ALT_INDEX
    assert "lemma_alt_only" in host_names(spec)  # admission knows the host names of the active set


def test_unknown_trusted_set_key_fails_loudly_in_the_declarative_registry() -> None:
    from declarative_spec import trusted_sets as ts

    with pytest.raises(KeyError, match="unknown declarative trusted_set 'nope'"):
        ts.get("nope")
    mp.activate_menu("rocketship")  # an imperative trusted set is not a declarative one
    with pytest.raises(KeyError, match="unknown declarative trusted_set 'rocketship'"):
        ts.current()
