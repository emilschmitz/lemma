# Lemma agent & engine rules

## Product path (report every failure against one step)

DuckDB is **not** a second engine. It is the pinned column store at **execute**.

| Step | Name | What happens |
|------|------|----------------|
| 1 | **sql** | Query + catalog schema |
| 2 | **transpile** | SQL → MethodSpec (`spec.rs`). Spec must be internally typed and complete. Holes here = **transpiler coverage failure**. |
| 3 | **agent** | Writes `run_query` so Verus can prove `≡ method_spec`. Only `AGENT_EDIT`. Agent cannot prove an ill-typed spec. Failures here with a fair spec = **agent stupidity** (or timeout). |
| 4 | **assemble** | Host stitches spec + agent body + loaders/`main`. Must not invent a second spec or drop types the spec uses. |
| 5 | **verify** | Verus on the assembled `.rs`. If errors are in generated spec/loaders → step 2 or 4, **not** 3. If errors are in `AGENT_EDIT` and spec is sound → step 3. |
| 6 | **compile** | Native binary. |
| 7 | **execute** | Run binary; **pin** DuckDB columns; time it. Failures here = **failed to execute** (pin, harness timeout, binary crash). |

When telling Emil about a problem, lead with **`step N (name):`** and **one** of these words. Do not mix stages. Do not invent a third label.

| What you say | When it is true |
|---|---|
| **The agent was too stupid** | You opened the traces. The spec is sound. The broken lines are inside `AGENT_EDIT`. Quote the file, the line, and the Verus/rustc error. A marked submit that is not `N verified, 0 errors` counts. No traces, no this label. |
| **Software fail** | Assemble, transpile, a call to a lemma the host deleted, a pin, a scorer, or missing traces. These should be impossible once the host is finished. Fix the software. Do not call this agent stupidity. |
| **It proved and then did not run** | Verus already said `N verified, 0 errors`, and step 7 (the timed run) died. That is a run fail, not a proof fail. |

**Traces before any claim about the agent.** If you are about to say the agent caused something, or you only suspect that, open the traces first. A driver line (`FAILED`, `TIMEOUT`, `fail_streak`) is not a trace. The trace is `mcp_results/runs/*.json`, `submitted.json`, and `verify_error_custom.log`.

**Proofs are the agent’s job** (`AGENT_EDIT` only). Host work is the harness: steps **2, 4, 6, 7** (typed spec, assemble, compile, pin/execute). Do not hand-write or patch proofs. If the agent fails on a **sound** spec, a **general** prompt tweak is allowed; query-specific prompt hacks are not.

## Git checkpoints (overrides “commit only when asked”)

For **this repo**, agents **must** create git commits as rollback points. Do **not**
wait for Emil to say “commit” on routine milestones. (Global Cursor “ask before
commit” does **not** apply here.)

**When to commit (local `git commit`) and push (`git push origin HEAD` by default;
do not wait for Emil to say “push”):**

1. After a **coherent host milestone** lands (Trusted/bridge/transpiler/injector/
   tests) and the relevant pytest slice is green — or after an intentional policy
   change even if the prove corpus is still climbing.
2. **Before** a risky corpus mutation (`inject_fold_bound_proofs --strip`, mass
   rewrite, brace “repair”, bulk restore).
3. After **recovering** from a bad inject/rewrite (so the fixed host + snapshot
   are restorable).

**Quality bar (still “make sure it’s good”):**

- Focused commits; message states **why** (milestone / checkpoint / recovery).
- Do not commit secrets, `.env`, credentials, or huge binaries.
- Do not commit paper TeX / Overleaf drafts unless Emil asks.
- After each checkpoint commit, **`git push origin HEAD`** (fast-forward). Do not
  wait to be asked. Still do not `--amend` / force-push unless Emil explicitly asks.
- Prefer green tests for the touched slice; if committing a known-broken WIP
  checkpoint, say so in the message (`WIP checkpoint: …`).

**`research_loop/generated/` is gitignored** (including prove_loop
`runquery_agent.rs`). Git alone will **not** roll back agent bodies. Before risky
inject/rewrite:

