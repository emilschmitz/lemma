# Adversary verdict: zero-copy lease (ZC-1, `LEMMA_ZERO_COPY=1`)

Manual adversary (Sonnet subagent, separate from the author). Protocol: `TRUSTED_ADDITION_PROTOCOL.md`. Date 2026-10-05.
Linked library: DuckDB v1.2.2 (`build/libduckdb`). Reference databases in this repo are v1.5.4 files (header bytes `v1.5.4`), which that
library cannot open; everything below was run on 1.2.2-format databases.

## Verdict: SOUND after fixes (findings 1, 2 and 3 must land first)

I found no hole in the Verus library and no input where ZC-1's layout and fidelity claims are false on DuckDB 1.2.2. I found one
silent wrong-answer path in the loader (finding 1), one wrong-table path in the generated `SELECT` (finding 2), and one unchecked ZC-1
clause (finding 3). Finding 4 is not a soundness finding but it changes the case for merging: as built, the "zero-copy" pin is not zero
copy. My recommendation is **do not merge ZC-1**; take the native streaming loader (see "Headline claim").

## Findings

### 1. Logical type, precision and scale are not checked: a same-width column with another scale verifies, runs, and returns a wrong answer. Class (a), plus (c) in the assembler.

`zero_copy_ffi.rs:101` `int_width` and `zero_copy.py:160` check only the storage width (`elem_bytes == size_of::<T>()`). The spec bakes the
catalog scale into its literals (`row_hit` in `tests/fixtures/declarative_proofs/zero_copy_sum_filter.spec.rs`: `value@[i0] > 50000000` means
`> 5000` at scale 4) and into `OUT_SCALES`. The copy path is immune because the exporter (`research_loop/decl_query_measure.py:_export_table`)
scales each Decimal by the catalog's scale. The borrowed path reads whatever integers DuckDB stores.

Reproduction (1.2.2 database whose `num.value` is `DECIMAL(38,2)` while the spec was generated for `DECIMAL(38,4)`):

```
d12 scale.duckdb "CREATE TABLE num AS SELECT (i*37 % 100000)::DECIMAL(38,2) AS value FROM range(100000) t(i)" "CHECKPOINT"
LEMMA_ZERO_COPY=1 ... zero_copy_oneshot.py build --sql-file q.sql   # q.sql = SELECT SUM(value) AS total FROM num WHERE value > 5000
  -> verification results:: 10 verified, 0 errors
./b1/zc_query        -> ROWNULL           (QUERY_LATENCY_US etc. all printed, no abort)
d12 scale.duckdb "select sum(value) from num where value > 5000"   -> 4987447500.00
```

The binary prints `NULL` for the sum, DuckDB prints 4987447500.00. The same happens for a `HUGEINT` column (width 16) and, with a spec that says
`i32`, for a `DATE` versus an `INTEGER` column (both 4 bytes). The harness's row-for-row comparison would catch it on the measured data, but the
proposal's ZC-1 text lists width as the only type check, and an "accepted" result must not rest on the harness.

Fix: `assemble_zero_copy_program` must receive the schema model (it only gets `spec_rs` today) and `main` must assert, per column, from
`duckdb_column_logical_type`: the type id equals the catalog's, and for DECIMAL `duckdb_decimal_width` and `duckdb_decimal_scale` equal the
catalog's (`DATE` only where the catalog says date). Two regression tests: a `DECIMAL(38,2)` versus catalog `(38,4)` database aborts; an
`INTEGER` column where the catalog says `DATE` aborts.

### 2. The SELECT is built from the sanitized Rust identifiers, not the real table and column names. Class (c): `zero_copy.py:90-92` (`_sql`) and `:155` (`count`).

The table name is the struct suffix and the column names are field idents, both produced by `rust_ident` (`schema_types.py:72`:
lowercase, every other character becomes `_`). The exporter uses `model.original_column_names` and `_quote` of the real name. The zero-copy
assembler never sees the original names. Generated with `emit_declarative_spec` on a schema with a table `"num x"` and column `"my col"`
(`scratchpad/adv/gen.py`):

```
num x -> Cols_num_x   SELECT "my_col" FROM "num_x"     assert!(n_num_x == zc_duck::count(&db, "num_x") ...
we"ird -> Cols_we_ird SELECT "a_b" FROM "we_ird"
```

If no table `num_x` exists this is a loud catalog error. If one exists (sanitization collision, e.g. `num x` and `num_x`), the program verifies
against the right spec, pins the wrong table, and the row-count assert compares the wrong table with itself (`count` uses the same wrong name,
so it cannot detect this). A related smaller point: the SQL is embedded as `r#"..."#` and the path as `"{db_path}"` with no escaping; a `"#` in
a name or a `\` or `"` in the path breaks the generated Rust (host-controlled input, so only noted).

