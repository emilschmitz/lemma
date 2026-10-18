# Lemma inside DuckDB 1.5.6

A DuckDB extension that answers a query with its **proved executor**: the `run_query` an agent wrote and Verus proved equal to
the query's MethodSpec, compiled as a shared library. The extension scans the columns the spec needs in the caller's transaction,
hands them to the library, and returns the library's rows as the query result. No LLM, no network and no agent run inside
DuckDB: an executor is made offline (`lemma optimize`, or `research_loop/in_duckdb.py`) and only looked up here.

Everything is behind the `in_duckdb` flag of `lemma.toml` (`[engine]`, default `false`): with it off, the assembler does not
emit library mode, `research_loop/in_duckdb.py` installs nothing and the in-DuckDB measure refuses to run. The extension
itself only ever runs executors whose manifest says `"in_duckdb": true`.

Built with DuckDB's official extension template (`github.com/duckdb/extension-template` at `a733bb1`, which pins DuckDB
`v1.5.6` = `069cc9f` and `extension-ci-tools` `3fd6109`). `duckdb/` and `extension-ci-tools/` are git submodules.

## Build

```sh
git submodule update --init --depth 1 db_extension/duckdb_ext/duckdb db_extension/duckdb_ext/extension-ci-tools
db_extension/duckdb_ext/build.sh          # runs under scripts/ram/heavy.sh, 2 compile jobs (LEMMA_EXT_JOBS=1 if a job is killed)
```

The first build compiles DuckDB (about 20 minutes at `-j2` on the 8-core box; later builds recompile the extension only). Outputs:

| File | What |
| --- | --- |
| `build/release/extension/lemma/lemma.duckdb_extension` | the loadable extension, with DuckDB's metadata footer (platform `linux_amd64`, `v1.5.6`) |
| `build/release/duckdb` | a DuckDB 1.5.6 CLI with Lemma statically linked (our downloadable DuckDB) |

## Load

Stock DuckDB 1.5.6 (CLI, Python wheel, ...). The extension is not signed, so unsigned extensions must be allowed:

```sh
duckdb -unsigned -c "LOAD 'path/lemma.duckdb_extension'; SELECT * FROM lemma_query('SELECT ...');"
```

```python
con = duckdb.connect("db.duckdb", config={"allow_unsigned_extensions": "true"})
con.execute("LOAD 'path/lemma.duckdb_extension'")
```

Or run our CLI, where Lemma is already loaded: `build/release/duckdb db.duckdb`.

## Use

| SQL | What |
| --- | --- |
| `SELECT * FROM lemma_query('<sql>')` | the proved executor's rows for `<sql>` (same column names and types as DuckDB's answer). No executor: error `no proved executor for this query; run `lemma optimize``. Never answered by DuckDB. |
| `SET lemma_mode = true` | every table-reading SELECT of the session is looked up; with an executor the plan is replaced by it (same snapshot, same result types), EXPLAIN shows a `LEMMA_QUERY` node with `engine: lemma`, the executor key and the proof line |
| `SET lemma_route_unproved = true` | in Lemma mode, a query without an executor runs on DuckDB unchanged instead of raising the error; labelled `engine=duckdb` in `lemma_last_query()`. Default `false`. Experiments never set it |
| `SELECT * FROM lemma_last_query()` | `engine` (`lemma`, `duckdb` or `none`), `reason`, `query_key`, `sql`, and for Lemma: `scan_us` (scan + copy), `load_us` (decode + every assumption check in the library), `run_us` (proved `run_query`), `total_us`, `rows` |
| `SET lemma_enqueue_misses = true` | a miss also writes `${lemma_home}/queue/<key>.sql` for the offline `lemma optimize`. Default `false` |
| `SET lemma_home = '<dir>'` | default `$LEMMA_HOME`, else `~/.local/share/lemma` (read at LOAD) |
| `lemma_normalize_sql(s)`, `lemma_sql_key(s)` | the cache-key form of a SQL text and its sha256 |

Statements that read no table (SET, constants, table functions such as `lemma_query` itself) and writes (INSERT, UPDATE, DELETE,
CREATE TABLE AS, COPY) are never routed. An explicitly PREPAREd statement in Lemma mode is an error (the extension cannot see its
text); run it as a plain query.

## Cache layout (shared with the `lemma` CLI)

```
${LEMMA_HOME:-~/.local/share/lemma}/executors/<key>/lib.so          the verified cdylib
                                               /manifest.json    see below
                                               /query.sql
${LEMMA_HOME:-~/.local/share/lemma}/queue/<key>.sql              misses (lemma_enqueue_misses)
```

`<key>` is the sha256 of the normalized SQL (`research_loop/in_duckdb.py` `normalize_sql`, mirrored by `NormalizeSql` in
`src/lemma_util.cpp`; `tests/test_in_duckdb.py` checks they agree): outside quotes and comments every whitespace run becomes one
space, quotes and comments are kept byte for byte, leading/trailing whitespace and trailing `;` are dropped, case is kept; a text
with `$` outside quotes is only trimmed. The extension compares the whole normalized text with the manifest too, not just the hash.

