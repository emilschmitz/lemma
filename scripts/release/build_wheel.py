"""Build the product wheel dist/lemma_db-<version>-py3-none-any.whl: everything `lemma` runs, nothing that needs a checkout.

    python3 scripts/release/build_wheel.py --duckdb-asset dist/lemma-<version>-duckdb-linux-x86_64.tar.gz [--out DIR] [--verus-docs DIR] [--allow-dirty]

--duckdb-asset is the release asset with our DuckDB binaries (scripts/release/build_bundle.sh writes it before the wheel). Its sha256 and size
go into lemma_data/duckdb_asset.json: `lemma setup` of the installed wheel downloads that asset of its version from the GitHub release and
refuses any other bytes (lemma_cli/duck.py download_release). So the asset uploaded to the release must be this exact file.

The wheel is staged from the files git tracks at HEAD (``git archive``; with --allow-dirty the tracked files of the working tree, and the
build info says ``-dirty``), so it never picks up local data, runs or generated files. Layout inside the wheel (site-packages):

  lemma_config.py, lemma_cli/, research_loop/, declarative_spec/, db_extension/   the runtime packages, at their repo-relative paths (so the
                                                                                 agent code the sandbox mounts is site-packages/db_extension/agent)
  verus_transpiler/, sql_transpiler/                                             the two workspace packages, vendored (they are not on PyPI)
  research_loop/vendor/verus_docs/                                               the Verus guide/examples/tests the agent reads (MIT; gitignored
                                                                                 in the checkout, made by research_loop/scripts/fetch_verus_docs.sh)
  lemma_data/                                                                    the repo-root files the runtime reads (lemma_config.resource):
      lemma.toml, scripts/ram/*.sh, scripts/fetch_libduckdb.sh, docker/agent/*, docker/prover/Dockerfile, tests/fixtures/declarative_proofs/,
      BUILD_INFO.json (source commit, build time), duckdb_asset.json (name, sha256 and size of the DuckDB release asset)

Left out: research_loop/artifacts (prove_loop tarballs), research_loop/testdata, db_extension's C++ sources and tests, every tests/ directory.
The dependencies keep pyproject.toml's ranges (uv.lock has a numpy per Python version); install.sh pins every version to uv.lock with its
constraints.txt.

PyPI: the wheel is what gets published (distribution ``lemma-db``; ``lemma`` on PyPI is another project). Its metadata (name, version,
description, authors, keywords, classifiers, URLs, license once there is one) is pyproject.toml's; only the dependencies differ (no
workspace packages, no path sources). The README is pyproject's README.md with its relative links made absolute GitHub URLs at the source
commit, so they work on the PyPI page. There is no sdist: the wheel is staged from a layout that exists only at build time (vendored
transpilers, the Verus docs), and the checkout's own sdist would carry workspace path dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
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
VENDORED = ("verus_transpiler/pyproject.toml", "db_extension/dafny_transpiler/pyproject.toml")
REPO_URL = "https://github.com/emilschmitz/lemma"
# pyproject.toml [project] keys copied into the wheel's metadata as they are (dependencies, scripts and the build layout are the wheel's own).
METADATA_KEYS = ("name", "version", "description", "requires-python", "license", "license-files", "authors", "keywords", "classifiers", "urls")

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

LAYOUT = """
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


def toml_value(value: object) -> str:
    """A TOML value for the metadata we copy: strings, lists of strings, and inline tables of strings (JSON spells those the same way,
    except tables)."""
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{json.dumps(k)} = {toml_value(v)}" for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    return json.dumps(value)


def wheel_pyproject(project: dict, deps: list[str]) -> str:
    """The staged pyproject.toml: the checkout's [project] metadata, the runtime dependencies, the wheel's package layout."""
    lines = ["[build-system]", 'requires = ["setuptools>=77"]', 'build-backend = "setuptools.build_meta"', "", "[project]"]
    for key in METADATA_KEYS:
        if key in project and key != "urls":
            lines.append(f"{key} = {toml_value(project[key])}")
    lines += ['readme = "README.md"', f"dependencies = {toml_value(deps)}"]
    if "urls" in project:
        lines += ["", "[project.urls]", *(f"{json.dumps(k)} = {json.dumps(v)}" for k, v in project["urls"].items())]
    return "\n".join(lines) + "\n" + LAYOUT


def absolute_links(readme: str, commit: str) -> str:
    """README.md for the PyPI page: every relative Markdown link or image target becomes the GitHub URL of that path at ``commit``
    (``blob`` for links, ``raw`` for images); absolute URLs and in-page anchors stay."""
    sha = commit.removesuffix("-dirty")

    def repl(m: re.Match[str]) -> str:
        bang, text, target = m.group(1), m.group(2), m.group(3)
        if re.match(r"^([a-z][a-z0-9+.-]*:|#|/)", target):
            return m.group(0)
        kind = "raw" if bang else "blob"
        return f"{bang}[{text}]({REPO_URL}/{kind}/{sha}/{target.removeprefix('./')})"

    return re.sub(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)", repl, readme)


def wheel_name(project: dict) -> str:
    """The wheel's file name: the normalized distribution name (``lemma-db`` -> ``lemma_db``), the version, a pure-Python tag."""
    return f"{re.sub(r'[-_.]+', '_', project['name']).lower()}-{project['version']}-py3-none-any.whl"


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
    ap.add_argument("--duckdb-asset", type=Path, required=True, help="the DuckDB release asset lemma-<version>-duckdb-linux-x86_64.tar.gz (build_bundle.sh)")
    args = ap.parse_args()
    if (args.verus_docs / "COMMIT").is_file() is False or (args.verus_docs / "COMMIT").read_text().strip() != VERUS_COMMIT:
        sys.exit(f"{args.verus_docs} is not the Verus docs at {VERUS_COMMIT}: run research_loop/scripts/fetch_verus_docs.sh (or pass --verus-docs DIR)")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    asset = f"lemma-{project['version']}-duckdb-linux-x86_64.tar.gz"  # lemma_cli/duck.py asset_name
    if args.duckdb_asset.name != asset:
        sys.exit(f"--duckdb-asset is {args.duckdb_asset.name}, this version's asset is {asset}")
    asset_info = {"name": asset, "sha256": hashlib.sha256(args.duckdb_asset.read_bytes()).hexdigest(), "size": args.duckdb_asset.stat().st_size}
    vendored = [d for f in VENDORED for d in tomllib.loads((ROOT / f).read_text())["project"]["dependencies"]]
    deps = list(dict.fromkeys([d for d in project["dependencies"] if not d.startswith(DROP_DEPS)] + vendored))
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
        (stage / "lemma_data" / "duckdb_asset.json").write_text(json.dumps(asset_info, indent=2) + "\n")
        (stage / "README.md").write_text(absolute_links((ROOT / project["readme"]).read_text(), commit))
        for name in project.get("license-files", []):
            shutil.copy2(ROOT / name, stage / name)
        (stage / "pyproject.toml").write_text(wheel_pyproject(project, deps))
        args.out.mkdir(parents=True, exist_ok=True)
        subprocess.run(["uv", "build", "--quiet", "--wheel", "--no-build-logs", "-o", str(args.out), str(stage)], check=True)
    wheel = args.out / wheel_name(project)
    print(f"built {wheel} ({wheel.stat().st_size / 1e6:.1f} MB, {shipped} files from {commit[:12]}, plus the Verus docs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
