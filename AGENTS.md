# Lemma agent & engine rules

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
