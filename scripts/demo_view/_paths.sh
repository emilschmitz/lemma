# Shared paths for demo right-pane viewers. Source from other scripts:
#   source "$(dirname "$0")/_paths.sh"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VIEW_DIR="${LEMMA_DEMO_VIEW_DIR:-$ROOT/research_loop/demo_view/state}"
WORKSPACE="$ROOT/research_loop/agent_workspace"
BODY="$WORKSPACE/runquery_agent.dfy"
SPEC="$WORKSPACE/context/ro/spec.dfy"
RUST="$ROOT/research_loop/working_query-rust/src/working_query.rs"
AGENT_LOG="$VIEW_DIR/agent.log"
PIPE_LOG="$VIEW_DIR/pipeline.log"

mkdir -p "$VIEW_DIR"

# Truncate a view file so tail only shows content from this session onward.
# Set LEMMA_DEMO_VIEW_KEEP=1 to preserve prior contents.
fresh_view_file() {
  local path="$1"
  if [[ "${LEMMA_DEMO_VIEW_KEEP:-0}" != "0" ]]; then
    touch "$path" 2>/dev/null || true
    return
  fi
  mkdir -p "$(dirname "$path")"
  : >"$path"
}

demo_clear_screen() {
  if [[ -t 1 ]] && command -v clear >/dev/null 2>&1; then
    clear
  fi
}
