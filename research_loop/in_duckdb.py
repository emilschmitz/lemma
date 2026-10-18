"""Lemma inside DuckDB: the executor cache the DuckDB extension (db_extension/duckdb_ext) reads, behind lemma.toml ``in_duckdb``.

An executor is one proved query compiled as a shared library with the fixed C entry point ``lemma_run``
(:mod:`declarative_spec.assemble_library`). Layout, shared with the ``lemma`` CLI:

    ${LEMMA_HOME:-~/.local/share/lemma}/executors/<key>/lib.so          the verified cdylib
    ${LEMMA_HOME:-~/.local/share/lemma}/executors/<key>/manifest.json    tables/columns/types to scan, result types, params, hashes
    ${LEMMA_HOME:-~/.local/share/lemma}/executors/<key>/query.sql        the SQL text
    ${LEMMA_HOME:-~/.local/share/lemma}/queue/<key>.sql                  misses the extension enqueued for `lemma optimize`

``<key>`` = sha256 (hex) of :func:`normalize_sql` of the SQL text, UTF-8. The C++ mirror is ``NormalizeSql`` in
``db_extension/duckdb_ext/src/lemma_extension.cpp``; ``tests/test_in_duckdb.py`` checks both agree.

Normalization (a cache key, never a rewrite of what runs): outside quotes and comments, every run of whitespace
(space, tab, newline, carriage return, form feed, vertical tab) becomes one space; text inside '...' and "..." and inside
comments (``--`` to the end of the line, the newline included; ``/* ... */``) is copied byte for byte; leading and trailing
whitespace and trailing semicolons are removed. Case is kept. If the text has a ``$`` outside quotes and comments
(dollar quoting, ``$1`` parameters) only the leading/trailing whitespace and trailing semicolons are removed. Two texts with
the same normalized form are the same query to DuckDB's parser; the extension also compares the full normalized text
with the manifest, so a hash collision cannot pick another query's executor.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import duckdb
import lemma_config

from declarative_spec import decline
from declarative_spec.assemble_library import ABI_VERSION, assemble_library_program, input_layout, output_layout, param_layout
from declarative_spec.emit import emit_declarative_spec
from research_loop.decl_query_measure import _DECIMAL_TYPE, plan_tables
from research_loop.table_assumptions import CatalogAssumptions

MANIFEST_FORMAT = 1
_WS = " \t\n\r\f\v"
_PROOF = re.compile(r"verification results:: (\d+ verified, 0 errors)\s*$", re.M)
_INT_DUCK = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT")


class InDuckdbDisabled(RuntimeError):
    """The ``in_duckdb`` flag of lemma.toml is off: no library is emitted and nothing is installed."""


def enabled() -> bool:
    return bool(lemma_config.get("in_duckdb"))


def require_enabled() -> None:
    if not enabled():
        raise InDuckdbDisabled("in_duckdb is off: set in_duckdb = true in lemma.toml [engine] (or LEMMA_IN_DUCKDB=true)")


def normalize_sql(sql: str) -> str:
    """The cache-key form of ``sql`` (module docstring). Mirrored byte for byte by the extension's ``NormalizeSql``."""
    out: list[str] = []
    i, n = 0, len(sql)
    pending_space = False
    while i < n:
        c = sql[i]
        if c in _WS:
            pending_space = True
            i += 1
            continue
        if pending_space and out:
            out.append(" ")
        pending_space = False
        if c in "'\"":
            j = sql.find(c, i + 1)
            j = n if j == -1 else j + 1  # an unterminated quote runs to the end (DuckDB rejects it anyway)
            out.append(sql[i:j])
            i = j
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j + 1
            out.append(sql[i:j])
            i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(sql[i:j])
            i = j
        elif c == "$":
            return _strip_end(sql)
        else:
            out.append(c)
            i += 1
    return _strip_end("".join(out))