Fix: pass original table and column names (as the exporter does) and quote-escape them; until then refuse when `rust_ident(original) != original.lower()`
for the table or any selected column. Regression tests: table `"num x"` (the generated SELECT names `num x`); two tables `num x` and `num_x` where
only the first is the catalog's.

### 3. ZC-1 item 1 says `p_k` is non-null, but main never checks it. Class (a), low severity.

`zero_copy.py:162` asserts `p % align_of::<T>() == 0`, which a null pointer satisfies, and `zero_copy_ffi.rs:152` stores the pointer unchecked;
`from_raw_parts(null, len)` is undefined behaviour (and a null element in a `Vec<&[T]>` is a niche). I could not make DuckDB return a null data
pointer: an empty table gives `duckdb_result_chunk_count == 0` (so `n == 0`, no chunks, `offs == [0]`, wf holds), and every non-empty chunk had a non-null
pointer in all my runs. Fix: `assert!(!p.is_null())` next to the alignment assert, in both modes. Test: a table with zero rows runs and returns the empty-input result.

### 4. The pin is not zero-copy: `duckdb_result_get_chunk` copies, so the claimed memory saving does not exist. Class (b) for the proposal text, and it undercuts the proposal.

`duckdb_result_get_chunk` fetches from the materialized result's `ColumnDataCollection` into a NEW chunk. Evidence on the 39.4M-row `num`
(`scratchpad/adv/t4.rs`, `VmRSS`, no timing):

```
RSS after open: 36 MB
RSS after duckdb_query (materialized result, no get_chunk yet): 953 MB
RSS after fetching all 19244 chunks (result still alive): 1564 MB     (+611 MB = the 39.4M x 16 B column)
RSS after destroying chunks (result alive): 1214 MB
```

