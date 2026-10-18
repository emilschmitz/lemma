"""`LEMMA_EXAMPLES=none`: no example file is mounted and no prompt, lemma-index or hint text names one.

The docs, the spec, the skeleton and the host lemma index stay. The mode is not used by any run yet.
"""

from __future__ import annotations

import re

import pytest

from declarative_spec import principles as P
from declarative_spec.example_registry import UNMOUNTED
from declarative_spec.pipeline import PARALLEL_HINT_NONE
from declarative_spec.prompt import build_declarative_prompt, helper_files, mount_examples, registered_examples
from declarative_spec.trusted_sets import current as current_trusted_set
from tests.test_declarative_principles import _prompt_specs

pytestmark = pytest.mark.usefixtures("exact_division_off")  # the real-form AVG / ratio and f64 idealization (lemma.toml [sql] exact_division = false)


def test_none_mounts_nothing_at_all(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv(P.ENV, "none")
    mount_examples(tmp_path)
    assert list(tmp_path.rglob("*")) == []  # not even an empty examples directory


def test_none_mount_leaves_the_directory_it_is_given_untouched(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    (tmp_path / "keep.txt").write_text("x")
    monkeypatch.setenv(P.ENV, "none")
    mount_examples(tmp_path)
    assert [p.name for p in tmp_path.rglob("*")] == ["keep.txt"]


def test_none_prompts_hints_and_lemma_index_name_no_example_file(monkeypatch: pytest.MonkeyPatch) -> None:
    specs = _prompt_specs(monkeypatch)
    monkeypatch.setenv(P.ENV, "none")
    every_file = {*P.names(), *(n for n, _w in registered_examples()), *helper_files(), *UNMOUNTED}
    texts: dict[str, str] = {"parallel hint": PARALLEL_HINT_NONE}
    for name, (sql, spec) in specs.items():
        texts[f"prompt[{name}]"] = build_declarative_prompt(sql=sql, spec_path="s.rs", edit_path="e.rs", lemma_index="", spec_text=spec)
        texts[f"prompt[{name}] dict"] = build_declarative_prompt(
            sql=sql, spec_path="s.rs", edit_path="e.rs", lemma_index="", spec_text=spec, dict_sizes={"events.ev_kind": 6, "items.it_group": 4}
        )
        texts[f"lemma index[{name}]"] = current_trusted_set().index_markdown(spec)
    assert len(texts) > 6
    for label, text in texts.items():
        assert not re.search(r"context/ro/examples|(?<!verus/)(?<![\w/])examples/", text), label
        assert "examples/INDEX.md" not in text, label
        leaked = [f for f in every_file if f.split("/")[-1] in text]
        assert not leaked, (label, leaked[:5])


def test_none_keeps_the_spec_docs_and_helper_region_text(monkeypatch: pytest.MonkeyPatch) -> None:
    sql, spec = next(iter(_prompt_specs(monkeypatch).values()))
    monkeypatch.setenv(P.ENV, "none")
    p = build_declarative_prompt(sql=sql, spec_path="context/ro/spec.rs", edit_path="e.rs", lemma_index="LEMMA-INDEX-BODY", spec_text=spec)
    assert "context/ro/spec.rs" in p and "AGENT_HELPERS_START" in p and "LEMMA-INDEX-BODY" in p and "verus/INDEX.md" in p


def test_scrub_is_the_identity_outside_none(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "see `context/ro/examples/a.rs`\nplain line"
    for mode in ("full", "principles"):
        monkeypatch.setenv(P.ENV, mode)
        assert P.scrub(text) == text
    monkeypatch.setenv(P.ENV, "none")
    assert P.scrub(text) == "plain line"


def test_none_is_a_valid_value_and_a_typo_is_still_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(P.ENV, "none")
    assert P.mode() == "none" and P.examples_none() and P.principles_only()
    monkeypatch.setenv(P.ENV, "nonee")
    with pytest.raises(ValueError, match="'none'"):
        P.mode()
