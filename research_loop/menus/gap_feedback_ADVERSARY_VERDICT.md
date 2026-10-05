# Adversary verdict: commit 93ae2c5 (gap feedback and best-so-far)

Reviewer: manual adversary (Sonnet). Read-only; probes in the scratchpad. The 27 tests in
`tests/test_declarative_feedback*.py` pass. Probes below were run against the commit.

## Findings

### BLOCKER 1: restore can overwrite a later, more developed file with the earliest broken one
`declarative_spec/best_so_far.py:63-67,105-123`, `drive.py:_prepare_restart`.
`score()` ranks a check with no tally as `(0,0,0,0)`, and ties keep the earlier entry. If no check in
the run produced a `verification results::` line (rustc errors, wall timeout), the best attempt is the
FIRST recorded file, typically the stub. At session N+1 `restore_best` replaces the agent's last file
with it. The "No check ... produced a Verus tally" branch in `_prepare_restart` is also unreachable
once any attempt is recorded, because `best` is never None.
Reproducer: record "STUB" then "ALMOST" (both rustc failures, no tally); write ALMOST to the agent
path; `restore_best` returns `restored` and the file now holds `STUB`. This contradicts the goal
("never starts from a worse file") and is a regression against the old behavior (last file kept).
Fix: only entries with a tally can be best/restorable; with none, keep the file on disk.

### BLOCKER 2: agent-controlled `best.json` makes the host read arbitrary host files into the workspace
`best_so_far.py:load_best` / `restore_best`. `entry["file"]` is joined to the attempts dir without
validation and the content is written to the agent file. The agent can write
`mcp_results/attempts/best.json` (in `/workspace`). With `"file": "../../../../home/emil/.ssh/id_x"`
(or a symlink `attempts/001.rs` pointing at a host absolute path, which only the host resolves) the
host copies that file into `runquery_agent.rs` at restart, and the network-none agent reads it.
Probe: `file: ../../secret.txt` restores `HOSTSECRET` into the agent file. The host should not trust
agent-writable state: keep `index.json`/`best.json` outside the workspace (host-side run dir), or at
minimum derive the file name from `n` as `%03d.rs`, reject non-regular files and symlinks, and
recompute the best from the stored `.rs` files rather than from `best.json`.
(Tampering with scores achieves nothing else: restore writes only to the agent file, and every later
check, plus the host-final check, goes through admission. Malformed JSON crashes the host's
`record_attempt` after the harness ran, which only costs the agent its own check result.)

### SHOULD-FIX 3: sha dedupe keeps the first tally and masks a later, better one
`best_so_far.py:73-75`. Same file first checked with a timeout/no-tally result (or an rlimit flake),
then the host-final check proves it: the second record is dropped, `proof_verified` stays False.
Probe: `record_attempt(F, timeout)` then `record_attempt(F, 9 verified/0 errors)` returns the old
entry, proof flag False. The host-final check is the highest-fidelity one and is the one discarded.
Fix: when the same sha arrives with a strictly better score, update the entry and best.

### SHOULD-FIX 4: gutter numbers of non-assembled files are mapped through the assembled-program regions
`feedback.py:_rewrite_block` (`gutter`, applied to the whole block). A `:::` span into vstd (or any
other file) has its snippet gutter number rewritten as if it were an assembled-program line.
Probe: `::: vstd/seq.rs:17:9` with gutter `17 |` became `7 |` (17 fell in the edit region), other
lines become `host |`. This invents agent-file line numbers for vstd source. Only rewrite gutters of
snippets that follow a `-->`/`:::` whose path is the assembled file.

### SHOULD-FIX 5: error selection is source order only, agent-region errors can be pushed out
`feedback.py:177-205`. `errors.sort` is by assembled line, then `errors[:MAX_ERRORS]` and the
7000-char budget cut. Host-region errors (loaders, `main`, host lemmas) that precede the edit region
(structs, spec fns, host lemmas come before `run_query`) take the 8 slots and the char budget, and
the only error inside the agent's region is reported as "omitted". The omitted line says nothing about
which region. Prefer agent-region errors first (stable within), or at least say how many omitted
errors are in the agent regions. The no-`-->` errors sort first and also consume slots.