```bash
./research_loop/scripts/checkpoint_prove_loop.sh <label>
git add research_loop/artifacts/prove_loop_<label>.tar.gz AGENTS.md # + host files
git commit -m "Checkpoint prove_loop <label> (+ host if changed)."
```

Restore: `tar -xzf research_loop/artifacts/prove_loop_<label>.tar.gz -C research_loop/generated`.

Workers must **not** be told “no commit”; briefs should say “checkpoint per
AGENTS.md” when they finish a milestone or before strip/inject.

## GCP / Spot compute policy

When booking cloud VMs for Lemma experiments:

- **At most two** compute instances at a time. Do not create a third; stop or delete one first.
- **No GPUs.** CPU/RAM only. **Never** A100/H100, TPU, multi-node, or anything in the
  **~$100/hr** class. If a create would exceed the cap, **stop** — do not “just this once.”
- Prefer template / known shape: Spot **`n2-highmem-64`** from snapshot
  `lemma-gendb-pre-spot-*` (or the saved `lemma-gendb-n2-highmem-64` template overrides).
  Target **~$2–4/hr**. On-demand n2-highmem-64 is ~$4.19/hr; **Spot** is ~$1.8–2.2/hr
  in us-east1/us-central1. **Hard cap $7/hr** total (all VMs combined). On-demand is OK if
  Spot is out of stock. If Spot stock fails, retry another zone — still ≤2 machines, still
  under the cap — do not “upgrade” the machine class. **Never** ~$100/hr GPUs / multi-node.
- Agent timeouts for paper/CLI runs stay **`AGENT_TIMEOUT_SEC=600`** (10 min) unless Emil
  overrides. Model is **Grok 4.7 high**: slug **`grok-4.7-high`** in
  `research_loop/config.env` `AGENT_CMD` (`agent … --model grok-4.7-high`).
  Do not launch paper runs on `cursor-grok-4.6-high`.

### Experiment harvest (non-negotiable)

Every paper/Spot/`LEMMA_EXPERIMENT=1` run must be **reproducible** and **logged**:

- **Clean git worktree.** Do not set `LEMMA_EXPERIMENT_ALLOW_DIRTY`. Commit first.
  Harvest `meta/` / `hardware.json` must record **commit SHA**, branch, and `git_dirty=false`.
- **Fresh EDGAR shuffle** for prove_loop / 98% gates — new `queries_resample_rN.sql`
  (new seed), not a recycled r13 body corpus and not cloned `run_query` transplants.
- Keep **full traces**: `research_loop/runs/<id>/` (workspace, logs, history, config
  snapshot), plus `LEMMA_EXPERIMENT_EVENT_URL` stream when on Spot. rsync/gsutil the run
  tree; do not rely on chat status.
- If the VM SKU/zone/disk changes, **re-run DuckDB session-hot baselines** on that box
  (machine details are part of the result).
- Snapshot `research_loop/config.env` flags used (timeouts, model, `AGENT_CMD`) into the
  run dir / experiment notes.
- **Docker sandbox is required** for `LEMMA_EXPERIMENT=1` CLI agents:
  `USE_AGENT_DOCKER=1`, `AGENT_IMAGE=lemma-agent:cli`, network-none + allowlisted egress
  (see `research_loop/AGENT_SANDBOX.md`). **Never silently** set `USE_AGENT_DOCKER=0`,
  drop `MAX_ITERATIONS` below the paper default, pin a fake `LEMMA_DATASET_SIZE`, or
  count host-agent / measure-failed runs as the 98% gate. If the sandbox cannot be
  brought up, **stop and tell Emil** — do not continue a watered-down protocol.

## Paper loop (the only overnight protocol)

**Prove agent from now on: Grok 4.7** (`grok-4.7-high` in `research_loop/config.env` `AGENT_CMD`). It is the new model. Do not launch on `cursor-grok-4.6-high`.

One project: **this repo** (`/home/emil/projects/lemma-db`). Harvest blobs live
in `harvest/` (symlink to `~/lemma-harvest`, gitignored). Do not commit traces,
overnight outputs, credentials, or `harvest/`. Home `~/AGENTS.md` only points
here. Do not keep a second instruction set.

