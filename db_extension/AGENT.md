# Lemma OpenRouter agent

Schema-driven **Verus** optimizer (not SSB-only). The host transpiles SQL with a caller-supplied
or catalog-resolved schema via `verus_transpiler`; agents edit `runquery_agent.rs` against
`/context/ro/spec.rs`. Legacy Dafny paths live under `research_loop/dafny_legacy/` and are not
used by the default optimizer.

## Schema

Pass an explicit schema dict to `run_optimization_loop(..., schema={...})`, set
`LEMMA_SCHEMA_JSON=/path/to/schema.json`, or use `DatabaseCatalog` against the DuckDB
file that holds the workload tables (`LEMMA_DUCKDB_PATH`). Unknown tables fail loudly —
there is no hardcoded SSB/TPCH schema invent path.

## Architecture

```
Host
  ├─ OpenRouter ReAct (LLM on host)     [default]
  ├─ EgressBridge allowlist UDS         [CLI-in-Docker: Cursor/Anthropic/…]
  ├─ McpSocketServer UDS → measure_core
  └─ tool/CLI container (--network none)
        ├─ tools_worker / agent CLI
        ├─ mcp_proxy (stdio MCP → MCP sock)
        └─ egress sidecar HTTPS_PROXY → only vendor API hosts
```

**CLI:** mount `~/.cursor` (or `AGENT_CREDENTIALS_DIR`), pass `AGENT_ENV` keys, egress
allowlist by profile (`cursor`, `anthropic`, …). Non-API web is blocked by the proxy.
With egress on, Cursor also gets `CURSOR_FORCED_SHELL_EGRESS=1` so **WebSearch/WebFetch**
are disabled automatically (they run in Cursor cloud via `api2`, not as local curls).
See `research_loop/AGENT_SANDBOX.md`.

**Real MCP:** `mcp_tool_specs.py` → host FastMCP, sandbox `mcp_proxy`, OpenRouter defs.

### Tools

| Tool | Action |
|------|--------|
| `validate_runquery` | Body lint |
| `run_runquery` | Host harness; `run_id` + metrics |
| `submit_runquery` / `submit` | Mark only |
| `get_submit_result` / `list_runs` / `mcp_health` | Read back |

### Register MCP (CLI on host)

```json
{
  "mcpServers": {
    "lemma-host": {
      "command": "uv",
      "args": ["run", "python", "-m", "db_extension.agent.mcp_host", "--transport", "stdio"],
      "env": {
        "LEMMA_AGENT_WORKSPACE": "/ABS/PATH/research_loop/agent_workspace",
        "LEMMA_QUERY_ID": "1"
      }
    }
  }
}
```

Inside Docker CLI mode, entrypoint writes `.cursor/mcp.json` → `python -m lemma_agent.mcp_proxy`.

## CLI-in-Docker (Cursor / other CLIs)

`--network none` + **allowlisted egress** (not open internet):

- Mount `AGENT_CREDENTIALS_DIR` (default `~/.cursor`) → `/root/.cursor`
- Pass `AGENT_ENV` keys (e.g. `CURSOR_API_KEY`)
- Host `EgressBridge` allowlist by `AGENT_EGRESS_PROFILE` (`cursor`, `anthropic`, …)
- Sandbox `HTTPS_PROXY=http://127.0.0.1:8118` → only those API hosts
- MCP measure via Unix socket / `mcp_proxy`

See `research_loop/AGENT_SANDBOX.md`. Rebuild: `docker build -t lemma-agent:latest -f docker/agent/Dockerfile .`

## Run

```bash
docker build -t lemma-agent:latest -f docker/agent/Dockerfile .
MOCK_AGENT=0 OPENROUTER_API_KEY=sk-or-... uv run python -m db_extension.run_optimizer "SELECT ..."
```

Custom schema example:

```bash
export LEMMA_SCHEMA_JSON=/path/to/schema.json   # {"V":"int"} or multi-table JSON
uv run python -c "
from db_extension.optimizer import run_optimization_loop
print(run_optimization_loop('SELECT SUM(v) FROM t', schema={'V':'int'}, use_mock=True))
"
```

## Tests

```bash
uv run python -m pytest db_extension/tests/test_measure_core.py db_extension/tests/test_mcp_socket.py db_extension/tests/test_mcp_host.py db_extension/tests/test_mcp_registry_sync.py db_extension/tests/test_model_bridge.py db_extension/tests/test_tools_worker_paths.py -q
```

## Run artifacts (GCP harvest)

Each optimizer job **with ``LEMMA_RESEARCH_LOG=1``** writes one harvest directory under
`research_loop/runs/<id>/`:

```
manifest.json
result.json
history.json
workspace/          # agent files, mcp_results/, egress_*.jsonl, trace.jsonl
logs/pipeline.log
logs/pipeline.jsonl
logs/docker_agent.*
logs/harness_iter*.json
logs/openrouter_meta_iter*.json
```

`research_loop/runs/LATEST` points at the most recent run (absolute path). Set automatically via
`LEMMA_RUN_DIR` and `LEMMA_AGENT_WORKSPACE` when research logging is on.

```bash
LEMMA_RESEARCH_LOG=1  # required for harvest dirs (default 0)
```

Archive the whole directory for GCP: `tar czf run.tgz -C research_loop/runs <id>/` or `gsutil cp -r research_loop/runs/<id>/ gs://bucket/path/`.
