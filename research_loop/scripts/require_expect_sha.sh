# Source from a repo checkout. The caller types the commit.
# require_expect_sha <hash> prints the full HEAD sha, or exits 1.
require_expect_sha() {
  local want="${1:-}"
  if [[ -z "$want" ]]; then
    echo "ERROR: type the commit hash to run, e.g. --expect-sha $(git rev-parse --short HEAD)" >&2
    exit 1
  fi
  if [[ ${#want} -lt 7 ]]; then
    echo "ERROR: commit hash must be at least 7 characters (got '${want}')" >&2
    exit 1
  fi
  local resolved
  if ! resolved="$(git rev-parse --verify "${want}^{commit}" 2>/dev/null)"; then
    echo "ERROR: ${want} is not a commit in this repo" >&2
    exit 1
  fi
  local head
  head="$(git rev-parse HEAD)"
  if [[ "$resolved" != "$head" ]]; then
    echo "ERROR: typed commit ${resolved} is not HEAD ${head}" >&2
    exit 1
  fi
  printf '%s\n' "$resolved"
}
