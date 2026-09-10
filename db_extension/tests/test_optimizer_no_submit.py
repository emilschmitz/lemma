"""Post-agent path must not assemble leftover runquery without a marked submit."""
from __future__ import annotations

from db_extension.optimizer import should_assemble_leftover_after_agent


def test_should_assemble_leftover_mock_always_true() -> None:
    assert should_assemble_leftover_after_agent(use_mock=True, submitted=None) is True
    assert should_assemble_leftover_after_agent(use_mock=True, submitted={"ok": True}) is True


def test_should_assemble_leftover_non_mock_requires_submit() -> None:
    assert should_assemble_leftover_after_agent(use_mock=False, submitted=None) is False
    assert should_assemble_leftover_after_agent(use_mock=False, submitted={"ok": True}) is True
