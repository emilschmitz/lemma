# Adversary verdict: should LEMMA_NARROW_CELLS=1 become the default? (declarative0, Sonnet manual adversary, 2026-10-05)

Worktree HEAD `8e0c485`. DuckDB 1.5.4. Scratch scripts: `/tmp/claude-1000/-home-emil-projects-lemma-db/bd3b4baa-20f9-4ec3-b72d-14c9857f1938/scratchpad/adv_nd/`
(`corpus.py`, `emit_all.py`, `diff.py`, `e2e_common.py`, `e2e_build.py`, `e2e_run.py`, `cmp_e2e.py`, `verify_corpus.py`, `verify2.py`, `join3.py`, `bigrows.py`, `nocaps.py`, `dk.py`).
No source or test file was edited, no commit, no GCP, no timing run. Verus only through `verus_guarded.sh`, one run at a time.

## Short answer

Semantics are sound and the answer to every query is unchanged. **The flip is NOT allowed yet**: nine shipped tests fail with the flag on, seven of them are the
verified worked-example bodies that the prompt mounts into the agent workspace (hand-written with `i64` cells; they do not compile against a narrow `Cols`),
and the flag's parse and the manual-workspace snapshot are not default-safe. These are fixture and plumbing fixes, not soundness findings.

## What was attacked, and the ON-vs-OFF table

Three harnesses:

* **Emit diff** (116 SQL texts: every class below, joins, GROUP BY, DISTINCT, EXISTS/IN, projections, NULLs), emitted ON and OFF, text-diffed.
  Run twice: a catalog with nullable columns (every query goes through the surface emitter) and a catalog with no nullable column and no dict mode
  (the count/join-sum emitter takes the join-sum shapes: `NONULL=1`).
* **Verus** on every ON-emitted spec with the stub body (`assume(false)`), plus ParVSTD (`LEMMA_PARALLEL_VSTD=1`) and dict (`LEMMA_STRING_ENCODING=dict`) variants.
* **Real exporter plus compiled generated binary** (`write_query_measure` on a tiny DuckDB file, then the assembled binary built with `verus --compile` for ON and for OFF;
  a loaded stub body hangs, so "timeout in 4 s" means "the loader accepted the data", a panic names the refusing assert): 57 data scenarios per mode.

| shape class | emit diff ON vs OFF | Verus (ON, stub) | real data, ON vs OFF accept/refuse |
|---|---|---|---|
| NULL validity vector on narrowed columns (i8 `nn` cap 2^7, i32 `ni`, i16 DECIMAL `pn`) | `Vec<iN>` only | verified (aggregates, IS NULL, group keys, mixed `(s2, ni)`) | identical (NULL accepted, 127/-127 accepted, 128 and -128 refused, NULL in a non-nullable column refused both) |
| group keys: single, mixed narrow/wide `(a,d)` `(b,g)`, tuple, string+narrow `(s,c)` `(s,b)`, DECIMAL key, date key | `Vec<iN>` only | verified | cap assert identical in both modes |
| joins narrow/narrow (`b=k`), i8 vs i64 (`c=x`), i32 vs i64, key narrow on one side (`t.d=u.kk`, `t.k8=u.y`), u64 vs i16, hugeint vs i64, two-key joins, EXISTS / IN / NOT IN, DECIMAL=DECIMAL, string=string | `Vec<iN>` only (plus SUM_CAP, F4) | verified (12-15 verified, 0 errors each) | not row-level tested (stub body); loader identical |
| parallel (`LEMMA_PARALLEL_VSTD=1`) scalar and join | `Vec<iN>` only | 8 of 8 verified | not run |
| dict strings (`LEMMA_STRING_ENCODING=dict`) with narrow group parts, nullable dict, join on dict string | `Vec<iN>` only | 7 of 7 verified | not run |
| DECIMAL (10,2) cap 1000, (12,4) cap 2^15, nullable (9,2) cap 2^15, no-cap (10,2) | `Vec<i16>` or `Vec<i64>` | verified | boundaries below |
| DATE | identical (already i32) | verified | 9999-12-31 and 0001-01-01 accepted both |
| HUGEINT, UBIGINT, DOUBLE | identical (i128, u64, f64) | verified (SUM(h), SUM(f) refused identically both modes) | n/a |
| native INTEGER/SMALLINT/TINYINT, no cap | `Vec<i32/i16/i8>` | verified | extremes `2^31-1`, `-2^31`, `32767`, `-32768`, `127`, `-128` accepted both |

### Cap boundaries (real exporter + binary; OFF refuses in the binary assert, ON refuses at pack or in the same assert)

