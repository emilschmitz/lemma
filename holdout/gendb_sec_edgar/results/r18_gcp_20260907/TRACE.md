# r18 overnight traces (SHA `1bfd7df`)

Do **not** classify from `driver.out` / `TIMEOUT after` / `timed_out=True` alone.
If you suspect an **agent fail** or a **prove timeout**, open:

- `lemma-overnight-out-r18/logs/r18_Q*.log`
- `research_loop/runs/<id>/workspace/verify_error_custom.log`
- `research_loop/runs/<id>/workspace/runquery_agent.rs`

Harvest: `/home/emil/lemma-overnight-out-r18` on `lemma-gendb-overnight`.
VM git + `driver.out` `git_sha` = **`1bfd7dfd13c425690749f7b8614449fd2ba55244`** (current `main` at launch).

## Rule

| What you saw | What the trace said |
|---|---|
| Optimizer `TIMEOUT after 300s` | Host **harness wall** (`max(COMPILE,VERUS_VERIFY)+120` = 300). Not automatically a Verus timeout. |
| Docker `timed_out=True` | **step 3** agent session hit `AGENT_TIMEOUT_SEC=600`. |
| `verification results:: N verified, M errors` | Verus **finished**. Proof/type error. **Not** a timeout. |

## Harvest

| qid | lemma_ok | elapsed | Trace class |
|---|---|---|---|
| Q1 | true | 699s | Full path OK; `latency_us=2789839` |
| Q3 | false | 2510s | Docker 600s + MCP verify **finished** with agent proof errors |
| Q7 | false | 2512s | (same wave; not fully dumped here) |
| Q5 | false | 2517s | |
| Q8 | false | 2518s | |
| Q4 | false | 2551s | Agent `OK` then host 300s wall; later MCP verify is **E0425** missing `skip_*_dead` |
| Q2 | false | 2616s | MCP **proved** (124/0) + submit; leftover file is a later broken edit; host CLI 300s wall ignored submit |
| abort | `fail_streak_6` | | After Q3,Q7,Q5,Q8,Q4,Q2 |

## Q2 — they proved inside the container; the leftover file is the later break

Run: `/home/emil/lemma-r15/research_loop/runs/20260907T122251Z_q377825_424d6dc4` on the VM.

MCP `run_runquery` is host-side Verus (workspace bind-mounted into Docker). The agent is locked in the container; the **proofs are on the host socket**. Re-checked 2026-09-07: 11 run JSONs + `submitted.json`.

| run_id | proof | lat | what happened |
|---|---|---|---|
| `T122848` | False | | first verify fail |
| `T122949` | False | | 121/1 |
| `T123029` | **True** | 2387 | first 124/0 |
| `T123123` | False | | **exec** timed out 120s on 50k rows (proof already existed) |
| `T123843` | **True** | 2439 | proved again |
| `T123959` / `T124029` | False | | 122/1 after speed edits |
| `T124131` | **True** | 1064 | proved again |
| `T124930` | True then **panic** | | `index out of bounds` on `fy_ok` (len 0, idx 255) |
| `T125218` | False | | 123/1 leftover invariant on `fy_ok` |
| `T125313` | **True** | **66** | **submitted** (`submitted.json`); `dataset_size=256`; `compiler_error` excerpt `124 verified, 0 errors`; `wall_harness_ms=12829` |

`submitted.json`: `ok True`, `proof_verified True`, `bench_skipped false`, `measure_path=kernel`. That 66 µs is **256 rows**, not full SEC.

Workspace `runquery_agent.rs` on disk **now** is the later `fy_ok` body (`123 verified, 1 errors` in `verify_error_custom.log`). That is **not** the winning submit body. They kept editing for SESSION_HOT after a good prove.

`r18_Q2.log` host line:

```
Verifying and compiling Verus program... TIMEOUT after 300s
```

**step 7 / infra:** Docker CLI `run_agent_iteration` returns `(body, proc)` only. It never sets `agent_meta["submitted_metrics"]`. OpenRouter does. Optimizer therefore **always** re-runs verify+compile+full-table execute (300s wall) and ignores the marked 124/0. Last Docker session `timed_out=True` (iter 4, 600s) after they broke the body.

