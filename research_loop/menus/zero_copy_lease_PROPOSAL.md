# Proposal: zero-copy lease of pinned DuckDB column buffers (`LEMMA_ZERO_COPY=1`) — for adversary review

Protocol: `TRUSTED_ADDITION_PROTOCOL.md`, step 1. Status: prototype behind the flag, default off, NOT cleared by an adversary
(verdict file: `zero_copy_lease_ADVERSARY_VERDICT.md`). Do not make it default, and do not use it for a paper number, before the verdict.

Question (Emil): can the declarative pipeline run directly on the DuckDB-pinned column buffers instead of copying the pinned rows
into Rust Vecs before `run_query`?

## 1. Short answer

* **Yes for one family of columns, and it is a small win, not a big one.** What costs a first query 30 to 100 times a DuckDB scan today is
  not the copy out of the pin. It is (a) the per-row Python exporter that writes the column files (31 to 266 s on SEC) and (b) DuckDB
  materializing the pinned result (about 0.55 to 0.85 s for 39.4M rows). A native loader that reads the pin through the C API and
  `memcpy`s it into `Vec`s needs NO new trusted statement beyond the one the exporter already carries, and removes (a). Zero-copy removes
  only the `memcpy` (0.14 to 0.2 s for the 630 MB `num.value` column) and one resident copy. See section 8 for the measured numbers.
