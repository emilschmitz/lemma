"""The shelved float error-bound lemmas (`declarative_spec/future_float_error_bounds/`) are invisible.

The prover agent only ever sees ACTIVE code. Nothing the agent can read (spec, host lemma block, lemma index, prompt,
`context/ro/` tree with the examples and docs mounts) may contain a name from the archive, a body that calls an archived
name is just an unknown-name compile failure (no special casing), and no pipeline module imports the archive.
The name list is derived from the archive itself so it cannot drift. The same rule holds for any lemma archived later:
add its folder to `ARCHIVES`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from declarative_spec.admit import admit_declarative_body, host_names
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.drive import _ensure_context_files
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.lemmas import float_error_lemmas_rs
from declarative_spec.prompt import build_declarative_prompt
from declarative_spec.trusted_sets import current
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

ROOT = Path(__file__).resolve().parent.parent
ARCHIVES = [ROOT / "declarative_spec" / "future_float_error_bounds"]
VERUS = Path("/home/emil/tools/verus/verus")

_FN = re.compile(r"\b(?:pub\s+)?(?:open\s+spec\s+|uninterp\s+spec\s+|proof\s+|spec\s+)?fn\s+([A-Za-z_]\w*)")


def _archive_rust_sources() -> list[str]:
    """Every Rust snippet of the archive: the `.rs` files and the Rust strings of the python modules."""
    texts = [p.read_text() for a in ARCHIVES for p in a.rglob("*.rs")]
    for a in ARCHIVES:
        for py in a.glob("*.py"):
            namespace: dict = {}
            code = py.read_text()
            if "def " not in code:
                continue
            spec = compile(code, str(py), "exec")
            exec(spec, namespace)  # noqa: S102 - our own archived module, to read the Rust it returns
            for name, fn in list(namespace.items()):
                if name.endswith("_rs") and callable(fn):
                    texts.append(fn())
    return texts


def shelved_names() -> set[str]:
    """Names the archive defines or uses that the active code does not define itself."""
    archived: set[str] = set()
    for text in _archive_rust_sources():
        archived |= set(_FN.findall(text))
    archived |= {"FLOAT_ABS_EPS", "host_error_exceeds_eps", "default_float_abs_eps"}
    active = set(_FN.findall(float_error_lemmas_rs()))
    for fixture in (ROOT / "tests" / "fixtures" / "declarative_proofs").rglob("*.rs"):
        active |= set(_FN.findall(fixture.read_text()))  # generic helper names an active fixture defines itself
    return archived - active


SCHEMA = {"t": {"k": "integer", "v": "double", "i": "bigint"}}
CATALOG = CatalogAssumptions(
    max_rows=100,
    tables={"t": TableAssumptions(max_rows=100, columns={"v": ColumnAssumption(max_value_exclusive=1024)})},
)
QUERIES = {
    "float": "SELECT k, SUM(v) AS s, AVG(v) AS a FROM t WHERE v > 1.5 GROUP BY k",
    "integer": "SELECT k, COUNT(*) AS c FROM t GROUP BY k",
}


def test_the_name_list_is_derived_and_not_empty() -> None:
    names = shelved_names()
    for expected in (
        "lemma_f64_sum_within_eps",
        "lemma_f64_left_fold_push",
        "f64_left_fold",
        "host_f64_sum_error",
        "real_sum_seq",
        "lemma_f64_add_exact",
        "host_u64_to_f64_exact",
        "f64_exact_int_max",
        "FLOAT_ABS_EPS",
    ):
        assert expected in names, expected
    # Active names are never in the list.
    assert not names & set(_FN.findall(float_error_lemmas_rs()))


def _contains_word(text: str, name: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text) is not None


def test_the_default_trusted_set_contains_no_shelved_name() -> None:
    names = shelved_names()
    block = current().lemmas_rs()
    index = current().index_markdown()
    for name in names:
        assert not _contains_word(block, name), f"host lemma block mentions {name}"
        assert not _contains_word(index, name), f"lemma index mentions {name}"


@pytest.mark.parametrize("kind", list(QUERIES))
def test_the_built_agent_workspace_contains_no_shelved_name(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from declarative_spec import drive
    from declarative_spec.verus_docs import DOCS_CACHE

    if not DOCS_CACHE.is_dir():  # the downloaded vstd/Verus docs are host-fetched; when absent, only they are skipped
        monkeypatch.setattr(drive, "mount_verus_docs", lambda ro: None)
    sql = QUERIES[kind]
    spec = emit_declarative_spec(sql, SCHEMA, CATALOG)
    _ensure_context_files(tmp_path, sql_query=sql, resolved_schema=SCHEMA, spec_text=spec)
    prompt = build_declarative_prompt(
        sql=sql,
        spec_path="context/ro/spec.rs",
        edit_path="runquery_agent.rs",
        lemma_index=current().index_markdown(),
        spec_text=spec,
    )
    ro = tmp_path / "context" / "ro"
    files = [p for p in ro.rglob("*") if p.is_file()]
    assert any(p.name == "spec.rs" for p in files) and any(p.name == "lemma_index.md" for p in files)
    assert any(p.parent.name == "examples" for p in files)
    names = shelved_names()
    texts = {str(p.relative_to(tmp_path)): p.read_text(errors="ignore") for p in files}
    texts["<prompt>"] = prompt
    for where, text in texts.items():
        for name in names:
            assert not _contains_word(text, name), f"{where} mentions the shelved name {name}"


def test_mounted_examples_never_come_from_the_archive() -> None:
    from declarative_spec import prompt as prompt_module

    mounted = {name for name, _what in prompt_module._EXAMPLES.values()}
    mounted |= {p.name for p in prompt_module._FIXTURES.glob("float_*.rs")}
    archived = {p.name for a in ARCHIVES for p in a.rglob("*.rs")}
    assert mounted and not mounted & archived
    for p in prompt_module._FIXTURES.glob("float_*.rs"):
        text = p.read_text()
        for name in shelved_names():
            assert not _contains_word(text, name), f"{p.name} uses the shelved name {name}"


@pytest.mark.parametrize("kind", list(QUERIES))
def test_the_emitted_spec_never_mentions_the_archive(kind: str) -> None:
    spec = emit_declarative_spec(QUERIES[kind], SCHEMA, CATALOG)
    for word in ("future_float_error_bounds", "shelved", "archive"):
        assert word not in spec.lower(), word


def test_a_body_calling_a_shelved_name_is_just_an_unknown_name() -> None:
    spec = emit_declarative_spec(QUERIES["float"], SCHEMA, CATALOG)
    for name in ("lemma_f64_sum_within_eps", "lemma_f64_left_fold_push", "host_u64_to_f64_exact"):
        body = f"    proof {{ {name}(); }}\n    Vec::new()\n"
        assert name not in host_names(spec)
        result = admit_declarative_body(body)
        assert result.ok, result.violations  # admission has no special case for it
        if VERUS.is_file():
            program = assemble_declarative_program(spec, body)
            path = Path("/tmp") / f"unknown_{name}.rs"
            path.write_text(program)
            proc = subprocess.run(
                [str(ROOT / "scripts" / "ram" / "verus_guarded.sh"), str(path), "--crate-type=lib"],
                capture_output=True,
                text=True,
                check=False,
            )
            out = proc.stdout + proc.stderr
            path.unlink(missing_ok=True)
            assert f"cannot find function `{name}`" in out, out[-1500:]


def test_nothing_in_the_pipeline_imports_the_archive() -> None:
    needle = "future_float_error_bounds"
    allowed = {a.name for a in ARCHIVES}
    offenders = []
    for base in ("declarative_spec", "research_loop", "db_extension", "verus_transpiler", "scripts"):
        for py in (ROOT / base).rglob("*.py"):
            if any(part in allowed for part in py.parts) or py.name.startswith("test_"):
                continue
            if re.search(rf"(import|from)\s+[\w.]*{needle}", py.read_text(errors="ignore")):
                offenders.append(str(py.relative_to(ROOT)))
    assert not offenders, offenders
    probe = (
        "import sys\n"
        "import declarative_spec.emit, declarative_spec.assemble, declarative_spec.admit, declarative_spec.trusted_sets\n"
        "import declarative_spec.prompt, declarative_spec.lemma_index, declarative_spec.drive, declarative_spec.pipeline\n"
        f"assert not [m for m in sys.modules if '{needle}' in m], [m for m in sys.modules if '{needle}' in m]\n"
    )
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=ROOT, check=False)
    assert proc.returncode == 0, proc.stderr[-1500:]
