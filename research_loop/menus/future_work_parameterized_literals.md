# Future work: parameterized literals (paused 2026-10-07)

Status: **paused** by Emil, listed as future work for the paper. Preserved on branch `worktree-agent-a231dc03f073f5e80`, tag
`archive/param-literals-wip-2026-10-07`. Nothing merged to `main`.

## The idea

Today the spec and the proved body inline every constant in the SQL (filter constants, string literals, date bounds). Changing a constant means a new spec and a new proof.
With `LEMMA_PARAM_LITERALS=1` (default off) the emitter makes constants run-time parameters of `run_query`; the spec's `ensures` is stated in terms of them. **One proved program then
serves every value of the parameters** (the proof quantifies over them), which fits dashboards and recurring queries with changing filter values: the generation and proof
cost is paid once for the whole family, and each new value costs only an execution.

## Why it matters against GenDB

From the GenDB paper (arXiv:2603.02081, main text through the conclusion): one executable per query. "Generating Reusable Components" (reusable data structures, relational
operators, query templates, and multi-query executables) is listed in its research agenda as future work, and the current system reuses only basic utility functions. So parameterized
reuse is not in the published prototype. For us it also answers the "a new value arrives" objection: DuckDB must re-execute for each value; one proved program covers all of them.

## What was done before the pause (preserved)

- `declarative_spec/params.py` (registry and extraction), wiring through parse, emit, assemble and the measure harness, the flag, a first spec emitting `lp_k` struct fields,
  a measurement script `research_loop/scripts/param_literals.py`, tests `tests/test_declarative_param_literals.py`.
- **Result:** the arena query r1_q02 lifted with 4 parameters (a dictionary string, two dates, a HAVING constant) was **proved** (PASS, rows match DuckDB) by adapting its existing body minimally.
- **Open:** speed. A first, noisy measurement showed the parameterized body at about 139 ms against 102 ms for the literal version (constants can no longer be folded; loops may vectorize
  differently). Not yet resolved, and the multi-value experiment (one program, about 5 values) was not run.

## Plan if resumed

1. Parameterize: comparison constants in WHERE/HAVING/ON, BETWEEN bounds, IN-list members (list length stays fixed), string equality and LIKE parts only if provable, date bounds, arithmetic constants.
   Keep LIMIT/OFFSET and structural constants literal. Dictionary mode: a string parameter must be translated to its code at run time (including the "value not in the dictionary" case: empty selection).
   Narrow cells: parameter wider than the cell needs the same care as the existing literal-wider-than-cell note; range assumptions checked at run time.
2. **Binding by construction and checked at run time:** the values come from the same parse that built the spec; before the call the host asserts they equal the values re-extracted from the SQL. No new trusted item.
3. Performance: literal vs parameterized per query (median of 9, full tables, `heavy.sh`, DuckDB 3 GB / 8 threads, x86-64-v3); fix lost constant folding and vectorization; hoist per-parameter work out of loops; branch-free comparisons.
4. Experiment: one proved program, about 5 parameter values, speed for each against DuckDB re-executing each, and amortization (generation plus proof once, N values).
5. Adversary review of the value binding, dictionary misses, range checks and type or scale mismatches.
