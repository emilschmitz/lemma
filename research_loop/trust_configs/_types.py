from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrustConfig:
    name: str
    transpiler: str
    note: str
    env: dict[str, str]
    assumption_package: str | None
