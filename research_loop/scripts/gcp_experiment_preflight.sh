#!/usr/bin/env bash
# GCP Spot experiment preflight: clean local git, pushed HEAD, flag card, optional remote sync.
# Usage (from repo root):
#   LEMMA_FAMILY=r23rocket bash research_loop/scripts/gcp_experiment_preflight.sh --expect-sha <commit>
#   LEMMA_PREFLIGHT_SSH=1 LEMMA_FAMILY=r23rocket bash research_loop/scripts/gcp_experiment_preflight.sh --expect-sha <commit>
# --expect-sha is required. The hash must be this checkout's HEAD.
set -euo pipefail

LEMMA_FAMILY="${LEMMA_FAMILY:-}"
LEMMA_REMOTE_HOST="${LEMMA_REMOTE_HOST:-lemma-gendb-overnight}"
LEMMA_GCP_ZONE="${LEMMA_GCP_ZONE:-us-east1-b}"
LEMMA_REMOTE_REPO="${LEMMA_REMOTE_REPO:-/home/emil/lemma-r15}"
LEMMA_PREFLIGHT_SSH="${LEMMA_PREFLIGHT_SSH:-0}"

EMIT="${LEMMA_EMIT_AGENT_PRIMITIVES:-0}"
FAST="${LEMMA_FAST_TRUSTEDS:-0}"
VECTOR="${LEMMA_ENABLE_VECTOR_SCAN:-0}"
SPILL="${LEMMA_ENABLE_SPILL_HASH:-0}"

err() {
  echo "ERROR: $*" >&2
}

# Source next to this script. Tests run the script with cwd set to a fake
# checkout, so a path relative to cwd cannot see require_expect_sha.sh.
_PREFLIGHT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=research_loop/scripts/require_expect_sha.sh
source "$_PREFLIGHT_DIR/require_expect_sha.sh"

cd "$(git rev-parse --show-toplevel)"
EXPECT_SHA=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expect-sha)
      EXPECT_SHA="${2:?--expect-sha needs the commit hash you mean to run}"
      shift 2
      ;;
    *)
      err "unknown argument '$1' (use --expect-sha <commit>)"
      exit 1
      ;;
  esac
done
LOCAL_SHA="$(require_expect_sha "$EXPECT_SHA")"

if [[ -n "${LEMMA_EXPERIMENT_ALLOW_DIRTY:-}" ]]; then
  err "LEMMA_EXPERIMENT_ALLOW_DIRTY is set; experiments require a clean worktree (unset it)."
  exit 1
fi

PORCELAIN="$(git status --porcelain)"
if [[ -n "$PORCELAIN" ]]; then
  err "local git worktree is dirty; commit or stash first."
  echo "$PORCELAIN" >&2
  exit 1
fi

ON_ORIGIN=0
for ref in origin/HEAD origin/main; do
  if git rev-parse --verify "$ref" >/dev/null 2>&1; then
    if git merge-base --is-ancestor HEAD "$ref" 2>/dev/null; then
      ON_ORIGIN=1
      break
    fi
  fi
done
if [[ "$ON_ORIGIN" -eq 0 ]]; then
  err "local HEAD ($LOCAL_SHA) is not an ancestor of origin/HEAD or origin/main; push first."
  exit 1
fi

LOCK="${LEMMA_OVERNIGHT_LOCK_FILE:-}"
if [[ -n "$LOCK" && -f "$LOCK" ]]; then
  pid=$(tr -d ' \n' < "$LOCK" || true)
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    err "another overnight is running (pid $pid lock $LOCK); one family at a time"
    exit 1
  fi
fi

family_lc="$(printf '%s' "$LEMMA_FAMILY" | tr '[:upper:]' '[:lower:]')"
card=""
if [[ "$family_lc" == *rocket* ]]; then
  card="rocket"
  if [[ "$EMIT" != "0" || "$FAST" != "0" ]]; then
    err "family $LEMMA_FAMILY (rocket) requires LEMMA_EMIT_AGENT_PRIMITIVES=0 and LEMMA_FAST_TRUSTEDS=0 (got EMIT=$EMIT FAST=$FAST)."
    exit 1
  fi
elif [[ "$family_lc" == *mid* ]]; then
  card="mid"
  if [[ "$FAST" != "1" ]]; then
    err "family $LEMMA_FAMILY (mid) requires LEMMA_FAST_TRUSTEDS=1 (got FAST=$FAST)."
    exit 1
  fi
  if [[ "$EMIT" != "0" ]]; then
    err "family $LEMMA_FAMILY (mid) requires LEMMA_EMIT_AGENT_PRIMITIVES=0 (got EMIT=$EMIT)."
    exit 1
  fi
  if [[ "$VECTOR" != "1" ]]; then
    err "family $LEMMA_FAMILY (mid) requires LEMMA_ENABLE_VECTOR_SCAN=1 (got VECTOR=$VECTOR)."
    exit 1
  fi
  if [[ "$SPILL" != "1" ]]; then
    err "family $LEMMA_FAMILY (mid) requires LEMMA_ENABLE_SPILL_HASH=1 (got SPILL=$SPILL)."
    exit 1
  fi
