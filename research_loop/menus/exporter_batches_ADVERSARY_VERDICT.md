# Adversary verdict: batched exporter (`_encode_columns` row-batch scan with per-column spools)

Subject: `research_loop/decl_query_measure.py` (`_encode_columns`, `_encode_batch`, `_finish`, `_export_planned_to`, `_export_planned`, `_BATCH_ROWS`) against the oracle `_export_table_rowwise` in `tests/_export_rowwise_reference.py`.

## Verdict: ACCEPT WITH FIXES

The byte claim survived every batching attack I could build: no BYTES difference at any batch size, on any input the oracle accepts and the exporter does not newly refuse. The remaining findings are loud refusals the oracle does not make (all already known or documented), file/fd hygiene on failure, and memory that is not batch-bound in two places (high-cardinality dictionaries; spool location). Fix findings 1 and 2 before the next paper family, because they are about the exact failure the rewrite was meant to remove (OOM on a 39.4M-row table) and about stale artifacts after a refusal.

## What was run

`uv run pytest tests/test_export_batches.py tests/test_export_bulk_differential.py -q`: 57 passed.

Scratch scripts in `/tmp/claude-1000/-home-emil-projects-lemma-db/bd3b4baa-20f9-4ec3-b72d-14c9857f1938/scratchpad/bb/` (`h.py` harness, `fuzz.py`, `targeted.py`, `t6.py` to `t9.py`, `why.py`). Each compares `_export_table_rowwise` with `_export_table`, treating "ValueError from both" as agreement.

- Random differential, `fuzz.py` seeds 1-8, 150 tables each (0 to 40 rows, 1 to 30 distinct strings, NULL rate 0/10/50/100%, columns BIGINT, VARCHAR as u8 dictionary with `__valid`, DECIMAL(38,4) as i128 with `__valid`, DECIMAL(12,2) as i64, DATE as i32, plain VARCHAR with `__valid`, DOUBLE, BOOLEAN, HUGEINT as i128 up to 2^100, UBIGINT up to 2^64-1; random DELETE/CHECKPOINT/UPDATE/self-INSERT), `_BATCH_ROWS` in {1, 2, 3, 7, 1000000}. Zero mismatches (the first four seeds mostly hit the "NULL in non-nullable" refusal, which also agreed; the last four seeds had every column nullable and zero refusals).
- Multi-row-group table (300k rows, 3001 distinct strings as u16 dictionary) at batch 122879, 122880, 122881, 50000, 299999, 300000, 1000000: identical.
- Rowid gaps: 600k-row table, `DELETE` of rows below 200000 and of 250000..419999 without checkpoint (rowid range 200000..599999, 230000 rows), batch 1000 to 1M; plus append after the delete; plus a 3M-row table with all but 20 rows deleted (batch 1000): identical, fast. Same after CHECKPOINT (DuckDB compacts, rowids restart at 0 or an offset, order preserved): identical.
- File database with first 150000 rows deleted, checkpoint, in-place UPDATE, more inserts, checkpoint (rowid range 27120..277129): opened `read_only=True` and as `ATTACH ... (READ_ONLY)` + `USE`: identical; no leftover `lemma_exp_enum_*` types.
- Dictionary boundary cases: 300 rows, 150 distinct, NULLs interleaved, shuffled, batch in {1, 2, 3, 50, 149, 150, 151, 299, 300, 301}; 4 NULLs at the start then values; a bad (2^40) or NULL value at positions 0, 5, 9, 10, 11 of 12 rows for batch 1/2/3/7: identical (including both-refuse).
- Empty table (dictionary, plain, `__valid`), empty `fields` (both ValueError), same column twice (`k`,`k`; code + dictionary + plain String of the same column), NaN, -0.0, inf, NUL inside a plain String (identical).
- Memory with `tracemalloc`, 400k rows (finding 4).
- Spool/fd and enum cleanup (finding 3), `write_query_measure` partial file (finding 2).

## Findings

### 1. Memory not batch-bound where the OOM is most likely: spools in TMPDIR (EXC-only / operational, medium)

`tempfile.TemporaryFile()` creates the per-column spools in `$TMPDIR` (default `/tmp`). Reproduction: `df -h /tmp` on this machine prints `tmpfs 7.4G`; on a tmpfs `/tmp` the complete export (all columns, 100% of the output, up to tens of GB for a 39.4M-row `num`) lives in RAM until `_finish`, so the batching only moves the same bytes from the process heap to shmem. On a disk-backed `/tmp` the export needs 2x the output size (spools plus `dest/cols_*.bin`) at the peak. Old: whole output in the process, bounded by nothing. New: bounded by the batch in the process, bounded by nothing in TMPDIR. Not a bytes problem.
Fix: spool into `dest` itself (`tempfile.TemporaryFile(dir=dest)` or `NamedTemporaryFile(dir=dest)`), or write the columns at known offsets of the destination file directly (row count is known up front: `total` is computed before the scan, the column order is fixed, so only the string/dict columns have unknown size; those alone need a spool). Check `df /tmp` on the Spot VM before the next run either way.

