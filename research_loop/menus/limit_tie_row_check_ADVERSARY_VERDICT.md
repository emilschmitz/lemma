# Adversary verdict: LIMIT-tie row check (commit fe2d751)

**Verdict: PASS WITH FINDINGS.** The repro class (key columns equal, tied last group differs) is fixed and `pytest tests/test_rows_match_limit_ties.py tests/test_speed_bench_queries.py` is 9 passed. One real mapping bug (F1, false accept) should be fixed before relying on it; F2 is an honest but under-documented weakening worth closing with a membership check.

## Findings

**F1 (medium, false accept): `order_info` mis-resolves ORDER BY names when an alias shadows a column.**
It matches the ORDER BY text against the *underlying expressions* of the select list before aliases. DuckDB resolves a bare ORDER BY name to the output alias first.
- `SELECT a AS b, b AS a FROM t ORDER BY a LIMIT 3` -> `order_cols [0]`; DuckDB sorts by output column 1.
- `SELECT x AS c, c AS x FROM t ORDER BY c LIMIT 3` -> `[1]`; DuckDB sorts by output column 0.
Repro (`rows_match_error(..., [0], True)`): expect `[[1,10],[2,10],[3,20]]`, got `[[1,10],[2,10],[3,77]]` -> returns None (accepted). The real sort key (col 1, 20 vs 77) disagrees but the wrong column is compared, and the differing row is a "last group" of one. Fix: resolve alias names first; or return None (strict) when a bare ORDER BY name is both an alias and a differently-positioned underlying column.

**F2 (medium, by design but weak): the last key group is not checked at all, not even for membership.**
- `ORDER BY k LIMIT 1` (or any result that is a single key group): only the key value is compared; every other column is free. Repro: expect `[[1,1],[2,1]]`, got `[[5,1],[6,1]]`, order col 1 -> accepted. Also `str` row with equal key but a wrong `x` at LIMIT 1 accepted.
- Non-key columns of last-group rows (e.g. a wrong SUM next to a tied COUNT key) are accepted, and the check cannot tell a genuine tie from a unique last row (expect holds only n rows). So a loader/pin/exec-side bug confined to the last group, or to a LIMIT 1 query, is now invisible to the row check. The docstring says the proof covers it, but the row check exists precisely to catch host (steps 2/4/6/7) bugs the proof does not cover (the r24 empty-vector episode was exactly that class).
- Recommendation: require a membership check. Run the reference query once more in DuckDB with LIMIT removed (or `WHERE key = lastkey`), and require each last-group got row to be in that multiset (without replacement), with count == tie slots. This is cheap relative to the run and keeps no new trust. If not done, say explicitly in the docstring and drive.py comment that LIMIT-tie results are only key-checked for the last group.

**F3 (low, false reject remaining): OFFSET.** `LIMIT n OFFSET m` yields `limited=True`, full length, but the *first* group may be cut at its start too, and the head multiset compare of that group false-rejects (and the helper ignores `offset`). Stays strict-fail, so safe, but an incomplete fix. Not run end to end; follows from the code.

**F4 (low): unsorted/ignored cases correctly strict.** UNION (`order_cols None`), derived-table outers with `*` (None), expression keys (None), no ORDER BY (not limited), LIMIT expression like `3+0` (parses to 3, fine) were all handled safely. DISTINCT, WITH, duplicated ORDER BY items (`[1,1]`), DESC/NULLS LAST: key comparison is direction-agnostic, positions are compared so direction cannot cause an accept of a wrong order. NULL keys compare equal (checked: accepted correctly, no crash). Float keys use tolerance; group boundaries use the same non-transitive tolerance (harmless: tolerant equal keys are equal).

**F5 (low): accept path also runs when nothing was cut** (result exactly LIMIT rows because the table has exactly that many rows): the last group is then unverified for no reason. Same fix as F2 removes it.

## Tests (c)
- `test_the_cut_is_only_assumed_when_the_result_is_full` is a source grep (`'info.get("limit") == len(prepared["rows"])' in src`). It is brittle and vacuous as behavior: it passes if the string sits in a comment, and `drive.py` is not executed. The "full" rule should be a small function (`limited_and_full(sql, rows)`) tested directly.
- No test for alias-shadowing, LIMIT 1, single-group result, OFFSET, UNION, NULL keys, or DESC. The F1 and F2 cases above should each be a test.
- The other tests are meaningful (wrong head row, wrong key, missing flag all refuse).

## (d) Honest weakening?
Partly. It is honestly stated in the `_equal_up_to_the_cut_tie_group` docstring, but the commit message and drive.py comment present it as "accept any valid tied choice", which overstates it: the code accepts any rows with the right key values in the last group, valid or not. A membership check against DuckDB is feasible and should be required (F2).

## Author response
- F1 (alias shadowing): fixed, an output alias is resolved before an underlying select expression (`test_an_output_alias_wins_over_an_underlying_column_of_the_same_name`).
- F2 (last group unchecked): fixed by the membership check the reviewer recommended: at prepare time DuckDB computes every row of the query WITHOUT its LIMIT whose ORDER BY keys equal the last kept row's (`decl_query_measure._tie_group_rows`, stored as `tie_rows` in expect.json and the bar); the last group's rows must each be a distinct member (tolerant equality). No tie rows (not computed) means the strict check. Tests: members used once, a non-member, a single-group result, no tie rows, and the DuckDB query itself on an in-memory table.
- Source-grep test replaced by `cut_applies` tested directly. F3 (OFFSET): stays strict, accepted.
