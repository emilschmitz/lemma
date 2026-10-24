"""Fresh-machine smoke test of the downloadable product. Opt in (minutes; real Docker, real Verus):

    scripts/release/build_bundle.sh [--duckdb-build DIR]        # dist/lemma-<version>-linux-x86_64.tar.gz of HEAD
    uv run pytest -m slow tests/test_product_smoke.py -s

In an empty HOME: unpack the bundle, run its install.sh, then the README quick start with the installed `lemma` command only:
`lemma setup --auth api-key`, `lemma optimize` on a tiny DuckDB, `lemma list`, `lemma duckdb ... -c`, and the user's own DuckDB 1.5.6 (the
Python package) with the bundled extension loaded.

REAL: install.sh, the uv tool install of the wheel, the source tree it unpacks, Docker, the agent image (built by `lemma setup` if
missing), the sandbox self-test (needs internet for api.anthropic.com), Claude Code in the container, the egress bridge, the MCP host,
the spec, admission, Verus (both the pipeline's proof and the install's re-verification + library compile), the timed run against
DuckDB, the extension, the input cache.
MOCKED: the model. Claude Code talks to research_loop/scripts/mock_anthropic_api.py (through the real bridge, test-only override
LEMMA_TEST_MOCK_ANTHROPIC_*), which writes a fixed, already proved body (tests/fixtures/declarative_proofs/decline/group_count_sum_checked.rs)
into AGENT_EDIT, calls run_runquery, then submit_runquery. The API key is a dummy.
NOT FROM THE BUNDLE: Verus and the Rust toolchain are this machine's (~/tools/verus, ~/.rustup): the fresh HOME points at them with
LEMMA_VERUS_REAL / RUSTUP_HOME / CARGO_HOME, as a user who installed them would have them.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
VERUS = Path.home() / "tools" / "verus" / "verus"
BODY = ROOT / "tests" / "fixtures" / "declarative_proofs" / "decline" / "group_count_sum_checked.rs"
SQL = "SELECT report, COUNT(*) AS cnt, SUM(line) AS total FROM pre WHERE line > 5 GROUP BY report"
DUMMY_KEY = "sk-ant-api03-SMOKE-dummy-NOT-A-REAL-KEY-0000"

pytestmark = pytest.mark.slow


def _bundle() -> Path:
    found = sorted((ROOT / "dist").glob("lemma-*-linux-x86_64.tar.gz"), key=lambda p: p.stat().st_mtime)
    if not found:
        pytest.skip("no bundle: run scripts/release/build_bundle.sh first")
    bundle = found[-1]
    version = subprocess.run(["tar", "-xzOf", str(bundle), "--wildcards", "*/VERSION"], capture_output=True, text=True, check=True).stdout
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    assert f"source {head}" in version, f"{bundle.name} is not HEAD ({version.strip()}): rebuild it with scripts/release/build_bundle.sh"
    return bundle


@pytest.fixture(scope="module")
def user(tmp_path_factory: pytest.TempPathFactory) -> dict:
    if not (shutil.which("docker") and shutil.which("openssl") and shutil.which("uv") and VERUS.is_file()):
        pytest.skip("needs docker, openssl, uv and Verus at ~/tools/verus")
    bundle = _bundle()
    tmp = tmp_path_factory.mktemp("fresh_machine")
    home = tmp / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("LEMMA_") and k not in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "VIRTUAL_ENV")}
    env.update({
        "HOME": str(home),
        "PATH": f"{home / '.local' / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR") or str(Path.home() / ".cache" / "uv"),  # reuse downloads, nothing else
        "LEMMA_VERUS_REAL": str(VERUS),
        "RUSTUP_HOME": os.environ.get("RUSTUP_HOME") or str(Path.home() / ".rustup"),
        "CARGO_HOME": os.environ.get("CARGO_HOME") or str(Path.home() / ".cargo"),
        "ANTHROPIC_API_KEY": DUMMY_KEY,
    })
    subprocess.run(["tar", "-xzf", str(bundle), "-C", str(tmp)], check=True)
    (unpacked,) = [p for p in tmp.iterdir() if p.name.startswith("lemma-")]
    done = subprocess.run(["bash", str(unpacked / "install.sh")], cwd=tmp, env=env, capture_output=True, text=True, check=False)
    print(done.stdout[-1500:], done.stderr[-1500:])
    assert done.returncode == 0
    db = tmp / "shop.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE pre(line BIGINT, report BIGINT)")
    con.execute("INSERT INTO pre SELECT (i * 7) % 23, i % 5 FROM range(2000) r(i)")
    con.close()
    return {"home": home, "env": env, "db": db, "tmp": tmp, "share": home / ".local" / "share" / "lemma"}


def lemma(user: dict, *args: str, env: dict | None = None, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(["lemma", *args], cwd=user["tmp"], env=env or user["env"], capture_output=True, text=True, timeout=timeout, check=False)
    print(f"$ lemma {' '.join(args)}  (exit {done.returncode})\n{done.stdout[-4000:]}\n{done.stderr[-3000:]}")
    assert DUMMY_KEY not in done.stdout and DUMMY_KEY not in done.stderr
    return done


def test_install_lays_out_the_command_the_source_tree_and_the_duckdb_binaries(user: dict) -> None:
    share = user["share"]
    assert (user["home"] / ".local" / "bin" / "lemma").is_file()
    assert (share / "duckdb" / "duckdb").is_file() and (share / "duckdb" / "lemma.duckdb_extension").is_file()
    assert (share / "src" / "lemma.toml").is_file()
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=share / "src", capture_output=True, text=True, check=True)
    assert status.stdout == ""  # one clean commit: pipeline runs record it and do not refuse


def test_setup_optimize_list_and_run_in_duckdb_from_a_fresh_home(user: dict) -> None:
    from research_loop.agent_sandbox import MOCK_CA_ENV, MOCK_PORT_ENV
    from research_loop.scripts.mock_anthropic_api import Conversation, MockAnthropic, make_ca

    done = lemma(user, "setup", "--auth", "api-key", timeout=1800)
    assert done.returncode == 0 and "READY" in done.stdout and "[ok] prover: Verus" in done.stdout and "[ok] duckdb: v1.5.6" in done.stdout

    cert, key = make_ca(user["tmp"])
    with MockAnthropic(Conversation(BODY.read_text().strip("\n")), cert, key, user["tmp"] / "mock_requests.jsonl") as mock:
        env = {**user["env"], MOCK_PORT_ENV: str(mock.port), MOCK_CA_ENV: str(cert)}
        done = lemma(user, "optimize", "--db", str(user["db"]), "--sql", SQL, env=env)
    assert done.returncode == 0, done.stderr[-3000:]
    assert re.search(r"PROVED  \d+ verified, 0 errors \(Verus\)", done.stdout) and f"lemma duckdb {user['db']}" in done.stdout
    (executor,) = (user["share"] / "executors").iterdir()
    assert {"lib.so", "manifest.json", "optimize.json", "proved", "query.sql"} <= {p.name for p in executor.iterdir()}

    listed = lemma(user, "list")
    assert listed.returncode == 0 and executor.name[:12] in listed.stdout and "verified, 0 errors" in listed.stdout and SQL in listed.stdout

    # `lemma duckdb FILE -c SQL`: our DuckDB CLI, lemma_mode on, the installed executor answers.
    shown = lemma(user, "duckdb", str(user["db"]), "-c", f"{SQL}; SELECT engine FROM lemma_last_query();")
    assert shown.returncode == 0 and re.search(r"│\s*lemma\s*│", shown.stdout)

    # The user's own DuckDB 1.5.6 (Python), the bundled extension loaded: same rows as DuckDB, engine=lemma, then an input-cache hit.
    plain = duckdb.connect(str(user["db"]), read_only=True)
    want = sorted(plain.execute(SQL).fetchall())
    plain.close()
    con = duckdb.connect(str(user["db"]), read_only=True, config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{user['share'] / 'duckdb' / 'lemma.duckdb_extension'}'")
    con.execute(f"SET lemma_home = '{user['share']}'")
    con.execute("SET lemma_mode = true")
    runs = []
    for _ in range(2):
        got = sorted(con.execute(SQL).fetchall())
        runs.append((got, con.execute("SELECT engine, cache, query_key FROM lemma_last_query()").fetchone()))
    con.close()
    print("plain:", want, "\nlemma:", runs)
    assert len(want) == 5
    (first, (engine1, cache1, key1)), (second, (engine2, cache2, _)) = runs
    assert first == want and second == want
    assert engine1 == "lemma" and engine2 == "lemma" and key1 == executor.name
    assert cache1.startswith("miss") and cache2 == "hit"

    # --bench on the installed executor: the in-DuckDB measure (cold and warm) against DuckDB, no new pipeline run.
    timed = lemma(user, "optimize", "--db", str(user["db"]), "--sql", SQL, "--bench")
    assert timed.returncode == 0 and "already optimized" in timed.stdout and re.search(r"bench \(in DuckDB.*cold .* vs DuckDB .*warm", timed.stdout)

    assert lemma(user, "remove", executor.name[:10]).returncode == 0 and not executor.exists()
