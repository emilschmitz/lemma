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
import tempfile
from pathlib import Path

import duckdb
import lemma_config

from declarative_spec import decline
from declarative_spec.assemble_library import (
    ABI_VERSION,
    STREAM_ABI_VERSION,
    assemble_library_program,
    assemble_stream_library_program,
    input_layout,
    output_layout,
    param_layout,
    stream_layout,
)
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.sql_text import _WS, _ident_char, _opaque_end, _string_end, _strip_end, literal_at, normalize_sql  # noqa: F401  (moved; re-exported)
from research_loop.decl_query_measure import _DECIMAL_TYPE, plan_tables
from research_loop.table_assumptions import CatalogAssumptions

MANIFEST_FORMAT = 1
_PROOF = re.compile(r"verification results:: (\d+ verified, 0 errors)\s*$", re.M)
_INT_DUCK = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT")


class InDuckdbDisabled(RuntimeError):
    """The ``in_duckdb`` flag of lemma.toml is off: no library is emitted and nothing is installed."""


def enabled() -> bool:
    return bool(lemma_config.get("in_duckdb"))


def require_enabled() -> None:
    if not enabled():
        raise InDuckdbDisabled("in_duckdb is off: set in_duckdb = true in lemma.toml [engine] (or LEMMA_IN_DUCKDB=true)")


# ---- query templates: the literal tokens the extension's matcher binds, and the template index -----------------------------------
#
# A template executor is listed in ``<home>/templates/<template_index_key>/<executor key>`` (an empty file). The extension looks a query
# without an exact executor up there by the same key computed from the query (``lemma::TemplateSkeleton`` in
# db_extension/duckdb_ext/src/lemma_util.cpp, mirrored here; tests check both agree), then matches it character for character against
# the template (``lemma::MatchTemplate``): the query must BE the template's text with one literal token per placeholder.


_PLACEHOLDER = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def template_skeleton(normalized: str) -> str:
    """``normalized`` with every ``$name`` and every literal token (:func:`literal_at`) replaced by ``?``; quoted identifiers and
    comments are kept. Mirror of ``lemma::TemplateSkeleton``."""
    out: list[str] = []
    i, n = 0, len(normalized)
    while i < n:
        m = _PLACEHOLDER.match(normalized, i)
        if m:
            out.append("?")
            i = m.end()
            continue
        lit = literal_at(normalized, i)
        if lit is not None:
            out.append("?")
            i = lit[1]
            continue
        j = _opaque_end(normalized, i)
        if j > i:
            out.append(normalized[i:j])
            i = j
            continue
        out.append(normalized[i])
        i += 1
    return "".join(out)


def template_body(sql: str) -> str:
    """A query template without its ``-- params:`` header line (``templates.parse_template``); other SQL as is."""
    from declarative_spec.templates import _HEADER

    m = _HEADER.search(sql)
    return sql if m is None else sql[: m.start()] + sql[m.end() :]


def template_index_key(sql: str) -> str:
    """The key the extension finds this executor's template (or a query that instantiates it) under."""
    return hashlib.sha256(template_skeleton(normalize_sql(template_body(sql), keep_dollar=True)).encode("utf-8")).hexdigest()


def index_template(home: Path, key: str, sql: str) -> None:
    """List the template executor ``key`` under its template index key (idempotent)."""
    entry = home / "templates" / template_index_key(sql) / key
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.touch()


def unindex_template(home: Path, key: str, sql: str) -> None:
    entry = home / "templates" / template_index_key(sql) / key
    entry.unlink(missing_ok=True)
    try:
        entry.parent.rmdir()
    except OSError:
        pass  # another template shares the skeleton (or it is gone)


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
        elif inner in ("f64", "Rat"):  # an exact rational (lemma.toml [sql] exact_division) leaves the library as its double num / den
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


