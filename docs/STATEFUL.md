# Stateful accelerators (`stateful`)

A query may be answered from a state the agent precomputes once per data version (a per-group table, prefix sums over
date buckets, an index), with no LLM-written trusted code. Switch: `[run] stateful = true` in `lemma.toml`.

## Contract (emitted by the transpiler, frozen)

The emitter states the query exactly as before; `declarative_spec/stateful.py` then replaces `run_query` by:

```rust
pub struct QDb { pub lineitem: Cols_lineitem }                       // one field per table, named like the run_query parameter
pub open spec fn query_pre(lineitem: &Cols_lineitem) -> bool { .. }  // the requires of run_query, verbatim
pub open spec fn query_post(lineitem: &Cols_lineitem, res: Vec<OutRow>) -> bool { .. }  // the ensures of run_query, verbatim
// AGENT_STATE_START  (agent: pub struct QAcc { .. } and further struct/enum types; Ghost fields allowed)
// AGENT_STATE_END
pub struct QState { pub snap: Ghost<QDb>, pub acc: QAcc }
impl QState {
    pub open spec fn db(&self) -> QDb { self.snap@ }
    pub open spec fn inv(&self) -> bool { query_pre(&self.snap@.lineitem) && qstate_inv(self) }  // qstate_inv: agent spec fn
}
pub fn build(lineitem: Cols_lineitem) -> (s: QState)
    requires query_pre(&lineitem),
    ensures s.inv(), s.db() == (QDb { lineitem: lineitem }),
{ /* AGENT_BUILD */ }
pub fn execute(s: &QState) -> (res: Vec<OutRow>)
    requires s.inv(),
    ensures query_post(&s.db().lineitem, res),
{ /* AGENT_EDIT */ }
```

Runtime parameters (query templates) are every non-table parameter of `run_query`: they become extra parameters of `execute` and of
`query_post`. A `requires` on a runtime parameter and a self join (two parameters of one table) are refused for now.

The degenerate case: `QAcc` owns the tables, `qstate_inv` says each equals the one in `s.db()`, and `execute` is a `run_query` body
(`tests/fixtures/declarative_proofs/stateful_degenerate_sum.rs`).

## What is proved

* `build` (Verus): from tables satisfying `query_pre`, it returns a state with `inv()` whose ghost snapshot is exactly its inputs.
* `execute` (Verus): from any state with `inv()`, the result satisfies `query_post` on the snapshot: the same postcondition `run_query`
  had. So `execute(&build(t))` meets the query spec on `t`. `qstate_inv` is the agent's, but it is assumed only where `build` proved
  it: a wrong or weak invariant makes a proof fail, it never changes an answer.
* The host runtime `QRuntime` (fixed code in the assembler, inside `verus!`, verified with the program): `refresh(v, t)` builds on `t`
  and records `v`; `execute_at(v)` returns `None` unless the kept state was built at `v`, and otherwise a result satisfying
  `query_post` on the snapshot that state was built from. Answering from another version's state does not verify
  (`test_runtime_without_the_version_check_does_not_verify`).

## What is trusted (unchanged plus one item)

* As before: Verus/vstd, the column-file reader in `main` (it checks the loader `requires` at run time), the export from DuckDB.
* New: the data version. The runtime cannot know the data; the caller passes a version with every call and must pass a new one
  whenever the tables change (DuckDB's commit id / table versions in the extension, a counter in the tests). The tables handed to
  `refresh` must be the snapshot at that version (DuckDB's snapshot isolation in the extension; the exported files in the tests).
  Under an unchanged version new data is not read (`test_same_version_is_trusted_not_rechecked`).
* No persistence: the state lives in process memory only and is rebuilt after a restart, so nothing on disk is trusted.

## Lazy maintenance

Nothing runs on a write. On each call the runtime compares the version; if no state exists or it was built at another version it
reads the current tables and calls `build`, then `execute`. One state is kept: going back to an older version number builds again.

## Host programs

* Measure `main` (the in-session and official measures): load, `refresh(0, ..)` once (`STATE_BUILD_US`, outside the timer), then the
  timed runs of `execute_at(0)`. Note: the timed figure is `execute` only; the build cost is reported separately and is not part of
  the speed verdict.
* Serve `main` (`assemble_declarative_program(.., serve=True)`): one call per stdin line `<version> <column file per table>`
  (order printed as `SERVE_TABLES:`); prints `BUILT 0|1`, `STATE_BUILD_US`, `EXEC_US`, the rows, `END`. This is the shape of the call
  an in-DuckDB extension makes through a fixed ABI: `is_current(version)`, else `refresh(version, tables)`, then
  `execute_at(version, params)`.

## Tests

`tests/test_stateful.py`: flag off byte-identical (22 TPC-H + 2 queries against the emitter of a254d17), flag-on contract text, admission
(accepts the fixtures; rejects assume/admit/external/impl/fn/derive/host names/`Cols_` names/host access in every region; requires
`QAcc` and `qstate_inv`), assembly of both mains, the prompt section, Verus on the fixtures and on mutated bodies and runtimes, and
differential runs of the compiled fixtures (`stateful_group_table.rs`, `stateful_date_prefix.rs`) against DuckDB on random tables under
inserts, deletes and updates (each a new version), and on TPC-H SF1.
