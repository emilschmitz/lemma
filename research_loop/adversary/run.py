"""Adversary runner: Grok in a write-only folder, host judges candidate.json.

The agent may read the repo and use the web. Its workspace is only the output
folder. Nesting ``agent sandbox run`` freezes ``.cursor`` and the CLI cannot
start, so the process is the CLI's own ``--sandbox enabled``. After it exits,
the host hashes the repo and Verus again and discards the run if they changed.

On a GCP VM run the same module; set ``ADVERSARY_TIMEOUT_SEC``. No Docker.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.adversary.candidate import load_candidate
from research_loop.adversary.judge import judge_candidate
from research_loop.adversary.tamper import (
    manifest_changes,
    repo_snapshot,
    sha256_file,
    unexpected_outputs,
)
from research_loop.harness import resolve_verus_bin


def _prompt_text(*, config_name: str, repo_path: Path, write_dir: Path) -> str:
    # PROMPT.md is fixed. Change it only when Emil explicitly asks.
    template = (ROOT / "research_loop/adversary/PROMPT.md").read_text(encoding="utf-8")
    template = template.removeprefix(
        "<!-- Host note: this prompt is fixed. Modify it only when Emil explicitly asks. -->\n\n"
    )
    candidate = write_dir / "candidate.json"
    return template.format(
        config_name=config_name,
        repo_path=str(repo_path),
        write_dir=str(write_dir),
        candidate_path=str(candidate),
    )


def agent_argv(write_dir: Path, repo_path: Path, prompt: str) -> list[str]:
    """Run the CLI directly.

    ``agent sandbox run`` freezes every ``.cursor`` directory, and the CLI
    cannot start without writing one. The host hash after the run is what
    discards a tampered repo. ``--sandbox enabled`` is the tool sandbox.
    """
    agent = shutil.which("agent") or "agent"
    return [
        agent,
        "-p",
        "--trust",
        "--sandbox",
        "enabled",
        "--workspace",
        str(write_dir),
        "--add-dir",
        str(repo_path),
        "--model",
        "grok-4.7-high",
        "--output-format",
        "text",
        prompt,
    ]


def _tool_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    verus = resolve_verus_bin()
    verus_digest = sha256_file(Path(verus)) if verus else None
    hashes["verus"] = verus_digest or ""
    try:
        import duckdb
    except ImportError:
        hashes["duckdb"] = ""
    else:
        digest = sha256_file(Path(duckdb.__file__))
        hashes["duckdb"] = digest or ""
    return hashes


def _run_agent(write_dir: Path, repo_path: Path, prompt: str, timeout: int) -> None:
    subprocess.run(
        agent_argv(write_dir, repo_path, prompt),
        cwd=str(write_dir),
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
    parser.add_argument(
        "--spec-style",
        choices=("recursive", "declarative"),
        default=None,
        help="default: LEMMA_SPEC_STYLE, else recursive",
    )
    args = parser.parse_args(argv)

    try:
        if args.candidate is not None:
            cand = load_candidate(args.candidate)
            report = judge_candidate(
                cand, config=args.config, verify=True, spec_style=args.spec_style
            )
            print(json.dumps(report, indent=2))
            return 0

        before_tree = repo_snapshot(ROOT)
        before_tools = _tool_hashes()
        with tempfile.TemporaryDirectory(prefix="lemma_adversary_out_") as tmp:
            write_dir = Path(tmp)
            prompt = _prompt_text(
                config_name=args.config, repo_path=ROOT, write_dir=write_dir
            )
            _run_agent(write_dir, ROOT, prompt, args.timeout)
            extra = unexpected_outputs(write_dir)
            tree_changes = manifest_changes(before_tree, repo_snapshot(ROOT))
            tool_changes = manifest_changes(before_tools, _tool_hashes())
            if extra or tree_changes or tool_changes:
                print("adversary tampered; candidate discarded", file=sys.stderr)
                if extra:
                    print(f"unexpected writes: {extra}", file=sys.stderr)
                if tree_changes:
                    print(f"repo changes: {tree_changes[:40]}", file=sys.stderr)
                if tool_changes:
                    print(f"tool changes: {tool_changes}", file=sys.stderr)
                return 3
            cand_path = write_dir / "candidate.json"
            if not cand_path.is_file():
                print("agent returned nothing: missing candidate.json", file=sys.stderr)
                return 2
            cand = load_candidate(cand_path)
            report = judge_candidate(
                cand, config=args.config, verify=True, spec_style=args.spec_style
            )
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
