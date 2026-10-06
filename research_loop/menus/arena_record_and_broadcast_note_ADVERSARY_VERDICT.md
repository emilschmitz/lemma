# Adversary verdict: arena_record.py (20356fb) and the broadcast-note (c4eda50)

Tests: `uv run pytest tests/test_arena_record.py tests/test_declarative_verus_docs.py -q` -> 9 passed.
Regenerating the real index (10 rows) reproduces `results_container.jsonl` byte-for-byte (diff = 0 lines), so rows are regenerable.
Pairing check on the real index: for all 7 logged rows, RESULT.run_dir == index run_dir, RESULT.database == manifest.duckdb_path, RESULT.model == manifest.agent_model. No wrong pairing today.

## Verdict: PASS WITH FINDINGS

## (A) arena_record.py

F1 (medium) stale `error` contradicts `status` on multi-session runs. Real repro: r1_q05 row has status=SUCCESS, submitted=True, kernel_us=140554, but error="agent timed out (AGENT_TIMEOUT_SEC): exit -9.  No submit." The launcher RESULT line carries the first session's error next to the final status; the row copies it verbatim (first 300 chars) and emits no note. wall_s 1196 s also spans two sessions and `checks`=27 spans both; nothing says the run had several sessions. Fix: derive session count (agent_stream/attempts/meta) or note "RESULT error is from an earlier session" when status==SUCCESS and error is non-empty.

F2 (medium) pairing is by hand and unchecked. Cheap check, all three fields exist in RESULT: `RESULT.run_dir == str(run_dir)`, `RESULT.database == manifest.duckdb_path`, `RESULT.model == manifest.agent_model`; raise on mismatch (fail fast). Also reject duplicate (query, attempt) in the index and a duplicated run_dir with differing queries. Today a copy-paste error in the index (e.g. q02 log with a q03 run_dir) would produce a plausible row. Also the SQL in RESULT could be compared with the query id's SQL file.

F3 (medium) `infra` is the one hand-typed field that changes accounting (`counts = not infra`). Nothing checks it against the run dir: an index entry marking a run with checks>0 / proved=True as infra silently drops a real attempt. Add: infra with checks>0 or submitted -> error (or note).

F4 (low-medium) `_result_line` returns the FIRST `RESULT ` line. If a log is appended to or reused (same `sonnet_qNN.log` name exists in old_r1/ and r1_pass1/), a stale first RESULT wins. Use the last, or require exactly one and fail otherwise. Also `RESULT.run_dir` mismatch (F2) would catch it.

F5 (low-medium) CLI bug: `if not (a.run_dir and a.query and a.attempt)` rejects `--attempt 0`, but the index itself uses attempt 0 for the infra rows. Repro: `arena_record.py <run_dir> --query x --attempt 0` -> "need RUN_DIR --query --attempt". Use `a.attempt is None`.

F6 (low) `rows_match` inference. True whenever submitted or kernel_us or below-bar message; False if ANY in-session run text contained "result rows differ" even if a later run/the final body passed and the run then failed for another reason (timeout, speed). Not named as a heuristic in the docstring. For a run with no proved run (q04, q06) rows_match is None with no note, although the note rule says underivable fields are named. kernel_us is taken from RESULT.latency_us whenever >0 even if status FAILED.

F7 (low) `verified_line` for non-proved runs: max(verified - 1000*errors) across ALL sessions' runs, so "34 verified, 1 errors" (q04) can come from a different, smaller program than the final one; it is documented as a heuristic but not tagged per row. `proved` means "some in-session run verified", `submitted` means the marker exists: semantics are right and distinct (r1_q01 att 1: proved=True, submitted=False, status FAILED is correct), but a reader of `proved` alone cannot tell it is any-session.

