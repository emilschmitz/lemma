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


## Re-review of 9e5b4d8 (diff 93ae2c5..9e5b4d8; manual adversary, Sonnet)

Scope: the fixes only. Read-only; probes in the session scratchpad; `uv run pytest tests/test_declarative_feedback*.py -q` gives 37 passed.

### No BLOCKERs, no MAJORs.

### SHOULD-FIX 1: a raise in `load_best` kills the whole drive run and discards its history
`declarative_spec/drive.py:278` calls `_prepare_restart` (-> `restore_best` -> `best_so_far.py:load_best`) outside any
try/except, and `db_extension/optimizer.py:735` does not catch either. A `ValueError`/`KeyError`/`JSONDecodeError`
from `load_best` therefore escapes `run_declarative_optimization_loop`: the `history` list, the prior iterations' results
and the "FAILED" dict are all lost; the caller sees a raw traceback. Loud is the intent, and that holds, but the run
is lost rather than reported as a failed iteration.
Reproducers (all in a fresh workspace; `record_attempt` then):
- delete `attempts/index.json`, then `record_attempt` another file: `n` restarts at 1, overwrites `001.rs`, `best.json`
  still names `001.rs` with the old sha, so the next `load_best` raises "does not match its recorded hash".
- write `{}` to `best.json`: `load_best` raises a bare `KeyError: 'file'` (line 123); write `{` to it: `JSONDecodeError`,
  and even `record_attempt` (via `_maybe_best` -> `load_best_entry`, line 112) raises inside the MCP `run_runquery` path
  (`measure_core.py:362`), turning an agent-writable file into an MCP-tool failure.
An agent that can write the workspace can use this to abort its own run; this is not an escalation, but the cheapest
sensible handling is to catch in `_prepare_restart`, record `iter_record["error"]`, and fall through with the agent's file
untouched (or end the family `FAILED` with the history intact).

### NOTE 1: validation is consistency, not authenticity (forgery passes)
`best_so_far.py:121-130`. Overwrite `001.rs` with new text and set `best.json["sha"]` to its hash: `load_best` returns
the forged text and `restore_best` writes it to the agent path (probe printed `EVIL`). Same for tampering `index.json`.
The checks stop accidental drift, a symlink, and path traversal in `file`, which is all they can do when the
workspace is the agent's. No escalation: the restored text only replaces the agent's own file and still goes through
host admission and the host region rebuild. Do not read the hash check as a security boundary; the comment says
"tampered?" and could say "inconsistent".
Smaller points that held up: `file` must `fullmatch(\d{3,}\.rs)` (no `/`, `..`, trailing newline); `is_symlink()` plus
`is_file()` is checked before the read; a symlinked `attempts/` directory itself is not checked (agent-controlled, the
hash still has to match, so the only gain is the forgery above); the check-then-read TOCTOU window only allows the same
forgery. `\d` matches non-ASCII digits (`٠٠١.rs` passes the regex), harmless because it is still one plain filename.

### NOTE 2: hash is over text, read back through universal-newline decoding (latent)
`best_so_far.py:63-98,126-128`. `record_attempt` hashes `source` as given and writes it, `load_best` hashes
`read_text()`, which turns `\r\n`/`\r` into `\n`. Reproducer: `record_attempt(ws, "a\r\nb\r\n", ...)` then `load_best`
raises "does not match its recorded hash". Not reachable today: both callers pass text that came out of
`read_text` (`drive.py:~290`, `measure_core.py:321`), so it is already normalised. A future caller that passes raw
bytes-decoded text would crash the restore path (see SHOULD-FIX 1). Hash the normalised text or read with `newline=""`.

### NOTE 3: ordering and tally upgrade (held up; two small remarks)
Probed `(has_tally, proved, -errors, verified)`:
- a proved file followed by a no-tally recheck of the same sha leaves best at `[1,1,0,9]`; a different no-tally file never
  becomes best; an errors-only tally never displaces a proved one; a tallied file that follows an earlier no-tally
  record of the same sha is upgraded in `index.json` and enters `best.json` only if strictly better (checked both
  orders). Restore can therefore not overwrite a better body with a worse one, and cannot lose a proved body.
- `proof_verified=True` without a tally line (not produced by the current pipeline: SUCCESS always carries
  `verify_summary`) is unranked and never best; fine.
- remaining case where the agent's file stays non-compiling: no tallied attempt exists at all (all checks were
  rustc/timeout/admission). Then there is nothing better to restore and "none" is returned; correct, and the restart note
  says so.
