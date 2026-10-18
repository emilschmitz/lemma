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
| `SELECT * FROM lemma_query('<template>', v1, v2, ...)` | a query template (`-- params:` header, `$name` placeholders, lemma.toml `[sql] templates`): one value per parameter in declaration order. BIGINT takes an integer value, DATE a DATE value (`DATE '1995-01-01'`), DECIMAL(p,s) an integer or DECIMAL value with at most s fractional digits (exact, never rounded), VARCHAR a VARCHAR. A wrong count or type, NULL, or a value outside the range `run_query` requires is an error, never rows. In `lemma_mode` a template executor is an error (the plan replacement cannot see bound values) |
| `SET lemma_mode = true` | every table-reading SELECT of the session is looked up; with an executor the plan is replaced by it (same snapshot, same result types), EXPLAIN shows a `LEMMA_QUERY` node with `engine: lemma`, the executor key and the proof line |
| `SET lemma_route_unproved = true` | in Lemma mode, a query without an executor runs on DuckDB unchanged instead of raising the error; labelled `engine=duckdb` in `lemma_last_query()`. Default `false`. Experiments never set it |
| `SELECT * FROM lemma_last_query()` | `engine` (`lemma`, `duckdb` or `none`), `reason`, `query_key`, `sql`, and for Lemma: `scan_us` (scan + copy), `load_us` (decode + every assumption check in the library), `run_us` (proved `run_query`), `total_us`, `rows` |
| `SET lemma_enqueue_misses = true` | a miss also writes `${lemma_home}/queue/<key>.sql` for the offline `lemma optimize`. Default `false` |
| `SET lemma_scan_threads = <n>` | threads of the scan that hands the columns to the executor; `0` (default) = DuckDB's `threads`. The bytes are the same for every value |
| `SELECT * FROM lemma_scan_inputs('<sql>')` | the input buffers `lemma_query` would hand to the executor (input, name, role, n, data), from the same scan; the executor does not run. For tests |
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
`lib.so`), `spec_sha256`, `lib_sha256`, `target_cpu`, `params` (a query template's parameters: name, SQL type, Rust type, scale, the `requires` range; empty for fixed SQL), `param_layout`, `input_layout`/`output_layout`
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
  uint64_t nparams, LemmaOut *out)` (ABI version 3); `params` carries a query template's values (since version 2: kind 1 = little-endian i64 as `run_query` takes it, i.e. DATE as
  the day number and DECIMAL scaled by 10^s; kind 4 = UTF-8 bytes; `lemma_param_layout` lists them and must equal the manifest).
  The fixed template checks count, kinds, lengths, the Rust type and the `requires` range of every parameter before it decodes a
  column; fixed SQL takes `nparams == 0`. A **stateful** spec (lemma.toml `stateful`) is refused in library mode: its runtime needs
  the caller's data version (`refresh(version)` / `execute_at(version)`, `docs/STATEFUL.md`); next step below. Inputs are one
  "rows" entry per table (`n` = row count) then one buffer per spec field, in the bytes of the column-file format that `main`
  reads (little-endian cells; strings as u32 length + UTF-8). **Owned inputs** (version 3): a field of fixed-width integer or
  `f64` cells arrives in a buffer the library allocated (`lemma_alloc_input(index, cap)`, a `Box<[T]>` of zeroed cells) and filled
  in place by the extension; `lemma_run` takes each as its `Vec`'s memory (no copy) before anything can fail, so the library frees
  it on every path (`lemma_free_input` returns one that never reached `lemma_run`). `bool`, string and dictionary fields stay
  borrowed. The library runs EVERY check `main` runs (lengths, catalog row and value caps, dictionary codes and uniqueness,
  declared unique keys, join caps: the same generated checks, the known shapes evaluated by fast helpers of the template:
  min/max per chunk on all cores, a sort of the dictionary instead of a hash set, a bitmap or sorted copy for an integer unique
  key; `assemble_library.fast_check`), and only then calls the verified loaders and `run_query`. The checks stay in Rust: the
  extension's scan is not trusted to have checked anything. A failed check is return code 1 with the message; a panic is
  caught (`catch_unwind`) and never crosses into DuckDB.
* **unsafe**: only in the fixed template, five blocks: (1) `slice::from_raw_parts` over the caller's `LemmaCol` / `LemmaParam`
  array, (2) over each input or parameter buffer, (3) writing the result into the caller's `LemmaOut`, (4) `Vec::from_raw_parts` in
  `lemma_free_out` to free it, (5) `Box::from_raw` of an owned input buffer (`lemma_take`: the buffer `lemma_alloc_input` made for
  that column, taken once).
  Each states its contract in a comment. No unsafe in agent regions (admission rejects it as before).
* **Compile**: `verus <file> --crate-type=cdylib --compile -- -C opt-level=3 -C codegen-units=1 -C target-cpu=<lemma.toml
  target_cpu>`; the proof line of that same run goes into the manifest.
* **Scan** (`ScanInputs` / `ScanTable`): for each table the spec reads, DuckDB's parallel table scan over exactly the needed
  column ids (`RowGroupCollection::InitializeParallelScan` / `NextParallelScan`, one task per row group, as `table_scan.cpp`
  does), for the committed row groups and then the transaction-local ones (its own uncommitted rows), all with the caller's
  `DuckTransaction`, so every thread reads one snapshot. `lemma_scan_threads` threads (default: DuckDB's `threads`). A task writes
  its rows at its row group's position in the destination (sized for every row of the table); afterwards the rows are packed to
  the front where a task returned fewer than its range (deleted rows, rows of a newer snapshot), so the result is the
  single-threaded row order byte for byte (`tests/test_in_duckdb.py`, against a Python encoding of `ORDER BY rowid`). Cells are encoded as the Python exporter
  (`research_loop/decl_query_measure.py`) encodes them: DATE = days since 1970-01-01, DECIMAL = integer value * 10^(spec scale)
  (overflow checked), DECIMAL to f64 through DuckDB's own BIGINT/HUGEINT-to-DOUBLE path, dictionary codes numbering distinct
  non-NULL strings in order of first appearance (u8/u16/u32, overflow refused), NULL = zero cell only where the catalog declares the
  column nullable (else an error), validity vectors as 0/1 bytes. Dictionary codes are numbered per task, then renumbered in
  task order (the table's first appearance) and rewritten in place where a task's numbering differs. Fixed-width cells are
  written once, straight into the owned buffer (a flat vector of the target width without NULLs is one `memcpy`); strings
  go through a per-task buffer and the library still copies them into `String`s.
* **Rows back**: the library writes `LMR1` + per column validity + cells (i128 integers, f64, bool, strings); the extension writes
  them into DuckDB vectors of the manifest's types (DECIMAL by its physical width, range-checked; DATE; HUGEINT; ...).
* **Lemma mode** is an `OptimizerExtension` (post-optimizer): it replaces the plan root (below EXPLAIN) with a `LogicalGet` of
  the executor table function; the result types must equal the plan's.
* Executor libraries are loaded once per process (by `lib_sha256`) from a private copy, so replacing `lib.so` on disk never changes
  a loaded executor; they are never unloaded.

* **Next step: stateful executors.** A further ABI version would keep one `QRuntime` per loaded library (behind a lock) and add
  `lemma_is_current(version)` and `lemma_run_at(version, ...)`: the extension asks first and scans only on a version change. The
  hard part is the version: it must change whenever any table the executor reads changes in the caller's snapshot (a transaction's
  start id changes per query; the catalog version does not track data), so the extension needs a per-table data version
  visible to the transaction. Until that is settled, a stateful spec is not installed.

## Timing

`research_loop/official_measure.py` `measure_in_duckdb` times `SELECT * FROM lemma_query('<sql>')` (scan + copy + checks +
`run_query` + rows back) against the SQL on DuckDB, K interleaved rounds with alternating first side, both on one read-only
connection under the measure's DuckDB settings. A query template binds round i to the bar's `template_bindings[i % n]` on both
sides (`lemma_query('<template>', literals...)` against the template run with the values bound), as the official verdict does. `research_loop/scripts/in_duckdb_bench.py` runs it for installed executors.

## Tests

```sh
uv run pytest tests/test_in_duckdb.py                      # unit + extension tests (skip the extension part if not built)
uv run pytest -m slow tests/test_in_duckdb.py              # + TPC-H SF1 (research_loop/generated/tpch_sf1.duckdb, read-only)
```

## Limits (today)

Only `Vec<OutRow>` results (no map-shaped results); string columns must be VARCHAR; no query parameters; executors are not
unloaded; string fields are copied twice (DuckDB vector -> per-task buffer -> `String`).