### 2. Failed export leaves a truncated `cols_<suffix>.bin` and a stale `expect.json` (EXC-only, medium)

`write_query_measure` now opens `dest/cols_<suffix>.bin` with `"wb"` before exporting. A refusal during the scan leaves a 0-byte file (the 8-byte header is written only in `_finish`, after all batches); a failure inside `_finish` leaves a partial file. The old code built the bytes and then `write_bytes`, so a refusal never touched an existing file.
Repro (`scratchpad/bb/t8.py`): run `write_query_measure` on the `_JOIN` test database (good run: `cols_t.bin` 47 bytes, `cols_u.bin` 56 bytes, `expect.json` 131 bytes), then `INSERT INTO u VALUES (NULL, NULL)` and rerun into the same `dest`: `ValueError: u.id has NULLs; the catalog does not declare the column nullable`, and now `cols_u.bin` is 0 bytes while `expect.json` is the previous run's and `bins` was never returned. Old: `cols_u.bin` unchanged (56 bytes). Anything that globs `cols_*.bin` or reads `expect.json` (`declarative_spec.bench.load_speed_bar`, the in-session `run_runquery`) sees a self-consistent-looking directory with a zero-row-count-less table file. The orchestrator normally uses a fresh `dest`, so severity is medium, not high.
Fix: write to `cols_<suffix>.bin.tmp` and `os.replace` after success, and delete `expect.json` (or write it last and unlink it at the start of `write_query_measure`).

### 3. Spool temp files stay open while a refusal exception is held (EXC-only, low)

