# SEC `value` as DECIMAL(38,4): the exact variant

Paper note: **SEC `value` is typed DECIMAL(38,s); GenDB's published schema uses DOUBLE. Results are
reported on the DECIMAL variant; DOUBLE coverage is reported separately.** Here s = 4.

## How it was built (and what it is not)

* The EDGAR source text (`num.txt`, `sub.txt`, `pre.txt`, `tag.txt` of the quarterly zips) is **not
  on this machine**. Only the 1M-row `num` slice `sec_edgar_local.duckdb` is local, and it is not an
  ingestion of EDGAR. It is synthetic: `holdout/gendb_sec_edgar/synth_tiny.py` draws
  `value = round(uniform(1.0, 1_000_000.0), 2)`; the measured slice maximum is 999,997.13 (the real
  maximum 1.884e17 is not in it), and `num.coreg` and `num.footnote` are NULL on every row. The full
  `sec_edgar.duckdb` is not local.
* So the DECIMAL file is **derived from the stored doubles**, not re-ingested:
  `holdout/gendb_sec_edgar/make_decimal_variant.py --scale 4` writes
  `holdout/gendb_sec_edgar/duckdb/sec_edgar_local_dec.duckdb` (gitignored, 19.4 MB), casting each
  DOUBLE through its shortest round-trip text (`CAST(CAST(x AS VARCHAR) AS DECIMAL(38,4))`). Other
  columns and tables are copied. The DOUBLE file is untouched.
* DOUBLE columns in SEC tables: exactly one, `num.value` (`schema.sql`; the local file agrees:
  sub/pre/tag have none). `load_data.py` ingests with DuckDB `read_csv` types from `schema.sql`.
* Scale choice: the slice has at most **2** decimals (measured). The EDGAR documentation (aqfs.pdf)
  gives `value` as NUMERIC(28,4), so s = 4 is used. That is documented, not verified here.

### What is needed for a real re-ingest (not downloaded; needs Emil's approval)

`setup_data.sh` fetches `https://www.sec.gov/files/dera/data/financial-statement-data-sets/{YYYY}q{1..4}.zip`
for 2022-2024 (12 zips, each holding `sub.txt num.txt pre.txt tag.txt`; the full `num` is 39,401,761
rows, several GB unzipped; zip sizes to be read from the SEC site, not measured). Then
`load_data.py` with `value` typed `DECIMAL(38,4)` instead of DOUBLE, after checking the maximum
number of decimals in `num.txt`. With the source text the table below can be exact.

## Losslessness (local slice, scale 4)

| table.column | rows | non-null | max decimals in the double's text | rows rounded by scale 4 | rows with `|x|*10^4 >= 2^53` (double cannot hold every 4-decimal multiple) | max abs |
|---|---|---|---|---|---|---|
| num.value | 1,000,000 | 1,000,000 | 2 | **0** | **0** | 999,997.13 |

Every row converts to the decimal its double prints as, with no rounding. That is lossless to the
double's own precision. It says nothing about the real EDGAR table: values near 1e17 cannot hold 4
decimals in a double (a double at 1.88e17 has a spacing of 32), so on the real data those rows
would be the decimal text of an already-rounded double, not the source value. They cannot be counted
here (the slice has none). The counts for the full table need the source text above;
`make_decimal_variant.losslessness` computes them (rounded / beyond_double / max_decimals).

## Pipeline changes

* `research_loop/assumption_packages/sec_margin.py`: package `sec_margin_dec`. The value cap is the
  same fact (`num.value < 2^62`) in stored units: `2^62 * 10^4` (about 2^75.3), derived from
  `VALUE_EXCLUSIVE` and `DEC_VALUE_SCALE`, never loosened. Measured maximum 1.884e17 stores as
  1.884e21 (about 2^70.7), under it. A two-table sum bound (2^31 rows * cap, about 2^106) fits i128;
  three-table nested sums do not, as for DOUBLE. `max_cell_u64` stays for u64 cells only.
* `ColumnAssumption.scale`: a cap is in stored units of `10^-scale`.
* `assumption_packages/check.py` understands DECIMAL: measures `MAX(ABS(col))` as the exact stored
  integer, and refuses a package whose `scale` is not the column's (so `sec_margin` on the DECIMAL
  file, or `sec_margin_dec` on the DOUBLE file, fails loudly).
* `sqlsmith_trusted_coverage.load_sec_schema(db_path)`: columns the file types DECIMAL(p,s)
  become `decimal(p,s)`; the file selects the variant. `declarative_draws.py` passes its DB, picks
  the matching package, and runs `check_package` before drawing.
* Already fine: `schema_types` (DECIMAL(38,4) is i128 with scale), `numeric_rewrite` (literals such
  as `1000000` and `0.5` are exact), `decl_query_measure` (i128 export, exact scaled results).
  Measured-catalog caps in `db_extension/dataset_config.py` (package unset, recursive pipeline) skip
  DECIMAL columns and were not changed.
* GenDB query generator: unchanged. Its templates are schema-agnostic text (`SUM(value)`,
  `HAVING SUM(n.value) > 1000000`, `value > 0`); the file was drawn with the DECIMAL DB as the filter
  database. 326 queries after dedup/filter, seed 20261004.

## Emission coverage (326 GenDB-shaped queries, `research_loop/generated/decl_coverage/dec_N.sql`)

