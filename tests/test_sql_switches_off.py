"""The [sql] switches of lemma.toml: every new SQL shape is off by default, and off means main's emitter.

``tests/fixtures/tpch22`` holds the 22 TPC-H queries, the SF1 schema and the sha256 of the spec (or the refusal) that the
emitter of main produced for each with every [sql] switch off. Switch off must reproduce it byte for byte.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import lemma_config
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from research_loop.assumption_packages import assumption_package

FIXTURES = Path(__file__).parent / "fixtures" / "tpch22"
SQL_KEYS = ("agg_times_constant", "derived_agg_expr", "cte_reuse", "left_join_count")
SCHEMA = json.loads((FIXTURES / "schema.json").read_text())
GOLDEN = json.loads((FIXTURES / "emit_golden.json").read_text())
CATALOG = assumption_package("tpch_sf1")


def emit_tpch(name: str) -> str:
    return emit_declarative_spec((FIXTURES / f"{name}.sql").read_text().strip(), SCHEMA, CATALOG)


@pytest.mark.parametrize("key", SQL_KEYS)
def test_every_sql_switch_is_in_lemma_toml_and_off(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(lemma_config.env_name(key), raising=False)
    assert lemma_config.default(key) is False
    assert lemma_config.schema()[key][0] == "sql"
    assert lemma_config.get(key) is False


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_switches_off_emit_what_main_emitted(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in SQL_KEYS:
        monkeypatch.delenv(lemma_config.env_name(key), raising=False)
    want = GOLDEN[name]
    if "sha256" in want:
        assert hashlib.sha256(emit_tpch(name).encode()).hexdigest() == want["sha256"]
    else:
        with pytest.raises(DeclarativeUnsupported) as err:
            emit_tpch(name)
        assert " ".join(str(err.value).split())[:120] == want["refused"]


def test_the_switch_environment_variable_turns_a_shape_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_AGG_TIMES_CONSTANT", "1")
    assert lemma_config.get("agg_times_constant") is True
    monkeypatch.setenv("LEMMA_AGG_TIMES_CONSTANT", "0")
    assert lemma_config.get("agg_times_constant") is False
