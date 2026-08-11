#!/usr/bin/env python3
"""Parallel re-verify prove_loop runquery_agent.rs bodies."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _classify(msg: str, *, admit_ok: bool) -> str:
    if not admit_ok:
        return "admission"
    if "precondition not satisfied" in msg:
        return "agent_verify_precondition"
    if "assertion failed" in msg:
        return "agent_verify_assert"
    if "cannot find function" in msg or "cannot find type" in msg:
        return "host_codegen"
    if "E0425" in msg or "E0308" in msg or "E0412" in msg:
        return "host_codegen"
    if "verification results::" in msg and "0 errors" in msg:
        return "pass"
    if "VERIFY True" in msg or "verification results::" in msg:
        m = re.search(r"(\d+) verified, (\d+) errors", msg)
        if m and int(m.group(2)) == 0:
            return "pass"
    if "timeout" in msg.lower():
        return "infra_timeout"
    return "agent_verify_other"


def _verify_one(dir_path: str) -> dict:
    d = Path(dir_path)
    verify_py = d / "verify_local.py"
    out: dict = {"dir": d.name, "status": "infra", "detail": ""}
    if not verify_py.is_file():
        out["status"] = "missing"
        return out
    try:
        proc = subprocess.run(
            [sys.executable, str(verify_py)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=420,
            check=False,
        )
    except subprocess.TimeoutExpired:
        out["status"] = "infra_timeout"
        return out
    text = proc.stdout + "\n" + proc.stderr
    admit_ok = "ADMIT True" in text
    if proc.returncode == 0:
        out["status"] = "pass"
        return out
    err_log = d / "verify_error.log"
    if err_log.is_file():
        text += "\n" + err_log.read_text(encoding="utf-8", errors="replace")
    out["status"] = _classify(text, admit_ok=admit_ok)
    out["detail"] = text[-1500:]
    return out


def collect_dirs(root: Path, rounds: tuple[str, ...]) -> list[Path]:
    dirs: list[Path] = []
    for rnd in rounds:
        for d in sorted(root.glob(f"{rnd}_q*")):
            if rnd == "r11" and d.name == "r11_q19":
                continue
            if (d / "runquery_agent.rs").is_file():
                dirs.append(d)
    return dirs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT / "research_loop" / "generated" / "prove_loop",
    )
    parser.add_argument("--rounds", nargs="+", default=["r11", "r12"])
    parser.add_argument("-j", type=int, default=8)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    dirs = collect_dirs(args.root, tuple(args.rounds))
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.j) as pool:
        futs = {pool.submit(_verify_one, str(d)): d for d in dirs}
        for fut in as_completed(futs):
            results.append(fut.result())
            r = results[-1]
            print(r["dir"], r["status"])

    counts = Counter(r["status"] for r in results)
    total = len(results)
    passed = counts.get("pass", 0)
    print("\n=== SUMMARY ===")
    print(f"total={total} pass={passed} ({100.0 * passed / total:.1f}%)")
    for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {k}: {v}")

    if args.report:
        args.report.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