The cleanup of `spools` is in a second `try/finally` that is reached only on the success path. When the first `try` raises a `ValueError` (late NULL in a non-nullable column, NUL, range, `seen != total`, code width), `spools` is never closed explicitly; the files are closed only when the frame is garbage-collected, which a held exception (logging, `pytest.raises` info, a stored `except` variable, the traceback in the orchestrator's failure record) prevents.
Repro (`scratchpad/bb/t7.py`): table of 50 good rows then `(b, NULL)`, `k` non-nullable, `_BATCH_ROWS=5`; call `_export_table` 20 times keeping each `ValueError`: open fds go from 4 to 84 (4 spools per call), and return to 4 after `keep.clear(); gc.collect()`. A `Bad` sink whose `write` raises `OSError` (the `_finish` path) does not leak (the second `finally` runs). The TEMP ENUM is dropped on every path (checked: 0 `lemma_exp_enum_*` left after refusals).
Fix: open the spools inside the same `try` that has the `finally`, e.g. one `try/finally` around the whole body that closes `spools` (or `contextlib.ExitStack`). Also create the spools lazily one at a time rather than `extend(generator)`, so a failure midway does not leak the already created ones.

### 4. High-cardinality dictionaries are not batch-bound (EXC-only / memory, low-medium, documented as "plus the dictionaries")

Reproduction (`t7.py`, `tracemalloc` peak, 400k rows): plain String 0.4 MB at batch 1000, 3.7 MB at 10000, 148 MB at 400001 (batch-bound, good); u8 dictionary of 50 values 0.2 / 0.2 / 1.2 MB (good); i128 0.1 / 0.5 / 19.2 MB (good); dictionary with 400k distinct values 131.6 MB at every batch size (about 330 bytes per distinct entry: `fetchall` tuples, `entries`, the ENUM literal SQL string, then `_pack_strings`). Extrapolated, a 20M-distinct-string column costs about 6.6 GB plus a 20M-literal `CREATE TYPE` statement. The old exporter had the same order of memory for the dictionary, so this is not a regression, but the docstring promise "bounded by `_BATCH_ROWS`" is false for such columns, and the only pinned-catalog string columns that are likely to be that large are the very ones named in the OOM story. The batch-bound claim holds for plain strings, i128 and low-cardinality dictionaries.
Fix (if needed): reject dictionaries above a distinct-count cap early (the u16/u32 width choice already implies it), or derive codes batch by batch from an in-process dict (no ENUM, no whole-table `GROUP BY` result in Python). Also note `judge_declarative.py` still calls `_export_table`, which returns the whole file as `bytes` (a `BytesIO` of the full output), so that caller is not memory-bound at all.

### 5. REFUSAL (new, loud): any table with a column named `rowid`, and any view, is now refused even when no dictionary column is used (low)

Old: accepted (the oracle never touches `rowid`). New: `ValueError` (`has a column named rowid ...`; and `Binder Error: Referenced column "rowid" not found` from `SELECT min(rowid)` on a view, which is raised even for plain `i64` columns because `bounds_rowid` and the batch scan need `rowid` unconditionally).
Repro A: `CREATE TABLE b (k BIGINT, s VARCHAR); CREATE VIEW t AS SELECT * FROM b;` fields `[("k","i64")]`: old 24 bytes, new ValueError. Repro B: `CREATE TABLE r (rowid BIGINT, k BIGINT); INSERT INTO r VALUES (5,1);` fields `[("k","i64")]`: old accepts, new ValueError (the exporter does not even need dictionary columns for this). The previous verdict (findings 2, 3) covered only dictionary columns on views / a `rowid` column; the batching widens both to all fields. Loud, so acceptable for the pinned base-table databases; say so in the docstring.

### 6. Known and unchanged (REFUSAL, low): NUL byte in a dictionary string

`SELECT ... chr(0)` in a dictionary column: old accepts, new `ValueError("a NUL byte in a dictionary string")` (the ENUM literal SQL cannot carry NUL). Plain String columns with NUL are identical. Unchanged from the previous verdict.

### 7. Informational: row order under `preserve_insertion_order=false` (not a defect)

With `SET preserve_insertion_order=false` and `threads=8` on a 500k-row table, oracle and new bytes differ at every batch size (`t9.py`). The oracle itself is nondeterministic there (its row order is the scan order); the new exporter's dictionary order is by `min(rowid)` while its rows arrive unordered within a batch, so both columns and dictionary stay self-consistent. With the default (`true`) the bytes are identical at batch 1000, 100000 and 1000000. The measure connection never sets it. No fix needed; do not set it on the export connection.

### 8. Nits

- `_BATCH_ROWS = 0` (or negative) never advances `lo` and loops forever; the production constant is fixed, but a monkeypatch/env hook later would hang instead of failing fast.
- `lo + _BATCH_ROWS` with `rowid` near 2^63 becomes a HUGEINT literal; the comparison remains correct, but I could not construct a table with such rowids, so it is untested.
- After a refusal the scan work already done is thrown away (e.g. a NULL in the last batch of a 39M-row `num` is found after the whole scan). The old exporter had the same cost; a cheap pre-check (`count(*) FILTER (WHERE col IS NULL)` for non-nullable columns, next to the range pre-check) would fail in seconds.

## Specific attacks that did NOT break it

Dictionary code order with a value's first occurrence at each side of a boundary, one new distinct value per batch, 150 and 151 distinct values at batch sizes 149/150/151, NULL cells interleaved and all-NULL batches (`__valid` and code 0 across batches, the all-NULL `[""]` dictionary); NULL only in the last batch; range pre-check against a bad value at the first, middle and last rows; i128 limbs across batches (random values to 2^100, NULLs, negatives); plain String across batches; deleted rows, rowid offset, gaps larger than the batch (3000 empty batches, 0.01 s), appends after delete, in-place UPDATE and checkpoint; multi-row-group tables at batch sizes straddling the 122880 row group; read-only and ATTACH read-only databases (TEMP ENUM works, none left over); empty table; empty `fields`; one column in two fields; the `seen != total` cross-check never fired; `_BATCH_ROWS` of 1, 2, 3, 7 on random tables gave identical bytes.

## Summary

ACCEPT WITH FIXES. The batched exporter emits bytes identical to the per-row oracle at every batch size I tried (about 1,200 random and constructed cases, 5 batch sizes each), and refuses wherever the oracle refuses. Fix before the next paper run: put the spools (or the output) outside a possibly tmpfs `/tmp` (finding 1), write cols files atomically and clear `expect.json` so a refusal cannot leave a truncated `cols_*.bin` (finding 2), and close the spools on the exception path (finding 3). High-cardinality dictionaries are still not batch-bound (finding 4), and views / `rowid`-named columns are now refused for all field kinds (finding 5), both loud.

## Disposition (author)

1. Fixed before the review: spools sit beside the destination file (this machine's /tmp is RAM); `_export_planned_to` derives the directory from the sink.
2. Fixed: write_query_measure writes cols_<suffix>.bin.part then renames; a stale expect.json is removed first.
3. Fixed: spools are closed in the same finally as the ENUM drop (test counts open fds over repeated refusals).
4. Not changed: dictionary entries are held in memory (about 330 B per distinct value, bounded by the dictionary cap, not by the table). judge_declarative still takes bytes.
5. Deliberate loud refusal (views, a column named rowid). 6. Unchanged (NUL in a dictionary string). 7, 8. Noted.