**Local r12/r13 50/50 is a different experiment.** August 2026, 50-query
resample, rocketship Trusteds, `VERIFY True`. r14 was a local tiny-SEC
rehearsal; agent-prove was not cleared. A Spot `n2-highmem-64` does **not**
replay that. The paper card is 61 jobs, fresh full-SEC shuffle, Docker CLI
(`USE_AGENT_DOCKER=1`, `AGENT_IMAGE=lemma-agent:cli`, `LEMMA_AGENT_BACKEND=cli`),
model **`grok-4.7-high`**, `LEMMA_SERIOUS=1`, `EMIT=0`, `FAST=0`, official
full-table measure, fail-streak 6. Bigger CPU does not turn a new shuffle into r13.

Loop, in order:

1. A **paper card** is a fresh SEC shuffle (new seed) plus Immanuel plus TPC-H.
   Launcher: `harvest/watch/launch_paper.sh`. Clean git, tracked SHA, one VM.
   Config verify must pass (Docker CLI, `grok-4.7-high`, not local `AGENT_CMD` /
   OpenRouter).
2. **Every 5 minutes, wake and check status** (VM up, family pid, ok/fail
   counts, streak). The wake is one monitored shell **in the open Cursor chat**
   (`research_loop/scripts/lemma_fail_wake.py`, `notify_on_output` on
   `AGENT_LOOP_TICK_lemma` and `AGENT_LOOP_WAKE`). It is not cron on the VM.
   It dies when that chat closes, the laptop sleeps, or the shell is not
   actually monitored. Arm it at the start of the session. Do not claim a wake
   exists if that shell is not running. A bare `sleep` with no
   `notify_on_output` does not create a turn.
   That same shell refreshes `$OUT/laptop_lease` on every poll. The guest
   `lemma_laptop_lease_watch.sh` (started by `overnight_lemma.sh`) halts the
   VM when the file is older than `LEMMA_LAPTOP_LEASE_SEC` (default 720).
   Chat death stops the refresher, so the Spot VM stops. Do not launch a
   paper family without that lease watch.
3. A **retry family** is not a paper card. After a host/harness fix: commit,
   push, rerun **only the qids that failed** in the dead family. Same SQL text,
   new family, `retry.json`, `LEMMA_SQL_FILE` + `LEMMA_SQL_ONLY=1`. Do not
   re-run greens. Do not append Immanuel/TPC-H unless one of those qids failed.
   Do not generate a new shuffle. Do not mix SHAs into the dead family.
4. **If the agent was too stupid** (errors inside `AGENT_EDIT` on a **sound**
   spec, no marked `N verified, 0 errors`): record it, notify with
   `AGENT TOO STUPID:` first line, **do not water down**, do not “fix” by
   weakening the bar. No `submitted.json` means you **cannot** use that label
   yet — treat missing submit + missing MCP runs as a harvest bug.
5. Do not start the next fresh paper card until that retry family finishes
   without a host abort (driver exit 0, or the only remaining misses are
   agent-stupid on a sound spec). A `fail_streak` abort or a still-open host
   hole does not start the fresh shuffle. After an agent-stupid record, do not
   water down. The later fresh card must not count that miss as a pass.

## Fail loop (overnight / Spot) — wake, check, repair or leave, retry marked

Keep the **5-minute paper loop** armed for the live family. **Every fail wakes
you. Do not skip the trace checklist because you already have a theory.**

On each wake:

1. **Pull** harvest + `traces/<qid>/` (GCS rsync). If `mcp_results/runs` or leftover
   verify are missing → **harness / software failed** (harvest), not agent. Fix harvest.
2. **Open traces in order** (this section below). Report **`step N (name):`** and
   **one primary blame class**.
3. **Fail report is the deliverable.** Driver `FAILED` / `fail_streak_N` /
   `lemma_ok=false` is **not** a report. Every wake, and every status that mentions
   fails, **must** include **Reason** and **Response** for **each** new fail qid.
   Do **not** stop at a one-line `FAILED` table. Do **not** end the turn on
   “analysis in progress” / “still looking.” If context is tight, ship the table
   for every qid you opened this wake. Copy it into `~/lemma-harvest/STATUS.md`.

   | Job | SQL (one line) | step N (name) | type | primary blame | smarter agent in `AGENT_EDIT`? | evidence (MCP run + rustc/verus) | **Reason** | **Response** |

   - **Reason** = the concrete hole. Quote the error. Name host line vs `AGENT_EDIT`.
   - **Response** = the next action: repair host + new family `retry.json`; record
     `AGENT TOO STUPID` (do not water down); fix harvest; do not mix SHA into the
     dead family.
