from __future__ import annotations

import subprocess

from declarative_spec import prompt


def test_section_has_lscpu_and_guidance() -> None:
    text = "\n".join(prompt.hardware_section())
    assert "## Hardware" in text and ("Model name" in text or "unavailable" in text) and "PHYSICAL core" in text or "unavailable" in text


def test_section_says_unavailable_when_lscpu_fails(monkeypatch) -> None:
    def boom(*a, **k):
        raise OSError("no lscpu")

    monkeypatch.setattr(subprocess, "run", boom)
    assert "hardware info unavailable" in "\n".join(prompt.hardware_section())
