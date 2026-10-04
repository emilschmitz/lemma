"""Run the real Claude Code sandbox path against the local mock model API (no credentials).

Usage: ``claude_mock_e2e.py [ok|hang]``. Runs ladder query 1 (a generated group-count) with
``claude-haiku-4-5-20251001`` through ``run_agent_docker``: real image, real entrypoint, real MCP
socket, real egress bridge. Only the model is the mock. See research_loop/AGENT_SANDBOX.md.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.agent_sandbox import MOCK_CA_ENV, MOCK_PORT_ENV
from research_loop.scripts.mock_anthropic_api import Conversation, Hang, MockAnthropic, make_ca

PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
DUMMY_KEY = "test-key-not-real"


def group_count_body(table: str, column: str) -> str:
    """Verus-verified reference body for ``SELECT <column>, COUNT(*) FROM <table> GROUP BY <column>`` (ubigint)."""
    body = (PROOFS / "u64_group_count_t_k.rs").read_text()
    body = body.replace("valid_cols_t", f"valid_cols_{table}").replace("ROW_CAP_t", f"ROW_CAP_{table}")
    return re.sub(r"cols\.k@", f"cols.{column}@", body)


@contextmanager
def mock_model(conversation: Conversation, directory: Path):
    """Start the mock and point the next ``run_agent_docker`` at it (env only, restored on exit)."""
    cert, key = make_ca(directory)
    log = directory / "mock_requests.jsonl"
    saved = {k: os.environ.get(k) for k in (MOCK_PORT_ENV, MOCK_CA_ENV, "ANTHROPIC_API_KEY")}
    with MockAnthropic(conversation, cert, key, log) as mock:
        os.environ[MOCK_PORT_ENV] = str(mock.port)
        os.environ[MOCK_CA_ENV] = str(cert)
        os.environ["ANTHROPIC_API_KEY"] = DUMMY_KEY
        try:
            yield log
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def main(scenario: str) -> int:
    from research_loop.scripts.declarative_ladder import run_ladder

    # Ladder query 1: SELECT bucket, COUNT(*) AS c FROM src GROUP BY bucket
    conversation = {"ok": Conversation, "hang": Hang}[scenario](group_count_body("src", "bucket"))
    with tempfile.TemporaryDirectory() as tmp, mock_model(conversation, Path(tmp)) as log:
        records = run_ladder("claude-haiku-4-5-20251001", indices=(1,))
        print(f"MOCK_REQUESTS {log.read_text()}")
    print(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "ok"))
