"""Build the product wheel dist/lemma-<version>-py3-none-any.whl: everything `lemma` runs, nothing that needs a checkout.

    python3 scripts/release/build_wheel.py [--out DIR] [--verus-docs DIR] [--allow-dirty]

The wheel is staged from the files git tracks at HEAD (``git archive``; with --allow-dirty the tracked files of the working tree, and the
build info says ``-dirty``), so it never picks up local data, runs or generated files. Layout inside the wheel (site-packages):

  lemma_config.py, lemma_cli/, research_loop/, declarative_spec/, db_extension/   the runtime packages, at their repo-relative paths (so the
                                                                                 agent code the sandbox mounts is site-packages/db_extension/agent)
  verus_transpiler/, sql_transpiler/                                             the two workspace packages, vendored (they are not on PyPI)
  research_loop/vendor/verus_docs/                                               the Verus guide/examples/tests the agent reads (MIT; gitignored
                                                                                 in the checkout, made by research_loop/scripts/fetch_verus_docs.sh)
  lemma_data/                                                                    the repo-root files the runtime reads (lemma_config.resource):
      lemma.toml, scripts/ram/*.sh, scripts/fetch_libduckdb.sh, docker/agent/*, docker/prover/Dockerfile, tests/fixtures/declarative_proofs/,
      BUILD_INFO.json (source commit, build time)

Left out: research_loop/artifacts (prove_loop tarballs), research_loop/testdata, db_extension's C++ sources and tests, every tests/ directory.
The dependencies keep pyproject.toml's ranges (uv.lock has a numpy per Python version); install.sh pins every version to uv.lock with its
constraints.txt.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERUS_COMMIT = "3a4d30bcdc4571e7927af97be9c4664973083eda"  # Verus 0.2026.07.18.3a4d30b (lemma_cli/setup_cmd.py VERUS_VERSION)
# The runtime dependencies: pyproject.toml's, minus the workspace packages (vendored above) and pytest (tests only), plus what those two need.
DROP_DEPS = ("sql-transpiler", "verus-transpiler", "pytest")

# repo path prefix -> path inside the wheel. The first matching prefix wins; a path matching none is not shipped.
PACKAGES = (
    ("lemma_config.py", "lemma_config.py"),
    ("lemma_cli/", "lemma_cli/"),
    ("declarative_spec/future_float_error_bounds/tests/", None),
    ("declarative_spec/", "declarative_spec/"),
    ("research_loop/artifacts/", None),
    ("research_loop/testdata/", None),
    ("research_loop/", "research_loop/"),
    ("db_extension/duckdb_ext/", None),
    ("db_extension/extension-template-c/", None),
    ("db_extension/src/", None),
    ("db_extension/tests/", None),
    ("db_extension/dafny_transpiler/src/sql_transpiler/", "sql_transpiler/"),
    ("db_extension/dafny_transpiler/", None),
    ("db_extension/", "db_extension/"),
    ("verus_transpiler/src/verus_transpiler/", "verus_transpiler/"),
    # repo-root resources (lemma_config.resource)
    ("lemma.toml", "lemma_data/lemma.toml"),
    ("scripts/ram/", "lemma_data/scripts/ram/"),
    ("scripts/fetch_libduckdb.sh", "lemma_data/scripts/fetch_libduckdb.sh"),
    ("docker/agent/", "lemma_data/docker/agent/"),
    ("docker/prover/", "lemma_data/docker/prover/"),
    ("tests/fixtures/declarative_proofs/", "lemma_data/tests/fixtures/declarative_proofs/"),
)

PYPROJECT = """[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "lemma"
version = "{version}"
description = "Lemma: verified query synthesis (an AI agent writes run_query, Verus proves it, DuckDB runs it)"
readme = "README.md"
requires-python = ">=3.11"
dependencies = {deps}

[project.scripts]
lemma = "lemma_cli.main:main"

[tool.setuptools]
py-modules = ["lemma_config"]
include-package-data = true

[tool.setuptools.packages.find]
where = ["."]
include = ["lemma_cli*", "research_loop*", "declarative_spec*", "db_extension*", "verus_transpiler*", "sql_transpiler*", "lemma_data*"]
namespaces = true

[tool.setuptools.package-data]
"*" = ["**/*"]
"""


def target(rel: str) -> str | None:
    for prefix, dest in PACKAGES:
        if rel == prefix or (prefix.endswith("/") and rel.startswith(prefix)):
            return None if dest is None else dest + rel[len(prefix):] if prefix.endswith("/") else dest
    return None


def tracked_files(allow_dirty: bool, stage_src: Path) -> str:
    """Export the tracked files into ``stage_src``; returns the source commit (``<sha>-dirty`` for a dirty working tree with --allow-dirty)."""
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip())
    if dirty and not allow_dirty:
        sys.exit("the git tree has uncommitted changes in tracked files: commit first (the wheel is HEAD), or pass --allow-dirty for a test build")
    if dirty:
        files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode().split("\0")
        for rel in filter(None, files):
            src = ROOT / rel
            if src.is_file():
                (stage_src / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, stage_src / rel)
        return sha + "-dirty"
    archive = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(stage_src, filter="tar")
    return sha


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    ap.add_argument("--verus-docs", type=Path, default=ROOT / "research_loop" / "vendor" / "verus_docs")
    ap.add_argument("--allow-dirty", action="store_true", help="build from the working tree's tracked files (test builds only; BUILD_INFO says -dirty)")
    args = ap.parse_args()
    if (args.verus_docs / "COMMIT").is_file() is False or (args.verus_docs / "COMMIT").read_text().strip() != VERUS_COMMIT:
        sys.exit(f"{args.verus_docs} is not the Verus docs at {VERUS_COMMIT}: run research_loop/scripts/fetch_verus_docs.sh (or pass --verus-docs DIR)")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    vendored = tomllib.loads((ROOT / "verus_transpiler" / "pyproject.toml").read_text())["project"]["dependencies"]
    deps = [d for d in project["dependencies"] if not d.startswith(DROP_DEPS)] + vendored
    with tempfile.TemporaryDirectory(prefix="lemma-wheel-") as tmp:
        src, stage = Path(tmp) / "src", Path(tmp) / "stage"
        src.mkdir()
        stage.mkdir()
        commit = tracked_files(args.allow_dirty, src)
        shipped = 0
        for path in sorted(p for p in src.rglob("*") if p.is_file()):
            dest = target(path.relative_to(src).as_posix())
            if dest is None or "__pycache__" in dest:
                continue
            (stage / dest).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, stage / dest)  # keeps the mode: the guard scripts stay executable
            shipped += 1
        shutil.copytree(args.verus_docs, stage / "research_loop" / "vendor" / "verus_docs")
        for pkg in ("lemma_data", "research_loop/vendor"):  # make the data directories packages so setuptools ships them
            (stage / pkg / "__init__.py").touch()
        info = {"lemma_version": project["version"], "source_commit": commit, "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "verus_docs_commit": VERUS_COMMIT}
        (stage / "lemma_data" / "BUILD_INFO.json").write_text(json.dumps(info, indent=2) + "\n")
        shutil.copy2(ROOT / "README.md", stage / "README.md")
        (stage / "pyproject.toml").write_text(PYPROJECT.format(version=project["version"], deps=json.dumps(deps)))
        args.out.mkdir(parents=True, exist_ok=True)
        subprocess.run(["uv", "build", "--quiet", "--wheel", "--no-build-logs", "-o", str(args.out), str(stage)], check=True)
    wheel = args.out / f"lemma-{project['version']}-py3-none-any.whl"
    print(f"built {wheel} ({wheel.stat().st_size / 1e6:.1f} MB, {shipped} files from {commit[:12]}, plus the Verus docs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