`uv run python -m research_loop.scripts.decl_coverage <file>`. Emission only, no Verus.

| variant | emitted | refusals, ranked |
|---|---|---|
| DOUBLE (`sec_margin`) | 314 / 326 | 12: SUM over an unknown operand (`SUM(CASE ... THEN n.value ELSE 0 END)`) |
| DECIMAL (`sec_margin_dec`) | 236 / 326 | 78: AVG over a DECIMAL (DuckDB averages in DOUBLE); 12: a DECIMAL result in CASE (same 12 queries, ELSE 0 has scale 0) |

* Non-AVG queries: 206 / 218 on both variants (same 12 CASE refusals).
* The DOUBLE emissions are not all usable. **43 of the 314 DOUBLE specs are ill-typed**: every MAX/MIN
  over `value` emits calls to `max_row_hit`, `max_key_at`, `max_max_value_val` that the spec never
  defines (E0425 in Verus). On DECIMAL there are 0 such specs (75 queries contain MAX on DOUBLE, 32
  on the DECIMAL-emitted set). Well-formed emission is therefore about 271 DOUBLE vs 236 DECIMAL;
  and DOUBLE ORDER BY/HAVING/comparison queries emit, but have no proved float comparison.
* The cost is `AVG(value)`: 78 of 326 queries (24%). That is a design decision (AVG as exact
  SUM/COUNT is a rational, DuckDB returns DOUBLE), left refused as instructed.

## Verus type-check, stub body (`loop {}`, `--no-verify`, `decl_typecheck_sample`, seed 7, 10 per variant)

* DOUBLE: **5 / 10** type-check. The 5 failures are the undefined `max_row_hit` / `max_key_at` /
  `max_max_value_val` emitter bug above (not a DECIMAL matter; emitter agent's domain).
* DECIMAL: **10 / 10** type-check.

## DuckDB timing on the same schema (`decl_duck_timing`, 1M-row `num` slice, 3 warmups, median of 7, microseconds; 8 threads / 1 thread)

| shape (query) | DOUBLE 8t | DECIMAL 8t | DOUBLE 1t | DECIMAL 1t |
|---|---|---|---|---|
| num JOIN sub, SUM(value) GROUP BY (Q104) | 12,716 | 18,143 | 26,083 | 42,152 |
| HAVING SUM(value) > x ORDER BY (Q106) | 13,624 | 19,000 | 23,934 | 43,998 |
| MAX(value) GROUP BY (Q6) | 3,910 | 3,782 | 2,701 | 2,560 |
| num JOIN sub JOIN tag, SUM(value) (Q106) | 22,900 | 18,676 | 24,808 | 49,821 |
| join with `n.value > 0`, SUM (Q147) | 17,795 | 24,349 | 28,202 | 45,595 |

DECIMAL(38,4) is a 128-bit integer in DuckDB: sums and scans are about 1.4x (8 threads) to 1.8x
(1 thread) slower, MAX only is on par. Single runs on a shared box, one measurement each; treat as
indicative (the 8-thread 3-table row is noise-inverted). The speed bar compares to DuckDB on the
same schema, so on DECIMAL the bar is up to about 1.8x easier on sum-heavy queries.

## Memory (exported column file, `num.value`)

16 bytes a cell (i128) vs 8 (f64): 1M rows = 16.0 MB vs 8.0 MB (a test asserts the 8-byte-per-cell
difference). DuckDB file sizes: 19.4 MB (DECIMAL) vs 21.2 MB (DOUBLE; compressed storage).

## Open problems seen (not fixed, outside this task)

1. **NULLs block every `num` query's measure.** The declarative column struct carries *all* columns
   of a table (`Cols_num` has `coreg`, `footnote`, ...), and `_export_table` refuses NULLs. `num.coreg`
   and `footnote` are NULL in this slice (and `coreg` is NULL for primary registrants in real
   EDGAR). So on either variant `write_query_measure` raises "num.coreg has NULLs" for any query over `num`.
   Either prune the struct to the columns the query reads or give NULLs semantics.
2. DOUBLE MAX/MIN emits ill-typed specs (above).
3. `SUM(CASE ... THEN value ELSE 0 END)` is refused on both variants (`ELSE 0` scale mismatch for
   DECIMAL; unknown operand for DOUBLE). 12 of 326 queries.
4. AVG over DECIMAL is refused: 78 of 326 queries.

## Reproduce

```
uv run python holdout/gendb_sec_edgar/make_decimal_variant.py --scale 4
uv run python holdout/gendb_sec_edgar/generate_queries.py --seed 20261004 --num-generate 700 --num-select 700 \
  --db-path holdout/gendb_sec_edgar/duckdb/sec_edgar_local_dec.duckdb --output research_loop/generated/decl_coverage/dec_N.sql
uv run python -m research_loop.scripts.decl_coverage research_loop/generated/decl_coverage/dec_N.sql
uv run python -m research_loop.scripts.decl_typecheck_sample research_loop/generated/decl_coverage/dec_N.sql
uv run python -m research_loop.scripts.decl_duck_timing research_loop/generated/decl_coverage/dec_N.sql
uv run python -m research_loop.assumption_packages.check --package sec_margin_dec --db holdout/gendb_sec_edgar/duckdb/sec_edgar_local_dec.duckdb
```
Tests: `tests/test_sec_decimal_variant.py` (17 cases).
