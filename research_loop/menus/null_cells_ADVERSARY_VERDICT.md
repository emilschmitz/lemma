# NULL output cells and NULL-last ORDER BY: adversary verdict (commit 1328225)

Manual adversary under `TRUSTED_ADDITION_PROTOCOL.md`. No engine code edited. DuckDB 1.5.4. Spec emission checked with
`declarative_spec.emit.emit_declarative_spec` on small catalogs (t: a, x nullable int, s nullable varchar, f/bb/d/m nullable
double/bool/date/decimal; u: b, y nullable, z). Verus not run (reading and Python only).

## Findings

### F1 (c, bug, silent misstatement): explicit `NULLS FIRST` is dropped; the spec states NULLS LAST

```sql
SELECT x FROM t ORDER BY x NULLS FIRST
SELECT x FROM t ORDER BY x DESC NULLS FIRST
SELECT x, COUNT(*) AS c FROM t GROUP BY x ORDER BY x NULLS FIRST
```

Data: t.x = 1, NULL, 3, NULL. DuckDB returns `NULL, NULL, 1, 3` (and `NULL, NULL, 3, 1` for DESC NULLS FIRST). The emitted
ensures is the same `null_last_order` text as for plain `ORDER BY x`: adjacent rows require a valid key before a NULL key.
A body that returns DuckDB's actual order violates the ensures, and a body that proves the ensures returns NULLs last, which
is not what the query says. The parser never reads `nulls_first` (`grep -n nulls_first declarative_spec` finds nothing), so the
modifier is silently ignored. Before this commit a nullable key could not be ordered by without a proof of non-NULL, so the
modifier was moot; the commit made it reachable. `ASC NULLS LAST` and `DESC` are correct only because they match the default.
Fix needed (a): refuse any ORDER BY key whose sqlglot `nulls_first` differs from DuckDB's default (ASC and DESC are both
NULLS LAST, so `nulls_first=True` is the only bad case; an explicit `NULLS LAST` is fine). Best place: where `OrderKey` is
built in parse, or in `nulls.py` for a key that is in `cells`/`keys`. Add a test for both directions.

### F2 (c, bug, breaks timed run loudly, not the proof): `Option<String>` cells print raw, the bench decodes hex

`assemble._row_printer` prints `String` fields as `row_hex(..)` but an `Option<String>` field as `format!("{}", v)` (raw text)
and `NULL` for None. `bench._decode_field` decodes every `str` kind cell (kind strips the `Option<`) with `bytes.fromhex`.
Reproduced the printer: `SELECT s FROM t` yields `match res[i].s { Some(v) => format!("{}", v), None => "NULL"... }`.
Effect for any non-NULL, non-empty string cell: `"US"` raises "string 'US'" ("proved but a result field did not parse");
`"10"` decodes to byte 0x10 and mismatches; a string whose text is `NULL` decodes to NULL. A string containing the unit
separator splits the row. So every timed run of `SELECT <nullable varchar>` (and a nullable varchar GROUP BY key, which had
the same latent bug) fails the row check. Not unsound (the proof is untouched) but the new plain-projection path makes it
common. Also `Option<bool>` prints `true`/`false` while kind is int (`int("true")` fails, loud). Fix: print `Some(v)` for
`Option<String>` with `row_hex(&v)` and `Option<bool>` as `1u8/0u8`; add a bench round-trip test with a NULL and a non-NULL string.

### F3 (b, accepted limitation / unverified): ORDER BY nullable BOOLEAN emits `<=` / `>=` on `bool`

`SELECT bb FROM t ORDER BY bb` (bb nullable boolean) emits `(...).1 <= (...).1` over bool. I did not run Verus. If Verus
rejects `<=` on bool this is a loud emit-time type error (same as a non-nullable bool ORDER BY before the commit), not silent.
Recommend refusing ORDER BY on a bool key, or confirming Verus accepts it. Low priority.

## Attack lines tried, no defect found

1. Multi-key ORDER BY, DESC, ties, LIMIT, DISTINCT. Mirrored `null_last_order` plus the `if tie {next} else {order}`
   chain in Python and checked DuckDB's actual output for 300 random tables (NULL-rich int/varchar/int keys with values
   1-3, `""`, `a`, `ab`, `b`, random ASC/DESC per key): every adjacent pair satisfies the stated not-after predicate. The
   omitted-row clause (`_order_hit_pairs`: last result row view vs `_key_cell` of the omitted hit, both `(valid, value)`) and the
   grouped `_omitted_after` (`key_of` / `key_of.idx`, which are pairs for nullable keys) use the same predicate on consistent
   operands. DISTINCT over Option cells: out_key pairs are distinct and `(false, d)` is one NULL group like DuckDB.
   `ORDER BY` with `-x`, `x+1`, `ABS(x)`, `CAST`, `x IS NULL`, `COLLATE`, `LOWER(s)`, `(x)`, ordinal `1`, OFFSET: all refused.
