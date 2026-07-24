# Lemma agent & engine rules

## General engine — not SSB-specialized

Lemma is a **general** verified query engine. The Verus transpiler, admission lint, native
externs, and agent pipeline must stay **schema-driven**.

- **Never** hardcode dataset-specific column names, table names, or literals in engine
  code (`verus_transpiler/`, `research_loop/assemble_verified_program.py`,
  `research_loop/admit_runquery.py`, loaders, etc.).
- **OK** in unit tests, benchmark query bodies (`benchmark_runqueries.py`), and
  workload SQL fixtures — those are query instances, not the engine.
- **OK** for global policies that apply to every query: value bounds, `LemmaMax*`
  constants, lemmas emitted per schema column type — not per benchmark query.

## Development workflow

During development, do **not** run the optimization agent loop. Write and test queries
directly (`research_loop/benchmark_verified.py`).

### H1 path agents (db_extension_*)

Primary metric: **`SESSION_HOT_US`** (GenDB hot recompute with session open). Path index:
`DB_EXTENSION_PATHS.md`. Agent briefs live under `db_extension_paths/agent/`,
`db_extension_runtime/agent/`, `db_extension_lease/agent/`, `db_extension_storage/agent/`.

Measure:

```bash
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
db_extension_paths/check_mem.sh uv run python db_extension_paths/measure_e2e_paths.py
```

### Legacy OpenRouter agent (Dafny bodies)

`db_extension/` still splices Dafny `RunQuery` bodies via `template_runquery.dfy` and
`db_extension/dafny_transpiler/` (SQL → Dafny spec). **Target migration:** Verus
`run_query` bodies via `research_loop/` harness. Do not extend the Dafny engine path.

## Agent contract (`run_query` body only)

The host injects signature + spec helpers; the agent must **not** add new declarations
outside the skeleton. For Verus paths, fill `run_query` so **`run_query` ≡ `method_spec`**
(proved loop or documented TRUSTED bridge). See `research_loop/agents/AGENTS.md`.

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

Preferred setup: OpenRouter host + tool Docker (`network none`). Legacy:
`LEMMA_AGENT_BACKEND=cli` + `USE_AGENT_DOCKER=1`.
