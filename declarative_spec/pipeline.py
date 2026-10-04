"""Local Verus check, compile, and run for assembled declarative programs."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

VERUS_CANDIDATES = (
    Path("/home/emil/tools/verus/verus"),
    Path("verus"),
)


def _verus_binary() -> str:
    for p in VERUS_CANDIDATES:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return "verus"


def verify_assembled(rs_source: str, *, timeout_sec: int = 180) -> tuple[bool, str]:
    verus = _verus_binary()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
        f.write(rs_source)
        path = f.name
    try:
        proc = subprocess.run(
            [verus, path],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, combined
    except subprocess.TimeoutExpired as e:
        def _text(chunk: str | bytes | None) -> str:
            if chunk is None:
                return ""
            if isinstance(chunk, bytes):
                return chunk.decode("utf-8", errors="replace")
            return chunk

        out = _text(e.stdout) + _text(e.stderr)
        return False, out or f"timeout after {timeout_sec}s"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _proof_verified(output: str) -> bool:
    for line in (output or "").splitlines():
        if "verification results::" in line and re.search(r"\b0 errors\b", line):
            return True
    return False


def _verify_summary(output: str) -> str:
    """The Verus ``verification results:: N verified, M errors`` line, or an empty string."""
    for line in (output or "").splitlines():
        if "verification results::" in line:
            return line.strip()
    return ""


def _latency_us(stdout: str) -> int:
    match = re.search(r"QUERY_LATENCY_US:\s*(\d+)", stdout or "")
    if not match:
        return -1
    return int(match.group(1))


def compile_and_run(
    rs_source: str,
    *,
    work_dir: Path | None = None,
    timeout_sec: int = 300,
) -> dict:
    """Verify, compile, and run. Success requires a printed QUERY_LATENCY_US."""
    verus = _verus_binary()
    owned_dir = work_dir is None
    directory = work_dir if work_dir is not None else Path(tempfile.mkdtemp(prefix="decl-run-"))
    directory.mkdir(parents=True, exist_ok=True)
    rs_path = directory / "declarative_query.rs"
    rs_path.write_text(rs_source)
    binary = directory / "declarative_query"
    try:
        proc = subprocess.run(
            [
                verus,
                str(rs_path),
                "--triggers-mode",
                "silent",
                "--compile",
                "--",
                "-C",
                "opt-level=3",
                "-C",
                "codegen-units=1",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
            cwd=directory,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": f"verus --compile timed out after {timeout_sec}s",
            "verify_msg": str(exc),
        }
    log = (proc.stdout or "") + "\n" + (proc.stderr or "")
    proved = proc.returncode == 0 and _proof_verified(log)
    if not proved or not binary.is_file():
        return {
            "status": "FAILURE",
            "proof_verified": proved,
            "latency_us": -1,
            "compiler_error": log[-4000:],
            "verify_msg": log[-4000:],
        }
    try:
        run = subprocess.run(
            [str(binary)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            cwd=directory,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "FAILURE",
            "proof_verified": True,
            "latency_us": -1,
            "compiler_error": "binary timed out",
            "verify_msg": log[-2000:],
        }
    finally:
        if owned_dir:
            try:
                binary.unlink(missing_ok=True)
            except OSError:
                pass
    latency = _latency_us(run.stdout or "")
    if run.returncode != 0 or latency < 0:
        err = (run.stderr or run.stdout or "binary did not print QUERY_LATENCY_US")[-2000:]
        return {
            "status": "FAILURE",
            "proof_verified": True,
            "latency_us": -1,
            "compiler_error": err,
            "verify_msg": log[-2000:],
        }
    return {
        "status": "SUCCESS",
        "proof_verified": True,
        "latency_us": latency,
        "compiler_error": "",
        "verify_msg": log[-2000:],
        "verify_summary": _verify_summary(log),
        "stdout": run.stdout or "",
    }


def extract_agent_edit(source: str) -> str:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    start_mark = "// AGENT_EDIT_START"
    end_mark = "// AGENT_EDIT_END"
    if start_mark not in normalized or end_mark not in normalized:
        raise ValueError("missing AGENT_EDIT markers")
    start = normalized.index(start_mark) + len(start_mark)
    end = normalized.index(end_mark)
    return normalized[start:end].strip()


def _apply_speed_bar(metrics: dict, speed_bar: dict | None) -> dict:
    if speed_bar is None or metrics.get("status") != "SUCCESS":
        return metrics
    duck_us = int(speed_bar["duck_us"])
    latency = int(metrics.get("latency_us", -1))
    stdout = str(metrics.get("stdout") or "")
    if "kinds" in speed_bar:
        from declarative_spec.bench import rows_from_stdout_general, rows_match_error

        err = rows_match_error(
            rows_from_stdout_general(stdout),
            list(speed_bar["rows"]),
            list(speed_bar["kinds"]),
            speed_bar.get("float_abs_eps"),
        )
    else:
        from declarative_spec.bench import rows_from_stdout

        got = rows_from_stdout(stdout)
        expect = [(int(k), int(v)) for k, v in speed_bar["rows"]]
        err = None
        if got != expect:
            err = (
                "proved but result rows differ from the loaded table "
                f"(got {len(got)} groups, expected {len(expect)})"
            )
    if err:
        return {
            **metrics,
            "status": "FAILURE",
            "duck_us": duck_us,
            "compiler_error": err,
        }
    if latency < 0 or latency >= duck_us:
        return {
            **metrics,
            "status": "FAILURE",
            "duck_us": duck_us,
            "compiler_error": (
                f"proved but slower than DuckDB: query {latency} us, DuckDB {duck_us} us. "
                "Count in a Vec of KEY_CAP slots. A HashMap update on every row loses."
            ),
        }
    return {**metrics, "duck_us": duck_us, "float_abs_eps": speed_bar.get("float_abs_eps")}


def run_declarative_metrics(
    *,
    spec_rs: str,
    agent_source: str,
    work_dir: Path | None = None,
    timeout_sec: int = 300,
    column_bins: dict[str, str] | None = None,
    speed_bar: dict | None = None,
) -> dict:
    """Admit the agent edit, assemble, compile, and run."""
    from declarative_spec.admit import admit_declarative_body, split_vstd_uses
    from declarative_spec.assemble import assemble_declarative_program

    try:
        if "AGENT_EDIT_START" in agent_source:
            body = extract_agent_edit(agent_source)
            outside = agent_source
        else:
            body = agent_source.strip()
            outside = agent_source
    except ValueError as exc:
        return {
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": str(exc),
        }
    uses, body, use_violations = split_vstd_uses(body)
    # Host-emitted `use` lines (hash axiom broadcast, `std_specs::ops::*`) are part of the
    # spec the agent file was copied from. Only imports the agent added are vetted.
    host_lines = {line.strip() for line in spec_rs.splitlines()}
    agent_outside = "\n".join(line for line in outside.splitlines() if line.strip() not in host_lines)
    file_uses, _rest, file_use_violations = split_vstd_uses(agent_outside)
    for line in file_uses:
        if line not in uses:
            uses.append(line)
    use_violations = use_violations + [v for v in file_use_violations if v not in use_violations]
    if use_violations:
        return {
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": "; ".join(use_violations),
        }
    admission = admit_declarative_body(body)
    if not admission.ok:
        return {
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": "; ".join(admission.violations),
        }
    try:
        assembled = assemble_declarative_program(
            spec_rs,
            body,
            column_bins=column_bins,
            extra_uses=uses,
            expected_rows=None if speed_bar is None else speed_bar.get("table_rows"),
        )
    except ValueError as exc:
        return {
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": str(exc),
        }
    metrics = compile_and_run(assembled, work_dir=work_dir, timeout_sec=timeout_sec)
    return _apply_speed_bar(metrics, speed_bar)
