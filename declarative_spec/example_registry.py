"""Which verified fixture bodies are mounted for the agent, what shape each proves, and which are deliberately not mounted.

Data only (the routing logic is in `prompt.py`). Every `*.rs` under `tests/fixtures/declarative_proofs/` must appear here,
in the recipe table of `prompt.py`, or in `UNMOUNTED`: `tests/test_declarative_routing.py` fails otherwise.
"""

from __future__ import annotations

# Registered fixtures that are not the recipe's own example: more shapes for the index, each a body Verus verified against
# a spec of that shape. A `dict_` basename is mounted in dictionary mode only.
MORE_EXAMPLES: tuple[tuple[str, str], ...] = (
    (
        "projection_null_cell.rs",
        "projection whose key column is nullable (an `(is_valid, value)` cell: test the validity bit first); its helper file is `projection_null_cell.helpers.rs`",
    ),
    ("count_case_global.rs", "one table, ungrouped `COUNT(CASE WHEN ... THEN 1 END)`"),
    (
        "self_join_count.rs",
        "a table joined with itself on an inequality, ungrouped COUNT(*) (nested loops; its bounds are written for a row cap of 4: redo the arithmetic for your cap)",
    ),
    (
        "hard/count_distinct.rs",
        "one table, ungrouped `COUNT(DISTINCT col)`: a `HashSetWithView` seen-set swept from the end",
    ),
    (
        "hard/map_count.rs",
        "one table, integer-key GROUP BY COUNT(*) into a `HashMapWithView<i64, u64>` (hash map, not a dense array)",
    ),
    (
        "hard/two_key.rs",
        "one table, GROUP BY TWO integer keys, COUNT(*), result `Vec<OutRow>` (distinct-key pass, then a count pass with a witness per group)",
    ),
    (
        "hard/usum_nonlinear.rs",
        "one table, filtered ungrouped SUM whose running-total bound `(n - i) * m` needs `by (nonlinear_arith)`",
    ),
    (
        "tpch_q14_promo_ratio.rs",
        "TPC-H Q14: a two-table join, ratio of two exact DECIMAL sums (one under a LIKE prefix), divided in DOUBLE",
    ),
    (
        "tpch_q19_disjunction.rs",
        "TPC-H Q19: a two-table join, ungrouped SUM under three OR-ed conjunctions (equalities, IN lists, ranges)",
    ),
    (
        "tpch_q3_join_group_topk.rs",
        "TPC-H Q3: THREE-table join, GROUP BY three keys, SUM of a decimal product, ORDER BY ... LIMIT 10 (plain strings)",
    ),
    (
        "tpch_shipmode_min_count_plain.rs",
        "plain strings: ungrouped MIN and COUNT under a string-literal filter (the literal built once as a `String`)",
    ),
    (
        "dict_filter_count_sum.rs",
        "dictionary string mode: ungrouped COUNT and SUM under a string-literal filter (one code comparison per row)",
    ),
    (
        "dict_group_count_sum_dense.rs",
        "dictionary string mode: GROUP BY a string key with COUNT(*) and SUM, one dense array per aggregate over the codes",
    ),
    (
        "dict_shipmode_min_count.rs",
        "dictionary string mode: ungrouped MIN and COUNT under a string-literal filter",
    ),
    (
        "dict_group_count_sum_parallel.rs",
        "dictionary string mode, PARALLEL: GROUP BY a string key, COUNT and SUM, per-worker dense arrays merged slotwise",
    ),
    (
        "hard/dict_group_two_keys_count_distinct_avg.rs",
        "dictionary string mode: GROUP BY two string keys with COUNT(*), COUNT(DISTINCT x) and AVG, ORDER BY the count (published-shape, long)",
    ),
    (
        "hard/dict_parallel_hash_group_topn.rs",
        "PARALLEL hash GROUP BY with merge: integer key of a wide range (no dense array), COUNT and SUM, top-20 by the sum: 4 vstd-thread workers each fold a row range into their own hash table (telescoping per key), merged by key, selection loop and host closing lemmas (long)",
    ),
    (
        "hard/dict_join_group_count_distinct_topn.rs",
        "dictionary string mode: two-table join, GROUP BY an int key and a nullable string key, two COUNT(DISTINCT x) and a SUM, ORDER BY the sum DESC LIMIT 20: dynamic group table, seen sets from the host COUNT(DISTINCT) library, selection loop, host closing lemmas (long)",
    ),
    (
        "hard/dict_having_scalar_subquery.rs",
        "dictionary string mode: join, GROUP BY two keys, SUM with HAVING against an uncorrelated scalar subquery, ORDER BY ... LIMIT (long)",
    ),
    (
        "hard/dict_parallel_q1.rs",
        "dictionary string mode, PARALLEL: two string keys, four aggregates, ORDER BY the keys, flat slot array per worker (TPC-H Q1, long)",
    ),
    (
        "hard/dict_parallel_q12.rs",
        "dictionary string mode, PARALLEL: two-table join, two conditional counts per ship mode, block-skip scan (TPC-H Q12, long)",
    ),
    (
        "parallel_ungrouped_sum.rs",
        "PARALLEL: ungrouped SUM, worker threads over row ranges of a shared `Arc`, partials telescoping",
    ),
    (
        "parallel_ungrouped_product_sum.rs",
        "PARALLEL: ungrouped SUM of a product with a date filter",
    ),
    (
        "parallel_ungrouped_product_sum_slices.rs",
        "PARALLEL: the product sum with the hot loop over `slice_subrange` blocks (no bounds checks)",
    ),
    (
        "parallel_ungrouped_min.rs",
        "PARALLEL: ungrouped MIN (workers return (value, any) pairs)",
    ),
    (
        "parallel_ungrouped_max.rs",
        "PARALLEL: ungrouped MAX (workers return (value, any) pairs)",
    ),
    (
        "parallel_ungrouped_count.rs",
        "PARALLEL: ungrouped COUNT(*) under a filter (additive partials)",
    ),
    (
        "parallel_dict_nullable_count_min.rs",
        "PARALLEL, dictionary strings: a nullable column with a string filter, COUNT and MIN",
    ),
    (
        "parallel_dict_filter_count_max_blockskip.rs",
        "PARALLEL, dictionary strings: filter, COUNT and MAX with a branch-free 32-row block flag that skips blocks",
    ),
    (
        "parallel_dict_filter_count_max_slices.rs",
        "PARALLEL, dictionary strings: the same scan over `slice_subrange` blocks",
    ),
)

# Fixtures that are deliberately NOT mounted (path relative to the fixtures directory -> why). A fixture file that is
# neither registered nor listed here fails the registry test, so a new proof cannot silently go unmounted.
UNMOUNTED: dict[str, str] = {
    "u64_group_count_t_k.rs": "the u64-key map count over the test spec's fixed names `t`/`k`; `hard/map_count.rs` is the same shape and is mounted",
    "u64_group_count_slots_t_k.rs": "the dense-counter recipe under the test spec's fixed names; its text is the block inlined as the dense_map recipe",
}


INDEX_GROUPS: tuple[tuple[str, str], ...] = (
    (
        r"(^|/)dict_",
        "Dictionary-coded strings (`LEMMA_STRING_ENCODING=dict`)",
    ),
    (r"parallel_", "Parallel scans (the spec's `run_query` takes `<table>_arc`)"),
    (r"float_", "Floats (DOUBLE columns and results)"),
    (r"tpch_", "TPC-H shapes (plain strings)"),
    (r"projection_", "Projections (no GROUP BY: one result row per input row)"),
    (r"join|self_join", "Joins"),
    (r".", "Aggregates (grouped and ungrouped, plain strings)"),
)
