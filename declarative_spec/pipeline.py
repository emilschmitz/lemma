"""Local Verus check, compile, and run for assembled declarative programs."""

from __future__ import annotations

import lemma_config
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from research_loop import official_measure as om
from declarative_spec import principles
from declarative_spec.feedback import FULL_LOG_NAME, format_failure
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from declarative_spec.verus_limits import (
    run_timeout_message,
    run_timeout_sec,
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
    override = os.environ.get("LEMMA_VERUS_BIN", "").strip()
    if override:
        return override
    # Default: the guarded wrapper (one slot machine-wide, memory-capped, waits for free memory). A runaway Z3 once took
    # the whole desktop session down; set LEMMA_VERUS_BIN to the real binary only on purpose.
    guard = Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"
    if guard.is_file() and os.access(guard, os.X_OK):
        return str(guard)
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
        return False, timeout_message(out, timeout_sec, getattr(e, 'wait_sec', None), getattr(e, 'run_sec', None))
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


def target_cpu() -> str:
    """LEMMA_TARGET_CPU: the rustc ``-C target-cpu`` of the compiled binary. Default ``x86-64-v3`` (AVX2, BMI2, FMA; every x86-64 CPU since 2013-2015).

    ``generic`` adds no flag (baseline x86-64, SSE2 only); ``native`` uses this machine's full ISA and ties the binary to it. ``native`` is NOT the
    default: on the AMD Zen box it turned on AVX-512 and made a proved TPC-H Q12 body 2.2x SLOWER than ``generic`` while ``x86-64-v3`` made it 1.35x faster.
    The flag only changes rustc code generation of already verified source; Verus never sees it. Rust does not contract a*b+c into FMA or reassociate
    floating point on its own, so results do not change.

    RISK: a v3 (or native) binary raises SIGILL on a CPU without AVX2/BMI2/FMA; that looks like a failed run. Set ``generic`` there. Every quoted speedup must
    say ``target_cpu=x86-64-v3 (AVX2/BMI2/FMA)`` against DuckDB's prebuilt baseline x86-64 binary (with its own runtime dispatch).
    """
    return str(lemma_config.get("target_cpu"))


def target_cpu_rustc_args() -> list[str]:
    cpu = target_cpu()
    return [] if cpu == "generic" else ["-C", f"target-cpu={cpu}"]


DECLINED_MESSAGE = (
    "DECLINED: the proved run_query returned None on the measured data (lemma.toml assumptions = false: no data assumptions, the body may "
    "decline, e.g. on a checked overflow). A decline is not a success and not a proof failure; in experiments it counts as a failed query. "
    "No other engine's answer was substituted."
)


class Declined(RuntimeError):
    """The compiled program declined (``run_query`` returned None): see ``declarative_spec/decline.py``."""


def _declined(returncode: int, stdout: str) -> bool:
    """The generated main's decline: its own line, then exit code ``DECLINE_EXIT_CODE``. Both, so a crash with code 3 is not a decline."""
    from declarative_spec.decline import DECLINE_EXIT_CODE, DECLINE_LINE

    return returncode == DECLINE_EXIT_CODE and DECLINE_LINE in (stdout or "").splitlines()


def declined_metrics(base: dict) -> dict:
    """The result of a declined run: status DECLINED, proved (Verus already said 0 errors), no latency, the label as the error text."""
    from declarative_spec.decline import STATUS_DECLINED

    return {**base, "status": STATUS_DECLINED, "declined": True, "proof_verified": True, "latency_us": -1, "compiler_error": DECLINED_MESSAGE}


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
    agent_source: str | None = None,
    keep_binary: bool = False,
    run_args: list[str] | None = None,
) -> dict:
    """Verify, compile, and run. Success requires a printed QUERY_LATENCY_US.

    ``run_args``: the binary's command line (a query template's parameter values, see ``templates.binary_args``).

    ``keep_binary`` leaves the compiled binary on disk (its path is ``binary_path`` in the result) for the official interleaved rounds;
    the caller then deletes it.

    ``agent_source`` is the agent's file; with it a failure's line numbers are mapped back to that file.
    The full, unreduced Verus log is always written to ``<work_dir>/verify_full.log``.
    """
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
                *target_cpu_rustc_args(),
            ],
            timeout=timeout_sec,
            cwd=directory,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": timeout_message(_text(exc.stdout) + _text(exc.stderr), timeout_sec, exc.wait_sec, exc.run_sec),  # type: ignore[attr-defined]
            "verify_msg": _text(exc.stdout) + _text(exc.stderr),
            "verus_wait_sec": exc.wait_sec,  # type: ignore[attr-defined]
            "verus_run_sec": exc.run_sec,  # type: ignore[attr-defined]
        }
    split = {"verus_wait_sec": proc.wait_sec, "verus_run_sec": proc.run_sec}  # type: ignore[attr-defined]
    log = (proc.stdout or "") + "\n" + (proc.stderr or "")
    (directory / FULL_LOG_NAME).write_text(log)
    proved = proc.returncode == 0 and _proof_verified(log)
    if not proved or not binary.is_file():
        shown = format_failure(
            log,
            assembled=rs_source,
            agent_source=agent_source,
            assembled_name=rs_path.name,
            directory=directory,
            full_log_hint=None if owned_dir else f"{directory.name}/{FULL_LOG_NAME}",
        )
        # compiler_error and verify_msg are the same text on purpose: the MCP layer must not repeat it.
        return {
            **split,
            "status": "FAILURE",
            "proof_verified": proved,
            "latency_us": -1,
            "compiler_error": shown,
            "verify_msg": shown,
        }
    try:
        from declarative_spec.heavy_phase import heavy_phase

        with heavy_phase("measure"):  # the timed run on the full tables: a quiet machine, no other export or proof at the same time
            run = subprocess.run(
                [str(binary), *(run_args or [])],
                capture_output=True,
                text=True,
                timeout=run_timeout_sec(),
                check=False,
                cwd=directory,
            )
    except subprocess.TimeoutExpired:
        if owned_dir:
            binary.unlink(missing_ok=True)
        return {
            **split,
            "status": "FAILURE",
            "proof_verified": True,
            "latency_us": -1,
            "compiler_error": run_timeout_message(run_timeout_sec()),
            "verify_msg": log[-2000:],
        }
    finally:
        if owned_dir and not keep_binary:
            try:
                binary.unlink(missing_ok=True)
            except OSError:
                pass
    latency = _latency_us(run.stdout or "")
    if _declined(run.returncode, run.stdout or ""):
        if owned_dir:
            binary.unlink(missing_ok=True)
        return declined_metrics({**split, "verify_msg": log[-2000:], "verify_summary": _verify_summary(log)})
    if run.returncode != 0 or latency < 0:
        if owned_dir:
            binary.unlink(missing_ok=True)
        err = (run.stderr or run.stdout or "binary did not print QUERY_LATENCY_US")[-2000:]
        return {
            **split,
            "status": "FAILURE",
            "proof_verified": True,
            "latency_us": -1,
            "compiler_error": err,
            "verify_msg": log[-2000:],
        }
    return {
        **split,
        "status": "SUCCESS",
        "proof_verified": True,
        "latency_us": latency,
        "latency_best_us": _best_us(run.stdout or ""),
        "load_us": _load_us(run.stdout or ""),
        "compiler_error": "",
        "verify_msg": log[-2000:],
        "verify_summary": _verify_summary(log),
        "stdout": run.stdout or "",
        "binary_path": str(binary),
        "run_dir": str(directory),
        "binary_owned": owned_dir,  # a temp dir the caller must clean; a caller-given work_dir keeps its binary as before
    }