| column, cap (exclusive) | value | OFF | ON |
|---|---|---|---|
| BIGINT cap 2^15 (i16) | 32767, -32767 | accepted | accepted |
| | -32768 (fits i16) | refused (assert, bound 32767) | refused (same assert) |
| | 32768, -32769, 40000 | refused (assert) | refused (`cannot pack ... as i16`) |
| BIGINT cap 2^20 (i32) | 2^20-1 | accepted | accepted |
| | 2^20, -2^20 | refused (assert, bound 1048575) | refused (same) |
| | 2^31, 2^40 | refused (assert) | refused (`cannot pack as i32`) |
| BIGINT cap 2^7 (i8) | 127, -127 | accepted | accepted |
| | -128 | refused | refused (assert) |
| | 128 | refused | refused (pack) |
| BIGINT cap 2^31 (i32) | 2^31-1, -(2^31-1) | accepted | accepted |
| | -2^31 | refused | refused (assert) |
| | 2^31 | refused | refused (pack) |
| BIGINT cap 2^15+1 (i32, not narrower) | 32768 | accepted | accepted |
| | 32769 | refused | refused |
| DECIMAL(10,2) cap 1000 (stored) | 9.99, -9.99 | accepted | accepted |
| | 10.00, -10.00, 327.67 (inside i16) | refused (bound 999) | refused (same assert) |
| | 327.68 (beyond i16) | refused (assert) | refused (pack) |
| DECIMAL(12,4) cap 2^15 | 3.2767, -3.2767 | accepted | accepted |
| | -3.2768 | refused | refused (assert) |
| | 3.2768 | refused | refused (pack) |
| nullable DECIMAL(9,2) cap 2^15 | NULL, 327.67, -327.67 | accepted | accepted |
| | 327.68 / -327.68 | refused | refused |
| no-cap DECIMAL(10,2) | 99999999.99 | accepted (i64) | accepted (i64, not narrowed) |
| 100 rows in cap, 1 violating row at 99/100, empty table | | accepted / refused / accepted | accepted / refused / accepted |

57 scenarios, **zero accept/refuse differences**. The only difference is where the refusal fires (pack at export under ON, loader assert in the binary under OFF);
both are loud, nothing wraps. A stale column file written under the other mode is also loud both ways (`column file has trailing or missing bytes`, or a slice-range panic).

## (a) Can out-of-cap data load silently under ON that OFF refuses (or vice versa)?

No. The integer-cap conjunct and runtime assert (146fe1f) are emitted in both modes with the same bound `|cell| <= cap - 1` and fire on the loaded cells; narrowing only adds the
width check in front of them. A -32768 in an i16 column with cap exactly 2^15 is refused in both modes (the cap is exclusive on |v|, so the lower bound is -32767); the boundary is consistent.
Repro: `LEMMA_NARROW_CELLS={0,1} PYTHONPATH=. uv run python .../e2e_run.py`, then `.../cmp_e2e.py` (needs `e2e_build.py` and a `verus_guarded.sh p.rs --compile` in `e2e_0` and `e2e_1` first).

## (b) Does the default change a user query result or an output field type?

* Result of every query: no. In 76 of 116 emitted specs the only difference is `Vec<i64>` becoming `Vec<iN>` in `Cols_t`; the spec reads every cell `as int`, and every predicate and arithmetic expression is byte-identical. All 23 (19 in the second corpus) refused queries are refused identically with the same message.
* **Output field type: yes, for projections.** `SELECT a, b, c FROM t WHERE ...` has `OutRow { a: i32, b: i16, c: i8 }` under ON and `i64` under OFF; a column whose narrowing comes only from a catalog cap does the same (`SELECT d FROM t` with BIGINT `d` cap 2^15 gives `OutRow { d: i16 }`; DECIMAL `p`, `r` gives i16; nullable gives `Option<i8>`, `Option<i32>`).
  The type of a user-visible output field now depends on the assumption package. 8 of 116 queries (6 of 116 in the second corpus). Aggregate outputs, MIN/MAX, group-key OutRow fields on map shapes are unchanged.
* Emitted text beyond widths: one more difference (F4: `SUM_CAP`).
* Acceptance set widens (a refusal under OFF becomes an accept under ON), sound by the DuckDB type: with `max_rows` 10^10 per table, `SELECT SUM(t.a) FROM t JOIN u ON t.b = u.k` (a INTEGER) is refused by OFF (`SUM(a) can exceed i128: ... x cell cap 9223372036854775807`) and accepted by ON (cell cap 2147483647). Repro `.../bigrows.py` under both modes. With 10^15 rows both refuse.

## (c) Anything narrowed with no package or no stated cap?

Only the DuckDB-native INTEGER / SMALLINT / TINYINT (`int`, `integer`, `int4`, `smallint`, `tinyint`), whose width is the stored width. Repro `.../nocaps.py`:

