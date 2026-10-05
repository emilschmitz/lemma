"""Local Verus check, compile, and run for assembled declarative programs."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from declarative_spec.verus_limits import (
    failure_prefix,
    run_verus,
    timeout_message,
    verus_limit_args,
    verus_timeout_sec,
)

VERUS_CANDIDATES = (
    Path("/home/emil/tools/verus/verus"),
    Path("verus"),
)


def _verus_binary() -> str:
    override = os.environ.get("LEMMA_VERUS_BIN", "").strip()  # e.g. scripts/ram/verus_guarded.sh
    if override:
        return override
    for p in VERUS_CANDIDATES:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return "verus"


def _text(chunk: str | bytes | None) -> str:
    if chunk is None:
        return ""
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8", errors="replace")
    return chunk


def verify_assembled(rs_source: str, *, timeout_sec: int | None = None) -> tuple[bool, str]:
    timeout_sec = verus_timeout_sec() if timeout_sec is None else timeout_sec
    verus = _verus_binary()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
        f.write(rs_source)
        path = f.name
    try:
        # cwd = the temp file's directory: Verus leaves a compiled executable named after the source in its cwd
        proc = run_verus([verus, path, *verus_limit_args()], timeout=timeout_sec, cwd=Path(path).parent)
        combined = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, combined
    except subprocess.TimeoutExpired as e:
        out = _text(e.stdout) + _text(e.stderr)
        return False, timeout_message(out, timeout_sec)
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


def _best_us(stdout: str) -> int:
    match = re.search(r"QUERY_LATENCY_BEST_US:\s*(\d+)", stdout or "")
    return -1 if match is None else int(match.group(1))


def _load_us(stdout: str) -> int:
    match = re.search(r"LOAD_US:\s*(\d+)", stdout or "")
    return -1 if match is None else int(match.group(1))


def _latency_us(stdout: str) -> int:
    match = re.search(r"QUERY_LATENCY_US:\s*(\d+)", stdout or "")
    if not match:
        return -1
    return int(match.group(1))


def compile_and_run(
    rs_source: str,
    *,
    work_dir: Path | None = None,
    timeout_sec: int | None = None,
) -> dict:
    """Verify, compile, and run. Success requires a printed QUERY_LATENCY_US."""
    timeout_sec = verus_timeout_sec() if timeout_sec is None else timeout_sec
    verus = _verus_binary()
    owned_dir = work_dir is None
    directory = work_dir if work_dir is not None else Path(tempfile.mkdtemp(prefix="decl-run-"))
    directory.mkdir(parents=True, exist_ok=True)
    rs_path = directory / "declarative_query.rs"
    rs_path.write_text(rs_source)
    binary = directory / "declarative_query"
    try:
        proc = run_verus(
            [
                verus,
                str(rs_path),
                "--triggers-mode",
                "silent",
                *verus_limit_args(),
                "--compile",
                "--",
                "-C",
                "opt-level=3",
                "-C",
                "codegen-units=1",
            ],
            timeout=timeout_sec,
            cwd=directory,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": timeout_message(_text(exc.stdout) + _text(exc.stderr), timeout_sec),
            "verify_msg": _text(exc.stdout) + _text(exc.stderr),
        }
    log = (proc.stdout or "") + "\n" + (proc.stderr or "")
    proved = proc.returncode == 0 and _proof_verified(log)
    if not proved or not binary.is_file():
        return {
            "status": "FAILURE",
            "proof_verified": proved,
            "latency_us": -1,
            "compiler_error": failure_prefix(log) + log[-4000:],
            "verify_msg": log[-4000:],
        }
    try:
        run = subprocess.run(
            [str(binary)],
            capture_output=True,
            text=True,
            timeout=300,
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
        "latency_best_us": _best_us(run.stdout or ""),
        "load_us": _load_us(run.stdout or ""),
        "compiler_error": "",
        "verify_msg": log[-2000:],
        "verify_summary": _verify_summary(log),
        "stdout": run.stdout or "",
    }


def speed_bar_mult() -> float:
    """How many times faster than DuckDB the proved binary must be. ``LEMMA_SPEED_BAR_MULT``, default 1.0."""
    mult = float(os.environ.get("LEMMA_SPEED_BAR_MULT", "1.0"))
    if mult <= 0:
        raise ValueError(f"LEMMA_SPEED_BAR_MULT must be positive, got {mult}")
    return mult


PARALLEL_HINT = (
    " This body is single-threaded and the bar is the reference engine on ALL cores: upgrade to the PARALLEL recipe "
    "(your spec has the `<table>_arc` parameters). Keep this verified body as the fallback, then write workers over row "
    "ranges with `vstd::thread::spawn`/`join` as in `context/ro/examples/parallel_ungrouped_sum.rs` (sums/counts: partials "
    "telescope; MIN/MAX: `parallel_ungrouped_min.rs`; GROUP BY over a small code domain: per-worker dense arrays, "
    "`dict_group_count_sum_parallel.rs`) and call `run_runquery` again. See the 'Parallel scan' section of DECLARATIVE.md."
)


def _apply_speed_bar(metrics: dict, speed_bar: dict | None, *, parallel_hint: bool = False) -> dict:
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
    mult = speed_bar_mult()
    speedup = duck_us / max(latency, 1)
    attained = {
        "speed_bar_mult": mult,
        "official_tables": speed_bar.get("table_rows"),  # the timed run is on these FULL tables, whatever dataset_size says
        "speedup": speedup,  # median of the timed runs
        "latency_best_us": metrics.get("latency_best_us"),
        "speedup_best": None
        if metrics.get("latency_best_us") in (None, -1)
        else duck_us / max(int(metrics["latency_best_us"]), 1),
        "duck_threads": speed_bar.get("duck_threads"),
        "duck1_us": speed_bar.get("duck1_us"),
        "speedup_1t": None if speed_bar.get("duck1_us") is None else int(speed_bar["duck1_us"]) / max(latency, 1),
    }
    if latency < 0 or latency * mult >= duck_us:
        return {
            **metrics,
            **attained,
            "status": "FAILURE",
            "duck_us": duck_us,
            "compiler_error": (
                f"proved but below the speed bar: query {latency} us, DuckDB {duck_us} us "
                f"({speedup:.2f}x; the bar is {mult:g}x faster than DuckDB). "
                "Use one pass over dense arrays; avoid a loop over one table inside another and a hash-map update per row where a dense Vec indexed by key works."
                + (PARALLEL_HINT if parallel_hint else "")
            ),
        }
    return {**metrics, **attained, "duck_us": duck_us}


def run_declarative_metrics(
    *,
    spec_rs: str,
    agent_source: str,
    work_dir: Path | None = None,
    timeout_sec: int | None = None,
    column_bins: dict[str, str] | None = None,
    speed_bar: dict | None = None,
) -> dict:
    """Admit the agent edit, assemble, compile, and run."""
    from declarative_spec.admit import admit_declarative_body, admit_helpers
    from declarative_spec.assemble import assemble_declarative_program

    def failure(message: str) -> dict:
        return {"status": "FAILURE", "proof_verified": False, "latency_us": -1, "compiler_error": message}

    # Only the two marked regions survive. Anything else in the agent file is discarded.
    try:
        if "AGENT_EDIT_START" in agent_source:
            body = extract_agent_edit(agent_source)
            helpers = extract_agent_helpers(agent_source)
        else:
            body = agent_source.strip()
            helpers = ""
    except ValueError as exc:
        return failure(str(exc))
    violations = list(admit_declarative_body(body).violations)
    if helpers:
        violations += admit_helpers(helpers, spec_rs).violations
    if violations:
        return failure("; ".join(violations))
    # Before Verus, not after the proof: a dense table over a product of key dictionaries that the prepared data puts past the budget.
    from declarative_spec import dense_budget

    if column_bins is not None and dense_budget.key_dictionaries(spec_rs) and not (speed_bar or {}).get("dict_sizes"):
        return failure("the prepared data has no dictionary sizes (expect.json lacks dict_sizes): re-run prepare so the dense-slot budget can be checked")
    dense = dense_budget.body_violation(body, spec_rs, None if speed_bar is None else speed_bar.get("dict_sizes"))
    if dense:
        return failure(dense)
    try:
        assembled = assemble_declarative_program(
            spec_rs,
            body,
            helpers=helpers,
            column_bins=column_bins,
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
    from declarative_spec import parallel

    # A body that never spawns a thread loses a bandwidth-bound scan to the all-core engine: tell it so when it can still upgrade.
    uses_threads = "spawn(" in body
    return _apply_speed_bar(metrics, speed_bar, parallel_hint=parallel.is_parallel(spec_rs) and not uses_threads)