def run_binary_timed(binary: Path, directory: Path) -> tuple[int, int]:
    """One more run of the compiled binary: (median-of-its-timed-runs us, best us). Loud on a crash, a timeout or a missing latency line."""
    latency, best, _stdout = run_binary_round(binary, directory, [])
    return latency, best


def run_binary_round(binary: Path, directory: Path, args: list[str]) -> tuple[int, int, str]:
    """One run of the compiled binary with ``args`` on its command line: (median us, best us, stdout). Loud like ``run_binary_timed``."""
    run = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=run_timeout_sec(), check=False, cwd=directory)
    latency = _latency_us(run.stdout or "")
    if _declined(run.returncode, run.stdout or ""):
        raise Declined(f"declined in an official round (parameters {args})" if args else "declined in an official round")
    if run.returncode != 0 or latency < 0:
        raise RuntimeError((run.stderr or run.stdout or "binary did not print QUERY_LATENCY_US")[-2000:])
    return latency, _best_us(run.stdout or ""), run.stdout or ""


def speed_bar_mult() -> float:
    """How many times faster than DuckDB the proved binary must be. ``LEMMA_SPEED_BAR_MULT``, default 1.0."""
    return float(lemma_config.get("speed_bar_mult"))


_PARALLEL_HINT_HEAD = (
    " This body is single-threaded and the bar is the reference engine on ALL cores: upgrade to the PARALLEL recipe "
    "(your spec has the `<table>_arc` parameters). Keep this verified body as the fallback, then write workers over row "
    "ranges with `vstd::thread::spawn`/`join` as in "
)
PARALLEL_HINT = (
    _PARALLEL_HINT_HEAD
    + "`context/ro/examples/parallel_ungrouped_sum.rs` (sums/counts: partials "
    "telescope; MIN/MAX: `parallel_ungrouped_min.rs`; GROUP BY over a small code domain: per-worker dense arrays, "
    "`dict_group_count_sum_parallel.rs`) and call `run_runquery` again. See the 'Parallel scan' section of DECLARATIVE.md."
)
PARALLEL_HINT_PRINCIPLES = (
    _PARALLEL_HINT_HEAD
    + "`context/ro/examples/parallel_scan_sum.rs` (sums/counts: partials telescope; MIN/MAX: merge (cell, any) pairs; "
    "GROUP BY over a small code domain: per-worker dense arrays merged slotwise) and call `run_runquery` again."
)
# examples = none: facts only (no recipe): the body is single-threaded, the reference engine uses all cores, the spec offers `<table>_arc`.
PARALLEL_HINT_NONE = (
    " This body is single-threaded; the reference engine runs on all cores; your spec has the `<table>_arc` parameters."
)
_SPEED_ADVICE = "Use one pass over dense arrays; avoid a loop over one table inside another and a hash-map update per row where a dense Vec indexed by key works."