| catalog | narrowed under ON |
|---|---|
| `None`; row caps only; global `max_cell_u64` / `max_native_u32` only; `abs_sum_exclusive` only | `a:i32, b:i16, c:i8`; BIGINT, DECIMAL (all widths), HUGEINT, UBIGINT, DOUBLE, DATE untouched |
| per-column cap on BIGINT/DECIMAL | narrowed to the narrowest signed width that holds `cap - 1` |
| cap on HUGEINT, UBIGINT, DOUBLE, DATE | not narrowed |
| table/column name case differs from the schema | still matched (casefold) |
| cap 0 or 1 | i8 (degenerate: every row is refused or only 0 loads) |

Data above a stated cap under the default: refused at export (beyond the width) or by the binary assert (inside the width), exactly as OFF (table above).
A schema that declares `integer` for a column that DuckDB actually stores as BIGINT is refused at export under ON (`cannot pack ... as i32`), where OFF loaded it wide: stricter, loud.

## (d) Safe with no user-approved package?

Yes for soundness: with no package nothing is narrowed beyond the declared SQL type, and with a package the caps it states were already a loader conjunct and runtime assert in both modes
(146fe1f), so narrowing adds no assumption. The speed-claims condition ("narrow only under a user-approved package") is about what a speedup claim must say, not about trust. Keep it:
the reporting must print the widths chosen next to a narrow speedup (item 7 of the speed-claims verdict).
Note the SEC harness picks its package itself when `LEMMA_SEC_PACKAGE` is unset (`declarative_round.sec_package` -> `package_for_db`), so under the default the cap-driven widths come from the repo package, not from anything the user approved in that session.

## Findings

### F1 (blocks the flip): nine tests fail with the flag on, seven are shipped worked examples the agent is shown

```
LEMMA_NARROW_CELLS=1 uv run pytest -q tests/test_declarative_null_cells_real.py \
  "tests/test_declarative_string_dict.py::test_parallel_dict_nullable_example_verifies_and_dropping_the_validity_bit_does_not" \
  "tests/test_declarative_string_dict.py::test_block_skip_example_verifies_and_a_wrong_skip_condition_does_not" \
  tests/test_declarative_tpch_q3_q14_q19.py tests/test_parallel_dict_adversary.py
LEMMA_NARROW_CELLS=0 ...same command...   # 74 passed
```

ON fails 9 (the same 9 pass OFF): `test_the_ordering_clause_matches_duckdb_on_real_sec_sub_rows_with_null_fy` (hand-written `OutRow { cik: ...i64 }` literals against an i32 field), the two string-dict example tests,
`test_declarative_tpch_q3_q14_q19.py::test_reference_body_verifies[tpch_q3_join_group_topk.rs]`, `test_wrong_body_is_rejected[...topk.rs-0/-1]`, `test_q3_top_groups_match_duckdb[3,10]`, `test_parallel_dict_adversary.py::test_parallel_nullable_dictionary_scan_matches_duckdb`.
Cause: the fixture bodies in `tests/fixtures/declarative_proofs/` assume i64 cells (E0308 `expected i64, found i16/i32`, e.g. `let m_new: i64 = if hit && (!any_w || v <= m_w) { v } else { m_w }`; `lemma_pa_push(..., kp, ...)` with a `p: i64` parameter given an i32).
`declarative_spec/prompt.py` mounts those fixtures into the agent workspace as examples. Under a default flip every agent gets worked examples that do not compile against the spec it is given.
Fix before the flip: make the fixtures width-agnostic (read cells with `as i64`/`as int`, convert with `i64::from`), or emit the example against the current width; keep one verified example per width class. The rest of the slice (1596 tests) passes ON. Broader suites (db_extension, other `tests/`) were not run.

### F2 (blocks the flip): the flag's parse and the manual-workspace snapshot are not default-safe

* `narrow_cells()` is `os.environ.get("LEMMA_NARROW_CELLS", "0").strip() == "1"`. Once the default is ON, the natural rewrite is `!= "0"`, which turns `false`, `off`, `no`, `` into ON. Parse strictly: accept exactly `0` and `1`, raise on anything else.
* `declarative_manual._job_env_snapshot` stores `LEMMA_NARROW_CELLS` only when it is set in the environment (`tests/test_declarative_manual.py:200-205` asserts it is absent when unset). `check` regenerates the spec and refuses a workspace spec that differs (`SpecMismatch`).
  Every workspace prepared before the flip (flag unset, wide bins and wide spec) is refused after it with `SpecMismatch`, and a later change of the default would break the new ones the same way. The snapshot must record the effective value, and the existing in-flight workspaces need `LEMMA_NARROW_CELLS=0` exported (or re-preparation).
  Loud, not unsound. Same for `container_batch.py` (passes the env only if set).