def _strip_end(text: str) -> str:
    text = text.strip(_WS)
    while text.endswith(";"):
        text = text[:-1].rstrip(_WS)
    return text


def executor_key(sql: str) -> str:
    return hashlib.sha256(normalize_sql(sql).encode("utf-8")).hexdigest()


def lemma_home() -> Path:
    home = os.environ.get("LEMMA_HOME", "").strip()
    return Path(home) if home else Path.home() / ".local" / "share" / "lemma"


def executor_dir(sql: str, home: Path | None = None) -> Path:
    return (home or lemma_home()) / "executors" / executor_key(sql)


def _duck_types(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, str]:
    q = '"' + table.replace('"', '""') + '"'
    return {str(name).casefold(): str(ty) for name, ty, *_ in con.execute(f"DESCRIBE {q}").fetchall()}


def output_descriptors(sql: str, spec: str, con: duckdb.DuckDBPyConnection) -> list[dict]:
    """One entry per result column: DuckDB's name and type for ``sql`` and the OutRow field that fills it."""
    fields = output_layout(spec)
    described = con.execute(f"DESCRIBE {sql}").fetchall()
    if len(described) != len(fields):
        raise ValueError(f"DuckDB returns {len(described)} columns, OutRow has {len(fields)}")
    scales_match = re.search(r"^// OUT_SCALES: ([0-9,]+)$", spec, re.M)
    scales = [int(x) for x in scales_match.group(1).split(",")] if scales_match else [0] * len(fields)
    out = []
    for (name, duck_type, *_), (field, rust), scale in zip(described, fields, scales, strict=True):
        duck_type = str(duck_type)
        inner = rust[len("Option<") : -1] if rust.startswith("Option<") else rust
        dec = _DECIMAL_TYPE.fullmatch(duck_type)
        if inner == "String":
            ok = duck_type == "VARCHAR"
        elif inner == "f64":
            ok = duck_type in ("DOUBLE", "FLOAT")
        elif inner == "bool":
            ok = duck_type == "BOOLEAN"
        else:
            ok = (dec is not None and int(dec.group(2)) == scale) or (scale == 0 and (duck_type in _INT_DUCK or duck_type == "DATE"))
        if not ok:
            raise ValueError(f"result column {name}: OutRow.{field} {rust} (scale {scale}) cannot hold DuckDB {duck_type}")
        out.append({"name": str(name), "duck_type": duck_type, "field": field, "rust_type": rust, "scale": scale})
    return out


def template_params(sql: str, spec: str) -> tuple[str, list[dict]]:
    """``(fixed-constant SQL to describe and plan the scan with, manifest params)`` of a query template; ``(sql, [])`` otherwise.

    The scan and the result types do not depend on the values, so the template is instantiated at one in-range value per
    parameter (its ``requires`` low end; 0 / the empty string when it has no range). Each manifest param: name, SQL type,
    the Rust type ``run_query`` takes, its scale (DECIMAL) and the range the library checks."""
    from declarative_spec import templates

    template = templates.parse_template(sql)
    if template is None:
        return sql, []
    ranges = {name: (ty, lo, hi) for name, ty, lo, hi in templates.spec_params(spec)}
    if [p.name for p in template.params] != list(ranges):
        raise ValueError(f"spec parameters {list(ranges)} are not the template's {[p.name for p in template.params]} in order")
    binding: dict[str, str] = {}
    out: list[dict] = []
    for p in template.params:
        rust, lo, hi = ranges[p.name]
        if rust != p.rust:
            raise ValueError(f"parameter {p.name}: the spec takes {rust}, the template declares {p.sql_type} ({p.rust})")
        binding[p.name] = "" if p.kind == "VARCHAR" else templates.text_of(p, lo if lo is not None else 0)
        out.append({"name": p.name, "sql_type": p.sql_type, "rust_type": rust, "scale": p.scale, "lo": lo, "hi": hi})
    return templates.instantiate(template, binding), out


