# Adversary verdict: bulk (numpy) column exporter

Subject: `_export_table` / `_encode_columns` / `_pack_strings` / `_decimal_unscaled_sql` in `research_loop/decl_query_measure.py`, against the per-row oracle `_export_table_rowwise` (`tests/_export_rowwise_reference.py`).

Claim under test: emitted bytes IDENTICAL to the old exporter for every input the old one accepts; `ValueError` for every input the old one refused.

## Verdict: ACCEPT WITH FIXES

`tests/test_export_bulk_differential.py`: 30 passed. About 200 further differential cases (scratch scripts in the session scratchpad, `exp1.py` to `exp5.py`) agree on the large mainstream: all NULL/validity shapes, narrow widths and their refusal, i64/u64/i128 extremes, dates incl. +-infinity and 5877641 AD, FLOAT/DOUBLE NaN/-0.0/inf, empty tables, tables over 2048 and over 500k rows, deleted-row/updated/checkpointed tables (rowid order equals scan order), read-only file DBs and read-only ATTACHed DBs (TEMP TYPE works there), column names with quotes/keywords/spaces, 1 MB and 20 MB strings, empty/unicode/quote/backslash/trailing-space/case-differing strings, the same column used twice, 256/257-entry u8 dictionaries, and dictionaries up to 4M distinct entries (new is not slower than old there). Temp ENUM types are always dropped, also after a refusal.

The claim is nevertheless false as stated. There is one realistic regression (Finding 1: DECIMAL with scale >= 20 is refused, the old exporter accepted it) and several smaller ones, all fixable. Findings 2 to 5 share one root cause (the dictionary is built by SQL: `GROUP BY` + `min(rowid)` + a generated ENUM literal) and disappear together if the dictionary is built in numpy from the already-fetched string column (e.g. `np.unique(..., return_index=True)` ordered by first index, or a dict pass over the fetched object array).

Differences are labelled BYTES (emitted bytes differ, silently), REFUSAL (old accepted, new raises) or EXC (only exception type/message differs).

## Findings

### 1. REFUSAL, high: DECIMAL with source scale >= 20 overflows in `_decimal_unscaled_sql`

The fractional part is `CAST((v - trunc(v)) * CAST(10^s AS DECIMAL(38,0)) AS HUGEINT)`. DuckDB multiplies the unscaled integers at result type DECIMAL(38,s); `frac_unscaled * 10^s` exceeds 10^38 once s >= 20 (and not-tiny fractions).

Repro (field `("v","i128")`, schema `{"v":"decimal(38,20)"}`, same for (30,20), (38,25), (38,30), (38,37)):
```sql
CREATE TABLE t (v DECIMAL(38,20));
INSERT INTO t VALUES (1.33333333333333333333), (-1.33333333333333333333);
```
- old: 40 bytes (valid, two i128 cells).
- new: `ValueError: Out of Range Error: Overflow in multiplication of DECIMAL(38) (33333333333333333333 * 1000...`.
- DECIMAL(38,38), value 0.1111...: old bytes; new `ValueError: Conversion Error: Could not cast value 100000000000000000000000000000000000000 to DECIMAL(...`.
- DECIMAL(38,19) and below are identical (the added test only goes to scale 4).

The catalog classifies DECIMAL(p<=38, s<=p) as supported (`_classify_decimal`), so these are in-contract inputs. Same expression is used on the f64 path.

Fix: do not multiply the fraction by 10^s in DECIMAL. Use `CAST(CAST((v - trunc(v)) AS DECIMAL(38,s)) ... )` is not enough; use integer arithmetic only, e.g. fetch `CAST(v * 1 AS ...)` split in two exact limbs: `hi = CAST(trunc(v) AS HUGEINT)` and `lo = CAST(replace(CAST(v - trunc(v) AS VARCHAR), ...))` is ugly; simplest robust fix: for src_scale > 18 split the fraction in two steps (multiply by 10^9, trunc, then by 10^(s-9)) so no intermediate exceeds 10^38, or use `HUGEINT` cast of `v * 10^k` per partial scale. Add differential tests at scale 20, 25, 30, 38.

### 2. BYTES (silent), medium: a user column named `rowid` changes dictionary code order

`min(rowid)` binds to the user column instead of the pseudo column.