elif [[ "$family_lc" == *fast* ]]; then
  card="fast"
  if [[ "$FAST" != "1" ]]; then
    err "family $LEMMA_FAMILY (fast) requires LEMMA_FAST_TRUSTEDS=1 (got FAST=$FAST)."
    exit 1
  fi
elif [[ "$family_lc" == *sloppy* ]]; then
  card="sloppy/emit"
  if [[ "$EMIT" != "1" || "$FAST" != "0" ]]; then
    err "family $LEMMA_FAMILY (sloppy/emit) requires LEMMA_EMIT_AGENT_PRIMITIVES=1 and LEMMA_FAST_TRUSTEDS=0 (got EMIT=$EMIT FAST=$FAST)."
    exit 1
  fi
else
  err "unknown LEMMA_FAMILY=$LEMMA_FAMILY; expected rocket, fast, mid, or sloppy in the name."
  exit 1
fi

WAIT="${LEMMA_WAIT_FOR_WRAPPER:-1}"
if [[ "$WAIT" != "1" ]]; then
  err "LEMMA_WAIT_FOR_WRAPPER=$WAIT; experiments must wait for run_and_halt (r23 overlapped families when this was 0)."
  exit 1
fi
# Multi-family Spot chains: set LEMMA_HALT_ON_FINISH=0 on non-final families so only
# the last family's run_and_halt.sh stops the VM (see overnight_lemma.sh).

echo "preflight OK: family=$LEMMA_FAMILY card=$card EMIT=$EMIT FAST=$FAST VECTOR=$VECTOR SPILL=$SPILL WAIT=$WAIT sha=$LOCAL_SHA"
echo "  rocket     -> EMIT=0 FAST=0"
echo "  fast       -> FAST_TRUSTEDS=1"
echo "  mid        -> FAST=1 EMIT=0 VECTOR=1 SPILL=1"
echo "  sloppy/emit -> EMIT=1 FAST=0"

if [[ "$LEMMA_PREFLIGHT_SSH" != "1" ]]; then
  echo "preflight: skipping SSH (set LEMMA_PREFLIGHT_SSH=1 to verify remote $LEMMA_REMOTE_HOST)"
  exit 0
fi

SSH_CMD=(gcloud compute ssh "$LEMMA_REMOTE_HOST" --zone "$LEMMA_GCP_ZONE" --command)
REMOTE_SCRIPT=$(cat <<EOS
set -euo pipefail
cd '$LEMMA_REMOTE_REPO'
git fetch --quiet origin
REMOTE_SHA=\$(git rev-parse HEAD)
echo "remote_sha=\$REMOTE_SHA"
if [[ "\$REMOTE_SHA" != "$LOCAL_SHA" ]]; then
  echo "ERROR: remote HEAD (\$REMOTE_SHA) != local ($LOCAL_SHA); git pull on box." >&2
  exit 1
fi
P=\$(git status --porcelain)
if [[ -n "\$P" ]]; then
  echo "ERROR: remote worktree dirty:" >&2
  echo "\$P" >&2
  exit 1
fi
HALT_PATH='research_loop/scripts/lemma_guest_halt.sh'
if [[ ! -f "\$HALT_PATH" ]]; then
  echo "ERROR: missing \$HALT_PATH on remote." >&2
  exit 1
fi
if head -n 1 "\$HALT_PATH" | grep -q 'wrapper'; then
  echo "ERROR: \$HALT_PATH looks like a wrapper (patched in place)." >&2
  exit 1
fi
git show "HEAD:\$HALT_PATH" > /tmp/lemma_halt_expected.$$
if ! cmp -s "\$HALT_PATH" /tmp/lemma_halt_expected.$$; then
  echo "ERROR: \$HALT_PATH differs from git show HEAD:\$HALT_PATH (patched in place?)." >&2
  diff -u /tmp/lemma_halt_expected.$$ "\$HALT_PATH" >&2 || true
  rm -f /tmp/lemma_halt_expected.$$
  exit 1
fi
rm -f /tmp/lemma_halt_expected.$$
echo "remote preflight OK sha=\$REMOTE_SHA"
EOS
)

if ! "${SSH_CMD[@]}" "$REMOTE_SCRIPT"; then
  err "remote preflight failed on $LEMMA_REMOTE_HOST (zone $LEMMA_GCP_ZONE repo $LEMMA_REMOTE_REPO)."
  exit 1
fi

echo "preflight: remote $LEMMA_REMOTE_HOST verified."
