"""JSON-lines RPC tool worker for the agent Docker sandbox."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from db_extension.agent.extract import extract_marked_body
    from db_extension.agent.sql_gate import check_duckdb_sql
except ImportError:
    from lemma_agent.extract import extract_marked_body
    from lemma_agent.sql_gate import check_duckdb_sql

WORKSPACE_ROOT = Path(os.environ.get("AGENT_WORKSPACE", "/workspace"))
CONTEXT_RO_ROOT = Path(os.environ.get("AGENT_CONTEXT_RO", "/context/ro"))
DATA_ROOT = Path(os.environ.get("AGENT_DATA", "/data"))
OUTPUT_LIMIT = 32_768
SHELL_TIMEOUT_SEC = 60
SUBMIT_FLAG = WORKSPACE_ROOT / ".lemma_submit"
RUNQUERY_PATH = WORKSPACE_ROOT / "runquery_agent.dfy"


def _resolve_allowed(path: str, allowed_roots: tuple[Path, ...]) -> Path:
    raw = Path(path)
    candidate = (raw if raw.is_absolute() else WORKSPACE_ROOT / raw).resolve()
    for root in allowed_roots:
        root_resolved = root.resolve()
        try:
            candidate.relative_to(root_resolved)
            return candidate
        except ValueError:
            continue
    raise PermissionError(f"path not allowed: {path}")


def _resolve_workspace(path: str) -> Path:
    return _resolve_allowed(path, (WORKSPACE_ROOT,))


def _resolve_read(path: str) -> Path:
    return _resolve_allowed(path, (WORKSPACE_ROOT, CONTEXT_RO_ROOT))


def _truncate(text: str, limit: int = OUTPUT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n... [truncated]"


def tool_read_file(args: dict) -> str:
    p = _resolve_read(args["path"])
    return p.read_text()


def tool_write_file(args: dict) -> str:
    p = _resolve_workspace(args["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args["content"])
    return f"wrote {len(args['content'])} bytes to {p}"


def tool_list_dir(args: dict) -> list[str]:
    p = _resolve_read(args.get("path", "."))
    if not p.is_dir():
        raise NotADirectoryError(str(p))
    return sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())


def _run_shell(command: str, cwd: str | None) -> subprocess.CompletedProcess[str]:
    work = WORKSPACE_ROOT if cwd is None else _resolve_workspace(cwd)
    return subprocess.run(
        ["bash", "-lc", command],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=SHELL_TIMEOUT_SEC,
    )


def tool_run_shell(args: dict) -> str:
    proc = _run_shell(args["command"], args.get("cwd"))
    out = ""
    if proc.stdout:
        out += proc.stdout
    if proc.stderr:
        out += ("\n" if out else "") + proc.stderr
    out += f"\n[exit {proc.returncode}]"
    return _truncate(out)


def tool_time_cmd(args: dict) -> dict:
    import time

    t0 = time.perf_counter()
    proc = _run_shell(args["command"], args.get("cwd"))
    wall_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "wall_ms": wall_ms,
        "exit_code": proc.returncode,
        "stdout": _truncate(proc.stdout or ""),
        "stderr": _truncate(proc.stderr or ""),
    }


def _load_duckdb():
    try:
        import duckdb
    except ImportError as e:
        raise RuntimeError("duckdb package not installed in container") from e
    return duckdb.connect(":memory:")


def _attach_data(con) -> None:
    if not DATA_ROOT.is_dir():
        return

    preferred = os.environ.get("AGENT_DATA_FILE", "").strip()
    candidates: list[Path] = []
    if preferred:
        p = DATA_ROOT / preferred
        if p.is_file():
            candidates.append(p)
    # Prefer well-known flat table names, then any tabular file.
    for name in ("lineorder_flat.tbl", "lineorder_flat.csv", "lineorder_flat.parquet"):
        p = DATA_ROOT / name
        if p.is_file() and p not in candidates:
            candidates.append(p)
    for p in sorted(DATA_ROOT.iterdir()):
        if p.is_file() and p.suffix.lower() in (".tbl", ".csv", ".parquet") and p not in candidates:
            candidates.append(p)

    for p in candidates:
        suf = p.suffix.lower()
        if suf in (".csv", ".tbl"):
            con.execute(
                f"CREATE TABLE lineorder_flat AS SELECT * FROM read_csv('{p}', delim='|', header=True)"
            )
            return
        if suf == ".parquet":
            con.execute(f"CREATE TABLE lineorder_flat AS SELECT * FROM read_parquet('{p}')")
            return


def tool_duckdb_sql(args: dict) -> str:
    mode = os.environ.get("AGENT_DATA_MODE", "stats")
    sql = args["sql"]
    err = check_duckdb_sql(sql, mode)
    if err:
        raise ValueError(err)
    con = _load_duckdb()
    try:
        _attach_data(con)
        cur = con.execute(sql)
        if cur.description:
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            lines = ["\t".join(cols)]
            for row in rows[:500]:
                lines.append("\t".join(str(c) for c in row))
            if len(rows) > 500:
                lines.append(f"... ({len(rows) - 500} more rows)")
            return _truncate("\n".join(lines))
        return "OK"
    finally:
        con.close()


def tool_submit(_args: dict) -> str:
    if not RUNQUERY_PATH.is_file():
        raise FileNotFoundError(f"{RUNQUERY_PATH} not found")
    text = RUNQUERY_PATH.read_text()
    extract_marked_body(text)
    SUBMIT_FLAG.write_text("ok\n")
    return "submission accepted"


_TOOLS = {
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "list_dir": tool_list_dir,
    "run_shell": tool_run_shell,
    "duckdb_sql": tool_duckdb_sql,
    "time_cmd": tool_time_cmd,
    "submit": tool_submit,
}


def handle_request(req: dict) -> dict:
    req_id = req.get("id")
    tool = req.get("tool")
    args = req.get("args") or {}
    try:
        if tool not in _TOOLS:
            return {"id": req_id, "ok": False, "result": f"unknown tool: {tool}"}
        result = _TOOLS[tool](args)
        return {"id": req_id, "ok": True, "result": result}
    except Exception as e:
        return {"id": req_id, "ok": False, "result": str(e)}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps({"id": None, "ok": False, "result": str(e)}), flush=True)
            continue
        resp = handle_request(req)
        print(json.dumps(resp, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
