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
export AGENT_CMD='agent -p --force --trust --approve-mcps --model composer-2.5 --output-format stream-json --stream-partial-output "$(cat PROMPT.txt)"'
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

## Claude Code agent (`lemma-agent:claude`)

Claude Code runs headless inside the same sandbox (network none, egress only to
`anthropic.com` / `api.anthropic.com` via the `anthropic` profile, inferred because the
command starts with `claude`; only the first word of `AGENT_CMD` selects the profile).
Build (the Docker bridge on this host cannot reach the network at build time, so use host
networking for the build only; runs stay `--network none`):

```bash
docker build --network host -t lemma-agent:claude --build-arg INSTALL_CLAUDE_CODE=1 -f docker/agent/Dockerfile .
```

The image gets Node from apt and `npm install -g @anthropic-ai/claude-code`, nothing else.
The command is built by `agent_sandbox.claude_agent_cmd(model)`: `claude -p --model <slug>
--output-format stream-json --verbose --permission-mode acceptEdits`, tools
`Bash,Read,Edit,Write,Glob,Grep,mcp__lemma-host`, `WebSearch`/`WebFetch` denied, MCP from
`/root/.cursor/mcp.json` with `--strict-mcp-config`, prompt on stdin. The stream is piped
through `lemma_agent.claude_stream`, which writes the Cursor-style transcript to
`workspace/logs/agent_stream.jsonl` (thinking deltas, `tool_call` started/completed, final
`result` with cost) and keeps Claude's raw stream in `workspace/logs/claude_raw.jsonl`.
`agent_stderr.log` is unchanged.

Credentials (the claude agent fails loudly if neither is set; nothing is read from `~/.claude`
or written to disk or logs):

1. `ANTHROPIC_API_KEY` in the launching shell. Passed to the container as `-e ANTHROPIC_API_KEY`
   (name only, so the value is not on the docker command line).
2. `LEMMA_CLAUDE_CONFIG_DIR=<dir>`: mounted read-only at `/root/.claude-host`, copied into
   the writable `CLAUDE_CONFIG_DIR=/root/.claude` by the entrypoint.

A model agent runs next to whatever is mounted or in its environment, so use a dedicated,
spend-capped API key. Cursor credentials and the Cursor CLI are not mounted into this container.

Facts learned from the mock end-to-end run (Claude Code 2.1.289):

- `claude` is a native binary (`claude.exe`), not a Node script. The image's Node 18 and
  `NODE_USE_ENV_PROXY=1` are irrelevant to it: it honors `HTTPS_PROXY` itself and goes through the
  sidecar with a plain `CONNECT` (see `egress_bridge.jsonl`).
- `--permission-mode acceptEdits --allowedTools Bash,Read,Edit,Write,Glob,Grep,mcp__lemma-host`
  runs Read, Edit, Bash and the lemma-host MCP tools headless with no permission prompt. No
  `--dangerously-skip-permissions` is used or needed.
- With `DISABLE_TELEMETRY`, `DISABLE_AUTOUPDATER`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` the only
  hosts the container contacted were the model API; `egress_denied.jsonl` was never created. Any other
  host is a 403 at the bridge and is logged there.
- The MCP proxy runs in the image, which has only `lemma_agent`. The host passes the
  `run_runquery` tool blurb in `LEMMA_RUN_RUNQUERY_BLURB` (the entrypoint writes it into `mcp.json`);
  a missing variable is a loud `KeyError`, the MCP server then shows `failed`.
- Claude Code writes text and tool_use blocks of one turn as separate `assistant` stream events;
  `claude_stream.py` handles that (`tests/fixtures/claude_stream_real_mock.jsonl` is the recorded real
  stream).
- Exit codes: a failing claude exits non-zero (`set -o pipefail`). `AGENT_TIMEOUT_SEC` kills the
  container; the run reports `timed_out` and exit `-9`, and the declarative driver records
  `agent timed out (AGENT_TIMEOUT_SEC): exit -9, no submit` (a failed or timed-out agent with no
  `submitted.json` fails the iteration instead of surfacing later as "empty agent body").
- Containers run with `--memory 3g --memory-swap 3g`.

### Mock model API (no credentials; plumbing tests)

`research_loop/scripts/mock_anthropic_api.py` is a TLS/SSE mock of `/v1/messages` that scripts
Read, Edit (reference body), Bash, `run_runquery`, `submit_runquery`, final text. The container's
Claude Code reaches it through the real egress bridge: env `LEMMA_TEST_MOCK_ANTHROPIC_PORT` +
`LEMMA_TEST_MOCK_ANTHROPIC_CA` (both or loud error) switch the egress profile to
`anthropic-mock-test`, which allows only `lemma-mock-anthropic.test` (reserved `.test` name, no real
vendor host) and makes the bridge dial 127.0.0.1:port for it. Real runs never set these, so their
policy (network none, only anthropic hosts) is unchanged. Run it (one heavy job at a time, memory
capped, Verus through `scripts/ram/verus_guarded.sh`):

```bash
systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run pytest tests/test_claude_mock_e2e.py -q
```

### Real-API steps (yours)

```bash
# 1. image (host networking for the build only; runs stay --network none)
docker build --network host -t lemma-agent:claude --build-arg INSTALL_CLAUDE_CODE=1 -f docker/agent/Dockerfile .
# 2. credentials, in your own shell. Either a dedicated spend-capped API key ...
export ANTHROPIC_API_KEY=...
#    ... or a directory you prepare that contains your login file:
# export LEMMA_CLAUDE_CONFIG_DIR=$HOME/lemma-claude-config
# 3. the SEC DuckDB the ladder needs
export LEMMA_DUCKDB_PATH=/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_local.duckdb
# 4. one cheap query first (haiku, ladder query 1 only), then the ladder
uv run python -c "from research_loop.scripts.declarative_ladder import run_ladder; run_ladder('claude-haiku-4-5-20251001', indices=(1,))"
uv run python research_loop/scripts/declarative_ladder.py claude-haiku-4-5-20251001
uv run python research_loop/scripts/declarative_ladder_claude.py   # haiku, then sonnet 5.5 only if haiku proves < 4/6
```

Per-run env only; `config.env` is untouched. Traces per run: `research_loop/runs/LATEST`.

### One launcher, one flag: `--style imperative|declarative`

Same container, same agent, same sandbox; the style flag switches the whole chain (emitter, trusted
set, prompt, agent-visible mounts, admission, assembler, measure). "Imperative" is the loop-and-invariant
path; the value was formerly spelled `recursive` and `recursive` is rejected. The two style names live in
`research_loop/spec_styles.py` (one place; `ENV_VALUE` there is what is written to `LEMMA_SPEC_STYLE`).

```bash
uv run python research_loop/scripts/run_container_agent.py --style declarative \
    --menu adversary_declarative0 --agent claude-haiku-4-5-20251001 \
    --query-sql "SELECT report, COUNT(*) AS cnt FROM pre WHERE line > 5 GROUP BY report"