def compile_library(rs_source: str, work_dir: Path, *, timeout_sec: int | None = None) -> tuple[Path, str]:
    """Verify and compile the library program to a cdylib: ``(path of the .so, "N verified, 0 errors")``. Loud on any failure."""
    from declarative_spec.pipeline import _verus_binary, target_cpu_rustc_args
    from declarative_spec.verus_limits import run_verus, verus_limit_args, verus_timeout_sec

    work_dir.mkdir(parents=True, exist_ok=True)
    rs = work_dir / "lemma_query.rs"
    rs.write_text(rs_source)
    proc = run_verus(
        [
            _verus_binary(), str(rs), "--triggers-mode", "silent", *verus_limit_args(), "--crate-type=cdylib", "--compile",
            "--", "-C", "opt-level=3", "-C", "codegen-units=1", *target_cpu_rustc_args(),
        ],
        timeout=verus_timeout_sec() if timeout_sec is None else timeout_sec,
        cwd=work_dir,
    )
    log = (proc.stdout or "") + "\n" + (proc.stderr or "")
    (work_dir / "verify_full.log").write_text(log)
    proof = _PROOF.search(log)
    lib = work_dir / "liblemma_query.so"
    if proc.returncode != 0 or proof is None or not lib.is_file():
        raise RuntimeError(f"library did not verify and compile (exit {proc.returncode}):\n{log[-3000:]}")
    return lib, proof.group(1)


