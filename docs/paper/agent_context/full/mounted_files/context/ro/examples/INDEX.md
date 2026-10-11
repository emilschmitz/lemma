# Worked examples: shape -> file -> what it proves

Every file is a `run_query` body (plus helpers) that Verus verified against a spec of the shape in the first column; your
table, column and field names differ. Find the closest row, then read THAT file (long ones: the header comment first, then the
loop you need with the Read tool's offset/limit; do not read the whole directory). `parallel_*` and `float_*` rows are techniques
to combine with a base shape. Helper files (`*.helpers.rs`) go in the helper region beside their body.

## Dictionary-coded strings (`LEMMA_STRING_ENCODING=dict`)

| shape | file | lines |
|---|---|---|
| dictionary string mode: ungrouped COUNT and SUM under a string-literal filter (one code comparison per row) | `dict_filter_count_sum.rs` | 82 |
| dictionary string mode: GROUP BY a string key as a dense array over dictionary codes, `Vec<OutRow>` with the key as a String | `dict_group_count_dense.rs` | 170 |
| dictionary string mode: GROUP BY a string key with COUNT(*) and SUM, one dense array per aggregate over the codes | `dict_group_count_sum_dense.rs` | 190 |
| dictionary string mode, PARALLEL: GROUP BY a string key, COUNT and SUM, per-worker dense arrays merged slotwise | `dict_group_count_sum_parallel.rs` | 588 |
| dictionary string mode: JOIN ON a string key (one dictionary per table): per-code count array over the small side, NUM's dictionary translated to its codes once through a `StringHashMap`, then two array reads per row | `dict_join_probe_sum.rs` | 411 |
| dictionary string mode: ungrouped MIN and COUNT under a string-literal filter | `dict_shipmode_min_count.rs` | 79 |
| dictionary string mode: a string-literal filter becomes one code comparison (literal's code looked up once) | `dict_string_filter_minmax.rs` | 88 |
| dictionary string mode: NOT EXISTS / LEFT JOIN ... IS NULL anti-join on three string keys into a two-key GROUP BY with HAVING, ORDER BY the count and LIMIT (the pre dictionaries are translated to num's codes, the pre keys packed into one `HashMapWithView<i128, bool>`; for a positive EXISTS flip the membership test) | `hard/dict_anti_join_group_topk.rs` | 1287 |
| dictionary string mode: GROUP BY two string keys with COUNT(*), COUNT(DISTINCT x) and AVG, ORDER BY the count (published-shape, long) | `hard/dict_group_two_keys_count_distinct_avg.rs` | 856 |
| dictionary string mode: join, GROUP BY two keys, SUM with HAVING against an uncorrelated scalar subquery, ORDER BY ... LIMIT (long) | `hard/dict_having_scalar_subquery.rs` | 2208 |
| dictionary string mode: a THREE-table join on string keys with a four-key GROUP BY, SUM and COUNT, ORDER BY the sum and LIMIT (chain the many side by a packed key, group map over packed codes, parallel Vecs, witness-index function for the top-k) | `hard/dict_join3_group_topk.rs` | 3223 |
| dictionary string mode: two-table join, GROUP BY an int key and a nullable string key, two COUNT(DISTINCT x) and a SUM, ORDER BY the sum DESC LIMIT 20: dynamic group table, seen sets from the host COUNT(DISTINCT) library, selection loop, host closing lemmas (long) | `hard/dict_join_group_count_distinct_topn.rs` | 1457 |
| PARALLEL hash GROUP BY with merge: integer key of a wide range (no dense array), COUNT and SUM, top-20 by the sum: 4 vstd-thread workers each fold a row range into their own hash table (telescoping per key), merged by key, selection loop and host closing lemmas (long) | `hard/dict_parallel_hash_group_topn.rs` | 1141 |
| dictionary string mode, PARALLEL: two string keys, four aggregates, ORDER BY the keys, flat slot array per worker (TPC-H Q1, long) | `hard/dict_parallel_q1.rs` | 1609 |
| dictionary string mode, PARALLEL: two-table join, two conditional counts per ship mode, block-skip scan (TPC-H Q12, long) | `hard/dict_parallel_q12.rs` | 1844 |
| dictionary string mode, PARALLEL STAR JOIN (SSB Q4.1, LEMMA_JOIN_CHAIN=1): fact table over 8 workers, four unique-key dimension arrays shared through `Arc`, per-worker flat slot arrays merged slotwise, sorted output (2.7x; long) | `hard/dict_parallel_star_join_group_sum_sorted.rs` | 1134 |
| dictionary string mode, PARALLEL STAR JOIN (SSB Q3.1, LEMMA_JOIN_CHAIN=1): TWO dictionary group keys (pair code) and a year with a WHERE-bounded code, ORDER BY the year then the SUM descending by insertion into a sorted Vec of slots (2.4x; long) | `hard/dict_parallel_star_join_two_keys_revenue_order.rs` | 988 |
| dictionary string mode, PARALLEL STAR JOIN (SSB Q4.2, LEMMA_JOIN_CHAIN=1): five tables, TWO string group keys from two dimensions plus a year, ORDER BY all three (strings by seq_le): sorted pair codes, emit by year then sorted code (2.25x; long) | `hard/dict_parallel_star_join_two_keys_string_order.rs` | 1273 |
| dictionary string mode: projection over a TWO-table join with a per-key MAX (correlated subquery or derived table), ORDER BY value DESC then two string keys, LIMIT k: per-(adsh, tag) max in a `HashMapWithView` keyed by a packed code pair, num's dictionary translated to sub's codes once, sub rows chained per code, sorted top-k `Vec` with exec string comparison (verified against the real SEC catalog spec, not run on the 39M-row table; the per-pair max map grows with the distinct pairs; no table over a product of dictionary sizes) | `hard/dict_projection_join_correlated_max_topk.rs` | 1576 |
| dictionary string mode, STAR JOIN (SSB Q4.1): a fact table scanned once, four unique-key dimension tables reached through arrays indexed by key, GROUP BY an int and a dictionary string, SUM of an expression, ORDER BY both keys; uses the host lemma `lemma_<fold>_row` (LEMMA_JOIN_CHAIN) | `hard/dict_star_join_group_sum_sorted.rs` | 792 |

## Parallel scans (the spec's `run_query` takes `<table>_arc`)

| shape | file | lines |
|---|---|---|
| PARALLEL, dictionary strings: filter, COUNT and MAX with a branch-free 32-row block flag that skips blocks | `parallel_dict_filter_count_max_blockskip.rs` | 512 |
| PARALLEL, dictionary strings: the same scan over `slice_subrange` blocks | `parallel_dict_filter_count_max_slices.rs` | 503 |
| PARALLEL, dictionary strings: a nullable column with a string filter, COUNT and MIN | `parallel_dict_nullable_count_min.rs` | 428 |
| PARALLEL: ungrouped COUNT(*) under a filter (additive partials) | `parallel_ungrouped_count.rs` | 293 |
| PARALLEL: ungrouped MAX (workers return (value, any) pairs) | `parallel_ungrouped_max.rs` | 323 |
| PARALLEL: ungrouped MIN (workers return (value, any) pairs) | `parallel_ungrouped_min.rs` | 323 |
| PARALLEL: ungrouped SUM of a product with a date filter | `parallel_ungrouped_product_sum.rs` | 327 |
| PARALLEL: the product sum with the hot loop over `slice_subrange` blocks (no bounds checks) | `parallel_ungrouped_product_sum_slices.rs` | 436 |
| PARALLEL: ungrouped SUM, worker threads over row ranges of a shared `Arc`, partials telescoping | `parallel_ungrouped_sum.rs` | 308 |

## Floats (DOUBLE columns and results)

| shape | file | lines |
|---|---|---|
| ungrouped AVG of a DECIMAL column | `float_avg_decimal.rs` | 71 |
| ungrouped AVG of a DOUBLE column | `float_avg_float.rs` | 97 |
| tuple-of-strings GROUP BY, COUNT, COUNT DISTINCT and AVG (long) | `float_avg_group_count_distinct.rs` | 586 |
| ungrouped AVG of an integer column (DOUBLE result) | `float_avg_int.rs` | 75 |
| COUNT under a DOUBLE comparison | `float_filter_count.rs` | 35 |
| GROUP BY, AVG over a DECIMAL column | `float_group_avg_decimal.rs` | 195 |
| GROUP BY, AVG(double), HAVING on the average | `float_group_avg_having.rs` | 238 |
| GROUP BY, SUM(double), HAVING on the sum | `float_group_sum_having.rs` | 214 |
| GROUP BY, SUM(double), ORDER BY the sum, LIMIT | `float_group_sum_order_limit.rs` | 448 |
| MIN and MAX of a DOUBLE column | `float_min_max.rs` | 67 |
| ORDER BY a DOUBLE column, LIMIT (selection by repeated minimum) | `float_order_limit.rs` | 346 |
| ungrouped SUM of a product of DOUBLE columns | `float_product_sum.rs` | 92 |
| ungrouped SUM of a DOUBLE column | `float_sum.rs` | 67 |

## TPC-H shapes (plain strings)

| shape | file | lines |
|---|---|---|
| TPC-H Q14: a two-table join, ratio of two exact DECIMAL sums (one under a LIKE prefix), divided in DOUBLE | `tpch_q14_promo_ratio.rs` | 296 |
| TPC-H Q19: a two-table join, ungrouped SUM under three OR-ed conjunctions (equalities, IN lists, ranges) | `tpch_q19_disjunction.rs` | 173 |
| TPC-H Q3: THREE-table join, GROUP BY three keys, SUM of a decimal product, ORDER BY ... LIMIT 10 (plain strings) | `tpch_q3_join_group_topk.rs` | 739 |
| plain strings: ungrouped MIN and COUNT under a string-literal filter (the literal built once as a `String`) | `tpch_shipmode_min_count_plain.rs` | 46 |

## Projections (no GROUP BY: one result row per input row)

| shape | file | lines |
|---|---|---|
| projection over a TWO-table join with a correlated scalar MAX subquery (or a join to a per-key MAX), ORDER BY ... LIMIT k: "next same-key row" chains and a sorted top-k `Vec` (plain string mode; dictionary mode has its own example `hard/dict_projection_join_correlated_max_topk.rs`; it proves but is slow: a proof template, not a speed template) | `hard/projection_join_correlated_max_topk.rs` | 756 |
| projection with a correlated scalar subquery `a = (SELECT MAX(a) ... WHERE same key)` | `projection_correlated_max.rs` | 87 |
| `SELECT DISTINCT cols ... WHERE ...` | `projection_distinct.rs` | 77 |
| two tables joined, plain projection `SELECT t.a, u.w ... JOIN ...` | `projection_join.rs` | 76 |
| projection whose key column is nullable (an `(is_valid, value)` cell: test the validity bit first); its helper file is `projection_null_cell.helpers.rs` | `projection_null_cell.rs` | 49 |
| projection with `ORDER BY ... LIMIT k` (multiplicity and the omitted-row clause) | `projection_top_k.rs` | 91 |
| one table, `SELECT cols WHERE ...` (no GROUP BY), result `Vec<OutRow>` | `projection_where.rs` | 47 |

## Joins

| shape | file | lines |
|---|---|---|
| two tables joined on a key, GROUP BY, SUM, result `Vec<OutRow>` | `join_group_sum.rs` | 325 |
| two tables joined on a string key, ungrouped MIN/MAX with a string-literal filter (`StringHashMap` probe) | `join_min_stringhashmap_probe.rs` | 123 |
| a table joined with itself on an inequality, ungrouped COUNT(*) (nested loops; its bounds are written for a row cap of 4: redo the arithmetic for your cap) | `self_join_count.rs` | 47 |

## Aggregates (grouped and ungrouped, plain strings)

| shape | file | lines |
|---|---|---|
| one table, ungrouped `COUNT(CASE WHEN ... THEN 1 END)` | `count_case_global.rs` | 24 |
| one table, filtered GROUP BY, COUNT(*), result `Vec<OutRow>` | `group_count_where.rs` | 196 |
| one table, filtered GROUP BY, SUM, result `Vec<OutRow>` | `group_sum_where.rs` | 203 |
| one table, ungrouped `COUNT(DISTINCT col)`: a `HashSetWithView` seen-set swept from the end | `hard/count_distinct.rs` | 50 |
| one table, GROUP BY two string columns, several decimal SUMs and COUNT(*), ORDER BY the keys (TPC-H Q1 shape) | `hard/group_decimal_sums_string_keys_sorted.rs` | 1134 |
| one table, integer-key GROUP BY COUNT(*) into a `HashMapWithView<i64, u64>` (hash map, not a dense array) | `hard/map_count.rs` | 63 |
| one table, tuple-of-strings GROUP BY, COUNT(*) and COUNT(DISTINCT), ORDER BY the count (sorted `Vec::insert`) | `hard/string_tuple_count_distinct_sorted.rs` | 550 |
| one table, GROUP BY TWO integer keys, COUNT(*), result `Vec<OutRow>` (distinct-key pass, then a count pass with a witness per group) | `hard/two_key.rs` | 200 |
| one table, filtered ungrouped SUM whose running-total bound `(n - i) * m` needs `by (nonlinear_arith)` | `hard/usum_nonlinear.rs` | 50 |
| one table, integer group key, COUNT(*), result `HashMapWithView<int, u64>` | `int_group_count.rs` | 63 |
| one table, string group key, COUNT(*), result `StringHashMap<u64>` | `string_group_count.rs` | 58 |
| one table, filtered ungrouped SUM of a product of two decimal columns, with a helper lemma | `ungrouped_decimal_product_sum.rs` | 65 |
| one table, filtered ungrouped MIN and MAX of an integer column, with a string-literal comparison in the filter | `ungrouped_minmax_string_filter.rs` | 54 |
| one table, filtered ungrouped SUM, result `Vec<OutRow>` of one row | `ungrouped_sum_where.rs` | 35 |
