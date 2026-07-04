# Demo right-pane viewers (tmux split)

Use with **tmux split** or two terminals. Left = DuckDB / `lemma()`. Right = one of these scripts.

## Quick tmux layout

```bash
tmux new-session -s lemma-demo
# split vertically (right pane)
tmux split-window -h -t lemma-demo:0

# Right pane — pick ONE:
tmux send-keys -t lemma-demo:0.1 "./scripts/demo_view/follow-runquery.sh" C-m

# Left pane — live demo or mock
tmux send-keys -t lemma-demo:0.0 "./scripts/demo.sh" C-m
# tmux send-keys -t lemma-demo:0.0 "./scripts/mockdemo.sh" C-m

tmux attach -t lemma-demo
```

Or manually: split (`Ctrl-b %`), cd to repo, run a script in the right pane.

## Scripts

| Script | Right pane shows | Best when |
|--------|------------------|-----------|
| **`follow-runquery.sh`** | `runquery_agent.dfy` streaming | **Default.** Agent writing RunQuery (real agent) |
| **`follow-agent-log.sh`** | Agent CLI output (`agent.log`) | Token-ish stream from Cursor/agent stdout |
| **`follow-spec.sh`** | `spec.dfy` (MethodSpec) | After workspace prep / transpile |
| **`follow-rust.sh`** | `working_query.rs` | After Dafny→Rust + postprocess |
| **`follow-events.sh`** | Timestamps of file changes | Overview / debugging |
| **`follow-pipeline-log.sh`** | `[INFO] optimizer …` lines | Compile/verify detail |
| **`watch-runquery.sh`** | Full file refresh ~5 Hz | Fallback if `tail -F` looks jumpy |

## Real agent + token stream

`./scripts/demo.sh` sets `MOCK_AGENT=0` (live agent; streams to `agent.log`). Mock replay:

```bash
./scripts/mockdemo.sh
```

Manual env (if not using the script):

```bash
export MOCK_AGENT=0
export USE_AGENT_DOCKER=0          # local agent; streams to agent.log
export LEMMA_DEMO_VIEW_DIR="$PWD/research_loop/demo_view/state"
export LEMMA_DEMO=1
export LEMMA_DATASET_SIZE=100000
export AGENT_CMD='agent -p --force --model composer-2.5 "$(cat PROMPT.txt)"'
```

Right pane:

```bash
./scripts/demo_view/follow-agent-log.sh   # CLI output
# or
./scripts/demo_view/follow-runquery.sh    # file as agent saves
```

**Note:** Agents often edit the file in bursts (save chunks), not char-by-char. `tail -F` on `runquery_agent.dfy` is usually the smoothest “code appearing” effect.

## Mock demo (`mockdemo.sh`)

- **`follow-runquery.sh`**: one quick jump when mock seeds body
- **`follow-rust.sh`**: updates after harness codegen
- **`follow-events.sh`**: shows verify/compile file touches

## Pipeline log pane

```bash
export LEMMA_LOG_LEVEL=INFO
./scripts/demo_view/follow-pipeline-log.sh
```

In another terminal, run optimizer with `2>>research_loop/demo_view/state/pipeline.log`.
