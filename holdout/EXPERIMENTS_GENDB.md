# GenDB-comparable experiments (fixed plan — audit before GCP deploy)

**Status:** local product path wired (2026-08-08). Phase 0 on GCP still needs VM +
API keys. Do **not** burn agent/$ until audit sign-off below.

Paper: [arXiv:2603.02081](https://arxiv.org/abs/2603.02081).

**One product path:** DuckDB storage + **`lemma_lease`** + Docker-sandboxed agent that
edits `run_query` and measures via **host MCP tools** (verify / run outside the container).
Experiment mode = same loop + **full metric harvest** under `research_loop/runs/<id>/`.

Primary metric: **`SESSION_HOT_US`** when `LEMMA_MEASURE_PATH=lease|auto|both` (lease binary).
Also keep Verus `latency_us` / `proof_verified`. Parallelism **on** for paper GCP runs.
No final-answer memoization. **`LEMMA_EXPERIMENT=1`**: no mock, no DuckDB result fallback,
force `LEMMA_RESEARCH_LOG=1`, fail loud (`CUSTOM_PIPELINE_FAILED`, exit ≠ 0).

### Local readiness (done)

| Item | Status |
|------|--------|
| Workload auto (`holdout` / `ssb` / `tpch` / `sec`) | `db_extension/workload_config.py` |
| `run_optimizer` loads correct tables (not silent SSB) | yes |
| Lease measure → `SESSION_HOT_US` | `db_extension/agent/lease_measure.py` |
| MCP merge lease metrics | `measure_core` + `LEMMA_MEASURE_PATH=auto` |
| Harvest `runs/<id>/` + `meta/hardware.json` | yes when experiment |
| Phase 0 docs + holdout generator script | `holdout/scripts/phase0_bringup.md`, `make_lemma_holdout.sh` |
| Unit tests (workload/flags/lease/artifacts/measure) | passing |

Needs on GCP: SF10 + full SEC data, agent API key (OpenRouter or Cursor CLI), MT paper runs.

---

## Holdout: stronger anti-leakage (“ours”)

| Set | Role |
|-----|------|
| **`queries_lemma_holdout.sql`** | **Primary.** `bash holdout/gendb_sec_edgar/make_lemma_holdout.sh` (seed `LEMMA_HOLDOUT_SEED`, default `20260808`). |
| **`queries.sql`** (GenDB’s six) | **Secondary parity** only. |

Data: SEC 2022–2024 via `setup_data.sh`. TPC-H SF10 for paper subset Q1/Q3/Q6/Q9/Q18.

---

## Metrics tracked (every experiment run)

Per iteration + best: `SESSION_HOT_US`, `PREP_US`, `OPEN_US`, `COLD_QUERY_US`, Verus
`latency_us`, `proof_verified`, `wall_s`, `agent_gen_wall_s`, tokens/cost when available.
Run tree: `manifest.json`, `result.json`, `history.json`, `meta/hardware.json`, `workspace/`,
`logs/`. SCP/gsutil the whole `research_loop/runs/<id>/`.

---

## Iteration policy

`MAX_ITERS=4` default for paper (env `MAX_ITERATIONS`). Early stop + keep best correct.
Timeouts: measure 300 s / agent 30 min (align GenDB).

---

## Hardware

Prefer **`n2-highmem-64`** while credits burn (~$4.19/hr). ≥200 GB disk. Stop when idle.
See prior sections for cost tables.

---

## Phase 0 / 1

Follow `holdout/scripts/phase0_bringup.md`. Then Phase 1 agent with:

```bash
export LEMMA_EXPERIMENT=1
export LEMMA_WORKLOAD=holdout   # or tpch / sec
export LEMMA_MEASURE_PATH=auto
export LEMMA_ALLOW_DUCKDB_FALLBACK=0
export MOCK_AGENT=0
# OpenRouter:
export OPENROUTER_API_KEY=...
# or Cursor CLI sandbox:
# export LEMMA_AGENT_BACKEND=cli USE_AGENT_DOCKER=1 CURSOR_API_KEY=...
```

---

## Audit sign-off (before GCP agent $)

- [ ] `LEMMA_EXPERIMENT=1` accepted (no mock; no DuckDB fallback; fail loud)
- [ ] Holdout seed + SQL frozen after SEC load on VM
- [ ] Metrics list accepted; harvest path `research_loop/runs/`
- [ ] `MAX_ITERS=4`, timeouts accepted
- [ ] Primary agent chosen (Cursor vs Claude/OpenRouter)
- [ ] Machine: `n2-highmem-64` (credits) + stop/suspend policy
- [ ] SSH access agreed
- [ ] Phase 0 bring-up smoke (lease + DuckDB baselines) reviewed before Phase 1

**Signed off by:** _____________ **date:** _____________
