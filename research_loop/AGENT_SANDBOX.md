# Agent Docker sandbox (CLI)

> OpenRouter tools path: [`db_extension/AGENT.md`](../db_extension/AGENT.md).

## Docker images

Default image is **tools-only** (OpenRouter host loop). For `LEMMA_AGENT_BACKEND=cli` +
`USE_AGENT_DOCKER=1`, build with the Cursor `agent` CLI installed:

```bash
docker build -t lemma-agent:latest -f docker/agent/Dockerfile .
docker build -t lemma-agent:cli --build-arg INSTALL_AGENT_CLI=1 -f docker/agent/Dockerfile .
```

If `INSTALL_AGENT_CLI=1` fails at build time (no network), mount the host `agent` binary
into the container or install manually; the build arg remains for CI with network access.

## Setup (Cursor CLI, network none, API-only egress)

```
Host
  ├─ EgressBridge (allowlist: *.cursor.sh / cursor.com / …)
  ├─ McpSocketServer (measure)
  └─ docker --network none
        ├─ mount ~/.cursor → /root/.cursor-host (copied into writable /root/.cursor)
        ├─ mount ~/.config/cursor → /root/.config/cursor-host (auth.json)
        ├─ CURSOR_API_KEY via AGENT_ENV (optional if auth.json enough)
        ├─ HTTPS_PROXY → sidecar → egress sock  (only allowlisted hosts)
        └─ agent CLI + mcp_proxy
```

Web fetches to non-allowlisted hosts fail at the proxy. No separate “deny web” config required.

When egress is on, the entrypoint also sets **`CURSOR_FORCED_SHELL_EGRESS=1`**, which Cursor’s
own CLI honors to disable **WebSearch / WebFetch** (cloud-side tools that would still work
via `api2.cursor.sh`). It also writes `/workspace/.cursor/cli.json` denying those tools.
Do **not** set `CURSOR_FORCED_SHELL_EGRESS_ALLOW_WEB_TOOLS` unless you intentionally want them back.

```bash
export USE_AGENT_DOCKER=1
export MOCK_AGENT=0
export AGENT_CMD='agent -p --force --trust --model composer-2.5 --output-format stream-json --stream-partial-output "$(cat PROMPT.txt)"'
export AGENT_ENV=CURSOR_API_KEY          # optional if ~/.config/cursor/auth.json exists
export AGENT_CREDENTIALS_DIR=$HOME/.cursor
export AGENT_AUTH_DIR=$HOME/.config/cursor
export AGENT_EGRESS_PROFILE=cursor       # optional; inferred from AGENT_CMD
# export LEMMA_EGRESS_ALLOWLIST=api.cursor.com,cursor.com   # full override if needed
export CURSOR_API_KEY=...

docker build -t lemma-agent:cli --build-arg INSTALL_AGENT_CLI=1 -f docker/agent/Dockerfile .
LEMMA_AGENT_BACKEND=cli AGENT_IMAGE=lemma-agent:cli uv run python -m db_extension.run_optimizer "SELECT ..."
```

### Other CLIs

| `AGENT_CMD` | Inferred profile | Typical env |
|-------------|------------------|-------------|
| `agent …` | `cursor` | `CURSOR_API_KEY` + `~/.cursor` |
| `claude …` | `anthropic` | `ANTHROPIC_API_KEY` |
| `codex …` | `openai` | `OPENAI_API_KEY` |

`AGENT_EGRESS_PROFILE=cursor,anthropic` unions allowlists.

**Denied egress** is logged to:
- `mcp_results/egress_bridge.jsonl` (all attempts)
- `mcp_results/egress_denied.jsonl` (denials only)
- host stderr as `[egress-denied] {...}`

Rebuild the agent image after entrypoint changes.

## Run artifacts (GCP harvest)

Each optimizer job with **`LEMMA_RESEARCH_LOG=1`** collects artifacts under
`research_loop/runs/<UTC>_q<qid>_<hex>/`:

```
manifest.json
result.json
history.json
workspace/          # trace.jsonl, runquery_agent.rs, mcp_results/, egress_*.jsonl
workspace/logs/agent_stream.jsonl   # Cursor CLI stream-json (live on mount; crash-safe)
workspace/logs/agent_stderr.log     # agent stderr tee (docker CLI)
logs/pipeline.log
logs/pipeline.jsonl
logs/agent_stream.jsonl       # copy of workspace stream when LEMMA_RUN_DIR set
logs/agent_stderr.log         # copy of workspace stderr when LEMMA_RUN_DIR set
logs/docker_agent.stdout
logs/docker_agent.stderr
logs/docker_meta.json
logs/harness_iter*.json
```

`research_loop/runs/LATEST` contains the absolute path of the latest run. Archive the directory for upload (`tar` / `gsutil cp -r`).