4. **If software / host failed** (transpile, assemble, inject calling an omitted
   lemma, pin, timeout policy, missing traces, classifier): **repair the host**,
   commit + push, **retry**. Do **not** leave a known host hole in a live SHA.
5. **If the agent was too stupid to prove** (errors inside `AGENT_EDIT` on a **sound**
   spec; a smarter agent could have submitted `N verified, 0 errors`): **do not
   water down** (no FAST on rocket, no `ensures true`, no row-cap rewind). Record
   the fail. Do **not** “repair” by weakening the proof bar.
   **Notify Emil bigly** — first line of the message, not buried. Use:
   **`AGENT TOO STUPID:`** `step 3 (agent)` / `qid` / one-line evidence from
   `AGENT_EDIT` (e.g. `assert forall` with no `by`, invented `step_row`,
   `assert("US"@ != ""@)`). Only after the trace checklist. Do **not** use this
   label for host/assemble holes (omitted-lemma **calls in generated spec /
   Trusted**, loaders, stitch). Nested `proof fn` inside `run_query` does **not**
   put a name in scope for a host lemma.
6. **Retries are a new family**, never mixed into the failed harvest SHA.
   Example: r26rocket SHA `e445686` host-fail Q11 → fix on `main` → **r27rocket**
   with `retry.json`:
   `{ "retry_of": "r26rocket", "from_sha": "…", "to_sha": "…", "reason": "…", "step": 4 }`.
   The retry SQL file contains only the failed qids; launch with `LEMMA_SQL_FILE`
   and `LEMMA_SQL_ONLY=1`. Do not overwrite `gs://…/r26rocket/`.

## Always read the traces on failure

**Always. Including when you only suspect the agent.** Any claim that agent behavior caused a fail, a timeout, a streak, or a bad score starts from the traces. Do not suspect out loud and then skip the files.

When a run, experiment, verify, assemble, or agent session **fails**, do **not** guess from the
one-line summary alone. A driver line `TIMEOUT after Ns` is **not** proof that Verus timed out.
`verify_error_custom.log` starting with `verification results:: N verified, M errors` means
Verus **finished** (proof error, not a timeout). Only treat it as a timeout if that file
(or Verus stderr) says timed out / no `verification results`.

**Open the traces and identify the concrete error. Order is mandatory:**

1. **`workspace/mcp_results/runs/*.json`** — every MCP `run_runquery`. Record
   `proof_verified`, `ok`, `latency_us`, `dataset_size`, and the `compiler_error`
   excerpt (`verification results:: N verified, M errors` or rustc).
2. **`workspace/mcp_results/submitted.json`** — if it exists, that marked run is
   the official prove. Do **not** contradict it with a later leftover file.
3. Only then leftover `workspace/verify_error_custom.log` and
   `workspace/runquery_agent.rs` (last edit; often a speed-chase overwrite).
4. Experiment / optimizer logs: `experiment_data/logs/*.log`, `nohup.out`,
   harvest `r18_Q*.log`. A `TIMEOUT after Ns` line is the **host harness wall**,
   not a Verus verdict.
5. `research_loop/generated/verify_error_custom.log` and
   `research_loop/agents/failed_transpile/verify_*.json` for local prove_loop.

Do **not** classify “agent could not prove” from leftover verify / `runquery_agent.rs`
alone. r18 Q2 leftover was 123/1 after they had already submitted **124/0**.

Report **`step N (name):`** from § Product path, then the concrete error from those files.
Fix host bugs when the trace shows spec/assemble/execute errors; do not blame the agent
until errors are inside `AGENT_EDIT` on a sound spec.

**Always name the failure type** (see `research_loop/agents/AGENTS.md`): e.g.
`transpile_fail`, `host_codegen`, `admission`, `agent_verify`, `agent_timeout`,
`measure_harness`, `infra`. Explicitly answer: could a smarter agent have fixed it
within `AGENT_EDIT` / allowed tools? If errors are in generated MethodSpec/loaders →
`host_codegen` — **no**.