`scratchpad/adv/t1.rs` section G also shows that fetching the same chunk twice returns a different pointer and a write through one handle
is not visible in the other. So the program holds the collection AND the fetched chunk copies (two decompressed copies), exactly what the
proposal charges to the copy path. Proposal section 7 ("Peak memory: the pin is the only copy") and section 1 ("removes only the memcpy ... and one
resident copy") are wrong for this API: zero-copy moves the memcpy inside `get_chunk` and keeps both copies. The control (`mode="copy"`) then
adds a third. Real zero-copy would need to borrow the collection's own blocks (not exposed by the C API) or keep streamed chunks (`duckdb_fetch_chunk`)
without ever materializing the collection.

### 5. Dependence on a deprecated API and on a version I could not test. Class (b), accepted limitation to record.

`duckdb.h` marks `duckdb_result_get_chunk`, `duckdb_result_chunk_count` and `duckdb_result_is_streaming` "scheduled for removal in a future
release" (header lines ~1030-1070). The fidelity of ZC-1 rests on the 1.2.2 implementation detail that a materialized result is fetched with
zero-copy disallowed (finding 4) and yields flat, owned vectors. Constant, dictionary-compressed and `ORDER BY` view inputs all came back flat and
correct (below). Whether 1.5.x does the same I could not check: no 1.5 `libduckdb` with the C API is in the repo, and the 1.5.4 database files do
not open with 1.2.2, so the prototype has never read the real `sec_edgar_dec.duckdb`. Re-validate on any DuckDB change (the proposal already says so),
and the SHA gate should record the library version.

### 6. Proposal numbers. Class (b), documentation.

The 39.4M-row `num` has 19,244 chunks of which 12 (not 11) are not 2048 rows (199, 246, 770, 838, 980, 1336, 1455, 1594, 1598, 1733, 1878,
1998); `t2.rs`. Chunks of a freshly built table (CTAS) are all 2048 except the last, so the "not uniform" claim is a property of data
loaded from storage, still true and still handled by `offs`.

### 7. Narrow cells are refused only at run time. Class (c), low severity (by reading, not demonstrated).

`_single_table` accepts any of `i8..i128`. With `LEMMA_NARROW_CELLS` a spec field narrower than storage verifies and compiles, and then the
width assert (`zero_copy.py:160`) aborts the binary loudly. No wrong answer (widths can only coincide when nothing was narrowed), but it wastes a
Verus run; refuse at assemble time when the flag is on. I could not get `regenerate_spec` to narrow a SEC column (the SEC catalog gave `i32` for
`qtrs` with the flag set), so I did not run the abort.

## What I tried that did not break it

* **Verus library.** Added to the assembled worked program (`scratchpad/adv/v1.py`, `v1.rs`): `proof fn`s claiming `false` from `wf`, a wrong
  cell index (`off(k)+j+1`), `a@ == b@` for two wf columns of equal length, "one chunk", "chunk 0 holds every row", "at least two offsets". All six
  fail (`verification results:: 11 verified, 6 errors`), the true one (`c@.len() == c.n`) verifies. `wf` pins `offs` monotone through
  `off(k+1) == off(k) + len` as integers (no `usize` wraparound in the view), empty chunks are allowed and harmless (`in_chunk` is false for
  them, `lemma_cell` proves uniqueness of the chunk), `n == 0` with no chunks is wf. The `choose` is uniquely determined for `i < n`, so the view is
  the concatenation. No `external_body`, `assume` or `admit` in `zero_copy_lib.rs`. The existing misplace/skip mutation tests are meaningful.
* **Dropped conjuncts.** A spec with a unique-key `valid_cols` conjunct is refused (`ZeroCopyUnsupported: ... unique key ...`,
  `scratchpad/adv/u.py`). The cap checks run over every chunk (`ZcFlat::iter().all` visits all chunks) and the row cap uses `n`; a conjunct the
  checker cannot restate raises, it is never skipped.
* **NULL detection.** `pin` aborts for a NULL at row 0, 63, 64, 2047, 2048, 4095, 4096 and 4999 of a 5000-row column (`t1.rs`), covering
  `len % 64 == 0` and `!= 0` chunks.
* **Type refusal.** `duckdb_column_type` ids: TIMESTAMP 12, TIME 14, UBIGINT 9, UHUGEINT 32, BOOLEAN 1 are all refused by `int_width`; DECIMAL(4/9/18/38)
  report internal types 3/4/5/16 and DATE is 13, as the code assumes.
* **Flat vectors and fidelity.** Constant, dictionary-valued and `ORDER BY` views, and a checkpointed, reopened table whose columns use constant,
  RLE, bit-packed, random, DECIMAL(18,3), DATE, HUGEINT, TINYINT and SMALLINT storage: an order-sensitive checksum of the pinned cells equals DuckDB's
  SQL checksum for all nine (`t3.rs`, 1.5M rows). Insertion order equals `ORDER BY rowid` on a 3M-row table.
* **Liveness and immutability.** A retained chunk is unchanged after `UPDATE`, `DELETE`, `INSERT`, `CHECKPOINT` on the same and on a second
  connection, and `DROP TABLE` (`t1.rs` F).
* **Alignment.** 977 chunks of a 2M-row HUGEINT column and 489 of a DECIMAL(38,4) column, and all 19,244 of `num`: every data pointer 16-aligned.
* **Empty table.** `chunk_count == 0`, no pointer to borrow.
* **Fresh copy on refetch**, as the proposal claims (finding 4 shows what that implies).

## What I could not check

* DuckDB 1.5.x behaviour (no 1.5 C library here), including whether result chunks stay flat and owned, and 16-byte alignment of chunk buffers.
* The real `sec_edgar_dec.duckdb` (1.5.4 format) and its measured numbers; I did no timing at all (the author owns the timing lock).
* `LEMMA_NARROW_CELLS` end to end (finding 7), a DATE `infinity` value (DuckDB stores it as an `i32` extreme; the exporter would error on
  `date - DATE '1970-01-01'`, the borrowed path would pass the raw integer to the catalog cap check), and columns whose names collide after sanitization on a
  real database (finding 2 is shown on generated text only).
* A hostile concurrent thread destroying the pin (single-threaded by construction, as the proposal says).

## Headline claim: is the copy out of the pin where the one-shot cost is?

I agree with the proposal's conclusion and would go further. The cost sits in the per-row Python export and in DuckDB materializing the
result; the memcpy is the smallest piece. Worse, finding 4 shows the borrowed path does not avoid that copy: `duckdb_result_get_chunk` performs it.
ZC-1 therefore buys, at most, replacing one memcpy (into a `Vec`) by another (into the fetched chunks), at the price of one new trusted
statement that depends on a deprecated API and on a library version we cannot yet link to the real database, chunked columns that agents must
walk with `lemma_cell`, and no narrow cells (which the earlier work measured as the larger kernel win). A native loader through the C API
that streams chunks (`duckdb_fetch_chunk`) straight into the verified loader's `Vec`s needs no new trusted statement beyond the one the
exporter already carries (the width, scale and validity checks of finding 1 and 3 are the same checks), frees each chunk as it goes, and keeps
narrow cells. Do not merge ZC-1. If it is wanted for research, keep it behind the flag and report any use as "zero-copy lease (ZC-1), not zero copy".

Scratch files (not part of the repo): `/tmp/claude-1000/-home-emil-projects-lemma-db/bd3b4baa-20f9-4ec3-b72d-14c9857f1938/scratchpad/adv/`
(`d12.rs`, `t1.rs`..`t4.rs`, `gen.py`, `u.py`, `v1.py`, `n.py`, `b1/zc_query.rs`).
