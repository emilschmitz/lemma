"""The installed-wheel layout (lemma_config.INSTALLED): repo-root resources from lemma_data/, writes under $LEMMA_HOME, provenance from the
installed package instead of git, experiments refused; the registry image names; and what scripts/release/build_wheel.py ships.

The checkout layout is the default of every other test; here INSTALLED is switched on for one test at a time."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import lemma_config as lc

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """lemma_config as a wheel install sees itself: ROOT = site-packages, resources under lemma_data/, LEMMA_HOME for writes."""
    site = tmp_path / "site-packages"
    (site / "lemma_data").mkdir(parents=True)
    (site / "lemma_data" / "lemma.toml").write_text((ROOT / "lemma.toml").read_text())
    monkeypatch.setattr(lc, "ROOT", site)
    monkeypatch.setattr(lc, "INSTALLED", True)
    monkeypatch.setattr(lc, "RESOURCES", site / "lemma_data")
    monkeypatch.setattr(lc, "TOML", site / "lemma_data" / "lemma.toml")
    monkeypatch.setenv("LEMMA_HOME", str(tmp_path / "home"))
    return site


def test_the_checkout_layout_is_unchanged() -> None:
    assert not lc.INSTALLED and lc.ROOT == ROOT and lc.TOML == ROOT / "lemma.toml"
    assert lc.resource("scripts", "ram", "verus_guarded.sh") == ROOT / "scripts" / "ram" / "verus_guarded.sh"
    assert lc.writable("research_loop", "runs") == ROOT / "research_loop" / "runs"


def test_installed_reads_resources_from_lemma_data_and_writes_under_lemma_home(installed: Path, tmp_path: Path) -> None:
    assert lc.resource("tests", "fixtures", "declarative_proofs") == installed / "lemma_data" / "tests" / "fixtures" / "declarative_proofs"
    assert lc.writable("research_loop", "runs") == tmp_path / "home" / "research_loop" / "runs"
    assert lc.writable("build", "libduckdb") == tmp_path / "home" / "build" / "libduckdb"
    assert lc.get("max_iterations") == 2  # lemma.toml read from the package copy


def test_installed_provenance_is_the_package_not_git(installed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, *a, **k: calls.append(cmd) or pytest.fail(f"git called: {cmd}"))
    monkeypatch.setattr(lc, "package_provenance", lambda: {"lemma_version": "9.9.9", "wheel_sha256": "ab" * 32})
    state = lc.git_state()
    assert state == {"git_sha": None, "git_dirty": None, "dirty_files": [], "package": {"lemma_version": "9.9.9", "wheel_sha256": "ab" * 32}}
    assert lc.require_clean_tree()["package"]["lemma_version"] == "9.9.9"  # nothing to be dirty; no refusal
    record = lc.record()
    assert record["git_sha"] is None and record["package"]["wheel_sha256"] == "ab" * 32 and calls == []


def test_installed_refuses_experiments(installed: Path) -> None:
    with pytest.raises(lc.ConfigError, match="experiments run from a git checkout"):
        lc.use_experiment("configs/experiments/x.toml", 0)


def test_the_checkout_still_refuses_a_dirty_tree_and_records_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    git("init", "-q")
    (repo / "f").write_text("1")
    git("add", "f")
    git("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm", "c")
    (repo / "f").write_text("2")
    monkeypatch.delenv("LEMMA_ALLOW_DIRTY", raising=False)
    with pytest.raises(lc.ConfigError, match="uncommitted changes"):
        lc.require_clean_tree(repo)
    assert lc.record(repo)["git_sha"] == git("rev-parse", "HEAD") and "package" not in lc.record(repo)


def test_package_provenance_reads_the_wheel_hash_from_the_install_record(monkeypatch: pytest.MonkeyPatch, installed: Path) -> None:
    class Dist:
        version = "0.1.0"

        def __init__(self, direct: dict) -> None:
            self.files = {"direct_url.json": json.dumps(direct), "RECORD": "lemma_config.py,sha256=x,1\n"}

        def read_text(self, name: str) -> str | None:
            return self.files.get(name)

    sha = "cd" * 32
    import importlib.metadata as md

    (installed / "lemma_data" / "BUILD_INFO.json").write_text(json.dumps({"source_commit": "f" * 40}))
    for direct in ({"url": f"file:///x/lemma-0.1.0-py3-none-any.whl#sha256={sha}", "archive_info": {}},  # uv (install.sh)
                   {"url": "file:///x/lemma.whl", "archive_info": {"hashes": {"sha256": sha}}},  # pip --hash
                   {"url": "file:///x/lemma.whl", "archive_info": {"hash": f"sha256={sha}"}}):
        monkeypatch.setattr(md, "distribution", lambda _name, d=direct: Dist(d))
        got = lc.package_provenance()
        assert got["wheel_sha256"] == sha and got["lemma_version"] == "0.1.0" and got["source_commit"] == "f" * 40
        assert got["installed_record_sha256"] == hashlib.sha256(b"lemma_config.py,sha256=x,1\n").hexdigest()


def test_an_image_registry_names_the_published_images_and_empty_keeps_the_research_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_IMAGE_REGISTRY", raising=False)
    assert lc.agent_image("claude") == "lemma-agent:claude" and lc.prover_image() == "lemma-prover:0.2026.07.18.3a4d30b"
    monkeypatch.setenv("LEMMA_IMAGE_REGISTRY", "ghcr.io/someone/")
    version = lc.package_version()
    assert lc.agent_image("codex") == f"ghcr.io/someone/lemma-agent-codex:{version}"
    assert lc.prover_image() == "ghcr.io/someone/lemma-prover:0.2026.07.18.3a4d30b"
    from declarative_spec.prover import image
    from research_loop.agent_harness import image_for

    assert image() == lc.prover_image() and image_for("gemini") == f"ghcr.io/someone/lemma-agent-gemini:{version}"
    out = subprocess.run([sys.executable, "-m", "lemma_config", "image", "prover"], cwd=ROOT, capture_output=True, text=True, check=True,
                         env={**os.environ, "LEMMA_IMAGE_REGISTRY": "r.example/x"}).stdout.strip()
    assert out == "r.example/x/lemma-prover:0.2026.07.18.3a4d30b"  # what scripts/ram/verus_guarded.sh runs


def test_the_guard_scripts_find_lemma_config_beside_lemma_data(tmp_path: Path) -> None:
    """Installed: the scripts live in site-packages/lemma_data/scripts/ram and read lemma.toml through LEMMA_PYTHON + site-packages."""
    site = tmp_path / "site-packages"
    (site / "lemma_data" / "scripts" / "ram").mkdir(parents=True)
    (site / "lemma_config.py").write_text("import sys\nif sys.argv[1:] == ['get', 'heavy_lock']: print('/tmp/x.lock')\n")
    script = (ROOT / "scripts" / "ram" / "heavy.sh").read_text().split("MEM_MAX=")[0] + 'cfg heavy_lock\n'
    (site / "lemma_data" / "scripts" / "ram" / "probe.sh").write_text(script)
    done = subprocess.run(["bash", str(site / "lemma_data" / "scripts" / "ram" / "probe.sh")], capture_output=True, text=True,
                          cwd=tmp_path, env={"PATH": os.environ["PATH"], "LEMMA_PYTHON": sys.executable})
    assert done.returncode == 0 and done.stdout.strip() == "/tmp/x.lock", done.stderr


def _build_wheel_module():
    spec = importlib.util.spec_from_file_location("build_wheel", ROOT / "scripts" / "release" / "build_wheel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_wheel_maps_the_runtime_and_leaves_out_tests_and_artifacts() -> None:
    target = _build_wheel_module().target
    assert target("lemma.toml") == "lemma_data/lemma.toml"
    assert target("scripts/ram/verus_guarded.sh") == "lemma_data/scripts/ram/verus_guarded.sh"
    assert target("tests/fixtures/declarative_proofs/hard/two_key.rs") == "lemma_data/tests/fixtures/declarative_proofs/hard/two_key.rs"
    assert target("db_extension/agent/mcp_proxy.py") == "db_extension/agent/mcp_proxy.py"
    assert target("verus_transpiler/src/verus_transpiler/transpiler.py") == "verus_transpiler/transpiler.py"
    assert target("db_extension/dafny_transpiler/src/sql_transpiler/value_bounds.py") == "sql_transpiler/value_bounds.py"
    for left_out in ("research_loop/artifacts/x.tar.gz", "tests/test_lemma_cli.py", "db_extension/duckdb_ext/src/lemma_extension.cpp",
                     "db_extension/tests/test_x.py", "research_loop/testdata/x.tbl", "scripts/setup.sh", "README.md", "configs/experiments/x.toml"):
        assert target(left_out) is None, left_out


@pytest.mark.slow
def test_the_built_wheel_holds_every_resource_the_runtime_reads(tmp_path: Path) -> None:
    docs = ROOT / "research_loop" / "vendor" / "verus_docs"
    if not (docs / "COMMIT").is_file():
        pytest.skip("no Verus docs (research_loop/scripts/fetch_verus_docs.sh)")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "release" / "build_wheel.py"), "--out", str(tmp_path), "--allow-dirty"], check=True)
    (wheel,) = tmp_path.glob("lemma-*.whl")
    z = zipfile.ZipFile(wheel)
    names = set(z.namelist())
    for need in ("lemma_config.py", "lemma_cli/main.py", "lemma_data/lemma.toml", "lemma_data/docker/agent/Dockerfile", "lemma_data/docker/agent/entrypoint.sh",
                 "lemma_data/docker/prover/Dockerfile", "lemma_data/scripts/fetch_libduckdb.sh", "lemma_data/BUILD_INFO.json",
                 "research_loop/scripts/run_container_agent.py", "research_loop/vendor/verus_docs/COMMIT", "research_loop/config.env",
                 "db_extension/agent/mcp_proxy.py", "verus_transpiler/__init__.py", "sql_transpiler/__init__.py",
                 "lemma_data/tests/fixtures/declarative_proofs/decline/group_count_sum_checked.rs"):
        assert need in names, need
    for script in ("lemma_data/scripts/ram/verus_guarded.sh", "lemma_data/scripts/ram/heavy.sh", "lemma_data/docker/agent/entrypoint.sh"):
        assert (z.getinfo(script).external_attr >> 16) & 0o111, f"{script} is not executable in the wheel"
    assert not [n for n in names if n.startswith("tests/") or "/artifacts/" in n or "__pycache__" in n]
    metadata = z.read(next(n for n in names if n.endswith("METADATA"))).decode()
    assert "Requires-Dist: duckdb==1.5.6" in metadata and "verus-transpiler" not in metadata and "pytest" not in metadata