2. Alias vs same-named column. Projection aliases are refused, so there is no alias to collide. `ORDER BY` resolves to an
   output field by bare name (`_order_field`, `_order_exprs_*`), but same-named columns in two joined tables, and self-joins,
   are refused up front ("column 'x' is ambiguous across tables"), so `t.x` selected with `u.x` ordered cannot reach the
   emitter. In the grouped path `SELECT a AS x ... GROUP BY a ORDER BY x` is refused by `nulls.py` (ORDER BY x resolves to
   the unproven nullable column); `SELECT x AS a, COUNT(*) ... GROUP BY x ORDER BY a` binds alias `a` in DuckDB and in the
   emitter alike. `GROUP BY k` on an alias of a nullable column is refused (conservative).
3. Proof via OR/NOT/non-top-level. `_mark_nullable_key` only trusts a top-level `!is_null(col)` conjunct. Checked
   `x IS NOT NULL OR a>1`, `x IS NOT NULL OR x IS NULL`, `x = x OR a>1`, `x IS NULL`, `EXISTS (... t.x IS NOT NULL)`, NOT EXISTS, IN
   subquery with the guard inside: all stay `Option`. `NOT (x IS NULL)`, `NOT (x IS NULL OR a>1)`, `x IS NOT NULL AND a>1`,
   `(a>1 OR a<0) AND x IS NOT NULL` become plain, and in each the where text contains the top-level valid conjunct, so
   NULL rows are excluded. The regex ignores the table alias prefix, which would be wrong for same-named columns of two
   tables, but that case is refused earlier; keep that ambiguity refusal or tighten the regex to the owner alias.
4. String collisions. `(false, "")` vs `(true, "")` differ by the bool; same for `(false,0)` vs `(true,0)`, floats, dates,
   decimals. Dict encoding (`LEMMA_STRING_ENCODING=dict`) emits `(if s__valid { (true, s__dict@[code]@) } else { (false, empty) })`,
   consistent with the plain path. A NULL cell's dict code is not read.
5. Exec readers: `assemble._out_row_fields` / `_row_printer` and `decl_query_measure._canon/_kind` handle `Option<..>` (see F2
   for the one that does not decode correctly). `parallel.py`, `drive.py`, `numeric_rewrite` (OUT_SCALES) do not look inside field
   types. Nullable decimal/date/float columns emit `Option<i64>/Option<i32>/Option<f64>`.

Other shapes checked and refused or correct: UNION arms (refused: nullable in SELECT list), derived tables, LEFT JOIN, nullable join
keys, aggregates over nullable columns in grouped queries, a nullable column in an expression or CASE, `SELECT *`.

## Classification

| id | class | summary |
|----|-------|---------|
| F1 | (c) bug, fix by tightening | `NULLS FIRST` ignored; spec says NULLS LAST |
| F2 | (c) bug in host bench path | `Option<String>` printed raw, decoded as hex; Option<bool> printed as true/false |
| F3 | (b) limitation / unverified | ORDER BY on a nullable bool key uses `<=` on bool |

## Overall verdict: MERGE-WITH-FIXES

The calculus itself (pair key, NULL-last predicate, omitted-row clauses, proof detection) held up under reading and 300
random DuckDB comparisons. F1 is a real silent misstatement and must be refused before merge. F2 does not affect soundness
but makes every timed `SELECT <nullable varchar>` fail its row check; fix it or the new surface cannot be benchmarked.

## Resolution (author)
* F1 fixed: the default sqlglot dialect reads a plain ASC key as NULLS FIRST, so `_null_rewrite_sql` marks each Ordered key
  with what the DuckDB dialect reads (`meta["duck_nulls_first"]`) and `nulls.py` refuses an explicit NULLS FIRST on a
  nullable key. Tests: `test_an_explicit_nulls_first_on_a_nullable_key_is_refused_not_ignored` (3 shapes),
  `test_nulls_last_and_a_non_nullable_key_are_unaffected`.
* F2 fixed: `assemble._row_printer` prints `Some(String)` through `row_hex` and `Some(bool)` as 1u8/0u8. Tests:
  `test_the_bench_row_printer_prints_option_cells_the_way_the_decoder_reads_them`.
* F3 open and not reachable from GenDB (no bool columns); a bool key is refused or loudly rejected by Verus, never silently wrong.