**Always name the blame class** (this is what Emil wants to hear; do not
stop at “TIMEOUT”). Pick **one primary**, then list secondaries. Use these
words:

| Blame class | Meaning | Typical product-path step |
|-------------|---------|---------------------------|
| **agent too stupid to prove** | Sound spec; agent never got `N verified, 0 errors` on a marked submit. | 3 agent / 5 verify |
| **agent too stupid to write something fast** | Proved; the *body they chose* is asymptotically / algorithmically slow (nested loop vs hash, no filter pushdown) **and** a smarter agent with the **same** Trusteds / row budget / flags **could** have written a fast one. | 3 agent (body) + 7 execute |
| **setup didn’t give the agent the ability to write something fast** | Fast join/scan Trusteds off (`LEMMA_FAST_TRUSTEDS=0`, `LEMMA_ENABLE_PARALLEL=0`); MethodSpec *is* nested `rem_join`; agent only times `LEMMA_MCP_ITERATE_ROWS` (50k) so they cannot select for the official pin. | flags / iterate vs official |
| **harness / software / setup failed — program it to be more resilient** | Pin size, wall clock, scoring, retries, abort policy, or classifier is wrong. A correct slow-or-fast body still dies. **Fix the host.** | 7 execute / overnight |

Do **not** call a proved nested-loop “agent too stupid to write something fast”
if the only legal exec shape is `rem_join_*` and hash/parallel Trusteds were
off. That is **setup didn’t give the ability**. Do **not** call an official
600s kill “agent too stupid to prove” when `verification results:: N verified,
0 errors` already exists.

