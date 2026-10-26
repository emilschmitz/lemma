"""Run the real Claude Code sandbox path against the local mock model API (no credentials).

Usage: ``claude_mock_e2e.py [ok|hang]``. Runs ladder query 1 (a generated group-count) with
``claude-haiku-4-5-20251001`` through ``run_agent_docker``: real image, real entrypoint, real MCP
socket, real egress bridge. Only the model is the mock. See research_loop/AGENT_SANDBOX.md.
"""

from __future__ import annotations

import json
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
    # Counting in a Vec of KEY_CAP slots (the shape that beats DuckDB's speed bar), not a HashMap.
    body = (PROOFS / "u64_group_count_slots_t_k.rs").read_text()
    body = body.replace("KEY_CAP_t_k", f"KEY_CAP_{table}_{column}")
    body = body.replace("valid_cols_t", f"valid_cols_{table}").replace("ROW_CAP_t", f"ROW_CAP_{table}")
    return re.sub(r"\bcols\.k\b", f"cols.{column}", body)


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


# One small SEC query per style with a Verus-verified reference body for the mock "model".
STYLE_CASES = {
    "declarative": (
        "SELECT report, COUNT(*) AS cnt FROM pre WHERE line > 5 GROUP BY report",
        PROOFS / "group_count_where.rs",
        "adversary_declarative0",
    ),
    "imperative": (
        "SELECT COUNT(*) FROM pre WHERE line > 0",
        ROOT / "tests" / "fixtures" / "imperative_proofs" / "count_pre_line_gt0.rs",
        "rocketship",
    ),
}


def run_style_case(style: str, conversation_cls=Conversation, directory: Path | None = None) -> dict:
    """The launcher, in ``style``, against the mock. Returns the launcher's result record."""
    from research_loop.scripts.run_container_agent import run

    sql, body_file, menu = STYLE_CASES[style]
    with tempfile.TemporaryDirectory() as tmp:
        with mock_model(conversation_cls(body_file.read_text().strip("\n")), directory or Path(tmp)):
            # The imperative profile's default agent is a Cursor slug, so Claude needs the override.
            return run(
                menu, style, sql, agent="claude-haiku-4-5-20251001", allow_override=style == "imperative"
            )


# lemma.toml [run] stream: the grouped stream fixture (all six regions) as the mock's "answer", on a small table of the fixture's shape.
STREAM_SQL = "SELECT s, COUNT(*) AS c, SUM(m) AS sm FROM t GROUP BY s"
STREAM_FIXTURE = PROOFS / "stream" / "group_string_count_sum.rs"
STREAM_ENV = {
    "LEMMA_STREAM": "1",
    "LEMMA_PUSHDOWN": "0",  # the stream contract evaluates the WHERE itself (docs/STREAM.md); no pushed export
    "LEMMA_AGENT_SCAN": "0",
    "LEMMA_EXAMPLES": "none",  # the experiment's setting: the stream prompt without technique recipes, no example mounted
}
# a 20k-row table: the binary-mode main and DuckDB both take about a millisecond, so the bar would be a coin toss; the dry run shows
# the plumbing (prove, compile, time, official rounds, submit), not a speedup
STREAM_SPEED_BAR = "0.001"


def stream_table(db: Path, rows: int = 20_000, seed: int = 1) -> None:
    """``t`` as in the stream fixtures (tests/test_stream.py): s VARCHAR and m DECIMAL(12,2), no NULLs in them."""
    import random

    import duckdb

    rng = random.Random(seed)
    keys = ["", "x", "short", "a string longer than twelve", "ünïcödé", "A", "x" * 40]
    con = duckdb.connect(str(db))
    con.execute("CREATE OR REPLACE TABLE t (a INTEGER NOT NULL, b BIGINT, d DATE NOT NULL, s VARCHAR NOT NULL, m DECIMAL(12,2) NOT NULL)")
    con.executemany(
        "INSERT INTO t VALUES (?, ?, DATE '1970-01-01' + CAST(? AS INTEGER), ?, CAST(? AS DECIMAL(12,2)))",
        [(rng.randint(-5, 20), rng.randint(-1000, 1000), rng.randint(9000, 11500), rng.choice(keys), rng.randint(-(10**9), 10**9) / 100) for _ in range(rows)],
    )
    con.close()


def run_stream_case(directory: Path, agent: str = "claude-haiku-4-5-20251001") -> dict:
    """The launcher on a stream spec, against the mock that writes the grouped stream fixture's six regions, then calls
    run_runquery and submit_runquery. Returns the launcher's result record. ``directory`` holds the database and the mock's files."""
    from declarative_spec import stream
    from research_loop.scripts.mock_anthropic_api import StreamConversation
    from research_loop.scripts.run_container_agent import run

    db = directory / "stream_t.duckdb"
    stream_table(db)
    saved = {k: os.environ.get(k) for k in (*STREAM_ENV, "LEMMA_DUCKDB_PATH", "LEMMA_AGENT_MODEL")}
    # the model slug through lemma.toml's key too, so the launcher's --agent and the exported config agree
    os.environ.update({**STREAM_ENV, "LEMMA_DUCKDB_PATH": str(db), "LEMMA_AGENT_MODEL": agent})
    try:
        regions = stream.extract_regions(STREAM_FIXTURE.read_text())
        with mock_model(StreamConversation(regions), directory):
            return run(
                "adversary_declarative0", "declarative", STREAM_SQL, agent=agent, speed_bar_mult=STREAM_SPEED_BAR, allow_override=True, max_iterations=1
            )
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main(scenario: str) -> int:
    from research_loop.scripts.declarative_ladder import run_ladder

    if scenario == "stream":
        with tempfile.TemporaryDirectory() as tmp:
            print(json.dumps(run_stream_case(Path(tmp)), indent=2, default=str))
        return 0
    if scenario.startswith("style-"):
        style, _, hang = scenario.removeprefix("style-").partition("-")
        print(run_style_case(style, Hang if hang == "hang" else Conversation))
        return 0
    # Ladder query 1: SELECT bucket, COUNT(*) AS c FROM src GROUP BY bucket
    conversation = {"ok": Conversation, "hang": Hang}[scenario](group_count_body("src", "bucket"))
    with tempfile.TemporaryDirectory() as tmp, mock_model(conversation, Path(tmp)) as log:
        records = run_ladder("claude-haiku-4-5-20251001", indices=(1,))
        for line in log.read_text().splitlines():
            rec = json.loads(line)
            rec.pop("headers", None)
            rec["tools"] = len(rec.get("tools", []))
            print(f"MOCK_REQUEST {rec}")
    print(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "ok"))
