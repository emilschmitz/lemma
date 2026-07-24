# Lemma OpenRouter agent

## Architecture

The **host** runs an OpenRouter (OpenAI-compatible) ReAct tool loop. Tool calls execute inside a **Docker** container with `--network none` by default. The agent edits `runquery_agent.dfy` between marker comments; the host extracts the body and the existing assemble/harness pipeline verifies it.

```
Host (OpenRouter API)  ←→  docker run -i lemma-agent:latest
                              └─ JSONL tools_worker (read/write/shell/duckdb/submit)
```

**Migration note:** This agent still splices **Dafny** `RunQuery` bodies (`db_extension/agent/template_runquery.dfy`, `db_extension/dafny_transpiler/`). The verified engine path is **Verus** (`research_loop/` harness, `verus_transpiler/`). New work should target Verus `run_query` bodies; Dafny is legacy-only for this OpenRouter loop.

## Configuration

Flags load from `research_loop/config.env` with process-env overrides (`db_extension/agent/config.py`).

| Flag | Default | Description |
|------|---------|-------------|
| `LEMMA_AGENT_BACKEND` | `openrouter` | `openrouter` or `cli` (legacy Cursor CLI sandbox) |
| `OPENROUTER_API_KEY` | (empty) | Required for OpenRouter backend |
| `OPENROUTER_MODEL` | `anthropic/claude-sonnet-4` | Model id |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | API base |
| `AGENT_TIMEOUT_SEC` | `600` | Wall-clock limit per iteration |
| `AGENT_NETWORK` | `0` | `1` enables container network (default off; GenDB agents had web search) |
| `AGENT_DATA_MODE` | `stats` | `none` / `stats` / `full` — DuckDB tool policy; no raw row dumps by default |
| `AGENT_WEB_SEARCH` | `0` | `1` allows web search tool in container |
| `AGENT_DOCS_MOUNT` | `1` | Mount primer/AGENTS docs into agent context |
| `AGENT_SUBMIT_ONLY_MEASURE` | `1` | Timed measure only via host submit/harness (not agent wall-clock gaming) |
| `AGENT_WORKLOAD_HINT` | `1` | Write `WORKLOAD.md` into context |
| `AGENT_IMAGE` | `lemma-agent:latest` | Tool-worker image |
| `AGENT_MAX_TURNS` | `40` | Max ReAct turns per iteration |

**Primary metric:** `SESSION_HOT_US` for H1 path agents (`DB_EXTENSION_PATHS.md`). OpenRouter Dafny loop uses harness wall-clock until Verus migration.

### GenDB fair-compare alignment

GenDB README agents had file I/O, terminal, and **web search**. Our defaults disable network and web search. GenDB disallowed result/intermediate caching and precomputed derived columns — align submit harness accordingly (no memoized final answers on hot runs).

## Container mounts

| Host | Container | Mode |
|------|-----------|------|
| `research_loop/agent_workspace` | `/workspace` | rw |
| `.../context/ro` | `/context/ro` | ro |
| SSB flat tbl parent dir | `/data` | ro (optional) |

When `AGENT_DOCS_MOUNT=1`, primer and AGENTS markdown are copied into `/context/ro`.

## Data modes

- **none** — `duckdb_sql` disabled; agent uses spec only.
- **stats** — read-only aggregate/stats queries (COUNT, SUMMARIZE, EXPLAIN, etc.).
- **full** — any read-only SQL.

## Run

Build the tool image (from repo root):

```bash
docker build -t lemma-agent:latest -f docker/agent/Dockerfile .
```

Run the optimizer with a real agent:

```bash
MOCK_AGENT=0 OPENROUTER_API_KEY=sk-or-... uv run python -m db_extension.run_optimizer "SELECT ..."
```

Legacy Cursor CLI path (still viable):

```bash
LEMMA_AGENT_BACKEND=cli USE_AGENT_DOCKER=1 MOCK_AGENT=0 uv run python -m db_extension.run_optimizer "SELECT ..."
```

Preferred: OpenRouter host + tool Docker (`network none`).

## Tests

```bash
uv run pytest db_extension/tests/ -q
```
