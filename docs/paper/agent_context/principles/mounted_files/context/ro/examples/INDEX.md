# Worked examples: seven small techniques

These are NOT examples of your query. Each file is a `run_query` body (plus helpers) that Verus verified against a tiny spec on an unrelated
event-log schema (`events`, `items`, `users`); it teaches ONE technique. Your tables, columns, caps and SQL differ: read the files whose technique
your spec needs, then combine and adapt them (rename, redo the arithmetic for YOUR caps, change the filter). The header comment of each file says what to take.
A query usually needs several of them at once; each file's header says what to take.

| technique | file | lines |
|---|---|---|
| filtered scan, COUNT and SUM over an integer and a DECIMAL (scaled integer) column; suffix-fold invariants, `i128` accumulators bounded by the cell caps, SUM of no rows is NULL | `scan_filter_sum_count.rs` | 50 |
| GROUP BY a dictionary-coded string key: one dense slot per code, every slot equals the host fold for its key, emit the nonzero slots with a ghost index | `group_by_dict_key.rs` | 190 |
| equi-join on a UNIQUE key as a lookup: index the dimension table once (`key + offset -> row + 1`), scan the fact table and probe it; the host's per-row chain lemma replaces counting matches (LEMMA_JOIN_CHAIN=1) | `join_unique_lookup.rs` | 146 |
| fact table plus TWO unique-key dimensions, GROUP BY a dimension's dictionary string; two probe indexes, dense slots over the group codes, the host's grouped-result closing lemmas (LEMMA_JOIN_CHAIN=1) | `star_join_group_by.rs` | 309 |
| ORDER BY ... LIMIT: a sorted streaming top-N (insert before the first smaller row, pop the overflow), with the spec's tie rule for omitted rows that tie the last kept one | `top_n_with_ties.rs` | 153 |
| PARALLEL scan with vstd threads: split the rows across 8 workers over a shared `Arc`, per-worker partial folds that telescope, merge in order (LEMMA_PARALLEL_VSTD=1) | `parallel_scan_sum.rs` | 308 |
| NULL-skipping aggregates over a nullable column (validity vector): COUNT(*) vs COUNT(col), SUM over no valid cell is NULL | `null_skipping_aggregate.rs` | 57 |
