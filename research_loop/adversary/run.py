"""Adversary runner: optional Grok agent in a repo copy, host judges candidate.json.

On a GCP VM run the same module; set ``ADVERSARY_TIMEOUT_SEC``; no Docker.
``VERUS`` is resolved via ``research_loop.harness.resolve_verus_bin``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.adversary.candidate import load_candidate
from research_loop.adversary.judge import judge_candidate

# Directory names, matched anywhere. Keeps the agent on source, not build
# trees, run traces, or dataset dumps.
_COPY_EXCLUDES = (
    ".git",
    "target",
    "harvest",
    "runs",
    "generated",
    "__pycache__",
    ".venv",
    "node_modules",
    "build",
    "ssb-dbgen",
    "data",
    "archive",
    "scratch",
    ".cache",
)


def _copy_repo(dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    cmd = ["rsync", "-a"]
    for name in _COPY_EXCLUDES:
        cmd.append(f"--exclude={name}")
    cmd.append(f"{ROOT}/")
    cmd.append(f"{dst}/")
    subprocess.run(cmd, check=True)


def _prompt_text(config_name: str, candidate_rel: str) -> str:
    template = (ROOT / "research_loop/adversary/PROMPT.md").read_text(encoding="utf-8")
    return template.format(config_name=config_name, candidate_path=candidate_rel)


def _run_agent(copy_root: Path, prompt: str, timeout: int) -> None:
    cmd = [
        "agent",
        "-p",
        "--force",
        "--trust",
        "--model",
        "grok-4.7-high",
        "--output-format",
        "text",
    ]
    subprocess.run(
        cmd,
        input=prompt,
        text=True,
        cwd=str(copy_root),
        timeout=timeout,
        check=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lemma adversary hunt")
    parser.add_argument("--config", default="hardware")
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("ADVERSARY_TIMEOUT_SEC", "600")),
    )
    parser.add_argument("--candidate", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        if args.candidate is not None:
            cand = load_candidate(args.candidate)
            report = judge_candidate(cand, config=args.config, verify=True)
            print(json.dumps(report, indent=2))
            return 0

        with tempfile.TemporaryDirectory(prefix="lemma_adversary_copy_") as tmp:
            copy_root = Path(tmp) / "repo"
            _copy_repo(copy_root)
            candidate_rel = "adversary_out/candidate.json"
            prompt = _prompt_text(args.config, candidate_rel)
            (copy_root / "ADVERSARY_PROMPT.txt").write_text(prompt, encoding="utf-8")
            _run_agent(copy_root, prompt, args.timeout)
            cand_path = copy_root / candidate_rel
            if not cand_path.is_file():
                print("agent returned nothing: missing adversary_out/candidate.json", file=sys.stderr)
                return 2
            cand = load_candidate(cand_path)
            report = judge_candidate(cand, config=args.config, verify=True)
            print(json.dumps(report, indent=2))
            return 0
    except subprocess.TimeoutExpired:
        print("agent timed out", file=sys.stderr)
        return 1
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
