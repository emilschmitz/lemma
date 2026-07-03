"""Human-readable demo output for recordings (stdout). Debug logging stays in pipeline_log (stderr)."""
from __future__ import annotations

import os
import sys

_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def demo_enabled() -> bool:
    return os.environ.get("LEMMA_DEMO", "0") not in ("0", "false", "False", "")


def verbose_enabled() -> bool:
    return os.environ.get("LEMMA_VERBOSE", "0") not in ("0", "false", "False", "")


def _out(line: str) -> None:
    if demo_enabled():
        print(line, file=sys.stdout, flush=True)


def format_duration_ms(ms: int | None) -> str:
    if ms is None or ms < 0:
        return "—"
    if ms >= 1000:
        return f"{ms / 1000:.2f} s"
    return f"{ms} ms"


def format_latency_us(us: int | None) -> str:
    if us is None or us < 0:
        return "—"
    if us >= 1_000_000:
        return f"{us / 1_000_000:.3f} s"
    if us >= 1000:
        return f"{us / 1000:.2f} ms"
    return f"{us} µs"


def execution_emoji(latency_us: int) -> str:
    return "🦥" if latency_us >= 1_000_000 else "🔥"


def demo_banner(title: str) -> None:
    _out(f"\n{_CYAN}{'━' * 48}{_RESET}")
    _out(f"{_CYAN}{title}{_RESET}")
    _out(f"{_CYAN}{'━' * 48}{_RESET}")


def demo_iteration(n: int, total: int) -> None:
    _out(f"\n{_DIM}── Iteration {n}/{total} ──{_RESET}")


def demo_step_done(emoji: str, label: str, ms: int | None, *, detail: str = "") -> None:
    suffix = f" ({format_duration_ms(ms)})" if ms is not None and ms >= 0 else ""
    extra = f" {_DIM}{detail}{_RESET}" if detail else ""
    _out(f"{emoji}  {label} … {_GREEN}done{_RESET}{suffix}{extra}")


def demo_step_pass_fail(emoji: str, label: str, ms: int | None, passed: bool) -> None:
    status = f"{_GREEN}passed{_RESET}" if passed else f"{_RED}failed{_RESET}"
    suffix = f" ({format_duration_ms(ms)})" if ms is not None and ms >= 0 else ""
    _out(f"{emoji}  {label} … {status}{suffix}")


def demo_execute(label: str, latency_us: int, *, cached: bool = False) -> None:
    emoji = execution_emoji(latency_us)
    prefix = "💾 " if cached else ""
    lat = format_latency_us(latency_us)
    _out(f"{prefix}{emoji}  {_RED}{label}{_RESET} … {_RED}{lat}{_RESET}")


def demo_duckdb_query(latency_us: int) -> None:
    _out(f"🦆  Executing with DuckDB … {_YELLOW}{format_latency_us(latency_us)}{_RESET}")


def demo_from_harness_metrics(metrics: dict, *, include_upstream: bool = False) -> None:
    """Print harness pipeline steps from JSON metrics."""
    if include_upstream and metrics.get("transpile_time_ms", -1) >= 0:
        demo_step_done("🏗️", "Transpiling query into Dafny spec", metrics["transpile_time_ms"])
    if metrics.get("admit_time_ms", -1) >= 0:
        ok = metrics.get("admit_ok", True)
        demo_step_pass_fail("🔍", "Linting implementation", metrics["admit_time_ms"], ok)
    if metrics.get("verification_time_ms", -1) >= 0:
        verified = metrics.get("proof_verified", False)
        demo_step_pass_fail("✅", "Verifying implementation", metrics["verification_time_ms"], verified)
    # Order matches harness.py: dafny translate → postprocess Rust → cargo
    if metrics.get("codegen_time_ms", -1) >= 0:
        demo_step_done("🏗️", "Translating Dafny to Rust", metrics["codegen_time_ms"])
    if metrics.get("postprocess_time_ms", -1) >= 0:
        demo_step_done("⚙️", "Post-processing Rust", metrics["postprocess_time_ms"])
    if metrics.get("cargo_time_ms", -1) >= 0:
        demo_step_done("🔧", "Compiling Rust (cargo)", metrics["cargo_time_ms"])
    lat = metrics.get("latency_us", -1)
    if metrics.get("status") == "SUCCESS" and lat >= 0:
        demo_execute("Executing optimized query", lat)


def demo_note(msg: str) -> None:
    _out(f"{_DIM}   {msg}{_RESET}")
