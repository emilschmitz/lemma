# EXISTS / NOT EXISTS over an ungrouped aggregate subquery: adversary verdict (manual adversary, Sonnet subagent)

Attacked: commit `7ace4e0` (`emit_surface._exists_fns` / `_ungrouped_aggregate`). Ground truth: python `duckdb` in memory
(part has 3 rows; li in three states: empty, rows none matching `qty > 100`, rows one matching). Spec read from
`declarative_spec.emit.emit_declarative_spec`. No Verus, no model runs, no benchmarks.
Evidence: `tests/test_exists_ungrouped_adversary.py` (held properties, 49 pass) plus ~95 ad-hoc probes (listed below).

## Overall verdict: HOLES FOUND (none unsound in the semantics; one is a broken test deliverable)

The semantic change is correct on every probe: for every accepted ungrouped aggregate subquery the spec's `exists_N` is only
the outer range check (TRUE for each outer row), `NOT EXISTS` negates it, and DuckDB agrees in all three li states, including
empty li. No wrong spec was accepted for valid SQL, and no needed refusal was lost. The one actionable hole is HOLE 1: the
two "verified reference bodies" of the commit cannot run.

## Holes

| # | Severity | Finding |
|---|---|---|
| 1 | **Broken deliverable (test, not spec)** | `tests/fixtures/exists_ungrouped/exists_agg_count.rs` and `not_exists_agg_count.rs` contain no `// AGENT_EDIT_START` / `// AGENT_EDIT_END` markers (`grep -c AGENT_EDIT` = 0). `extract_agent_edit` raises `ValueError: missing AGENT_EDIT markers`, so `test_reference_body_for_exists_over_an_aggregate_verifies`, `..._not_exists_...` and `test_the_old_data_dependent_answer_does_not_verify` FAIL (3 failed, 35 passed) on any machine where a Verus binary is found (the skip is checked first). The commit's claim "two verified reference bodies" is therefore not backed by a runnable test; whether the bodies verify is unchecked here (Verus not run). Fix: wrap the body in the AGENT_EDIT markers (see `tests/fixtures/declarative_proofs/*.rs`). |
| 2 | harmless (accepts invalid SQL) | `exists (select okey, sum(price) from li)` (non-aggregate column without GROUP BY) and `exists (select max(nonexistent) from li)` are accepted with `exists_1 = outer range`; DuckDB raises a Binder Error on both. The subquery body is no longer checked in the aggregate path, so invalid SQL passes. No valid query gets a wrong answer. |
| 3 | pre-existing, loud, not caused by 7ace4e0 | EXISTS nested in the WHERE of a non-aggregate EXISTS is emitted as a bare `... && (exists_1)` (a fn name, not a call, and the nested fn is never emitted); the same for plain nested EXISTS with no aggregate (`exists (select 1 from li where exists (select 1 from part p2 where p2.pkey > 100))`). `exists (select s from (select sum(price) as s from li) t)` (derived table, outer select has no aggregate) emits `t.n` for an undeclared `t`. Both should fail at Verus type check (not run here), i.e. loud, not a wrong-but-verifying spec. Note the aggregate path now removes this problem for the same nesting *inside an aggregate subquery* (the nested EXISTS is correctly dropped). |

No refusal was lost that mattered: HAVING / LIMIT / OFFSET / GROUP BY / ORDER BY / DISTINCT / union / window / WITH name / outer
join inside the subquery are all still `DeclarativeUnsupported` (the parser refuses them first; `_exists_fns`'s own HAVING guard is a
second line, covered by the commit's test). Refusals for unsupported aggregate arguments (`CAST`, `/`, `%`, overflowing arithmetic,
arithmetic around an aggregate) still fire because they happen at parse. Aggregate arguments that DuckDB would error on at run time
(integer overflow) are refused by the overflow check, so no accepted query errors in DuckDB where the spec says TRUE.

## Probes (SQL abbreviated as `exists(...)`; outer is `select count(*) as c from part where ...` unless stated)

Notation: spec = emitted `exists_N` body; DuckDB = count over li states (empty / none-match / match).

