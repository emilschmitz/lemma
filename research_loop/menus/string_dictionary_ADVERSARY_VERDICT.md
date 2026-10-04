# String dictionary review (manual adversary, Sonnet subagent)

Target: `LEMMA_STRING_ENCODING=dict` as proposed in `string_dictionary_PROPOSAL.md`, commit `3f9e6a0`. Soundness only (float rounding is
out of scope here). Tests: `tests/test_string_dict_adversary.py` (48 pass; Verus through `verus_guarded.sh`).

## Verdict: merge as default: **no, not yet; yes after conditions 1 and 2**

I found no unsound path. The relation the proofs rely on is checked at runtime on every path and the spec means the same as the plain
encoding. Two things block flipping the default: the reviewed commit is incomplete, and the coverage/speed claim is not re-verified.

### Conditions before flipping the default from plain to dict

1. **Ship the missing files.** `3f9e6a0` does not contain `research_loop/table_assumptions.py` (`ColumnAssumption.max_distinct`), the dictionary
   exporter in `research_loop/decl_query_measure.py`, nor the distinct-cap check in `research_loop/assumption_packages/check.py`; they existed only as
   uncommitted edits in worktree `agent-addcd33571290f391` (the commit's own tests fail with `TypeError ... max_distinct` on integration). I copied
   those three files unchanged into my branch (`ea31343`) to review the real implementation; commit them on the source branch.
2. **Re-run the coverage and speed claim on the default path.** I did not re-run `decl_dict_bench.py` (a 39M-row DuckDB build was running; the benchmark
   needs the SF1 TPC-H database). In dict mode every query goes through the surface emitter; the refusal set equals the plain one on a 26-query battery, but
   the legacy emitters' coverage (grouped COUNT, join SUM over string keys) must be measured on the coverage sample before the default changes.
3. Keep `dict` opt-in until a full paper card has run in dict mode with no new refusals and the same rows as DuckDB (the harness `rows_match_error` is the
   only check that `dict[code[i]]` is DuckDB's cell, exactly as for plain strings).

## (1) Can the loader relation be false while the proof assumes it? No.

* `_runtime_checks` asserts both conjuncts (every code below the dictionary length; entries pairwise distinct through a `HashSet` of Rust `String`s) for every
  table with a string column; an unknown `valid_cols` conjunct raises at assembly. The asserts sit in `main` before `run_query` for **every** table:
  checked on a two-table join with the same column name `s` in both (`t_s__dict`, `u_s__dict`, both checks and both "entry repeats" asserts precede
  `run_query(`), on a self-join (one load, one check), and on a table with no string column (no dictionary at all).
* Decided exactly by compiled Rust: empty table (accepted), `n > 0` with an empty dictionary (aborts), code one beyond the dictionary (aborts), repeated
  entry (aborts), `"a"` vs `"a "` and composed vs decomposed `e` (distinct, accepted).
* Code width: 256 distinct fit u8 (codes 0..255), 257 raises `cannot pack 256 as u8` at export (loud), same at 65536/65537 for u16; `code_type` maps
  256 to u8, 257 to u16, 65537 to u32. A `max_distinct` smaller than the data fails at export, and `check.py` measures it.
* Round trip of 13 tricky strings (emoji, NUL, newline, CRLF, trailing space, empty, composed vs decomposed, backslash, 100 kB) plus reversed duplicates:
  `dict[code[i]]` equals DuckDB's cell for every row, the dictionary is distinct, its length equals `COUNT(DISTINCT s)`. DuckDB and Python agree on string
  equality (binary collation: `'a' = 'A'`, `'a' = 'a '`, `'é' = 'e'||chr(769)` all false). The reader uses `String::from_utf8(...).expect`, so invalid
  UTF-8 aborts instead of being altered.
* NULL cells are refused at export (before the dictionary branch); an empty table exports an empty dictionary; strings over 4 GB are refused.
* Two-table dictionary program: the loader verifies (`N verified, 0 errors`, one Verus job).
* Residual trust (unchanged from plain): nothing proves the file's strings are DuckDB's; the harness compares printed rows.

## (2) Does any spec statement mean something different? No.

For 19 accepted query shapes (equality, `<>`, LIKE, NOT LIKE, IN list, IN subquery, COUNT DISTINCT, GROUP BY one and two string keys, DISTINCT,
ORDER BY, CASE, HAVING on a string key, string joins across tables, self-join, a join where both tables name the column `s`, `s = g` on two columns of one
table, `s = ''`, a literal absent from the dictionary) the dict spec equals the plain spec **textually** once `t.c__dict@[t.c@[i] as int]@` is read back as
`t.c@[i]@` (struct and `valid_cols` excluded). So no statement keeps a raw code, and no emitted comparison relates codes of two columns (checked by pattern
on the join specs: a join on `t.s = u.k` compares `t.s__dict@[..]@ == u.k__dict@[..]@`, each through its own dictionary). A literal absent from the
dictionary compares false for every row, same as plain. Ordering, BETWEEN, MIN/MAX on strings, LOWER/LENGTH/concat are refused in both encodings (same
refusal set). The one shape whose text differs, `GROUP BY s` with `COUNT(*)`, now uses the surface emitter instead of the legacy `StringHashMap` emitter
(its spec has no `Vec<String>` and goes through the accessor like the two-key case). Keyword-named columns (`type`, `match`) get `r#type` plus
`r#type__dict` and consistent loader variables. A column named `*__dict` is refused.

Aside, not dict-specific: a quoted upper-case column `"S" = 'x'` emits the bare token `S` in both encodings (Verus rejects it, so it fails loudly).

## Open items (none unsound)

* Commit completeness (condition 1), pinned by `test_the_reviewed_commit_ships_every_file_it_needs`.
* Coverage/speed unverified (condition 2).
* `max_distinct` is a data assumption enforced at export and by `check.py`, not by `main`; that is safe because the exporter, not `main`, picks the code width
  and fails on overflow.
