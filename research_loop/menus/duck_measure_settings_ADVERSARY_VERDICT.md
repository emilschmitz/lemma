# Adversary verdict: DuckDB measure settings (a376529) and tie handling in expect.json (bfcc745)

Verdict: PASS WITH FINDINGS

The main goal holds. The one host measure connection (`write_query_measure`, which every container prepare reaches through `declarative_spec/drive._maybe_large_table`) is capped at 3GB, 8 threads, with a temp directory. Reference timing and export share that one connection. All 26 tests in test_duck_measure_settings, test_rows_match_limit_ties and test_declarative_manual pass. I ran only synthetic tmp DBs (6M rows, DuckDB 1.5.4). The real SEC DB, Verus and containers were not touched.

## Findings

### F1 (MEDIUM): the tie-group query bypasses the cap, so the cap does not protect it
`_tie_group_rows` runs the query without LIMIT, filtered to the last kept row's ORDER BY keys, and calls `fetchall()`. It then builds `_canon` Python lists, and `tie_rows` is written into expect.json.

DuckDB's memory_limit does not govern Python objects. A query like `... ORDER BY low_cardinality_col LIMIT 1000` over `pre` (9.6M rows) or `num` (39M rows) has a tie group of millions of rows. That means millions of Python tuples, then lists, then a multi-GB JSON that every `run_runquery` re-parses.

Repro: synthetic 6M-row table, `SELECT g,a,s FROM t ORDER BY g LIMIT 10`, `_tie_group_rows(...)`. It returned 2,000,000 rows and Python maxrss went 558MB to 1078MB for 3 columns. Scale that to 9.6M rows by 5 columns of strings.

Suggested fix: cap the tie group size and fail loudly (no fallback, per AGENTS.md), or stream or aggregate it.

Related: `_tie_group_rows` also re-runs the full LIMIT query with `fetchall()[-1]`. That is bounded by LIMIT, so it is fine.

### F2 (MEDIUM, pre-existing but now on the path HEAD~1 advertises): a map result crashes the in-session check
expect.json always contains `"kinds": null` for a map result. `pipeline._apply_speed_bar` tests `"kinds" in speed_bar`, which is true, and then calls `list(speed_bar["kinds"])`.

Repro: `SELECT k, COUNT(*) AS c FROM t GROUP BY k`, then `write_query_measure`, then `_apply_speed_bar({"status":"SUCCESS",...}, json.loads(expect.json))`. Result: `TypeError: 'NoneType' object is not iterable`.

`drive.py` builds its own bar and omits `kinds` for map results, so the official path is fine. But `verus_bridge` reads expect.json via `load_speed_bar`, so the in-session MCP path hits the TypeError. `tests/test_declarative_manual.py` uses map queries but only checks `load_speed_bar`, never `_apply_speed_bar`.

HEAD~1 also writes `order_cols`, `limited` and `tie_rows=None` for map results, which is harmless but pointless.

Suggested fix: write `kinds` only when it is not None, or test `speed_bar.get("kinds") is not None`.

### F3 (MEDIUM): other DuckDB connections reachable from the same flows are still uncapped
- `research_loop/decl_columns.py:51` (`LEMMA_DECL_ROWS` path in `_maybe_large_table`) opens an in-memory `duckdb.connect()` with no pragmas. It builds an n-row table, then `fetchall()`s all n values into Python and then into an array. Zero protection at large n. It is also timed under default threads and memory, so it is not "identical settings".
- `research_loop/scripts/declarative_oneshot.py:149,194` opens an uncapped connection on the real DB and `fetchnumpy()`s whole tables (`pin_encode`, 3 times). `--mem-reference` copies tables into an uncapped `:memory:` DB. Its `PRAGMA threads` is copied, but there is no memory limit.
- `declarative_round.tpch_schema_and_catalog` (line 114) is a read-only connection that only runs DESCRIBE and COUNT(*). It is harmless, but it is uncapped.
- `db_extension/dataset_config.connect_measured_duckdb` is used by the table_unique_keys, column caps and row-count helpers. Those run full-column aggregates (`GROUP BY ... HAVING count>1`, `max(abs(col))`) on the SEC DB with default 80% RAM. The reachable caller is `research_loop/sec_table_assumptions.py`, the legacy measured-catalog path. The declarative path uses `assumption_package(...)` instead. Also uncapped: `assumption_packages/profile.py:264`, `check.py:242`, `decl_duck_timing`, `decl_fuzz`, `sec_feasibility_timed`, `gendb_published_one_run` and `run_optimizer`.

The container prepare path itself (`write_query_measure`) is clean. A single `open_measure_connection` helper has not been rolled out to these callers.