### F3 (low, theoretical, not a blocker): the native caps exclude the stored minimum

`classify_sql_type` gives INTEGER/SMALLINT/TINYINT `cell_exclusive_cap` 2^31 / 2^15 / 2^7, i.e. `|cell| <= 2^31 - 1`. DuckDB 1.5.4 stores `-2147483648`, `-32768`, `-128` in those types (`dk.py` inserts and reads them; the e2e scenarios `ni=-2^31`, `b=-32768`, `c=-128` load under both modes).
There is no loader conjunct for a native type (the type is the guard), so nothing refuses the minimum and every bound derived from `cap - 1` (`SUM_CAP`, the i128 fit check) is one step short for a column that contains the type minimum.
Under OFF the same flavor exists for BIGINT (`-2^63`), but the INTEGER bound there was 2^63, so it was never reached; under ON it is reachable for the three native widths.
The practical window is negligible (the signed SUM slot is always i128; the fit check only differs for non-power-of-two row caps near 2^96), and `SUM_CAP` is a declared const that no verified assembled file uses (grep over 80 assembled programs: 0 hits).
Fix when convenient: for a native width state the cap as `2^31 + 1`-inclusive (`|cell| <= 2^31`), or say in the docstring that the native bound is `|cell| <= cap` and make the derivations use it.

### F4 (informational, expected): the one emitted-text change beyond widths

Count/join-sum emitter (no nullable column, no dict): `SELECT u.k, SUM(t.a) AS x FROM t JOIN u ON t.b = u.k GROUP BY u.k`:
`SUM_CAP` 9223372036854775807000000 (OFF) becomes 2147483647000000 (ON), and `valid_cols` states `<= 32767` / `<= 2147483647` (the type max) instead of `<= 9223372036854775807`. A tighter, type-true bound (see F3 for its off-by-one at the minimum).
Repro: `NONULL=1` `emit_all.py` for both modes, `diff.py nn`, `show_diff.py nn "<that sql>"`.

### F5 (pre-existing, both modes, unrelated to narrowing)

* A column named `n` collides with the row-count field `n` of `Cols_t` (`error[E0124]: field n is already declared`, E0599 `len` on `usize`). Loud at Verus. Repro: `SELECT SUM(n) FROM t` with a column `n`.
* Unknown column in a WHERE clause (`WHERE zzz > 3`, also inside an OR) is emitted into the spec as an undefined identifier instead of a clean "column not found" refusal; it dies at Verus (`E0425`). Loud, not silent.
* The count/join-sum emitter does not build a printable timed result for unkeyed-cap group-by shapes in the stub assemble (`a timed run needs a printable result`), identical ON and OFF.

## Not attacked / limits

No real-agent body was run; join and group-key shapes were checked at the spec/loader level (stub body), and the i16-key agent body was proved by the manual prover in the earlier round. Parallel and dict variants were checked by Verus on the stub only, not with row data.
The exporter judge path (`research_loop/adversary/judge_declarative.py:224`) builds its model with `SchemaModel.from_caller` and no `with_nullable(catalog)`, so a cap-narrowed BIGINT there would raise at export (loud); not exercised.
The `LEMMA_NARROW_CELLS` real-SEC measure speedup claims were not re-measured (no timing runs, by instruction).

## Required before the default is flipped

1. F1: fix the nine tests by making `tests/fixtures/declarative_proofs/*` examples width-agnostic (the agent-visible ones first), and run the full `tests/` with the flag on.
2. F2: strict `0`/`1` parse; snapshot the effective value in `_job_env_snapshot`; update `test_declarative_manual.py:200-205`; tell the operator that in-flight workspaces prepared under OFF need `LEMMA_NARROW_CELLS=0`.
3. Update the tests that pin the old default (`test_the_default_keeps_every_integer_i64`, the `delenv` in `tests/test_declarative_nulls.py:39`, `tests/test_declarative_oneshot.py`).
4. F3: decide whether the native cap is `|cell| < 2^k` or `<= 2^k`, and record it; optional but cheap.
5. Print the chosen widths next to a narrow speedup (speed-claims item 7).

**Flipping the default is not allowed now. It is allowed once items 1-3 are done (items 4-5 may follow).** Overridable with `LEMMA_NARROW_CELLS=0` as proposed.

VERDICT: ACCEPT WITH FIXES (F1 fixtures that fail to compile under narrow cells, F2 strict flag parse and snapshot of the effective value; F3 native-minimum off-by-one is low; flip NOT allowed until F1 and F2 are fixed)