| # | Probe | Spec | DuckDB | Verdict |
|---|---|---|---|---|
| 1 | `exists(select sum(price) from li where qty>100)` | outer range only | 3 / 3 / 3 | held |
| 2 | `not exists(...same...)` | `!exists_1` over outer range | 0 / 0 / 0 | held |
| 3 | `not (exists(agg))`, `not (not exists(agg))` | `!((exists_1))`, `!(!exists_1)` | 0/0/0 and 3/3/3 | held |
| 4 | `exists(agg) and exists(select 1 from li where qty>100)` | exists_1 range only; exists_2 data dependent | 0 / 0 / 3 | held |
| 5 | `not exists(agg) or exists(select 1 ...)` | same | 0 / 0 / 3 | held |
| 6 | `exists(agg) and not exists(select min(qty) from li)` (two aggregate EXISTS) | both range only | 0 / 0 / 0 | held |
| 7 | `exists(agg) and ptype='a'`, `exists(agg) or ptype='a'` | AND/OR keep the predicate | 1,1,1 and 3,3,3 | held |
| 8 | agg with `FILTER (where ...)` | range only | 3/3/3 | held |
| 9 | `count(distinct okey)` | range only | 3/3/3 | held |
| 10 | agg over a join inside the subquery (`li join part p2`) | range only | 3/3/3 | held |
| 11 | correlated: `where li.okey = part.pkey` / `p2.pkey > p1.pkey` / `ptype='a'` (outer col) | range only | 3/3/3 | held |
| 12 | `sum(price)/sum(disc)` (aliased) ratio, `count(*)/count(*)`, `avg(price)`, `sum(price), count(*)`, `sum(..) as s, max(..) as m`, `sum(case when .. end)` | range only | 3/3/3 | held (hidden aggregates for ratio/AVG classify correctly) |
| 13 | aggregate nested in arithmetic in the select list (`sum(price)*2 as x`, `max+min`, `2*max`) | refused `SELECT expression` | 3/3/3 | held (refusal, unchanged) |
| 14 | `sum(price)+1` without alias, `max(price)/min(price)` | refused | 3/3/3 | held |
| 15 | aggregate subquery with a nested EXISTS / NOT EXISTS / IN / scalar subquery in its WHERE | range only, nested dropped | 3/3/3 (valid SQL forms) | held |
| 16 | `exists(select 1 from li where qty > (select min(qty) from li))` (non-aggregate outer sub, aggregate scalar inside) | data dependent (`exists e0 ... > sq_1`) | 0 / 3 / 3 | held (old path, unchanged) |
| 17 | `exists(select sum(s) from (select price as s from li) t)` (aggregate over derived table) | range only | 3/3/3 | held |
| 18 | `exists(select s from (select sum(price) as s from li ...) t)` (derived table contains the aggregate, outer select is plain) | `exists e0 < t.n && true`, `t` undeclared | 3/3/3 | hole 3 (pre-existing, loud) |
| 19 | `exists(select 1 from li where ...)` plain | data dependent | 0 / 0 / 3 | held (unchanged) |
| 20 | `exists(select 1 from li group by okey)`, `exists(select okey, count(*) ... group by okey)`, `not exists(... group by)` | refused (GROUP inside a subquery) | data dependent | held (refusal) |
| 21 | `having sum(price) > N`, `having count(*) > N` with or without `select 1` | refused | 0/0/0 or 0/0/3 | held (refusal) |
| 22 | `limit 1`, `offset 1`, `order by 1`, `distinct`, `union`, `sum(..) over ()` | refused | | held (refusal) |
| 23 | `with t as (select sum(..)) ... exists(select * from t)` | refused (WITH name inside a subquery) | 3/3/3 | held (refusal) |
| 24 | `select count(*) from part where exists(...) is true` | refused | | held |
| 25 | `pkey in (select max(okey) from li)`, `pkey not in (select max(qty) from li)`, `pkey in (select count(*) ... where ...)` | refused (IN subquery shape; `emit_in._check_shape` rejects aggs without groups) | data dependent | held. The `nulls.py` NOT IN rewrite (`NOT EXISTS (inner)`) can only feed an IN that is refused at emit, so the aggregate meaning change cannot reach it |
| 26 | `pkey = (select max(okey) from li)`, `(select count(*) from li) = 0` | refused (scalar subquery / FROM) | | held |
| 27 | projection outer: `select pkey from part where [not] exists(agg)` | range only / negated | all 3 rows / none, for every state | held |
| 28 | grouped outer: `select ptype, count(*) ... where [not] exists(agg) group by ptype` | range only / negated | 3 groups / none | held |
| 29 | grouped outer with `having exists(agg)` | range only | 3 groups | held |
| 30 | outer table is the other one: `select count(*) from li where [not] exists(select max(pkey) from part where pkey>100) and/or qty>5` (empty part-match) | range only over li | (0,0,1) both | held |
| 31 | `select okey, sum(price) from li where exists(agg over part) group by okey` | range only | group rows in non-empty states, empty li gives none | held |
| 32 | `exists(select count(*) from li where false)` | range only | 3/3/3 | held |
| 33 | outer join: `part join li on ... where exists(agg over li l2)` | `exists_1(part, li, i0, i1)`, range for both indexes | 0 / 2 / 2 (join row count) | held; see item 4 below |
| 34 | `part join li on exists(agg)` (EXISTS in JOIN ON) | refused (JOIN ON predicate) | | held |
| 35 | EXISTS in a CASE inside an aggregate | refused (CASE) | | held |
| 36 | integer-overflow / division / cast / `like` / `%` inside the aggregate subquery | overflow, `CAST`, `/`, `%` refused; `like` accepted (range only) | 3/3/3 | held |
| 37 | `select 1 from li ... exists (select 1)` (no FROM) | refused (FROM) | | held |