Repro: `CREATE TABLE t (rowid BIGINT, s VARCHAR); INSERT INTO t VALUES (3,'a'),(2,'b'),(1,'c'),(9,'a');` fields `[("s","u8"),("s__dict","String")]`.
- old: codes `0,1,2,0`, dictionary `[a,b,c]`.
- new: codes `2,1,0,2`, dictionary `[c,b,a]` (ordered by the user's rowid values).
Also `rowid VARCHAR` as the dict column itself, or two dict columns: dictionary becomes sorted by the value (z,a,m -> a,m,z). Code and dictionary stay self-consistent, so query answers do not change, but the bytes differ and "code order = first appearance" is violated. A non-numeric `rowid` column makes the order lexicographic.

Fix: build order without `rowid` (see the root-cause note), or refuse tables with a column named `rowid` loudly.

### 3. REFUSAL, medium: views (no `rowid`)

Repro: `CREATE TABLE base(s VARCHAR); INSERT INTO base VALUES ('b'),('a'),('b'); CREATE VIEW t AS SELECT * FROM base;` fields `[("s","u8"),("s__dict","String")]`.
- old: bytes. new: `ValueError: Binder Error: Referenced column "rowid" not found in FROM clause!`.
Plain (non-dictionary) columns on views are fine. Any table function / view / subquery-backed "table" fails only for dictionary columns. Only matters if the pipeline ever points at views; the exporter did not need rowid before.

Fix: `row_number() OVER ()` as a subquery, or the numpy-side dictionary.

### 4. REFUSAL, low: NUL bytes inside dictionary strings

Repro: `CREATE TABLE t (s VARCHAR); INSERT INTO t VALUES ('a'||chr(0)||'b'), ('zz');` fields `[("s","u8"),("s__dict","String")]` (also `'a\0'`, `'\0'`).
- old: bytes, dictionary entry `a\0b` (3 bytes). new: `ValueError: Parser Error: unterminated quoted string` (the NUL is embedded in the `CREATE TYPE ... ENUM('...')` SQL text).
Plain `String` fields with NULs are identical in both. Rare in real data but a hard failure where the old one worked.

### 5. REFUSAL, low: columns with a non-default collation

Repro: `CREATE TABLE t (s VARCHAR COLLATE NOCASE); INSERT INTO t VALUES ('A'),('a'),('b'),('B');` fields `[("s","u8"),("s__dict","String")]`; also `COLLATE NOACCENT` with `'e'`,`'é'`.
- old: 4 distinct entries `A,a,b,B` (Python string identity). new: `GROUP BY` merges them under the collation, then `CAST('a' AS ENUM)` fails: `ValueError: Conversion Error: Could not convert string 'a' to UINT8`.
Loud, never silent. Plain `String` fields on such a column are identical. Fix: `GROUP BY CAST(q AS VARCHAR COLLATE "BINARY")`-style, or the numpy-side dictionary.

### 6. REFUSAL, low: declared vs actual DECIMAL scale mismatch on an empty or all-NULL column

The old code refused a too-precise DECIMAL only when it met a row; the new code raises at plan time.
Repro: `CREATE TABLE t (v DECIMAL(10,3));` (empty, or only NULL rows with `v` nullable), schema `{"v":"decimal(10,2)"}`, field `("v","i64")` (and `{"v":"double"}`, `("v","f64")`).
- old: 8 bytes (empty) / valid all-default bytes. new: `ValueError: "v" has more than 2 fractional digits`.
Only reachable if the catalog type disagrees with the stored type, so effectively a stricter, arguably better refusal. Mention only to correct the "same refusals" claim.

### 7. BYTES / REFUSAL, low: schema type differs from the DuckDB column type

The old exporter encoded whatever Python value came back; the new one casts in SQL. Observed (schema type -> actual column -> field):
- varchar -> BOOLEAN -> String / dict: old `True`/`False`, new `true`/`false` (BYTES).
- varchar -> FLOAT -> String: old `0.10000000149011612` (Python float repr), new `0.1` (BYTES).
- varchar -> BLOB -> String: old `b'ab\x00c'` (Python bytes repr, which is garbage anyway), new `ab\x00c` (BYTES).
- varchar -> DECIMAL(10,3) -> String: old refused (`1.500 has more than 0 fractional digits`), new accepts `1.500`.
- bigint -> DOUBLE -> i64 (`1.5, 2.5, -1.5`): old truncates `1,2,-1`, new rounds `2,2,-2` (BYTES).
- decimal(10,2) -> DOUBLE -> i64 (`1.5, 2.7`): old `1,2` (truncation of the float, ignoring the scale), new `2,3`.
- boolean -> VARCHAR -> bool (`'abc'`): old `true` (truthy), new `ValueError`.
Identical for varchar from INTEGER, DOUBLE (incl. nan, 1e+20, 1e-07), DATE, TIMESTAMP, UUID, and for bigint from VARCHAR, UBIGINT, UHUGEINT. A mismatch between the catalog and the table is already a catalog bug, so low severity, but the bytes differ without an error in the DOUBLE->integer and BOOLEAN/FLOAT->String cases.

### 8. Resource: plain String columns are 4-5x heavier in memory

The old code streamed 500k-row chunks ("a Python tuple per row for a 6M-row table is gigabytes"); the new code materialises each plain String column as one numpy object array of Python strs plus a `.tolist()` plus `raw` list of encoded bytes.
Repro: `CREATE TABLE t AS SELECT 'val_'||(i%1000) AS s FROM range(5000000) r(i)`, field `("s","String")`: peak RSS about 1575 MB new vs about 330 MB old (54 MB output). Long-string dictionary case (100k distinct x 2 KB) peaked at 2.6 GB (old and new in the same process, so shared), new took 4.8 s vs 0.6 s old there (ENUM literal build). Dictionary columns and numeric columns are fine and faster (6M rows, 50 distinct: 0.2 s vs 2.7 s). Not a failure on the measured tables, but a wide table with several plain string columns on a small box could now OOM where the old one did not. Fix if it matters: chunk the plain-string path (LIMIT/OFFSET or `fetch_record_batch`).

### 9. EXC only: exception type differs from `ValueError` outside the guarded block

The `LIMIT 0` description query in `_encode_columns` runs before the `try`, so a missing column or an empty field list raises `duckdb.BinderException` / `ParserException` instead of `ValueError` (old wrapped the first query). Repro: schema `{"a","b"}` but table has only `a`, fields `[("b","i64")]`; or `fields=[]`. The measure caller already catches `duckdb.Error` and re-raises `ValueError`, so the end behaviour is the same; direct callers and the differential harness (which only catches `ValueError`) see the difference. Also message-only differences: `cannot pack code 256 as u8` vs `cannot pack 256 as u8`; DuckDB `Conversion Error` text for UHUGEINT overflow vs `cannot pack ... as i128`; `"v" has more than N fractional digits` without the value. For a NULL in a not-nullable dictionary column with more than 256 entries, the old one reports the NULL, the new one the code width (both refuse).

## Checked and found identical (no finding)

NULL default cells and validity vector; code 0 for NULL dictionary cells; all-NULL dictionary (entry `""`); NULL vs empty-string distinct; narrow i8/i16/i32 packing and one-past refusal (including with NULLs); i128 hi/lo split for negatives and 38-digit values; DECIMAL(38,19) and below incl. negative fractions; DECIMAL into f64 (refusals match, and large HUGEINT/DECIMAL(38,0) to double rounds identically); UBIGINT up to 2^64-1; HUGEINT extremes; DATE extremes and +-infinity; booleans; FLOAT/DOUBLE specials (NaN sign bit, -0.0, inf, denormals); strings with quotes, backslashes, unicode, combining marks, 1 MB and 20 MB values, trailing spaces; same column twice; omitted columns; empty table in all kinds; multi-chunk tables; deleted/updated/checkpointed tables; read-only and attached read-only databases; column names `m`, `s`, `c0`, `select`, quoted names.

## Disposition (author, after the review)

1. Fixed: from source scale 19 up the unscaled integer is taken from the exact decimal text (no DECIMAL multiply); differential tests at (38,20), (30,25), (38,30), (38,38), (38,19).
2. Fixed as a loud refusal: a table with a column named rowid and a dictionary column raises ValueError (test).
3. Already a loud ValueError (Binder Error on a view); the product reads base tables. Not changed.
4. Fixed as a loud refusal (NUL in a dictionary string, test). 5. Loud refusal, not changed (collated columns do not occur in the pinned catalogs).
6. Accepted: stricter, plan-time refusal of a catalog/table scale mismatch.
7. Fixed as loud refusals: BOOLEAN/FLOAT/BLOB/DECIMAL into a String field, DOUBLE/FLOAT into an integer field, VARCHAR into a bool field (test). Other catalog/type mismatches are catalog bugs.
8. Not changed: plain String columns are materialized whole (about 4x the old streaming memory); dictionary and numeric columns, the shipped default, are not affected.
9. Fixed: the description queries are inside the ValueError wrapper.

10. Later change (author): a DECIMAL whose scaled value fits 18 digits is scaled with plain 64-bit arithmetic (HUGEINT arithmetic cost Q6 38 s, now 2.9 s); the same differential tests pass.