- same-sha with an existing tally keeps the first tally even if a later run of the identical file proves (flaky
  rlimit); the loop ends on a proved host-final check anyway, so no effect. A tie between equal-score files keeps the
  earlier one (strict `>`).

### SHOULD-FIX 2: a `help:`/`note:` snippet after a vstd `:::` span is left unrewritten
`feedback.py:153-165`. The gutter state is "the span named by the last `-->`/`:::` line"; sub-diagnostics such as
`help:` suggestions print snippets of the primary file without a new `-->`. Reproducer (probe p2, case 1): primary
`--> declarative_query.rs:23:1`, then `::: vstd/seq.rs:17:5`, then `help: try` with `23 | res2`. Output keeps `23  | res2`
(host line number) while the same block's first snippet shows `4  | res`: the agent sees two different numbers for
the same line and the 23 reads as a line of its own file. Wrong in the safe direction less often than the old code,
but it is a mis-attribution the state machine introduces. Fix: reset `current_is_assembled` to the primary file at a
line matching `^(help|note|warning|error)` (non-indented sub-diagnostic head).

### NOTE 4: location lines with a space in the path are skipped
`feedback.py:35` (`_LOC` uses `\S+?`). For a run directory containing a space (probe p2, case 2) `-->` is not matched,
so it is printed with the host path, but the following snippet gutter is rewritten (`4  | res`): half rewritten and
a host path leak (`_scrub_paths` also stops at the space). Workspace paths are generated by the host and have no
spaces today; mention only.

### NOTE 5: the omission line misdescribes the selection
`feedback.py:~259`. With the new agent-first choice the footer still says "showing the first N of M, in source order"
(probe p2, case 3: "showing the first 4 of 9"; with 11 host errors and one agent error it would claim the first 8). The
displayed set is "agent-region errors first, then host errors up to the caps, displayed in source order". The agent
may infer that errors beyond the cap are all later in the file. Change the wording.

### NOTE 6: error selection, what held up and the residual
- An agent-region (primary span) error is always shown: it sorts first into `chosen`, and the first block is exempt
  from the budget check (`if chosen and ...`). Probe: 9 agent errors of 3000 chars each show 4 (budget 7000) with the
  omitted count; 11 host errors plus one location-less error show the location-less one first, then 7 host ones. Agent
  errors alone beyond `MAX_ERRORS` or `TOTAL_CHARS` hide only the later agent errors, never all of them.
- `size = min(len(block.text), BLOCK_CHARS)` is computed before `_scrub_paths`, which can only change the length by a few
  characters per path; overshoot of `TOTAL_CHARS` is bounded by that, not a defect.
- The budget loop `break`s at the first block that does not fit instead of `continue`, so one large host block can
  keep a later small host block out. Cosmetic.
- Residual: classification is by the primary `-->` alone. An error whose primary span is host code but whose cause is
  the agent (the old NOTE 7 class) counts as host, so with >= 8 agent-primary errors it is hidden. A rare overlap; the
  location-less and host-primary errors are otherwise kept in order after the agent ones.
- The `_scrub_paths` lookbehind `(?<![\w.)\]])` now skips a path directly after `)` or `]`; a leak is possible only
  for text like `...)/home/x/y` and nothing in rustc/Verus output is shaped that way.

### NOTE 7: gutter state machine, what held up
`feedback.py:153-165`. A snippet line is only rewritten by the anchored `^\s*\d+\s*\|` pattern at the start of a line, after
the `_LOC` check for that line, so: a code line that contains `|` or `-->` is always behind its own gutter
prefix and is never read as a location; a message line cannot start with `-->`/`:::` plus a path:line:col unless
rustc printed it; `...` elision lines and `   |` continuation lines pass untouched; a `:::` to a non-assembled
file switches the state off and a later `-->` switches it on. Only the help/note case above is wrong, plus the initial
default (`True`) applies to any snippet that precedes the first location line (none seen in rustc/Verus output).

### What held up (summary)
Tie/upgrade logic, no-tally attempts never best, symlink/file-name/hash checks stop drift and path tricks, the new
`prove_measure_competitive.py` ordering (compiler_error first) is a one-line message-priority change with no
behaviour risk, the tests in `tests/test_declarative_feedback_fixes.py` pass and the original blockers 1 and 2 are closed
(a no-tally stub can no longer be restored; a tampered file refuses loudly).

VERDICT (9e5b4d8): PASS