### F4 (LOW-MEDIUM): the cap is per connection, not collective, and does not cover the exporter's Python side
- Each prepare gets its own 3GB. N concurrent prepares means N x 3GB plus numpy batches (1M rows x columns, plus string lists in `_pack_strings`) plus the dictionary `fetchall` of distinct strings (up to millions of Python strs for a big column). The lemma.slice 9G cap is the only real collective bound.
- No code ties the 3GB to the cgroup, so the two numbers can drift apart.
- An OOM at the cap raises `duckdb.Error`, which `write_query_measure` converts to `ValueError`. That fails loudly, as intended. I did not exercise it on a join that truly exceeds 3GB.

### F5 (LOW, methodology): the cap changes the "hot" reference
With 3GB against a 1.7GB database plus working memory, buffer-pool pages will be evicted during joins and aggregates. Before, ~80% RAM kept the whole DB cached.

- New `duck_us` and `duck1_us` are not comparable with bars recorded before a376529. Nothing marks old versus new beyond the `duck_settings` key.
- The reference may pay I/O or decompression that the pre-cap runs did not. That biases speedups upward.
- I could not measure this without the real DB. Worth one A/B on a join query (3GB versus unlimited) before quoting speedups.

### F6 (LOW): `SET threads=1` is safe but the "identical settings" claim is only partly true
The `SET threads=1` happens last, after `_tie_group_rows`, and the connection is closed right after. No later query runs single-threaded; verified that the pragma persists only on that connection. `duck_threads` is read before it. Both runs share memory_limit and temp_directory, so the claim holds for the reference.

- `threads` is an explicit 8, not the machine's core count. The box has 8 cores, so it is the same here. On a bigger box the reference is throttled.
- A 1-thread run shares the same 3GB, so that comparison is coherent.

### F7 (LOW): temp_directory behavior
- DuckDB creates only the leaf directory and does not create parents: with a nonexistent `dest`, any spill failed with `IOException: Failed to create directory`. `write_query_measure` calls `dest.mkdir(parents=True)` before `open_measure_connection`, so production is OK. A standalone `open_measure_connection(db, dest)` call with a missing `dest` is a trap, and the first test hides it because it never spills.
- Spilling works with `read_only=True`: a 300MB cap with a 6M-string GROUP BY and a 6M self-join both succeeded, and the spill directory was removed afterwards.
- `max_temp_directory_size` is left at its default (90% of free disk), so a spill is bounded only by disk, not RAM. `decl_data/duck_tmp` sits in the workspace, which may be mounted for the agent. `sandbox_hide` covers expect.json but I did not check duck_tmp.

### F8 (LOW, tests): brittle or weak assertions
- `startswith(("2.7","3.0","2.8"))` on `current_setting('memory_limit')` depends on DuckDB's formatting. It was `2.7 GiB` on 1.5.4 and could change by version or locale. The preceding `"GiB" in ... or "GB" in ...` line is redundant (it is ORed, effectively always true).
- Nothing asserts that `temp_directory` was applied. Only the `memory_limit` and `threads` settings are checked.
- Nothing asserts that the exporter path (`_encode_columns`) uses the same connection (it does, structurally).
- `memory_limit_effective` is only checked for truthiness.
- No test covers a spill or OOM, the mkdir ordering (F7), or a map result's `_apply_speed_bar` (F2).

### F9 (INFO)
- An invalid `LEMMA_DUCK_THREADS` raises an uncaught `ValueError`, which fails fast. The env values are interpolated into PRAGMA SQL unescaped, which is fine for operator-controlled input.
- `LEMMA_DUCK_*` is not in `_JOB_ENV_KEYS`. That is fine, since measuring happens only at prepare and the values are recorded in expect.json.
- Stale expect.json: unlinked at the start of `write_query_measure`, and written last, so a failed re-prepare leaves none. OK.
- HEAD~1 (the tie fields in expect.json) works for OutRow results. The bar built by `drive.py` and the one `load_speed_bar` reads now agree on `order_cols`, `limited` and `tie_rows`. A map result is the exception (F2).

## Summary
The change meets its stated goal for the container host measure connection. Fix F1 (the unbounded Python tie-group materialization, the real hole in "never exceed the cap") and F2 (a crash in the in-session check for map results) before relying on this at scale. F3 is a hardening backlog: move the remaining ad hoc connections onto `open_measure_connection`.

## Author response
- F1: fixed. `_tie_group_rows` counts the tie group first and returns None (strict row check) above `MAX_TIE_ROWS` = 200000 (test with a lowered cap).
- F2: fixed. `_apply_speed_bar` tests `speed_bar.get("kinds") is not None` (a map result has `"kinds": null`); test added.
- F3: not applied. The container/manual prepare path is `write_query_measure` (clean, per the reviewer); the listed uncapped connections are the synthetic LEMMA_DECL_ROWS path, one-shot/fuzz/feasibility scripts and the legacy measured-catalog path, none used by container_batch runs. Left, documented.
- F4: accepted (one prepare at a time under the heavy slot). F5: to be checked on the real DB on the first real run; old and new duck_us are not comparable, the run rows record duck_settings. F6: accepted (8 threads = this machine). F7: fixed (dest created before the PRAGMA, asserted). F8: assertions simplified, temp_directory asserted.