def _apply_speed_bar(metrics: dict, speed_bar: dict | None, *, parallel_hint: bool = False, official: bool = False) -> dict:
    """Row check first (always), then the speed verdict.

    ``official=True`` (the host re-measure after submit / at the end of the loop): K interleaved rounds of DuckDB and the binary, verdict on the
    ratio of the medians (research_loop/official_measure.py). Otherwise (in-session ``run_runquery``): the single binary run against the DuckDB
    median taken at prepare, as before; labelled so in ``measurement``.
    """
    if speed_bar is None or metrics.get("status") != "SUCCESS":
        return _release_binary(metrics)
    duck_us = int(speed_bar["duck_us"])
    latency = int(metrics.get("latency_us", -1))
    stdout = str(metrics.get("stdout") or "")
    err = _rows_error(stdout, speed_bar, speed_bar["rows"], bool(speed_bar.get("limited")), speed_bar.get("tie_rows"))
    if err:
        return _release_binary({
            **metrics,
            "status": "FAILURE",
            "duck_us": duck_us,
            "compiler_error": err,
        })
    mult = speed_bar_mult()
    official = official and not speed_bar.get("synthetic")  # the synthetic dev bar (LEMMA_DECL_ROWS) has no DuckDB file to re-time; its result says so in `measurement`
    rounds_info: dict = {"measurement": om.MEASUREMENT_IN_SESSION}
    if official:
        try:
            rounds_info, latency, duck_us, best_us = _official_rounds(metrics, speed_bar)
        except Declined as exc:  # a later round (another template binding) declined: labelled, never replaced by the reference engine's time
            return _release_binary({**declined_metrics(metrics), "duck_us": duck_us, "measurement": om.MEASUREMENT_OFFICIAL, "compiler_error": f"{DECLINED_MESSAGE} ({exc})"})
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            return _release_binary({
                **metrics,
                "status": "FAILURE",
                "latency_us": -1,
                "duck_us": duck_us,
                "measurement": om.MEASUREMENT_OFFICIAL,
                "compiler_error": f"official interleaved measure failed: {exc}",
            })
        metrics = {**metrics, "latency_us": latency, "latency_best_us": None}  # best-of-45 vs a median is not comparable: not reported
    metrics = _release_binary(metrics)
    speedup = duck_us / max(latency, 1)
    attained = {
        **rounds_info,
        "speed_bar_mult": mult,
        "official_tables": speed_bar.get("table_rows"),  # the timed run is on these FULL tables, whatever dataset_size says
        "speedup": speedup,  # in session: median of the binary's timed runs vs the prepare-time DuckDB median; official: median of rounds vs median of rounds
        "latency_best_us": metrics.get("latency_best_us"),
        "speedup_best": None
        if metrics.get("latency_best_us") in (None, -1)
        else duck_us / max(int(metrics["latency_best_us"]), 1),
        "target_cpu": target_cpu(),  # a non-generic binary is tied to a CPU class: every quoted speedup must say so
        "duck_threads": speed_bar.get("duck_threads"),
        "duck1_us": speed_bar.get("duck1_us"),
        "speedup_1t": None if official or speed_bar.get("duck1_us") is None else int(speed_bar["duck1_us"]) / max(latency, 1),
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
                + (f"[{om.MEASUREMENT_OFFICIAL}: medians of {len(rounds_info['official_rounds'])} rounds, per round (ours/DuckDB us): {_rounds_text(rounds_info)}] " if official else "")
                + ("" if principles.examples_none() else _SPEED_ADVICE)  # none: no strategy advice in host feedback
                + ((PARALLEL_HINT_NONE if principles.examples_none() else PARALLEL_HINT_PRINCIPLES if principles.principles_only() else PARALLEL_HINT) if parallel_hint else "")
            ),
        }
    return {**metrics, **attained, "duck_us": duck_us}