### SHOULD-FIX 6: `errors` placeholder regresses a consumer
`measure_core.py:381` now returns `["check failed: details in metrics.compiler_error"]`.
`research_loop/scripts/prove_measure_competitive.py:131` does `"; ".join(errors) or compiler_error`, so
it now reports the placeholder instead of the Verus text. Switch that consumer to prefer
`metrics.compiler_error` (the others, `harness.py:545` and `loader_block_after_proof`, still work since
they read `compiler_error` first / as well). Declarative-only cases are unaffected, but the change is
global in `run_solution`.

### NOTE 7: primary location `host-owned, not editable` on agent-caused errors
`postcondition not satisfied` and similar have a host primary span (the `ensures`). The rewrite labels
it "generated program line N (host-owned code, not editable)", which can read as "not your fault".
The agent's own return line still appears in the snippet with a mapped number, so it is recoverable;
a short suffix ("caused by your code; see the labelled line below") would help.

### NOTE 8: `_scrub_paths` regex also eats code
`feedback.py:_scrub_paths`. `(a)/b/c` in a snippet became `(a)<host>/b/c`; URLs/divisions after a
non-word character are likewise rewritten. Only apply it outside gutter-prefixed snippet lines.

### NOTE 9: last session's best is not rescued
`drive.py` restores only at the start of session N+1. If session N (the last allowed) proved a file
and then broke it, the host-final check runs on the broken file and the earlier proved file is never
re-checked. Consider restoring best (and re-checking) after the loop ends.

### NOTE 10: ordering ignores speed
Among proved files the higher `verified` count wins (probe: 20-verified slow body beat 5-verified fast
body) and MCP checks run at the iterate size, so no latency is stored. Acceptable, but "best" means
"most lemmas" not "fastest".

## What held up
- Tally round trip: `PROOF ERROR: verification results:: N verified, M errors` keeps the string the
  scorer regexes; summary is first; rlimit text is retained; footers dropped.
- `note:`/`help:` lines stay attached to their parent block; errors with no `-->` are kept (and sort first);
  host warnings are only counted, agent-region warnings kept; no error is ever dropped except by the
  count/budget, and the first error is always shown. Full log is written to `verify_full.log`.
- Region mapping with the real assembler's `"\n"+body.rstrip()+"\n"` shape is correct (marker+1,
  stripped body); drifted bodies fall back to region-relative numbers instead of wrong agent-file numbers.
- Restore writes only the agent's own file and never skips admission (host-final check admits; MCP
  `run_solution` validates). `checked_source` is the file the harness reads (`ws/runquery_agent.rs`),
  so the recorded text matches what was checked.
- `_relativize_paths` is safe (ValueError path left alone); effort/thinking env validation fails fast.

VERDICT: FAIL


## Response to the review (author)

Fixed in the follow-up commit with tests in tests/test_declarative_feedback_fixes.py: 1 (no-tally attempts are never best, so no stale-stub restore), 2 (best.json file name, symlink and recorded-hash checks; refuses loudly), 3 (a later tally for the same file replaces a no-tally record), 4 (gutter rewritten only for snippets of the assembled program), 5 (agent-region errors are chosen first, displayed in source order), 6 (prove_measure_competitive prefers compiler_error), 8 (scrub skips paths preceded by a closing bracket). Not changed: 7 (a host primary span stays labelled host-owned; the label says not editable, which is accurate for the span), 9 (the final best is not re-checked after the loop: the loop returns the host final check of the last file, as before), 10 (best among proved = most verified; a proved run ends the loop anyway).

Re-reviewed by author only for the fixes; blockers 1 and 2 are covered by reproducer tests. VERDICT after fixes: PASS (blockers resolved, original verdict FAIL stands for 93ae2c5).