def _provenance() -> dict:
    """``git_sha`` / ``git_dirty`` of the checkout. An installed wheel has no git: ``git_sha`` is the commit the wheel was built from (its
    BUILD_INFO; the extension reads this field as a string), ``git_dirty`` None, and ``package`` the version and wheel hash."""
    state = lemma_config.git_state()
    if "package" in state:
        return {"git_sha": state["package"]["source_commit"] or "", "git_dirty": None, "package": state["package"]}
    return {"git_sha": state["git_sha"], "git_dirty": state["git_dirty"]}


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
    abi: int = ABI_VERSION,
) -> Path:
    """Emit the spec, admit the body, assemble library mode, verify + compile, and install ``executors/<key>/``. Returns the dir.

    The manifest records what the extension needs and checks: the input layout with the DuckDB column types read at install,
    the result types, the DuckDB version, the proof line, the spec and library hashes, the git commit. ``abi`` 4 installs a
    version-4 library (no ``lemma_run_borrowed``; for tests of the extension's version-4 path).

    A stream spec (lemma.toml [run] stream, docs/STREAM.md) installs a STREAMING executor: ``agent_source`` holds the six regions
    (AGENT_STATE / HELPERS / INIT / STEP / MERGE / FINISH, admitted by ``admit_stream``), the library is the ABI 6 template
    (``assemble_stream_library_program``; ``abi`` is then 6 whatever was passed), and the manifest says ``mode: "stream"`` with a
    ``stream`` section (the chunk layout). No pushed predicate (docs/STREAM.md: the proved step evaluates the WHERE).

    A stream JOIN (phase 2a, ``stream_join.is_join``): ``sql`` must carry the run's ``-- stream: <table>`` line (the recorded choice,
    ``<run dir>/stream_choice.json``; emitting a join without it is refused). The agent source holds seven regions (also AGENT_BUILD),
    the library is the Pool template, the manifest's ``stream`` section names the streamed table and the build tables (Cols suffixes,
    q_build's order), and each BUILD table's rows entry gets its own pushed single-table predicate (``where``) whatever lemma.toml
    ``pushdown`` says: the extension materializes the build tables through the ABI 5 input path, and the spec re-applies the WHERE to
    every pair, so dropping build rows that fail a conjunct of their own table is sound (declarative_spec/pushdown.py). The streamed
    table is never filtered. The executor's key and SQL are the query WITHOUT the ``-- stream:`` line (what a caller sends); the choice
    lives in the manifest and in the spec."""
    require_enabled()
    from declarative_spec import stream
    from declarative_spec.admit import admit_declarative_body, admit_helpers, admit_stream
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers

    spec = emit_declarative_spec(sql, schema, catalog)
    streaming = stream.is_stream(spec)
    from declarative_spec import stream_join

    join = streaming and stream_join.is_join(spec)
    query_sql = without_stream_header(sql) if join else sql  # the key, the manifest's SQL and the library's lemma_query_sql
    if streaming:
        regions = stream.extract_regions(agent_source)
        violations = list(admit_stream(**regions, spec_rs=spec).violations)
        if violations:
            raise ValueError("; ".join(violations))
        program = assemble_stream_library_program(spec, regions, sql=query_sql)
        abi = STREAM_ABI_VERSION
    else:
        if "AGENT_EDIT_START" in agent_source:
            body, helpers = extract_agent_edit(agent_source), extract_agent_helpers(agent_source)
        else:
            body, helpers = agent_source.strip(), ""
        violations = list(admit_declarative_body(body).violations)
        if helpers:
            violations += admit_helpers(helpers, spec).violations
        if violations:
            raise ValueError("; ".join(violations))
        program = assemble_library_program(spec, body, helpers=helpers, sql=sql, abi=abi)
    plain_sql, params = template_params(sql, spec)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        inputs = input_descriptors(plain_sql, schema, catalog, spec, con)
        outputs = output_descriptors(plain_sql, spec, con)
    finally:
        con.close()
    if not streaming:
        add_pushdown(inputs, sql, schema)
    elif join:
        builds = stream_builds(spec)
        add_pushdown(inputs, sql, schema, suffixes=set(builds), always=True)
    home = home or lemma_home()
    key = executor_key(query_sql)
    final = home / "executors" / key
    final.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{key[:12]}-", dir=final.parent))
    try:
        lib, proof = compile_library(program, work_dir or (stage / "build"))
        shutil.copyfile(lib, stage / "lib.so")
        provenance = _provenance()
        manifest = {
            "format": MANIFEST_FORMAT,
            "abi_version": abi,
            "in_duckdb": True,
            # lemma.toml assumptions of the spec this executor proves: false = no data assumptions, run_query may decline (lemma_run status 1).
            "assumptions": not decline.is_decline_spec(spec),
            "key": key,
            "sql": query_sql,
            "normalized_sql": normalize_sql(query_sql),
            "duckdb_version": "v" + duckdb.__version__,
            **provenance,
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
        if streaming:
            # ABI 6: the extension's StreamTable hands DuckDB's chunks to the library in this column order (lemma_stream_layout).
            manifest["mode"] = "stream"
            manifest["stream"] = {"layout": stream_layout(spec), "pushdown": False}
            if join:
                # the streamed table and the build tables (Cols suffixes; the builds in q_build's order = lemma_stream_builds)
                manifest["stream"]["table"] = stream_table(spec)
                manifest["stream"]["builds"] = builds
                manifest["stream"]["stream_header"] = f"-- stream: {stream_join.header_table(sql)}"
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
        (stage / "query.sql").write_text(query_sql + "\n")
        shutil.rmtree(stage / "build", ignore_errors=True)
        if final.exists():
            # Replace in two renames, so a reader never sees a half-removed executor: the old one leaves under a dot name first.
            old = final.parent / f".old-{key[:12]}-{os.getpid()}"
            final.rename(old)
            stage.rename(final)
            shutil.rmtree(old, ignore_errors=True)
        else:
            stage.rename(final)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    if params:
        index_template(home, key, query_sql)  # lemma(...) finds it for any query that is this template with literals in place of $name
    return final


_STREAM_LINE = re.compile(r"^[ \t]*--[ \t]*stream:[^\n]*(?:\n|$)", re.MULTILINE | re.IGNORECASE)


def without_stream_header(sql: str) -> str:
    """``sql`` without its ``-- stream: <table>`` line (stream_join.with_header puts it first): the query as a caller sends it."""
    return _STREAM_LINE.sub("", sql, count=1)


def stream_table(spec: str) -> str:
    """The streamed table's Cols suffix of a stream spec (``stream_table_<t>``)."""
    return re.search(r"pub uninterp spec fn stream_table_(\w+)\(id: u64\)", spec).group(1)


def stream_builds(spec: str) -> list[str]:
    """The build tables' Cols suffixes of a join stream spec, in q_build's (pool_open's) order."""
    sig = re.search(r"pub fn pool_open\(sh: Stream_\w+, (.*?), p: Params, nslots: usize\)", spec)
    return [part.split(":")[1].strip().removeprefix("Cols_") for part in sig.group(1).split(", ")]


def add_pushdown(inputs: list[dict], sql: str, schema: dict, *, suffixes: set[str] | None = None, always: bool = False) -> None:
    """lemma.toml ``pushdown``: each ``rows`` entry gets the transpiler's pushed-down predicate of its table (``where``, DuckDB SQL;
    a query template's ``$name`` placeholders stay, the extension substitutes the values ``lemma_query`` gets) and the parameters it
    reads (``where_params``). The extension applies it inside its scan (DuckDB's filter pushdown in the caller's snapshot), so only
    rows that can matter are handed to the executor. Sound by ``declarative_spec/pushdown.py``; the spec is unchanged. Flag off, or
    nothing pushed for a table: no key, the whole table is scanned as before. ``suffixes``: only those tables (a stream join's build
    tables); ``always``: whatever the flag says (a build table, see install_executor)."""
    if not always and not lemma_config.get("pushdown"):
        return
    from declarative_spec.pushdown import plan_pushdown

    plan = plan_pushdown(sql, schema, dialect="duckdb")
    for entry in inputs:
        if suffixes is not None and entry["suffix"] not in suffixes:
            continue
        if entry["kind"] == "rows" and plan.where(entry["table"]) is not None:
            entry["where"] = plan.where(entry["table"])
            entry["where_params"] = list(plan.params(entry["table"]))


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