**Hard rule — missing traces:** If `workspace/mcp_results` (runs/*.json,
submitted.json) or leftover `verify_error_custom.log` were **not harvested** off
the VM, do **not** classify “agent too stupid to prove”. Default to **harness /
software failed** (traces not saved; fix harvest before blaming the agent).

### Worked example — r24rocket 2026-09-20 (`fail_streak_6`)

Harvest: `~/lemma-harvest/r24rocket`. SHA `c818042`. Official pin
`dataset_size=39401761` = **max COUNT(*) of every DuckDB table** (`num`),
applied as the **same `LIMIT` on every table** (`pin_table`:
`SELECT cols FROM t LIMIT n`). Real SEC sizes: `num` 39,401,761, `pre`
9,600,799, `sub` 86,135, `tag` 1,070,662. Iterate cap 50k.
`LEMMA_FAST_TRUSTEDS=0`, `LEMMA_ENABLE_PARALLEL=0`.

**Note:** r24rocket agent prompts did **not** inject official pin X and MCP iterate
max Y at run time (hardcoded “not full table” wording). Current harness/CLI prompts
and `context/ro/row_budgets.md` now insert those numbers from host config dynamically.

| Job | Step | Primary blame | What happened |
|-----|------|---------------|----------------|
| **Q25** | **5 verify / 3 agent** | **harness / software failed** | **Primary blame is the host**, not the agent. Harvest has **no** `workspace/mcp_results/runs/*.json`, **no** `submitted.json`, and **no** leftover `verify_error_custom.log` (overnight rsyncs `$OUT` logs only; run dir stayed on the VM). Without those traces we **cannot** call “agent too stupid to prove”. Driver log only: four iters each hit `CUSTOM_PIPELINE_FAILED [verify]`, then Docker `exit=-9 timed_out=False` at ~600s (`timeout --signal=KILL`). Host RAM was ~490 GiB free — **not OOM**. Never a marked submit. Exact Verus `N verified, M errors` was on the dead VM disk. Fix: classify GNU-timeout `-9` as `agent_timeout`; **always** ship `mcp_results` + leftover verify with the harvest (`harvest_traces`). |
| **Q18, Q20, Q21, Q16, Q23** | **7 execute** | **harness failed — make it resilient** | Agent **did prove** (127–130/0). MCP iterate `dataset_size=50000` ran (0.4–9s). Official `SELECT … LIMIT 39401761` on each table → nested `rem_join` over real `pre`×`sub` (~9.6M×86k, ~330× iterate join work) hit **600s wall**. DuckDB hash-join of the same SQL is ~0.4–0.6s. Overnight treats proved+unmeasured as **fail** and `fail_streak_6` aborted 41 remaining jobs. Same official TIMEOUT **retried 3×** on the same `run_id` (Q18). |
| same jobs, secondary | flags / iterate | **setup didn’t give the ability to write something fast** | Speed Trusteds off. Join spec is nested `rem_join`. `run_runquery` without `dataset_size` is the 50k cap (**not** full table). |
| same jobs, **not** primary | — | **not** “agent too stupid to write something fast” | Nested loop that is 5s @ 50k×50k is hundreds of seconds–hours @ 9.6M×86k. Hash join was not on the rocket menu. |
| same jobs, **not** | — | **not** “agent too stupid to prove” | Proof already finished. |

**Did the agent know official is the large tables?** Yes, the **sizes**.
`data_profile.md` (injected; `LEMMA_AGENT_DUCK_EXPLAIN=1`) prints actual
`COUNT(*)` (`num` 39,401,761, …). The prompt also says: prefer
`run_runquery` **without** `dataset_size` = “host MCP iterate cap, **not
full table**”; `submit_runquery` then the host times full table. They
were **told** 39M exists. They were **told not to time it** while
iterating. They had **no** in-session 39M stopwatch (600s agent wall;
default MCP is 50k). So they could pick a nested-loop body that looked
fast at 50k and still die on the official pin.

**Host work this implies (do not wait for a smarter agent):** pin LIMIT per
table the query actually reads (not global max); don’t count official TIMEOUT
as a prove-fail for `fail_streak`; don’t re-run a cached official timeout;
emit hash/parallel Trusteds on the rocket path **or** stop scoring nested-loop
kernels against full SEC @ 600s; classify Docker `exit=-9` as timeout; rsync
`research_loop/runs/*/workspace/mcp_results` + leftover verify, not just
overnight `$OUT` logs.

### Worked example — r26rocket 2026-09-20 abort (`fail_streak_6`)

Harvest: `~/lemma-harvest/r26rocket`. SHA `e445686`. Consecutive misses (resume
retry): **Q11, Q24, Q28, Q26, Q16, Q29**. No `submitted.json` on any of the six.
Transpile OK. Official pin never ran. Fast never started.

**Cluster (Q11/Q24/Q28/Q26/Q16 + in-flight Q27):** `host_codegen` **step 4 assemble**.
Product transpile uses large-SEC catalog → spec emits only
`lemma_rem_cap_native_add_fits_rows` (ROWS²·NATIVE does not fit u64 at 39M).
`assemble_verified_program._boundary_helpers` calls `multi_agg_step_trusted_rs`
**without** that catalog → skip empty → host inductive slot lemma still calls
`lemma_rem_cap_native_add_fits(rem_tail_u64)` at assembled `custom_query.rs:2694`
(Q26: 2654 and 2789). rustc E0425, help names `_rows`. **Smarter agent: no** —
that call is outside `AGENT_EDIT`. Nested `proof fn` inside `run_query` is not
in scope for the host lemma. Tests that pass `catalog=` into
`multi_agg_step_trusted_rs` miss this because assemble drops it.
**Response:** thread the transpile catalog into assemble; test assembled RS
omits the unsuffixed call; do **not** put the unsound lemma back; **r27rocket**
`retry.json` step 4 with retry SQL (failed qids only) and `LEMMA_SQL_ONLY=1`.
Do not mix into r26.

**Q29:** different SQL (3-table join LIMIT 50). No host rem_cap call.
**AGENT TOO STUPID:** `step 3 (agent)` / Q29 / `while` in proof mode, then
invented `lemma_take50_to_origin` / leftover `i0 = i0 - 1` usize vs int.
**Smarter agent: yes.** Record; do not water down. Retry on r27 only because
the family is already dead from the host cluster.

| Job | SQL | Step | Type | Primary | Smarter? | Evidence | Reason | Response |
|-----|-----|------|------|---------|----------|----------|--------|----------|
| **Q11** | pre⋈sub `stmt='CI'` COUNT/COUNT DISTINCT/AVG line LIMIT 500 | **4 assemble** / 5 verify | `host_codegen` | **harness — omitted-lemma call** | **no** | MCP last `…T234041_461dbd4a` E0425 `custom_query.rs:2694` host `lemma_multi_agg_helper_slot2_*` | Spec has `_rows` only; assemble still calls unsuffixed rem_cap | Repair assemble catalog; r27rocket `retry.json` step 4 |
| **Q24** | same join-agg `stmt='EQ'` LIMIT 100 | **4 assemble** | `host_codegen` | **harness** | **no** | 4/4 MCP E0425 at **2694**; agent also nested-def the omitted lemma in `AGENT_EDIT` | Host call at 2694; agent leftover at 2936/3112 is secondary stupidity | Same host repair. Do not treat nested def as a fix. |
| **Q28** | same `stmt='BS'` LIMIT 1000 | **4 assemble** | `host_codegen` | **harness** | **no** | first MCP `expected ','`; then 4× E0425 at **2694** | Same host hole; early parse is secondary | Same. |
| **Q26** | num⋈sub SUM/AVG `uom='shares'` fy=2023 | **4 assemble** | `host_codegen` | **harness** | **no** | 5/5 MCP E0425 at **2654 and 2789** (two SUM slots) | Same omit/call split, two host sites | Same. |
| **Q16** | same as Q11 LIMIT 1000 | **4 assemble** | `host_codegen` | **harness** | **no** | leftover E0425 ×2: host **2694** + agent call 3128; agent **redefines** omitted lemma with false ROWS²·NATIVE | Host still blocks N/0 even if agent deleted their call | Same. Do not restore unsound lemma. |
| **Q29** | pre⋈sub⋈tag `10-Q/A` EQ custom=0 LIMIT 50 | **3 agent / 5 verify** | `agent_verify` | **agent too stupid to prove** | **yes** | MCP `…T231313_f9e9d152` `cannot use while in proof`; later E0425 `lemma_take50_to_origin`; leftover E0308 `i0 = i0 - 1` | Errors inside `AGENT_EDIT` on a sound spec | Record. No FAST / no `ensures true`. r27 only because family already aborted. |

## No fallbacks without explicit approval

**Never** add a fallback, silent alternate path, soft degrade, “if X is down do Y”,
or any other substitute that can look like success when the intended path failed —
**especially for scientific / `LEMMA_EXPERIMENT` runs** — unless Emil has **explicitly
approved that specific fallback** in the conversation (or an approved written design).

- Prefer **loud failure** over a clever backup.
- Do not invent MCP-down, DuckDB, mock-agent, dirty-git, missing-tool, or “save the file
  and hope” escapes in prompts, harnesses, or product code without that approval.
- Existing forbidden mocks in the pipeline contract below still apply; this rule is
  broader: **no new fallbacks of any kind without asking first.**

## Pipeline contract (non-negotiable)

```
SQL + schema → MethodSpec (transpiler) → agent writes run_query → Verus proves run_query ≡ method_spec → native exec
```

- **MethodSpec is the ground truth.** It must be a **real open-spec fold** (recursive `decreases`,
  Map updates, nested-loop join helpers, …) — **never** `arbitrary()`, and never a vacuous
  `#[verifier::external_body]` that invents the whole query result.
- **Agent fills `run_query` only** so Verus proves `ensures res == method_spec(...)` (or the
  documented view equality). The agent **must not** add `#[verifier::external_body]`,
  `arbitrary()`, `assume`, `unimplemented!`, new `spec fn`s, or any new TRUSTED surface.
- **Predefined TRUSTED helpers only** (host-injected in `value_bounds` / `agent_primitives` /
  NativeAgg bridges): arithmetic wrappers, string/ILIKE bridges, HashMap↔Map view lemmas, etc.
  Those are fixed APIs. **The engine must not auto-emit a TRUSTED `run_query` or a TRUSTED
  whole-query `method_spec` to “make SQL look supported.”**
  **Rocketship bar** (expert-trustworthy IF–THEN under named data caps): see
  `docs/TRUSTED_FAMILIES.md` and `research_loop/agents/AGENTS.md` § “Rocketship Trusted bar”.
  Host loop removes empty fold-slot `assume_*`; do not greenwash via corpus reinject.
- **Forbidden mocks (anywhere in the product path):**
  - `method_spec` / query helpers = `arbitrary()`
  - `run_query` = `unimplemented!` / empty `external_body` claiming `ensures ≡ method_spec`
  - Auto-codegen HashMap bodies marked verified without a real MethodSpec fold
  - Silent DuckDB / other-engine fallback for “verified” success
- **Prefer failure over mocks.** If SQL cannot yet get a **real** MethodSpec, **fail
  transpile loudly** (`failed_transpile/` / `UnsupportedContractError`). Never ship a green
  “verified” path that is actually `arbitrary()`, `unimplemented!`, or a vacuous TRUSTED
  whole-query bridge. Incomplete support → hard fail; do not fake it.

`verus_transpiler/codegen_exec.py` is experimental only — **not** the research-loop / optimizer
contract. Default transpile emits MethodSpec + **commented RunQuery skeleton** for the agent.

## General engine — not SSB-specialized

Lemma is a **general** verified query engine. The Verus transpiler, admission lint, native
externs, and agent pipeline must stay **schema-driven**.

- **Never** hardcode dataset-specific column names, table names, or literals in engine
  code (`verus_transpiler/`, `research_loop/assemble_verified_program.py`,
  `research_loop/admit_runquery.py`, loaders, etc.).
- **OK** in unit tests, benchmark query bodies (`benchmark_verified.py`), and
  workload SQL fixtures — those are query instances, not the engine.
- **OK** for global policies that apply to every query: value bounds, `LemmaMax*`
  constants, lemmas emitted per schema column type — not per benchmark query.

## Development workflow

During development, do **not** run the optimization agent loop. Write and test queries
directly (`research_loop/benchmark_verified.py`).

### H1 path agents (db_extension_*)

Primary metric: **`SESSION_HOT_US`** (GenDB hot recompute with session open). Path index:
`docs/DB_EXTENSION_PATHS.md`. Agent briefs live under `db_extension_paths/agent/`,
`db_extension_runtime/agent/`, `db_extension_lease/agent/`, `db_extension_storage/agent/`.

Measure:

```bash
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
db_extension_paths/check_mem.sh uv run python db_extension_paths/measure_e2e_paths.py
```

### OpenRouter / optimizer agent (Verus)

`db_extension/` optimizes via **Verus** (`transpile_sql_to_verus` + `runquery_agent.rs`).
Schema is caller/catalog/`LEMMA_SCHEMA_JSON` — not SSB-hardwired. Dafny lives only under
`dafny_legacy/` / `dafny_transpiler/` (quarantine); do not extend that path.

## Agent contract (`run_query` body only)

Host injects signature + `requires valid_cols` + `ensures res == method_spec(...)`.
Agent edits **only** the marked body. Admission must reject new TRUSTEDs / `arbitrary` /
`unimplemented!`. Details: `research_loop/agents/AGENTS.md`.

## Agent sandbox flags

Loaded from `research_loop/config.env` (see `db_extension/AGENT.md` for OpenRouter host):

| Flag | Default | Meaning |
|------|---------|---------|
| `AGENT_NETWORK` | `0` | Container network off |
| `AGENT_DATA_MODE` | `stats` | `none` / `stats` / `full` — no raw row dumps by default |
| `AGENT_WEB_SEARCH` | `0` | Web search tool off |
| `AGENT_DOCS_MOUNT` | `1` | Mount primer/AGENTS docs into context |
| `AGENT_TIMEOUT_SEC` | `600` | Per-iteration timeout |
| `AGENT_SUBMIT_ONLY_MEASURE` | `1` | Timed measure via host submit/harness only |
| `AGENT_MCP_URL` | (empty) | Optional; prefer Unix-socket MCP (`db_extension/AGENT.md`) |

Preferred setup: OpenRouter host + tool Docker (`network none`) + Unix-socket MCP /
sandbox `mcp_proxy`. CLI-in-Docker: Inspect-style model bridge + MCP with network none.
Host FastMCP: `uv run python -m db_extension.agent.mcp_host --transport stdio`.
Legacy: `LEMMA_AGENT_BACKEND=cli` + `USE_AGENT_DOCKER=1`.