def _rows_error(stdout: str, speed_bar: dict, rows: list, limited: bool, tie_rows: list | None) -> str | None:
    """The row check: the binary's printed rows against DuckDB's ``rows`` (None when they match)."""
    if speed_bar.get("kinds") is not None:  # a map result has `"kinds": null` in expect.json
        from declarative_spec.bench import rows_from_stdout_general, rows_match_error

        return rows_match_error(
            rows_from_stdout_general(stdout),
            list(rows),
            list(speed_bar["kinds"]),
            speed_bar.get("order_cols"),
            limited,
            tie_rows,
        )
    from declarative_spec.bench import rows_from_stdout

    got = rows_from_stdout(stdout)
    expect = [(int(k), int(v)) for k, v in rows]
    if got != expect:
        return "proved but result rows differ from the loaded table " f"(got {len(got)} groups, expected {len(expect)})"
    return None


def _release_binary(metrics: dict) -> dict:
    """Delete the kept binary (see compile_and_run ``keep_binary``) and drop its path from the result."""
    path = metrics.get("binary_path")
    if path is None:
        return metrics
    if metrics.get("binary_owned"):
        Path(path).unlink(missing_ok=True)
    return {k: v for k, v in metrics.items() if k not in ("binary_path", "run_dir", "binary_owned")}


def _rounds_text(info: dict) -> str:
    return "; ".join(f"{r['round']}:{r['order']} {r['ours_us']}/{r['duck_us']}" for r in info["official_rounds"])


