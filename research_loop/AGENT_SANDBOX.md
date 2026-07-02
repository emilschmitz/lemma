# Agent Docker sandbox

The optimizing agent runs in a **Docker container** with network access (LLM APIs). Dafny verify, Rust compile, and DuckDB stay on the **host**.

## How submission works (the loop)

Each optimization iteration:

1. **Host** transpiles SQL → writes `spec.dfy` into read-only context.
2. **Host** copies `templates/runquery_agent.dfy` into `agent_workspace/` (iteration 1 only; later iterations keep the file for refinement).
3. **Host** writes `PROMPT.txt` (feedback from last harness run) and runs `docker run`.
4. **Agent** edits **only** `/workspace/rw/runquery_agent.dfy` (body inside `{ ... }`).
5. **Agent exits** — saving that file **is** the submission (headless `-p` / print mode).
6. **Host** reads the body, splices into trusted `RunQuery` shell (`assemble_runquery.py`), runs `admit_runquery`, then `harness.py`.
7. Harness JSON (verify error or latency) feeds the **next** iteration’s prompt.

No separate “submit” button — one Docker run = one iteration.

## Setup

### 1. Build the agent image (once)

```bash
docker build -t verified-hillclimbing-agent:latest docker/agent
```

The image installs (best effort): **Cursor Agent** (`agent`), **agy**, **Claude**, **Codex**, **OpenCode**, **Pi**. Each tool has its own license — you must comply with the vendor TOS when passing API keys.

### 2. Configure API keys and command

Edit `research_loop/config.env` or export env vars before running the DuckDB optimizer:

```bash
export CURSOR_API_KEY="your-key"
export AGENT_ENV=CURSOR_API_KEY
export AGENT_CMD='agent -p --force --model composer-2.5 "$(cat PROMPT.txt)"'
```

Run optimizer (real agent, not mock):

```bash
export MOCK_AGENT=0
export USE_AGENT_DOCKER=1
uv run python -m db_extension.run_optimizer "SELECT ..."
```

### Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `USE_AGENT_DOCKER` | `1` | Run agent in Docker |
| `AGENT_IMAGE` | `verified-hillclimbing-agent:latest` | Docker image name |
| `AGENT_CMD` | Cursor `agent` + Composer 2.5 | Shell command run **inside** container in `/workspace/rw` |
| `AGENT_ENV` | `CURSOR_API_KEY` | Comma-separated env var **names** copied from host into container |
| `AGENT_TIMEOUT_SEC` | `600` | Agent run timeout |
| `MOCK_AGENT` | `1` in extension | Set `0` to use real agent |

Override at runtime:

```bash
AGENT_CMD='agy -p "$(cat PROMPT.txt)"' \
AGENT_ENV=GOOGLE_API_KEY \
MOCK_AGENT=0 \
uv run python -m db_extension.run_optimizer "SELECT ..."
```

### Alternative agents (install commands in image)

| Agent | Install (in Dockerfile) | Example `AGENT_CMD` | Typical env |
|-------|-------------------------|---------------------|-------------|
| **Cursor** (default) | `curl https://cursor.com/install \| bash` | `agent -p --force --model composer-2.5 "$(cat PROMPT.txt)"` | `CURSOR_API_KEY` |
| **agy** (Antigravity) | `curl -fsSL https://antigravity.google/cli/install.sh \| bash` | `agy -p "$(cat PROMPT.txt)"` | Google/Gemini auth |
| **Claude Code** | `curl -fsSL https://claude.ai/install.sh \| bash` | `claude -p "$(cat PROMPT.txt)"` | `ANTHROPIC_API_KEY` |
| **Codex** | `npm install -g @openai/codex` | `codex exec "$(cat PROMPT.txt)"` | `OPENAI_API_KEY` |
| **OpenCode** | `npm install -g opencode-ai` | `opencode run "$(cat PROMPT.txt)"` | provider keys |
| **Pi** | `npm install -g --ignore-scripts @earendil-works/pi-coding-agent` | `pi -p "$(cat PROMPT.txt)"` | provider keys |

## Mount layout

```
agent_workspace/          → /workspace/rw   (read-write)
  runquery_agent.dfy      ← agent edits this
  PROMPT.txt              ← host writes each iteration
  context/ro/             → /context/ro     (read-only in container)
    spec.dfy
    COMPILATION_GUIDE.md
```

Host repo (`postprocessor.py`, `harness.py`, etc.) is **not** mounted writable.

## Trust boundary

- Agent file is **untrusted** — only the body is used.
- Host injects `ensures res == MethodSpec(data)` via `assemble_runquery.py`.
- `admit_runquery` runs before verify (NativeAggMap linearity).

## Mock mode (no Docker)

```bash
MOCK_AGENT=1 uv run python -m db_extension.run_optimizer "SELECT ..."
```

Uses generated RunQuery and skips the agent container entirely.

## Licensing note

Bundling multiple agent CLIs in one image is for **user convenience**. You are responsible for accepting each vendor’s terms and supplying your own API keys. We do not redistribute model access.