Classes: **step 3** they *could* prove (they did). **step 7/infra** threw the prove away. **step 3** again they overwrote a live proof.

## Q3 — Docker 600s; when verify ran, it finished with proof errors

Run: `20260907T122251Z_q926930_cff48c74`

`r18_Q3.log`: `agent_docker_end: exit=-1 timed_out=True` on multiple iters. **step 3 / infra** (agent budget).

Same run `verify_error_custom.log` **starts with**:

```
verification results:: 124 verified, 3 errors
error: assertion failed
    --> custom_query.rs:2798  assert(s2 as int == prev_full.2 as int + 1);
error: assertion failed
    --> custom_query.rs:2934  assert(s3 as int == prev_full.3 as int + 1);
error: invariant not satisfied at end of loop body
    --> rem_join_sq / st.inner@ bound forall
```

Also `case_when_u64` in **exec** `run_query` body (agent), not a missing host `case_when_u64` spec. **step 3 (agent).**

## Q4 — missing helpers, not timeout

Run: `20260907T122251Z_q817923_9a650bc0`

`verify_error_custom.log` is **2193 bytes**, rustc **E0425**:

```
cannot find function `skip_pre_dead` in this scope
cannot find function `skip_tag_dead`
cannot find function `skip_sub_dead`
```

Agent called helpers the host does not inject. **step 3 (agent)** (or missing Trusted if we decide those names are a host API — they are not in the current menu).

Log also has one `TIMEOUT after 300s` after agent `OK (517 s)` — same harness wall as Q2.

## Pipeline

```
1 sql → 2 transpile OK (2 ms on these) → 3 agent (600s / bad invariants / invented skip_*)
       → 4 assemble → 5 verify (MCP: finished with errors; host pass: sometimes 300s wall)
       → 6 compile → 7 execute  (Q1 only)
```

Not a regression of r13 join `verify_local` (32/32 still `VERIFY True`). Not r17 90s. Not `stmt` on `num` Binder pin.

## Tools vs proof (r18 abort wave)

The join menu **was** in the assembled file for Q2 (`join_method_spec_helper`, `rem_join`, `lemma_rem_join`, `agg_step`). `skip_*_dead` **does not exist** anywhere in the host (r13 four-table bodies use `rem_join_4`, not those names).

| Query | Trace | Tools? |
|---|---|---|
| Q2 | MCP proved **4 times** (124/0); submit `T125313`; leftover log is 123/1 `fy_ok`; host 300s ignore-submit | Helpers present. Not “unable to prove.” |
| Q3 | Verus finished: 124 ok, 3 fail — asserts in `run_query` + invariant | Same. |
| Q4 | rustc E0425 `skip_pre_dead` / `skip_tag_dead` / `skip_sub_dead` | Agent invented names. Real four-table helpers are `rem_join_4` / `lemma_rem_join_4_*`. |
| Q5 | Four Docker `timed_out=True`. **No** `verify_error_custom.log` | Never got a Verus verdict. Not a missing-Trusted line. |
| Q7 | E0308: `i0 = i0 - 1` — `usize` vs `int` in the agent loop | Type mix in the body, not a missing lemma. |
| Q8 | Verus finished: 124 ok, 2 fail — `lemma_multi_agg_helper_slot0_sum_native_leq_*` **precondition** `valid_cols_num(num)` | Lemma **exists**. Call site did not keep `valid_cols_num`. |

## Slow body that does prove r18 Q2

r18 Q2 is r13 Q1 with `fy = 2024` and `LIMIT 500`. Copying the r13 Q1 nested-loop body (reverse scan, rem/cell lemmas, `apply_having_filter_exec_*`) and changing `2022` → `2024`:

```
ADMIT True
VERIFY True
```

in ~6s (`/tmp/lemma-r18-q2-diag`, 2026-09-07). So a **slow** join that matches `join_method_spec_helper` **is** possible on this spec. The overnight agent’s Q2 file failed one invariant on that same helper; they did not land this loop. Hard part is the **proof steps** (reverse indices, rem lemmas, HAVING), not “Verus cannot prove any implementation.”