Classification (question 2): `_ungrouped_aggregate` is `bool(sub.aggs) and not sub.group_columns`. Verified: hidden aggregates for ratio and AVG
count as aggregates (correct); an aggregate with arithmetic around it is refused before it can be misclassified; a subquery with an
aggregate plus a plain column and no GROUP BY is invalid SQL in DuckDB (hole 2, harmless); set operation / DISTINCT / window / HAVING / LIMIT
inside the subquery are refused by the parser; an aggregate in a nested subquery lives in that nested `Query`, not in `sub.aggs`, so it
does not turn a plain EXISTS (item 16) into an always-true one.

## Item 4: well-formedness of the generated `exists_N` (text only, Verus not run)

For `select count(*) as c from part join li on part.pkey = li.okey where exists (select sum(price) from li l2 where l2.qty > 100) and not exists (select max(pkey) from part p2)`:

```
pub open spec fn exists_1(part: &Cols_part, li: &Cols_li, i0: int, i1: int) -> bool {
    &&& 0 <= i0 < part.n as int && 0 <= i1 < li.n as int
}
pub open spec fn exists_2(part: &Cols_part, li: &Cols_li, i0: int, i1: int) -> bool { (same) }
... row_hit(part, li, i0, i1) ... (exists_1(part, li, i0, i1) && !exists_2(part, li, i0, i1))
```

Arity (params `part, li`; indexes `i0, i1`) matches every call site; the unused index parameters and unused params are legal in a spec fn
(the pre-existing path also passes all main indexes). When the aggregate subquery is the only user of a table (outer `from part`, sub over
`li`), the spec still takes `li: &Cols_li` as a parameter (it carries only `n`, no columns, since the aggregate columns are no longer read);
`run_query(part, li)` therefore still receives an unused `li` argument. Not unsound; a mild loss of precision (the agent gets an unused argument).
Pinned by `test_multi_table_outer_exists_fn_is_well_formed_text`.

## Reproduce

```
cd /home/emil/projects/lemma-db/.claude/worktrees/agent-afd7da90f775761ea
uv run pytest tests/test_exists_ungrouped_adversary.py -q          # held properties: 49 pass
uv run pytest tests/test_exists_ungrouped_aggregate.py -q           # shows HOLE 1: 3 failed (missing AGENT_EDIT markers), 35 passed
# single probe (spec text):
uv run python - <<'EOF'
from tests.test_exists_ungrouped_aggregate import SCHEMA, CATALOG
from declarative_spec.emit import emit_declarative_spec
print(emit_declarative_spec("select count(*) as c from part where exists (select s from (select sum(price) as s from li where qty > 100) t)", SCHEMA, CATALOG))
EOF
```

DuckDB side of each probe: create `li(okey bigint, price decimal(15,2), disc decimal(15,2), qty integer)` and `part(pkey bigint, ptype varchar)`
with `part = (1,'a'),(2,'b'),(3,'c')`, li states `[]`, `[(1,3.0,0.5,2),(2,5.0,0.25,3)]`, `[(1,3.0,0.5,200),(2,5.0,0.25,3)]` (`tests.test_exists_ungrouped_aggregate._duck`).