`manifest.json` (written by `research_loop.in_duckdb.install_executor`): `format`, `abi_version`, `in_duckdb`, `key`, `sql`,
`normalized_sql`, `duckdb_version`, `git_sha`, `git_dirty`, `proof` (`N verified, 0 errors` from the Verus run that compiled
`lib.so`), `spec_sha256`, `lib_sha256`, `target_cpu`, `params` (empty until query templates), `input_layout`/`output_layout`
(must equal what the library reports), `inputs` (per buffer: table, column, DuckDB type at install, Rust type, role, scale,
nullable) and `outputs` (DuckDB name and type, OutRow field, scale).

The extension refuses, with an error and never with DuckDB's rows: a manifest for another DuckDB version, a proof line that is not
`N verified, 0 errors`, `in_duckdb` false, a manifest of another query, a `lib.so` whose sha256 differs from the manifest, a
library whose embedded SQL or layouts differ from the manifest, a table column whose type changed since install, and a result
whose types differ from the plan's.

## Design

* **Library mode** (`declarative_spec/assemble_library.py`): the `verus!` part (spec, agent body, host lemmas, verified
  `load_cols_*`) is byte for byte what the binary gets; `main` is replaced by a fixed C entry point, the same template for every
  query. C ABI (`src/include/lemma_abi.h`): `lemma_run(const LemmaCol *cols, uint64_t ncols, const LemmaParam *params,
  uint64_t nparams, LemmaOut *out)`; `params` is reserved for query templates (version 1 requires `nparams == 0`). Inputs are one
  "rows" entry per table (`n` = row count) then one buffer per spec field, in the bytes of the column-file format that `main`
  reads (little-endian cells; strings as u32 length + UTF-8). The library decodes them into the `Vec`s, runs EVERY check `main`
  runs (lengths, catalog row and value caps, dictionary codes and uniqueness, declared unique keys, join caps; the same generated
  code), and only then calls the verified loaders and `run_query`. A failed check is return code 1 with the message; a panic is
  caught (`catch_unwind`) and never crosses into DuckDB.
* **unsafe**: only in the fixed template, four blocks: (1) `slice::from_raw_parts` over the caller's `LemmaCol` array, (2) over
  each input buffer, (3) writing the result into the caller's `LemmaOut`, (4) `Vec::from_raw_parts` in `lemma_free_out` to free it.
  Each states its contract in a comment. No unsafe in agent regions (admission rejects it as before).
* **Compile**: `verus <file> --crate-type=cdylib --compile -- -C opt-level=3 -C codegen-units=1 -C target-cpu=<lemma.toml
  target_cpu>`; the proof line of that same run goes into the manifest.
* **Scan** (`ScanInputs`): for each table the spec reads, `DataTable::InitializeScan` / `Scan` over exactly the needed column ids,
  with the caller's `DuckTransaction` (its snapshot, including its own uncommitted rows: `DataTable::Scan` reads the transaction-local
  storage after the committed row groups), single-threaded, in row order. Cells are encoded as the Python exporter
  (`research_loop/decl_query_measure.py`) encodes them: DATE = days since 1970-01-01, DECIMAL = integer value * 10^(spec scale)
  (overflow checked), DECIMAL to f64 through DuckDB's own BIGINT/HUGEINT-to-DOUBLE path, dictionary codes numbering distinct
  non-NULL strings in order of first appearance (u8/u16/u32, overflow refused), NULL = zero cell only where the catalog declares the
  column nullable (else an error), validity vectors as 0/1 bytes. One copy per column into a contiguous buffer; the library copies
  once more into its `Vec`s (the spec is unchanged).
* **Rows back**: the library writes `LMR1` + per column validity + cells (i128 integers, f64, bool, strings); the extension writes
  them into DuckDB vectors of the manifest's types (DECIMAL by its physical width, range-checked; DATE; HUGEINT; ...).
* **Lemma mode** is an `OptimizerExtension` (post-optimizer): it replaces the plan root (below EXPLAIN) with a `LogicalGet` of
  the executor table function; the result types must equal the plan's.
* Executor libraries are loaded once per process (by `lib_sha256`) from a private copy, so replacing `lib.so` on disk never changes
  a loaded executor; they are never unloaded.

## Timing

`research_loop/official_measure.py` `measure_in_duckdb` times `SELECT * FROM lemma_query('<sql>')` (scan + copy + checks +
`run_query` + rows back) against the SQL on DuckDB, K interleaved rounds with alternating first side, both on one read-only
connection under the measure's DuckDB settings. `research_loop/scripts/in_duckdb_bench.py` runs it for installed executors.

## Tests

```sh
uv run pytest tests/test_in_duckdb.py                      # unit + extension tests (skip the extension part if not built)
uv run pytest -m slow tests/test_in_duckdb.py              # + TPC-H SF1 (research_loop/generated/tpch_sf1.duckdb, read-only)
```

## Limits (today)

Only `Vec<OutRow>` results (no map-shaped results); string columns must be VARCHAR; no query parameters; executors are not
unloaded; the scan is single-threaded and copies each column twice (DuckDB vector -> buffer -> `Vec`).