def _official_rounds(metrics: dict, speed_bar: dict) -> tuple[dict, int, int, int]:
    """K interleaved rounds: (info for the result, ours median us, DuckDB median us, best us of the binary over the rounds)."""
    from declarative_spec.heavy_phase import heavy_phase

    binary, directory = Path(metrics["binary_path"]), Path(metrics["run_dir"])
    k = om.official_rounds()
    mult_ = speed_bar_mult()
    bests: list[int] = []

    def ours() -> int:
        latency, best = run_binary_timed(binary, directory)
        bests.append(best)
        return latency

    bindings = speed_bar.get("template_bindings")
    outputs: list[str] = []
    if bindings:
        from declarative_spec import templates

        template = templates.parse_template(str(speed_bar["sql"]))
        if template is None:
            raise ValueError("expect.json has template_bindings but its SQL is not a query template")

        def ours_bound(binding: dict) -> int:  # a template round: the round's values on the binary's command line
            latency, best, stdout = run_binary_round(binary, directory, templates.binary_args(template, binding))
            bests.append(best)
            outputs.append(stdout)
            return latency

    with heavy_phase("measure"):  # one quiet-machine phase for all rounds: no proof or export between the two sides
        duck, close = om.duck_round_timer(speed_bar, directory)
        overhead = getattr(duck, "python_overhead_us", None)
        try:
            rounds = om.interleave(ours_bound, duck, k, bindings) if bindings else om.interleave(ours, duck, k)
        finally:
            close()
    if bindings:  # each round's rows against DuckDB's rows for the same values: a wrong answer for any binding fails the measure
        for entry, stdout, expect in zip(rounds, outputs, duck.rows, strict=True):  # type: ignore[attr-defined]
            err = _rows_error(stdout, speed_bar, expect["rows"], expect["limited"], expect["tie_rows"])
            if err:
                raise RuntimeError(f"round {entry['round']} with parameters {entry['binding']}: {err}")
    summary = om.summarize(rounds)
    info = {
        "measurement": om.MEASUREMENT_OFFICIAL,
        "official_rounds": rounds,
        "official_k": k,
        "official_duck_reps": om.duck_reps(),
        "ours_median_us": summary["ours_median_us"],
        "duck_median_us": summary["duck_median_us"],
        "ratio_band": [summary["ratio_min"], summary["ratio_max"]],  # per-round DuckDB/ours; noise is ~+-4%, a band over 1/mult is not a verdict
        "inconclusive": summary["ratio_min"] * mult_ < 1.0 <= summary["ratio_max"] * mult_,
        "duck_python_overhead_us": overhead,  # execute+fetchall of SELECT 1: counted in DuckDB's figure, not ours; not subtracted
        "check_run_latency_us": metrics.get("latency_us"),  # the first run (row check); not part of the verdict
        "prepare_duck_us": speed_bar.get("duck_us"),  # DuckDB at prepare; not part of the verdict
    }
    return info, summary["ours_median_us"], summary["duck_median_us"], min(bests)


def _admit_and_assemble(spec_rs: str, agent_source: str, column_bins: dict[str, str] | None, speed_bar: dict | None) -> tuple[str, str, str]:
    """Admit the agent edit and assemble the program: ``(assembled, body, "")``, or ``("", "", error message)``."""
    from declarative_spec.admit import admit_declarative_body, admit_helpers
    from declarative_spec.assemble import assemble_declarative_program

    # Only the two marked regions survive. Anything else in the agent file is discarded.
    try:
        if "AGENT_EDIT_START" in agent_source:
            body = extract_agent_edit(agent_source)
            helpers = extract_agent_helpers(agent_source)
        else:
            body = agent_source.strip()
            helpers = ""
    except ValueError as exc:
        return "", "", str(exc)
    violations = list(admit_declarative_body(body).violations)
    if helpers:
        violations += admit_helpers(helpers, spec_rs).violations
    if violations:
        return "", "", "; ".join(violations)
    # Before Verus, not after the proof: a dense table over a product of key dictionaries that the prepared data puts past the budget.
    from declarative_spec import dense_budget

    if column_bins is not None and dense_budget.key_dictionaries(spec_rs) and not (speed_bar or {}).get("dict_sizes"):
        return "", "", "the prepared data has no dictionary sizes (expect.json lacks dict_sizes): re-run prepare so the dense-slot budget can be checked"
    dense = dense_budget.body_violation(body, spec_rs, None if speed_bar is None else speed_bar.get("dict_sizes"))
    if dense:
        return "", "", dense
    try:
        assembled = assemble_declarative_program(
            spec_rs,
            body,
            helpers=helpers,
            column_bins=column_bins,
            expected_rows=None if speed_bar is None else speed_bar.get("table_rows"),
        )
    except ValueError as exc:
        return "", "", str(exc)
    return assembled, body, ""


PARTIAL_LABEL = "partial check: not a proof of run_query; submit still requires a full verified run_runquery run"


