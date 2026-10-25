"""lemma.toml ``prover``: the docker prover (docker/prover/Dockerfile) gives the same spec, the same Verus verdict and the same program output
as the host install. Opt in (real Docker, real Verus on both sides): ``uv run pytest -m slow tests/test_prover_docker.py``."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from declarative_spec import pipeline, prover, schema_types, vstd_index
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
from tests.test_assumptions_off_fixtures import CASES, FIXTURES, GUARD, _columns

pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def _both_provers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if not VERUS_CANDIDATES[0].is_file():
        pytest.skip("no host Verus at [prover] verus_home")
    if subprocess.run(["docker", "image", "inspect", prover.image()], capture_output=True, check=False).returncode != 0:
        pytest.skip(f"no prover image {prover.image()} (lemma setup, or docker build -t {prover.image()} docker/prover)")
    monkeypatch.delenv("LEMMA_ASSUMPTIONS", raising=False)
    monkeypatch.delenv("LEMMA_ASSUMPTION_PACKAGE", raising=False)
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(GUARD))
    monkeypatch.setenv("LEMMA_HEAVY_LOCK", str(tmp_path / "lock"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))  # the image's vstd is copied out afresh


def _use(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("LEMMA_PROVER", mode)
    for cached in (vstd_index.vstd_modules, vstd_index.broadcast_groups, schema_types.ambiguous_verus_names):
        cached.cache_clear()


def _program(name: str, column_bins: dict[str, str] | None = None) -> str:
    sql, schema = CASES[name]
    return assemble_declarative_program(emit_declarative_spec(sql, schema, None), (FIXTURES / name).read_text(), column_bins=column_bins)


def _summary(log: str) -> str:
    found = re.findall(r"verification results:: \d+ verified, \d+ errors", log)
    assert found, log[-3000:]
    return found[-1]


@pytest.mark.parametrize("name", ["group_count_sum_checked.rs", "join_group_sum_checked.rs", "usum_unchecked_must_fail.rs"])
def test_the_same_program_gets_the_same_verdict_on_host_and_in_docker(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}
    for mode in ("host", "docker"):
        _use(monkeypatch, mode)
        program = _program(name)
        ok, log = verify_assembled(program, timeout_sec=3000)
        seen[mode] = (program, ok, _summary(log))
        print(mode, name, seen[mode][1:])
    assert seen["host"] == seen["docker"]  # byte-identical spec + assembled program, same Verus line
    assert seen["docker"][1] == (name != "usum_unchecked_must_fail.rs")


def test_a_program_compiled_in_docker_prints_the_same_rows_as_the_host_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bins = tmp_path / "pre.bin"
    _columns(bins, [(150, 10), (250, 3), (-25, 7), (99, 6)])
    rows = {}
    for mode in ("host", "docker"):
        _use(monkeypatch, mode)
        metrics = pipeline.compile_and_run(_program("usum_checked.rs", column_bins={"pre": str(bins)}), work_dir=tmp_path / mode, timeout_sec=3000)
        assert metrics["status"] == "SUCCESS", metrics.get("compiler_error", "")[-2000:]
        rows[mode] = [line for line in metrics["stdout"].splitlines() if line.startswith("ROW")]
    assert rows["host"] == rows["docker"] == ["ROW\u001f224"]  # 150 - 25 + 99
