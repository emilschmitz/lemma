"""Post-agent host must not assemble leftover runquery without a marked submit."""
from __future__ import annotations

from db_extension.agent import measure_core as mc
from db_extension.optimizer import post_agent_next_step, should_assemble_leftover_after_agent


def test_should_assemble_leftover_only_when_mock() -> None:
    assert should_assemble_leftover_after_agent(use_mock=True, submitted=None) is True
    assert should_assemble_leftover_after_agent(use_mock=False, submitted=None) is False
    body = "fn"
    submitted = {"ok": True, "runquery_body": body, "runquery_sha256": mc.runquery_sha256(body)}
    assert should_assemble_leftover_after_agent(use_mock=False, submitted=submitted) is False


def test_post_agent_next_step_real_agent_paths() -> None:
    assert post_agent_next_step(use_mock=False, submitted=None) == "no_submit_fail"
    body = "fn"
    submitted = {"ok": True, "runquery_body": body, "runquery_sha256": mc.runquery_sha256(body)}
    assert post_agent_next_step(use_mock=False, submitted=submitted) == "official_measure"
    assert post_agent_next_step(use_mock=True, submitted=None) == "assemble_leftover"