F8 (low) sha is `git_sha[:7]` (fixed truncation; fine). `causes.json`: a cause can never override a derived field (only the `cause` key is set); stale/unmatched keys and missing causes are silent. `attempt` and `query` are index-typed and not checked against the run (no query id in the manifest? then F2's SQL check is the only way). Absolute worktree paths in the index make regeneration depend on that worktree existing.

F9 (low) tests: test 1 is real (asserts `notes == []` and many derived fields); test 2 covers None/notes/cause/infra; test 3 covers the speed-bar parse. Missing: multi-session RESULT (F1), RESULT/run_dir mismatch (F2), attempt 0 (F5), a log with two RESULT lines (F4), infra with a proved run (F3). Test 2 reuses one run dir for two index rows, so it does not exercise pairing.

## (B) broadcast note (c4eda50)

No blocking issues. Ran `lemmas_markdown` on the real vstd source: 56 entries noted, 0 missed zero-arg broadcast fns, and none of the vstd signatures has nested generics. The note appears in the entry the agent greps (`lemma_set_empty_len` has `- note:` right after `sig`, within `grep -A5/-A6` of the name). The prompt (declarative_spec/prompt.py:863-867) already says only `broadcast use ...group_<name>` is allowed and "axiom is already broadcast: do not name it", so the note is consistent with it. The Verus error text quoted is the one observed in two real runs; a zero-arg broadcast fn has no quantifier to instantiate, so it takes effect only via `broadcast use` of a group: claim correct.

Regex `_NO_VALUE_PARAMS = fn\s+\w+\s*(?:<[^>]*>)?\s*\(\s*\)`:
- B1 (low, false negative) nested generics: `fn f<A: Foo<B>>()` does NOT match (`[^>]*` stops at the first `>`). Verified in Python. Absent in current vstd, would silently miss in a later vstd pin. `_strip_generics` already exists in the module; use it on the signature first.
- B2 (low, false positive) `search` is unanchored: a signature like `fn k(s: Seq<int>, f: spec_fn() -> bool)` is not matched (checked), but `fn z<T>() ...` followed by a where clause is correctly matched. Params containing `fn()` after a first param do not match because `\(\s*\)` must follow the name. OK.
- B3 (low) 7+ noted entries are macro templates (`<$($T,)+>` / `$U`) that are not real names; the note is harmless but noisy, and the 'impl-owner' duplicates (lemma_obeys_eq_spec x3) get the note correctly.
- B4 (low) kind gate uses `"broadcast" in line` (first line of the item only): `pub broadcast\nproof fn` split across lines or an attribute on the same line is missed; not present in vstd.
- Non-broadcast zero-arg lemma (`pub proof fn lemma_plain_unit<A>()`) correctly NOT noted and is callable. Multi-line signatures work because `_signature_and_clauses` joins the signature lines.

Agent-steering risk (B5, low): "prove it yourself with an `assert` or a lemma of your own" can push toward `assume`/`#[verifier::external_body]` in a struggling agent; the note does not forbid them. Suggest appending "(never assume or an axiom)". The cheaper steer is also to name the already-listed group (e.g. group_set_axioms for lemma_set_empty_len) when the fn is a member of a group: the index has that group list, and the note could say "it is in group_X; `broadcast use` it". Currently the note leaves the agent to find the group.

## Author response
F1 fixed (a SUCCESS row has no error; sessions counted from agent_stream.jsonl; notes say wall_s/checks/proved span sessions). F2 fixed (RESULT.run_dir, database, model must match the manifest; duplicate (query, attempt), a run dir for two queries, a log used twice are errors). F3 fixed (infra with any run_runquery call, a submit or a proof is refused; a 401 in claude_raw and absent tool calls are recorded as derived evidence; an index-only reason is noted). F4 fixed (the LAST RESULT line; the run_dir check catches a same-named log from another run; the two same-named logs in different folders are legitimate, they are told apart by RESULT.run_dir). F5 fixed (`attempt is None`). F6 fixed (kernel_us only for SUCCESS, else only from the host's below-the-bar message with `kernel_basis` marking it; rows_match False only when the FINAL result says rows differ, otherwise None with the reason in notes). F7 `proved_scope` added; `verified_line` now prefers fewest errors, stated in the docstring. F8/F9 accepted; tests added for F1-F7 and the compare table. B1 fixed (generics stripped before the regex), B5 fixed (the note says never assume or an axiom and names the allowed group, or says none exists). B2-B4 accepted (absent in vstd).