def verify_functions_only(
    *,
    spec_rs: str,
    agent_source: str,
    names: list[str],
    work_dir: Path,
    column_bins: dict[str, str] | None = None,
    speed_bar: dict | None = None,
    timeout_sec: int | None = None,
) -> dict:
    """Admit and assemble like a full run, then verify only the named functions (one Verus run each, ``--verify-root --verify-function NAME``).

    No compile, no timing, no row check. The Verus guards apply (the guarded binary) and ``verus_timeout_sec`` bounds all the names together.
    """
    assembled, _body, error = _admit_and_assemble(spec_rs, agent_source, column_bins, speed_bar)
    if error:
        return {"label": PARTIAL_LABEL, "all_verified": False, "functions": [], "error": error}
    timeout_total = verus_timeout_sec() if timeout_sec is None else timeout_sec
    work_dir.mkdir(parents=True, exist_ok=True)
    rs_path = work_dir / "declarative_partial.rs"
    rs_path.write_text(assembled)
    verus = _verus_binary()
    deadline = time.monotonic() + timeout_total
    results: list[dict] = []
    wait_total = run_total = 0.0
    for name in names:
        left = max(1, int(deadline - time.monotonic()))
        try:
            proc = run_verus(
                [verus, str(rs_path), "--triggers-mode", "silent", *verus_limit_args(), "--verify-root", "--verify-function", name],
                timeout=left,
                cwd=work_dir,
            )
        except subprocess.TimeoutExpired as exc:
            wait_total += exc.wait_sec or 0.0  # type: ignore[attr-defined]
            run_total += exc.run_sec  # type: ignore[attr-defined]
            results.append({"name": name, "verified": False, "summary": "", "error": timeout_message(_text(exc.stdout) + _text(exc.stderr), timeout_total, exc.wait_sec, exc.run_sec)})  # type: ignore[attr-defined]
            break
        wait_total += proc.wait_sec or 0.0  # type: ignore[attr-defined]
        run_total += proc.run_sec  # type: ignore[attr-defined]
        log = (proc.stdout or "") + "\n" + (proc.stderr or "")
        verified = proc.returncode == 0 and _proof_verified(log)
        entry: dict = {"name": name, "verified": verified, "summary": _verify_summary(log)}
        if not verified:
            entry["error"] = format_failure(
                log, assembled=assembled, agent_source=agent_source, assembled_name=rs_path.name, directory=work_dir, full_log_hint=None,
            )
        results.append(entry)
    return {"label": PARTIAL_LABEL, "all_verified": bool(results) and len(results) == len(names) and all(r["verified"] for r in results), "functions": results}


def run_declarative_metrics(
    *,
    spec_rs: str,
    agent_source: str,
    work_dir: Path | None = None,
    timeout_sec: int | None = None,
    column_bins: dict[str, str] | None = None,
    speed_bar: dict | None = None,
    official: bool = False,
) -> dict:
    """Admit the agent edit, assemble, compile, and run. ``official``: the verdict is K interleaved rounds (see ``_apply_speed_bar``)."""
    assembled, body, error = _admit_and_assemble(spec_rs, agent_source, column_bins, speed_bar)
    if error:
        return {"status": "FAILURE", "proof_verified": False, "latency_us": -1, "compiler_error": error}
    from declarative_spec.templates import spec_params

    run_args: list[str] | None = None
    if spec_params(spec_rs):
        run_args = (speed_bar or {}).get("binding_args")
        if run_args is None:
            return {"status": "FAILURE", "proof_verified": False, "latency_us": -1, "compiler_error": "a query template's binary needs parameter values: prepare the data with bindings (expect.json binding_args)"}
    metrics = compile_and_run(
        assembled, work_dir=work_dir, timeout_sec=timeout_sec, agent_source=agent_source, keep_binary=official and speed_bar is not None and not speed_bar.get("synthetic"), run_args=run_args
    )
    from declarative_spec import parallel

    # A body that never spawns a thread loses a bandwidth-bound scan to the all-core engine: tell it so when it can still upgrade.
    uses_threads = "spawn(" in body
    return _apply_speed_bar(metrics, speed_bar, parallel_hint=parallel.is_parallel(spec_rs) and not uses_threads, official=official)
