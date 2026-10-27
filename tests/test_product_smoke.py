"""Fresh-machine smoke test of the installed product (the wheel, no checkout). Opt in (minutes; real Docker, real Verus):

    scripts/release/build_product.sh            # or, reusing a DuckDB build: --skip-duckdb-build; images: see below
    uv run pytest -m slow tests/test_product_smoke.py -s

Images ("simulating a pull"): when the release has images/*.tar.gz (build_product.sh --save-images), their registry tags are removed and
install.sh --load-images loads them back; otherwise the registry tags named in the release's VERSION must already exist locally
(build_images.sh tags them). `lemma setup` then finds them and pulls nothing; the pull path itself is covered by tests/test_lemma_cli.py.

In an empty HOME, from an empty working directory, with no PYTHONPATH, no Verus and no Rust toolchain (no ~/tools/verus, no RUSTUP_HOME /
CARGO_HOME, no cargo or rustup on PATH) and a `git` on PATH that fails and leaves a mark when anything calls it: install.sh of the release,
then the user's steps with the installed `lemma` only: `lemma setup --auth api-key` (prover = docker), `lemma optimize` on a tiny DuckDB
of a GROUP BY that the stream gate accepts (lemma.toml [product] executor = auto: a STREAMING executor, ABI 6, docs/STREAM.md), `lemma list`
(kind stream), `lemma duckdb -c` (the proved executor answers, equal to DuckDB, lemma_last_query engine = lemma, mode = stream; again right
after an INSERT; and ordinary DuckDB SQL: CREATE TABLE, INSERT, a join, read_csv), a second `lemma optimize` (already optimized), and the
run's provenance (package version and wheel sha256, no git; the executor choice as product_executor). A last test installs the same
release into a stock ubuntu:22.04 container (uv only) and runs our DuckDB there with the executor the second test proved.

REAL: install.sh, `uv tool install` of the wheel, Docker, the prover image (Verus and rustc run there), the agent image, the sandbox
self-test (needs internet for api.anthropic.com), Claude Code in the container, the egress bridge, the MCP host, the spec, admission,
Verus (the pipeline's proof and the install's re-verification + library compile), the timed run against DuckDB, the extension, the cache.
MOCKED: the model. Claude Code talks to research_loop/scripts/mock_anthropic_api.py (through the real bridge, test-only override
LEMMA_TEST_MOCK_ANTHROPIC_*), whose StreamConversation writes the six regions of a fixed, already proved stream body
(tests/fixtures/declarative_proofs/stream/group_string_count_sum.rs) into the agent file, calls run_runquery, then submit_runquery. The API
key is a dummy.
SHARED WITH THIS MACHINE: the uv download caches (downloads only) and the Docker daemon's images.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
BODY = ROOT / "tests" / "fixtures" / "declarative_proofs" / "stream" / "group_string_count_sum.rs"
SQL = "SELECT s, COUNT(*) AS c, SUM(m) AS sm FROM t GROUP BY s"  # the fixture's query (t: m DECIMAL(12,2), s VARCHAR, no NULLs)
CHOICE = {"kind": "stream", "setting": "auto", "reason": "the stream gate accepts this query", "abi": 6}
DUMMY_KEY = "sk-ant-api03-SMOKE-dummy-NOT-A-REAL-KEY-0000"
PLAIN_SQL = (  # ordinary DuckDB, no executor: Lemma mode off for this connection
    "SET lemma_mode = false; CREATE TABLE city(id INTEGER, name VARCHAR); INSERT INTO city VALUES (1, 'Oslo'), (2, 'Lima'); "
    "SELECT c.name, s.qty FROM city c JOIN read_csv('{csv}') s ON s.city_id = c.id ORDER BY c.name;"
)
GIT_TRAP = "#!/bin/sh\necho \"$@\" >> \"$(dirname \"$0\")/git_called\"\necho 'git is not part of the product' >&2\nexit 97\n"

pytestmark = pytest.mark.slow


def _version(release: Path) -> dict[str, str]:
    return dict(line.split(" ", 1) for line in (release / "VERSION").read_text().splitlines())


def _release() -> Path:
    found = sorted((p for p in (ROOT / "dist").glob("lemma-*-linux-x86_64") if p.is_dir()), key=lambda p: p.stat().st_mtime)
    if not found:
        pytest.skip("no release directory: run scripts/release/build_product.sh (or build_bundle.sh) first")
    release = found[-1]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    assert _version(release)["source"].split("-")[0] == head, f"{release.name} is not HEAD ({_version(release)['source']}): rebuild it"
    return release


def _images(release: Path) -> list[str]:
    tags = [_version(release)["agent_image"], _version(release)["prover_image"]]
    if not list((release / "images").glob("*.tar.gz")):
        missing = [t for t in tags if subprocess.run(["docker", "image", "inspect", t], capture_output=True).returncode != 0]
        if missing:
            pytest.skip(f"images {missing} are neither in the release nor tagged locally (scripts/release/build_images.sh)")
    return tags


@pytest.fixture(scope="module")
def user(tmp_path_factory: pytest.TempPathFactory) -> dict:
    if not (shutil.which("docker") and shutil.which("openssl") and shutil.which("uv")):
        pytest.skip("needs docker, openssl and uv")
    release = _release()
    images = _images(release)
    tmp = tmp_path_factory.mktemp("fresh_machine")
    home, cwd, trap = tmp / "home", tmp / "cwd", tmp / "trap"
    for d in (home, cwd, trap):
        d.mkdir(parents=True)
    (trap / "git").write_text(GIT_TRAP)
    (trap / "git").chmod(0o755)
    drop = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "VIRTUAL_ENV", "RUSTUP_HOME", "CARGO_HOME", "RUSTUP_TOOLCHAIN", "XDG_CACHE_HOME", "PYTHONPATH")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LEMMA_", "UV_")) and k not in drop}
    path = [p for p in os.environ["PATH"].split(os.pathsep) if not any(t in p for t in (".cargo", "rustup", "tools/verus"))]
    env.update({
        "HOME": str(home),
        "PATH": os.pathsep.join([str(trap), str(home / ".local" / "bin"), *path]),
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR") or str(Path.home() / ".cache" / "uv"),  # downloads only
        "UV_PYTHON_INSTALL_DIR": str(Path.home() / ".local" / "share" / "uv" / "python"),  # the interpreter download, nothing else
        "ANTHROPIC_API_KEY": DUMMY_KEY,
    })
    for tool in ("cargo", "rustc", "rustup", "verus"):
        assert shutil.which(tool, path=env["PATH"]) is None, f"{tool} is still on the fresh user's PATH"
    install = ["bash", str(release / "install.sh")]
    if list((release / "images").glob("*.tar.gz")):  # simulate the pull: drop the registry tags, load them from the release
        subprocess.run(["docker", "rmi", *images], capture_output=True, check=False)
        install.append("--load-images")
    done = subprocess.run(install, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    print(done.stdout[-2000:], done.stderr[-2000:])
    assert done.returncode == 0
    db = tmp / "shop.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE t(s VARCHAR, m DECIMAL(12,2))")
    con.execute("INSERT INTO t SELECT 'key ' || (i % 5) || (CASE WHEN i % 5 = 3 THEN ' longer than twelve' ELSE '' END), "
                "((i * 7) % 2300) / 100 FROM range(2000) r(i)")
    con.close()
    (tmp / "sales.csv").write_text("city_id,qty\n1,5\n2,7\n")
    return {"home": home, "env": env, "db": db, "tmp": tmp, "cwd": cwd, "trap": trap, "release": release, "images": images,
            "share": home / ".local" / "share" / "lemma"}


def lemma(user: dict, *args: str, env: dict | None = None, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(["lemma", *args], cwd=user["cwd"], env=env or user["env"], capture_output=True, text=True, timeout=timeout, check=False)
    print(f"$ lemma {' '.join(args)}  (exit {done.returncode})\n{done.stdout[-4000:]}\n{done.stderr[-3000:]}")
    assert DUMMY_KEY not in done.stdout and DUMMY_KEY not in done.stderr
    return done


def test_install_lays_out_the_wheel_and_the_duckdb_binaries_and_no_source_tree(user: dict) -> None:
    share, home = user["share"], user["home"]
    assert (home / ".local" / "bin" / "lemma").is_file()
    assert (share / "duckdb" / "duckdb").is_file() and (share / "duckdb" / "lemma.duckdb_extension").is_file()
    assert (share / "build" / "libduckdb" / "libduckdb.so").is_file()
    assert not (share / "src").exists() and not list(home.rglob(".git"))
    tool_python = home / ".local" / "share" / "uv" / "tools" / "lemma" / "bin" / "python"
    probe = subprocess.run([str(tool_python), "-c", "import lemma_config, json; print(json.dumps([lemma_config.INSTALLED, str(lemma_config.ROOT), "
                            "str(lemma_config.TOML)]))"], cwd=user["cwd"], env=user["env"], capture_output=True, text=True, check=True)
    installed, root, toml = json.loads(probe.stdout)
    assert installed and root.startswith(str(home)) and toml.endswith("lemma_data/lemma.toml") and str(ROOT) not in probe.stdout


def test_setup_optimize_and_run_in_duckdb_from_the_installed_wheel(user: dict) -> None:
    from declarative_spec import stream
    from research_loop.agent_sandbox import MOCK_CA_ENV, MOCK_PORT_ENV
    from research_loop.scripts.mock_anthropic_api import MockAnthropic, StreamConversation, make_ca

    done = lemma(user, "setup", "--auth", "api-key", timeout=1800)
    assert done.returncode == 0 and "READY" in done.stdout and "[ok] duckdb: v1.5.6" in done.stdout
    assert "[ok] prover (docker): Verus 0.2026.07.18.3a4d30b and Rust 1.96.0-x86_64-unknown-linux-gnu in the image " + user["images"][1] in done.stdout
    assert f"[ok] image {user['images'][0]}" in done.stdout and "pulling" not in done.stdout and "building" not in done.stdout
    assert not (user["home"] / "tools").exists() and (user["home"] / ".cache" / "lemma" / "prover").is_dir()  # vstd from the image

    cert, key = make_ca(user["tmp"])
    with MockAnthropic(StreamConversation(stream.extract_regions(BODY.read_text())), cert, key, user["tmp"] / "mock_requests.jsonl") as mock:
        env = {**user["env"], MOCK_PORT_ENV: str(mock.port), MOCK_CA_ENV: str(cert)}
        done = lemma(user, "optimize", "--db", str(user["db"]), "--sql", SQL, env=env)
    assert done.returncode == 0, done.stderr[-3000:]
    assert re.search(r"PROVED  \d+ verified, 0 errors \(Verus\)", done.stdout)
    assert "executor: stream (ABI 6; [product] executor = auto): the stream gate accepts this query" in done.stdout
    assert "  executor: stream (ABI 6)" in done.stdout
    (executor,) = (user["share"] / "executors").iterdir()
    assert {"lib.so", "manifest.json", "optimize.json", "proved", "query.sql"} <= {p.name for p in executor.iterdir()}

    # Provenance without git: the installed package's version and the wheel's sha256 (install.sh), in the executor and the run manifest.
    wheel = next(user["release"].glob("lemma-*.whl"))
    manifest = json.loads((executor / "manifest.json").read_text())
    package = manifest["package"]
    assert package["wheel_sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest() and package["lemma_version"] in wheel.name
    assert manifest["git_dirty"] is None and manifest["git_sha"] == package["source_commit"]
    assert manifest["mode"] == "stream" and manifest["abi_version"] == 6
    assert json.loads((executor / "optimize.json").read_text())["executor"] == CHOICE
    run_dir = Path(json.loads((executor / "optimize.json").read_text())["run_dir"])
    assert run_dir.is_relative_to(user["share"])  # the run went under LEMMA_HOME, never into site-packages
    run_manifest = json.loads((run_dir / "manifest.json").read_text())
    assert run_manifest["git_sha"] is None and run_manifest["package"]["wheel_sha256"] == package["wheel_sha256"]
    assert run_manifest["product_executor"] == CHOICE
    effective = run_manifest["lemma_config"]
    assert (effective["stream"]["value"], effective["pushdown"]["value"], effective["agent_scan"]["value"]) == (True, False, False)

    listed = lemma(user, "list")
    assert listed.returncode == 0 and f"{executor.name[:12]}  stream  " in listed.stdout and SQL in listed.stdout

    # Our DuckDB CLI with Lemma mode on: the streaming executor answers (equal to DuckDB) on DuckDB's own scan chunks.
    shown = lemma(user, "duckdb", str(user["db"]), "-c", f"{SQL}; SELECT engine, mode FROM lemma_last_query();")
    assert shown.returncode == 0 and re.search(r"│\s*lemma\s*│\s*stream\s*│", shown.stdout)
    for write in ("", "INSERT INTO t VALUES ('key 9', 1.50), ('key 0', 2.25); "):  # fresh data: the first call after a write streams too
        csv = subprocess.run([str(user["share"] / "duckdb" / "duckdb"), "-csv", "-noheader", "-cmd", "SET lemma_mode = true", str(user["db"]),
                              "-c", f"{write}{SQL}; SELECT engine || '/' || mode FROM lemma_last_query();"], cwd=user["cwd"],
                             env={**user["env"], "LEMMA_HOME": str(user["share"])}, capture_output=True, text=True, check=True).stdout
        con = duckdb.connect(str(user["db"]), read_only=True)
        want = sorted((s, str(c), str(sm)) for s, c, sm in con.execute(SQL).fetchall())
        con.close()
        lines = [line for line in csv.splitlines() if line]
        assert lines[-1] == "lemma/stream", csv
        got = sorted(tuple(line.rsplit(",", 2)) for line in lines[:-1])
        assert got == want and len(want) == (6 if write else 5), (got, want)

    # Full DuckDB in the same CLI: DDL, DML, a join with read_csv.
    plain = lemma(user, "duckdb", "-c", PLAIN_SQL.format(csv=user["tmp"] / "sales.csv"))
    assert plain.returncode == 0 and re.search(r"Lima\s*│\s*7", plain.stdout) and re.search(r"Oslo\s*│\s*5", plain.stdout)

    again = lemma(user, "optimize", "--db", str(user["db"]), "--sql", SQL)
    assert again.returncode == 0 and "already optimized" in again.stdout
    assert not (user["trap"] / "git_called").exists(), (user["trap"] / "git_called").read_text()
    user["executor"] = executor


def test_the_release_installs_and_runs_in_a_stock_ubuntu_22_04(user: dict) -> None:
    """install.sh in ubuntu:22.04 (glibc 2.35, no Python: uv brings it), then our DuckDB there: ordinary SQL, and the executor proved by the
    previous test (compiled in the prover image, glibc >= 2.34) answering the query. No Docker inside: proving needs the host's daemon."""
    executor = user.get("executor")
    if executor is None:
        pytest.skip("needs the executor of test_setup_optimize_and_run_in_duckdb_from_the_installed_wheel")
    if subprocess.run(["docker", "image", "inspect", "ubuntu:22.04"], capture_output=True).returncode != 0:
        pytest.skip("ubuntu:22.04 is not present (docker pull ubuntu:22.04)")
    box = user["tmp"] / "ubuntu"
    (box / "lemma_home" / "executors").mkdir(parents=True)
    (box / "bin").mkdir()
    shutil.copy2(shutil.which("uv"), box / "bin" / "uv")
    shutil.copytree(executor, box / "lemma_home" / "executors" / executor.name)
    shutil.copy2(user["db"], box / "shop.duckdb")
    shutil.copy2(user["tmp"] / "sales.csv", box / "sales.csv")
    script = f"""set -eu
export HOME=/box/home PATH=/box/home/.local/bin:/box/bin:/usr/bin:/bin LEMMA_HOME=/box/lemma_home UV_CACHE_DIR=/uvcache
mkdir -p $HOME
/release/install.sh
lemma duckdb -c "{PLAIN_SQL.format(csv='/box/sales.csv')}"
lemma duckdb /box/shop.duckdb -c "{SQL}; SELECT engine FROM lemma_last_query();"
lemma list
"""
    done = subprocess.run(
        ["docker", "run", "--rm", "--network", "host", "-u", f"{os.getuid()}:{os.getgid()}", "-v", f"{user['release']}:/release:ro",
         "-v", f"{box}:/box", "-v", f"{user['env']['UV_CACHE_DIR']}:/uvcache", "ubuntu:22.04", "bash", "-c", script],
        capture_output=True, text=True, timeout=1800, check=False,
    )
    print(done.stdout[-4000:], done.stderr[-3000:])
    assert done.returncode == 0
    assert re.search(r"Lima\s*│\s*7", done.stdout) and re.search(r"│\s*lemma\s*│", done.stdout) and executor.name[:12] in done.stdout