* **What zero-copy costs:** one new trusted statement (section 3), chunked columns (DuckDB result chunks are at most 2048 rows and are NOT all
  full, so a column is a list of slices, not one slice), no narrow cells (the loaded width is DuckDB's storage width), and agent bodies that
  walk chunks. Strings, dictionary codes and NULL masks cannot be borrowed.
* **Recommendation:** do the native loader first (no new trust). Treat zero-copy as an optional second step for fixed-width scans where the
  copy is the remaining cost (very wide tables, memory-bound boxes), after the adversary verdict.

## 2. What exists

* `lemma_lease` (`db_extension_lease/`, `db_extension_paths/src/lemma_pin.cpp`, `docs/DB_EXTENSION_PATHS.md`): `lemma_pin_table` runs
  `SELECT cols FROM t`, retains the `duckdb_result` and every `duckdb_data_chunk` (`duckdb_result_get_chunk`), and hands out raw data and validity
  pointers per (chunk, column). It is H1 harness code (unverified Rust kernels over the pointers), not wired into the declarative path.
  **The pin is chunked**: there is no flat buffer. It is also not a view of DuckDB storage: DuckDB's persistent storage is compressed per row
  group segment, so a pin is the *decompressed, materialized* result.
* `lemma_storage` (`ScanTableSegment`) reads row-group storage below the SQL layer, still into `DataChunk`s of at most 2048 rows.
* The declarative path today (`declarative_spec/assemble.py`): the harness writes `cols_<table>.bin` (`decl_query_measure._export_table`:
  `fetchmany` plus a Python `struct.pack` per cell, narrow widths, dictionary codes), `main` reads the file into `Vec`s, runs the
  `valid_cols` runtime checks, calls `run_query`. The verified loader `load_cols_*` has `requires` = the restated `valid_cols`, `ensures valid_cols`.

## 3. The trusted statement (ZC-1)

There is **no new Verus lemma, `external_body` fn or `assume`**. The new trusted code is one `unsafe` block in the generated plain-Rust `main`
(`std::slice::from_raw_parts` over a pinned chunk), exactly where the file reader sits today. The statement it relies on is:

> **ZC-1.** Let `R` be the `duckdb_result` of `SELECT c FROM t` on the read-only database, and `ch_0 .. ch_{m-1}` the chunks returned by
> `duckdb_result_get_chunk(R, 0..m-1)`, kept alive (not destroyed) until `run_query` has returned. For column `c` of native storage type `T`
> (two's-complement little-endian `i8/i16/i32/i64/i128`; DECIMAL = its scaled integer; DATE = days since 1970-01-01 as `i32`), with
> `p_k = duckdb_vector_get_data(duckdb_data_chunk_get_vector(ch_k, c))` and `len_k = duckdb_data_chunk_get_size(ch_k)`:
> 1. **layout:** `p_k` is non-null, aligned to `align_of::<T>()`, and addresses `len_k` initialized `T` values (the vector is a flat vector);
> 2. **liveness and immutability:** no code writes or frees that memory from before the first read until after `run_query` returns;
> 3. **fidelity:** the cell `r` of `c` in the SQL result is `p_{k}[r - sum_{k'<k} len_{k'}]` for the chunk `k` containing `r`
>    (chunks in index order are the rows in result order), and the column has no NULL;
> 4. **count:** `sum_k len_k` is the table's row count `n`.

What Verus takes as given: the struct `PinnedCol { n, chunks: Vec<&[T]>, offs: Vec<usize> }` is well-formed (`wf`) and its slices hold the column
(this is the same kind of fact as "the `Vec<i128>` the loader built holds the column" today). What Verus proves about it (verified host code,
`declarative_spec/zero_copy_lib.rs`): `wf` is `offs[0] == 0`, `offs[m] == n`, `offs[k+1] == offs[k] + chunks[k].len()`; its view is the
concatenation of the chunks; `lemma_cell(c, k, j)`: `c@[offs[k] + j] == chunks[k]@[j]`.

Checked by `main` at runtime, loudly (a failed check aborts, there is no fallback to the copy path): width of the pinned type equals `size_of::<T>()`
(through `duckdb_column_type` and, for DECIMAL, `duckdb_decimal_internal_type`); alignment of every `p_k`; the validity mask of every
chunk is absent or all ones (no NULL); `sum len_k` (the `n` the loader gets); the catalog caps (`valid_cols`: row cap, `|cell|` caps),
by the same generated assertions the copy path runs, over the borrowed memory.

NOT checkable by us: item 2 (immutability, liveness) and the content part of item 3 (that the pointer's content equals what SQL returns). Item
1's "flat vector" has no accessor in the C API of the linked version (`duckdb_vector_get_data` on a constant or dictionary vector would
return a single element). The mitigations are structural, not proofs: the chunks come from `duckdb_result_get_chunk` of a *materialized* result
(the chunk is a caller-owned `DataChunk` of flat vectors, destroyed only by us); the harness's existing row-for-row comparison of the printed
result with the reference engine's catches a misread on the measured data. This is the same status as the file exporter's claim "the file holds
DuckDB's cells", which nothing checks either today.

## 4. Verus-side representation

`&[T]` slices have the vstd view `Seq<T>` (`impl<T> View for [T]`). A single `&[T]` is not enough because the pin is chunked, so a column is

```
pub struct PinnedCol<'a, T> { pub n: usize, pub chunks: Vec<&'a [T]>, pub offs: Vec<usize> }
view = Seq::new(n, |i| chunks[chunk_of(i)]@[i - offs[chunk_of(i)]])      // the concatenation
```

and `valid_cols` gains `t.c.wf()`. Because the view is a `Seq<T>`, **every emitted spec statement (`t.c@[i]`, `t.c@.len()`) is unchanged**, and so are
`row_hit`, `sum_total` and the whole `ensures`. Only the struct's field type, the `valid_cols` conjunct, the loader's parameter type and the
agent's way of reading cells change. Reading cell `j` of chunk `k` is a slice index; the proof step that connects it to the spec is
`lemma_cell`. A random-access `get(i)` is not provided: it needs a binary search over `offs` (proof and speed cost); queries that probe by row
index (hash joins on borrowed build sides) stay on the copy path for now. `Vec<T>` instead of slices would need a copy, which is what we avoid;
`Vec::from_raw_parts` is not supported by Verus and would be unsound with a foreign allocator anyway.

The lifetime parameter is elided at every use (`run_query(num: &Cols_num)` is accepted by Verus and rustc). The parallel shape needs `'static`
(`Arc<Cols>` into spawned threads): the pin would be leaked for the process lifetime. Not in the prototype.

## 5. Which column kinds

| Column kind | Zero-copy? | Why |
|---|---|---|
| TINYINT..BIGINT, HUGEINT, DECIMAL(p<=38,s), DATE | **yes**, at DuckDB's storage width | native little-endian two's complement; the spec already works on the scaled integer. `i128` alignment is 16 in Rust and the buffer must be 16-aligned: checked at runtime (a failed check aborts). |
| unsigned ints, BOOLEAN, DOUBLE | possible, not built | need a content check (`bool` bytes 0/1, finite doubles), same scan as today's checks |
| narrow cells (`LEMMA_NARROW_CELLS`, loaded width below the storage width) | **no** | borrowing gives the storage width. Narrowing is a pass over the data (a copy at memory speed). One-shot against kernel speed trade: choose per workload. |
| VARCHAR (plain or dictionary codes) | **no** | `string_t` is 16 bytes inline-or-pointer, not UTF-8 slices. Codes need an encode pass (a `CAST(c AS ENUM)` inside DuckDB) after which the codes are a fixed-width column that CAN be borrowed. A column declared ENUM in the database already is codes plus a dictionary. |
| nullable columns (`__valid`) | **no** | DuckDB validity is a bit mask (`uint64` words, bit set = valid), the spec's `__valid` is `Vec<bool>`. A bit-mask view is possible (`(w[r/64] >> (r%64)) & 1`) but is another trusted layout fact and another proof. |
| anything via a join or filter result | not meaningful | result chunks of operators are arbitrary-sized; the representation (prefix sums) handles that, the pin of a base table is the case measured |

## 6. How it composes with `valid_cols` and the runtime checks

The loader still must check every `valid_cols` conjunct that is a claim about the data (row cap, `|cell|` caps). The checks run on the
borrowed memory with the same generated assertions. The scan is cheap against the copy: on 39.4M `i128` cells, 18 to 35 ms for the cap scan
against 140 ms for the memcpy. They cannot be dropped, and the verified loader's `requires` is the same text. A unique-key conjunct needs random
access over the cells and is refused by the prototype (it can be done by iterating chunks into a hash set).

## 7. Lifetime, aliasing, mutation risks

* The slices borrow memory owned by the pin. The pin must outlive `run_query` (here: `main` holds `Pin` to its end; the borrow is a raw-pointer
  slice with an unconstrained lifetime, so Rust does not enforce this, `main` does by construction).
* Rust treats `&[T]` as immutable for its lifetime. DuckDB does not write chunks it handed to a caller, but nothing enforces it; a concurrent
  `duckdb_destroy_data_chunk` (another thread, the Python harness) is a use-after-free. The prototype is single process, single thread for the pin.
* Table writes during the call do not change a retained result chunk (it is a materialized copy). That is a property of `duckdb_result_get_chunk`
  on this version, not of the C API contract; a later DuckDB may return references into buffer-manager blocks, which an UPDATE or a checkpoint
  can move or evict. Re-validate on every DuckDB upgrade. Pinning storage segments directly (`lemma_storage`) would be a different statement.
* Peak memory: the pin (decompressed) is the only copy. The copy path holds the pin and the `Vec`.
* Two DuckDB instances: the binary opens the database itself (read only). Library and database versions must match (the repo's
  `build/libduckdb` is 1.2.x, the database files are 1.5.x: the prototype reads a 1.2.x-format copy of the columns).

## 8. Prototype and numbers

Query: `SELECT SUM(value) AS total FROM num WHERE value > 5000`, SEC `num.value` DECIMAL(38,4) (`i128`), 39,401,761 rows, one proved body per
representation (`tests/fixtures/declarative_proofs/zero_copy_sum_filter.rs` borrowed chunks, `..._flat.rs` the control), single thread,
8-core shared box, `flock /tmp/lemma_timing.lock`, median of 9 binary starts (kernel = each binary's own median of 9), result equal to DuckDB 1.5.4
(1624021105172689090.7327). Both binaries link DuckDB 1.2.2 and read a 1.2-format copy of the column (the 1.5.4 file does not open with it).

| step (us) | zero-copy (borrowed chunks) | native copy (C-API pin + memcpy into one Vec) |
|---|---|---|
| PIN (SELECT materialized, chunks fetched) | 471,832 | 483,013 |
| WRAP / memcpy | 76 | 124,745 |
| CHECK (caps scan) | 19,253 | 17,816 |
| kernel (`run_query`) | 25,164 | 25,658 |
| **one shot** | **516,325** | **651,232** |

DuckDB 1.5.4 in place, same SQL, Python, no preparation: 226,055 us. Existing shipped path on this column (not re-measured: its `prepare` fails in
this worktree, vendor docs missing): 22.4 s vectorized pin+encode and about 36 s per-row export, from `decl_oneshot.jsonl` and the speed-claims verdict.

Reading: zero-copy saves 135 ms of 651 ms (21 percent) over a native copy loader, and both are 40 to 70 times faster than the shipped exporter. Neither
beats the reference answering in place for ONE query (516 and 651 ms vs 226 ms, a first query is 2.3x and 2.9x slower); the kernel is 9x faster
(25 vs 226 ms), so break-even is 2 queries (zero-copy) or 3 (copy). Caveats: the reference timing is Python on 1.5.4, the binaries use 1.2.2; the machine was
shared and PIN varied 0.41 to 1.3 s between starts in my spikes; the kernel is single threaded.

**The pin is not zero-copy inside DuckDB.** `duckdb_result_get_chunk` returns a fresh caller-owned copy on every call (a refetch gives another
pointer), so DuckDB copies twice (materialize, then fetch). The adversary measured the resident set: 953 MB after the query, 1,564 MB after
fetching all chunks. "Zero copy" removes only Lemma's own third copy. A streaming `duckdb_fetch_chunk` retains one copy but ran 2 to 4 times slower
here (single-threaded scan). Chunk sizes: 12 of 19,244 chunks of `num` are not 2048 rows.

**Adversary verdict** (`zero_copy_lease_ADVERSARY_VERDICT.md`): SOUND after fixes, do not merge. Open findings: (1) the loader checks the pinned storage width only,
not logical type/precision/scale: a `DECIMAL(38,2)` column under a `DECIMAL(38,4)` spec verified and printed NULL instead of the DuckDB sum
(needs the schema model passed to the assembler; NOT fixed in the prototype); (2) generated `SELECT` uses sanitized identifiers, a wrong-table risk for
names with spaces (NOT fixed); (3) null-pointer check added; (7) narrow-cell specs should be refused at assemble time (not done).

## 9. Changes needed in emit, assemble and the prompt (not done here beyond the prototype)

* `emit`: none for the spec functions. The struct field type and `valid_cols` conjunct are a textual rewrite today (`zero_copy.rewrite_spec`);
  it should move into the emitter behind the flag.
* `assemble`: the zero-copy `main` (done in the prototype, one table, no parallel); the harness must link the DuckDB library, pass the database path,
  and stop writing `cols_*.bin` for these columns. The `PIN_US` of the binary is the pin cost the speed-claim reporting must show.
* prompt: columns are not indexable; the sliced hot-loop recipe becomes the canonical loop (chunk by chunk, `lemma_cell` per cell). The lemma
  index gets `lemma_cell`, `lemma_offs_mono`. The admission lint already accepts the worked body (`PinnedCol`, `lemma_cell`, `lemma_offs_mono` are host names).
* reporting: every result that uses it says "zero-copy lease (ZC-1)", and the one-shot number includes the pin.

## 10. What is false in reality (for the adversary)

1. DuckDB's chunk sizes are not uniform (measured: 11 of 19,244 chunks have a size other than 2048 on `num`, the last has 1,878). A representation
   assuming 2048-row chunks would be wrong; ours carries prefix sums.
2. A "flat vector" is assumed; a different version or query shape (`WHERE`, joins) could hand back dictionary or constant vectors.
3. `i128` buffers are 16-aligned today by allocation luck; the check turns a violation into an abort, not into a misread.
4. Fidelity (item 3) is not independently checked.
5. The prototype links a DuckDB (1.2.x) that is not the reference engine (1.5.x).