uv run python research_loop/scripts/run_container_agent.py --style imperative \
    --menu rocketship --agent claude-haiku-4-5-20251001 --allow-override \
    --query-sql "SELECT COUNT(*) FROM pre WHERE line > 0"
```

`--menu` names a profile (`research_loop/menu_profile.py`) that sets every axis; `LEMMA_MENU=<name>`
does the same for `run_optimization_loop`. Axes: `style`, `trusted_set` (`rocketship`, `fast`,
`adversary_imperativespec0` for imperative; `declarative_default` for declarative), `assumption_package`,
`agent`, `speed_bar_mult`. Overrides, each ONE axis: `LEMMA_SPEC_STYLE`/`--style`,
`LEMMA_TRUSTED_SET`/`--trusted-set`, `LEMMA_ASSUMPTION_PACKAGE`/`--assumption-package`,
`LEMMA_AGENT_MODEL`/`--agent`, `LEMMA_SPEED_BAR_MULT`/`--speed-bar-mult`. An override that contradicts a
value the profile sets fails unless `--allow-override` (`LEMMA_MENU_ALLOW_OVERRIDE=1`); a trusted set that
does not belong to the style fails always. The resolved selection (every axis and its source) is printed
first and stored in the run's `manifest.json` under `menu`. Note: a shell that exports
`LEMMA_ASSUMPTION_PACKAGE` (e.g. `prove_loop`) counts as an override.

`/workspace/context/ro` is mounted read-only inside the container (nested mount after the rw workspace).

### Verified against the mock vs needs your real run

| Behavior | Mock | Real run |
|---|---|---|
| Container starts, network none, memory cap, entrypoint, MCP socket, egress bridge | verified | - |
| Claude Code reaches its API through HTTPS_PROXY sidecar (CONNECT, TLS, custom CA) | verified | real `api.anthropic.com` TLS and the `anthropic` allowlist (`anthropic.com`, `api.anthropic.com`) cover every host a real session contacts |
| Headless permissions: Read/Edit/Bash/lemma-host MCP with no prompt | verified | same flags, expected identical |
| `run_runquery` proves (`proof_verified: true`) and `submit_runquery` writes `submitted.json` | verified | - |
| `agent_stream.jsonl` / `claude_raw.jsonl` / `agent_stderr.log`, harvest layout like Cursor | verified | `thinking` events: the mock emits none, so the thinking-delta conversion is only covered by the hand-made `claude_stream_sample.jsonl` |
| Timeout kill (`AGENT_TIMEOUT_SEC`), exit -9, failing claude fails the run | verified | - |
| Ladder plumbing: slug -> `--model`, SUCCESS classification, results record | verified (query 1) | - |
| Telemetry / auto-update traffic is off | no denied or unexpected hosts seen | confirm `egress_denied.jsonl` stays empty |
| Credentials: `ANTHROPIC_API_KEY` pass-through by name | verified (dummy key) | real key accepted |
| `LEMMA_CLAUDE_CONFIG_DIR` login-file mount and its format | not tested | needs your real login file |
| Model behavior, proof success rate, rate limits / 429 / overload errors, real costs | not testable | needs your run |
| Real stream details the mock cannot produce (thinking blocks, usage/cost, `api_retry` on real errors) | not testable | check `claude_raw.jsonl` once |

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