def _git() -> tuple[str, bool]:
    root = Path(__file__).resolve().parents[1]
    sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, check=True).stdout.strip())
    return sha, dirty


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def install_executor(
    *,
    sql: str,
    schema: dict,
    catalog: CatalogAssumptions | None,
    agent_source: str,
    db_path: Path,
    home: Path | None = None,
    work_dir: Path | None = None,
) -> Path:
    """Emit the spec, admit the body, assemble library mode, verify + compile, and install ``executors/<key>/``. Returns the dir.

    The manifest records what the extension needs and checks: the input layout with the DuckDB column types read at install,
    the result types, the DuckDB version, the proof line, the spec and library hashes, the git commit."""
    require_enabled()
    from declarative_spec.admit import admit_declarative_body, admit_helpers
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers

    spec = emit_declarative_spec(sql, schema, catalog)
    if "AGENT_EDIT_START" in agent_source:
        body, helpers = extract_agent_edit(agent_source), extract_agent_helpers(agent_source)
    else:
        body, helpers = agent_source.strip(), ""
    violations = list(admit_declarative_body(body).violations)
    if helpers:
        violations += admit_helpers(helpers, spec).violations
    if violations:
        raise ValueError("; ".join(violations))
    program = assemble_library_program(spec, body, helpers=helpers, sql=sql)
    plain_sql, params = template_params(sql, spec)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        inputs = input_descriptors(plain_sql, schema, catalog, spec, con)
        outputs = output_descriptors(plain_sql, spec, con)
    finally:
        con.close()
    home = home or lemma_home()
    key = executor_key(sql)
    final = home / "executors" / key
    final.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{key[:12]}-", dir=final.parent))
    try:
        lib, proof = compile_library(program, work_dir or (stage / "build"))
        shutil.copyfile(lib, stage / "lib.so")
        sha, dirty = _git()
        manifest = {
            "format": MANIFEST_FORMAT,
            "abi_version": ABI_VERSION,
            "in_duckdb": True,
            # lemma.toml assumptions of the spec this executor proves: false = no data assumptions, run_query may decline (lemma_run status 1).
            "assumptions": not decline.is_decline_spec(spec),
            "key": key,
            "sql": sql,
            "normalized_sql": normalize_sql(sql),
            "duckdb_version": "v" + duckdb.__version__,
            "git_sha": sha,
            "git_dirty": dirty,
            "proof": proof,
            "spec_sha256": hashlib.sha256(spec.encode("utf-8")).hexdigest(),
            "lib_sha256": _sha256_file(stage / "lib.so"),
            "target_cpu": str(lemma_config.get("target_cpu")),
            "params": params,
            "param_layout": param_layout(spec),
            "input_layout": input_layout(spec),
            "output_layout": [f"{f} {t}" for f, t in output_layout(spec)],
            "inputs": inputs,
            "outputs": outputs,
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
        (stage / "query.sql").write_text(sql + "\n")
        shutil.rmtree(stage / "build", ignore_errors=True)
        if final.exists():
            shutil.rmtree(final)
        stage.rename(final)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return final


def input_descriptors(sql: str, schema: dict, catalog: CatalogAssumptions | None, spec: str, con: duckdb.DuckDBPyConnection) -> list[dict]:
    """One entry per ``LemmaCol``, in the order of ``lemma_input_layout``: what the extension scans and how it encodes each cell.

    The encodings are those of the column-file exporter (``decl_query_measure._encode_columns``): a DATE is days since
    1970-01-01, a DECIMAL the integer value * 10**scale (the spec's scale), a dictionary column u8/u16/u32 codes numbering the
    distinct non-NULL strings in order of first appearance in the scan, a NULL cell of a nullable column the zero cell
    (code 0), a NULL in a column not declared nullable an error."""
    plans = plan_tables(sql, schema, catalog, spec)
    layout = input_layout(spec)
    out: list[dict] = []
    for suffix, (table, names, types, infos, nullable, dict_of, valid_fields) in plans.items():
        duck = _duck_types(con, table)
        if layout[len(out)] != f"rows {suffix}":
            raise ValueError(f"library layout {layout[len(out)]!r} is not the rows entry of {suffix}")
        out.append({"kind": "rows", "suffix": suffix, "table": table})
        first = len(out)
        for idx, fty in enumerate(types):
            base = duck[names[idx].casefold()]
            entry: dict = {
                "kind": "field", "suffix": suffix, "table": table, "column": names[idx], "rust_type": fty,
                "duck_type": base, "nullable": bool(nullable[idx]), "scale": 0, "source_scale": 0,
            }
            dec = _DECIMAL_TYPE.fullmatch(base)
            if idx in valid_fields:
                role = "valid"
            elif idx in dict_of:
                role = "dict"
                entry["codes_of"] = first + dict_of[idx]
            elif fty in ("u8", "u16", "u32") and infos[idx].exec_rust == "String":
                role = "code"
            elif fty == "String":
                role = "string"
            elif fty == "bool":
                role = "bool"
            elif fty == "f64":
                role = "f64"
            elif infos[idx].is_date:
                role = "date"
            elif dec:
                role = "decimal"
            else:
                role = "int"
            if dec and role in ("f64", "decimal"):
                entry["scale"], entry["source_scale"] = int(infos[idx].scale), int(dec.group(2))
                if entry["source_scale"] > entry["scale"]:
                    raise ValueError(f"{table}.{names[idx]} has more than {entry['scale']} fractional digits")
            if role in ("string", "code", "dict") and base != "VARCHAR":
                raise ValueError(f"{table}.{names[idx]}: in-DuckDB scans read strings from VARCHAR columns only, not {base}")
            if role == "date" and base != "DATE":
                raise ValueError(f"{table}.{names[idx]}: a date field over {base}")
            if role == "bool" and base != "BOOLEAN":
                raise ValueError(f"{table}.{names[idx]}: a bool field over {base}")
            entry["role"] = role
            line = layout[len(out)]
            if not line.startswith(f"{suffix}.") or not line.endswith(f" {fty}"):
                raise ValueError(f"library layout {line!r} does not match {table}.{names[idx]} {fty}")
            entry["field"] = line[len(suffix) + 1 : -len(fty) - 1]
            out.append(entry)
    if [e["kind"] == "rows" for e in out] != [line.startswith("rows ") for line in layout]:
        raise ValueError(f"manifest inputs do not follow the library layout {layout}")
    return out
