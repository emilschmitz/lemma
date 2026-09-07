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

When telling Emil about a problem, lead with **`step N (name):`** and the one-liner class (`transpiler coverage` / `assemble` / `agent stupidity` / `failed to execute` / `infra`). Do not mix stages.

**Proofs are the agent’s job** (`AGENT_EDIT` only). Host work is the harness: steps **2, 4, 6, 7** (typed spec, assemble, compile, pin/execute). Do not hand-write or patch proofs. If the agent fails on a **sound** spec, a **general** prompt tweak is allowed; query-specific prompt hacks are not.

## Git checkpoints (overrides “commit only when asked”)

For **this repo**, agents **must** create git commits as rollback points. Do **not**
wait for Emil to say “commit” on routine milestones. (Global Cursor “ask before
commit” does **not** apply here.)

**When to commit (local `git commit`; push when Emil asks or when a clean tree is
needed for `LEMMA_EXPERIMENT`):**

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
- Do not `--amend` / force-push unless Emil explicitly asks.
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
  overrides; model **`cursor-grok-4.6-high`** in `research_loop/config.env` `AGENT_CMD`.

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

## Always read the traces on failure

When a run, experiment, verify, assemble, or agent session **fails**, do **not** guess from the
one-line summary alone. **If you even suspect an agent fail or a prove timeout, open the
traces first.** A driver line `TIMEOUT after Ns` is **not** proof that Verus timed out.
`verify_error_custom.log` starting with `verification results:: N verified, M errors` means
Verus **finished** (proof error, not a timeout). Only treat it as a timeout if that file
(or Verus stderr) says timed out / no `verification results`.

**Open the traces and identify the concrete error:**

- Experiment / optimizer logs: `experiment_data/logs/*.log`, `nohup.out`
- Verify: `research_loop/generated/verify_error_custom.log` and
  `research_loop/agents/failed_transpile/verify_*.json`
- Agent session: run dir under `research_loop/runs/<id>/` — especially
  `workspace/runquery_agent.rs`, `workspace/logs/agent_stream.jsonl`,
  `workspace/logs/agent_stderr.log`, MCP result JSON under `workspace/mcp_results/`
- Harness / assemble output referenced in `CUSTOM_PIPELINE_FAILED [...]` lines

Report **`step N (name):`** from § Product path, then the concrete error from those files.
Fix host bugs when the trace shows spec/assemble/execute errors; do not blame the agent
until errors are inside `AGENT_EDIT` on a sound spec.

**Always name the failure type** (see `research_loop/agents/AGENTS.md`): e.g.
`transpile_fail`, `host_codegen`, `admission`, `agent_verify`, `agent_timeout`,
`measure_harness`, `infra`. Explicitly answer: could a smarter agent have fixed it
within `AGENT_EDIT` / allowed tools? If errors are in generated MethodSpec/loaders →
`host_codegen` — **no**.

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
