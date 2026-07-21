# Holdout evaluation proposals

Novel holdout sets **outside** SSB-15 / TPC-H Q1/Q3/Q6 fixtures. Score:
`ratio = lemma_us / duckdb_1t_us` (lower is better). DuckDB is oracle/timing reference only —
never research-loop execution fallback.

---

## 1. TPC-H SF1 shifted-literal variants (Q9 / Q12 / Q14 / Q18 shapes)

**Goal:** Same join/agg structure as classic TPC-H but literals moved (date windows, `LIKE`
patterns, `MKTSEGMENT` filters) so memorized fixture bodies fail.

**Why holdout:** Not in `verified_runqueries.py` or `tpch_runqueries.py` as proved fixtures.

**Primitives stressed:** `build_hashset_u32` + `probe_sum_u64`, zone-map pruning on
`lineitem`/`orders` dates, optional `par_filter_sum_u64`.

**Scoring:** SF1 `.tbl` under `data/tpch-sf1/`; compare median `QUERY_LATENCY_US` vs
`duckdb -c "PRAGMA threads=1; …"` on identical SQL.

---

## 2. Synthetic Zipfian skew join + group-by

**Goal:** Two-table equijoin with Zipf(α≈1.2) keys and heavy-hitter groups — stresses hash
table capacity hints and small-card vs HashMap choice.

**Why holdout:** Generated via `scripts/gen_zipf_join_tbl.py` (tiny 50k + medium 500k rows);
not checked into benchmark fixtures.

**Primitives stressed:** `build_hashset_u32(capacity_hint=…)`,
`SmallCardBuckets<N>` when post-join NDV ≤ 64, zone maps on build key.

**Scoring:** Same SQL at 50k / 500k; report ratio + verify correctness vs DuckDB hash join.

---

## 3. SEC-EDGAR-like string-heavy filter (GenDB bench analogue)

**Goal:** Wide string columns (`form_type`, `cik`), selective `LIKE`/equality filters, scalar
`COUNT`/`SUM` — mimics EDGAR workloads without shipping full data.

**Why holdout:** Schema stub + generator script only; no SSB/TPC-H table names.

**Primitives stressed:** `decode_dict_str` (`duckdb_like`), `table_aggregate_stats` NDV for
dict cardinality, ILIKE TRUSTED bridges.

**Scoring:** Stub `.tbl` (100k rows); ratio vs DuckDB 1T; optional proof on tiny 1k slice.

---

## 4. Cross-scale template (50k / 500k / SF1)

**Goal:** One parameterized SQL template (e.g. date-range group-by SUM) at three scales —
tests whether agent choices generalize.

**Why holdout:** Scale is not a separate fixture; same MethodSpec shape, different `limit` /
row count in context only.

**Primitives stressed:** Zone-map segment size vs `hardware_profile` cache hints; parallel
externs when `LEMMA_ENABLE_PARALLEL=1`.

**Scoring:** Plot ratio vs scale; correctness checksum vs DuckDB at each scale.

---

## 5. Multi-template MethodSpec shape (parameter bindings)

**Goal:** Fixed SQL template with bound parameters `(lo_date, hi_date, region_id)` drawn from
a small grid; agent must not hardcode one binding.

**Why holdout:** Bindings rotated at eval time; not single literal set in any checked-in
`run_query` body.

**Primitives stressed:** Agent reads `context.json` stats (min/max, zone maps) — not row IDs;
`may_satisfy_range_u32` for segment pruning.

**Scoring:** Mean ratio over binding grid; max regression vs DuckDB flagged if ratio > 2× on
any binding.
