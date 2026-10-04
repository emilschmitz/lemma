# Proposal: dictionary-encoded string columns (`LEMMA_STRING_ENCODING=dict`) — for adversary review

Protocol: `TRUSTED_ADDITION_PROTOCOL.md`, step 1. Status: implemented behind the flag, default `plain`, NOT cleared by an
adversary. Do not make `dict` the default before the verdict.

## What changes
A string column `c` of a table is loaded as two vectors instead of `Vec<String>`:

```
pub c: Vec<u8|u16|u32>,      // one code per row
pub c__dict: Vec<String>,    // the distinct values
```

Every spec statement about the cell is made through one accessor, textually substituted for `t.c@[i]@`
(`declarative_spec/emit_surface.py::_string_views`):

```
t.c__dict@[t.c@[i] as int]@
```

so the SQL meaning of every predicate, key and output is unchanged. `valid_cols_<table>` gains, per string column, the
loader relation as a REQUIREMENT of `run_query`:

```
forall|i: int| #![trigger t.c@[i]] 0 <= i < t.n as int ==> (t.c@[i] as int) < t.c__dict@.len()
forall|a: int, b: int| #![trigger t.c__dict@[a]@, t.c__dict@[b]@] 0 <= a < b < t.c__dict@.len() ==> t.c__dict@[a]@ != t.c__dict@[b]@
```

`t.c@.len() == t.n` is kept for the codes; the dictionary has its own length. The code width comes from the catalog
(`ColumnAssumption.max_distinct`, a data assumption, `check.py` measures `COUNT(DISTINCT c)`): u8 up to 256, u16 up to
65536, else u32. A column named `*__dict` is refused.

## Trusted surface
No new `external_body`, `assume`, lemma or spec fn. The only new trusted code is the same kind as before: the generated
`main` reads the column file. It checks the relation at runtime (`assemble.py::_runtime_checks`: every code is below the
dictionary length; the dictionary entries are pairwise distinct, via a `HashSet`) next to the other `valid_cols` facts,
and the loader fns `ensure valid_cols_*` from the restated `requires`, which Verus verifies. The exporter
(`decl_query_measure._export_table`) writes: row count, then per field in struct order either `n` values, or for
a `__dict` field its own count (u64) followed by that many length-prefixed strings.

## What could be false
1. The exporter builds a wrong dictionary (a code pointing at the wrong string). The runtime asserts only check the
   RELATION (codes in range, entries distinct), not that `dict[code[i]]` equals the DuckDB cell. The same is true of
   plain strings: nothing checks that the file's strings are DuckDB's. The harness compares the binary's printed rows
   with DuckDB's (`rows_match_error`), which catches a wrong dictionary on the measured data.
2. String equality semantics. The dictionary is deduplicated by Python `str` equality (byte equality of the UTF-8), the
   spec by `Seq<char>` equality. They agree except for strings that are not valid UTF-8 (DuckDB VARCHAR is valid UTF-8).
3. `max_distinct` too small: the u8 code type would then truncate. The exporter packs with `struct.pack("<B", code)`,
   which raises on a code above 255, so the export fails loudly; `check.py` also fails on the real database.
4. `valid_cols` is a requirement on the data. A dataset violating it is rejected by `main`, never silently accepted.

## Which shapes it unlocks, measured
TPC-H SF1, `SELECT MIN(l_extendedprice) AS lo, COUNT(*) AS n FROM lineitem WHERE l_shipmode = 'AIR'` (hand-proved bodies
`tests/fixtures/declarative_proofs/tpch_shipmode_min_count_{plain,dict}.rs`, both verified; result rows equal DuckDB's):

| encoding | binary | DuckDB (all cores) | binary / DuckDB |
|---|---|---|---|
| plain `Vec<String>` | 36.4 ms | 6.3 ms | 5.8x slower |
| dict (u8 codes) | 7.0 ms | 8.0 ms | 0.9x (about parity) |

The dictionary is 5.2x faster than plain on this scan and removes the gap to DuckDB. SEC synthetic (1M `num` rows)
`SELECT MIN(ddate), MAX(ddate) FROM num WHERE uom = 'pure' AND qtrs = 3`: plain 299 us, dict 305 us (parity: the plain
body only touches `uom` on the rows with `qtrs = 3`; the win is for filters that read the string first).
Measured with `research_loop/scripts/decl_dict_bench.py {tpch,sec}`. The grouped T2 query (GROUP BY l_returnflag) needs a
dense-array-over-codes body that has not been hand-proved; the index note describes the recipe.

## Review asks
Attack: (a) an input satisfying `valid_cols` for which the accessor reads a different string than the plain encoding
would (duplicate or out-of-range code, empty dictionary with n > 0); (b) a spec path that still reads `t.c` as a string
(missed substitution; the regex `_string_views` handles `.c@[idx]` and `(.c@[idx]@)`, not `.c@[idx]` inside a trigger or
an `as int` cast); (c) the legacy count/join emitters in `emit.py` are not dictionary-aware; in dict mode `_emit_integer_sql` sends every
query to the surface emitter (test `test_dict_mode_never_uses_the_legacy_emitters`): confirm there is no other path that
writes a `Vec<String>` struct field for a string column.
