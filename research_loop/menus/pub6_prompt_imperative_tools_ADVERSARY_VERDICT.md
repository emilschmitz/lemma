# Adversary verdict: prompt imperative + tools statement (ce1acdb)

Verdict: SOUND AFTER FIXES (one stale test fixed; two accuracy caveats recorded, no obligation change).

## (a) Proof obligations / pressure to cheat
- The text changes no obligation: no new permitted edit, no mention of assume/external_body/trusted. Admission (drive.py -> admit) is untouched and still rejects placeholder/trusted bodies.
- "Do not stop until verified" adds pressure, but the escape is explicit and honest ("say plainly why in your last message") and the same sentence calls an empty/placeholder body a failure. It does not tell the agent to weaken the spec. No conflict with AGENTS.md "Never leave an implementation unproved" (it reinforces it) or "Pipeline contract" (agent edits run_query only; prompt line ~622 still names AGENT_EDIT bounds).
- Residual risk (low, inherent): any "must succeed" text can tempt a model to submit something admission then rejects; that costs an iteration, not soundness.

## (b) Bypass and claim accuracy
- Bypass: nothing the text says opens a path. Bash was already in `_CLAUDE_TOOLS`; the text only says it is useless for Verus. Official verify/submit is host-side via the MCP socket; Bash cannot produce a submitted.json.
- "Verus is not on its PATH": TRUE (docker/agent/Dockerfile and entrypoint install no verus; PATH only adds /root/.local/bin, /root/.cursor/bin).
- "Bash has no network": MOSTLY true. Container is `--network none`; the only egress is a unix-socket allowlist proxy (HTTP(S)_PROXY=127.0.0.1:8118) limited to the vendor API profile (anthropic for claude). So npm/pip/GitHub are denied; the model API host is reachable. Wording "no network" is a harmless simplification; "no network beyond the model API" would be exact. Not changed (tests pin the phrase).
- MCP names `mcp__lemma-host__run_runquery` / `submit_runquery`: TRUE per tests/fixtures/claude_stream_real_mock.jsonl tools list (also validate_runquery etc. exist).
- ToolSearch: that fixture's tool list does NOT contain ToolSearch and has the MCP tools loaded directly, so the "if not in your tool list yet" conditional is the right framing for Claude Code (harmless if never needed). For the Cursor `agent` CLI backend (default egress profile "cursor", same prompt builder) the claim is FALSE: no ToolSearch, and MCP tools are named `lemma-host` / `run_runquery`, not `mcp__lemma-host__*`. The prompt is backend-blind, so a Cursor run gets a wrong tool name and a nonexistent tool. Harmless for the Claude pub6 path; if the Cursor backend is used for declarative runs, make the sentence backend-conditional (follow-up, not done: needs a backend arg through drive.py).

## (c) Placement / conflicts
- Imperative is the last section, after "## Previous host error" on retries (tests assert order and that it ends with "not a result."). No conflict with the retry prompt: it says fix and continue. Only conflict-ish: the "Done means ... beats the reference engine" bullet is stricter than "N verified, 0 errors + submit"; the imperative's stop condition is the weaker one. Acceptable.
- Merge risk: the other agent edits the do-list / worked examples in the same file. The tools bullet (~line 610) and the appended `sections.extend` at the end (~687) are the touched hunks; likely conflicts only if that agent edits the same bullets or the tail of build_declarative_prompt. Also prompt length is asserted `< 450` lines in test_declarative_prompt.py; both edits add lines.

## (d) Tests
- Found a real failure: tests/test_declarative_prompt.py::test_prompt_is_ordered_and_has_no_duplicate_sections still asserted the removed sentence "You cannot run Verus". Fixed it to assert "Verus is not on its PATH". After fix: `uv run pytest tests/test_pub6_host.py tests/test_declarative_audit.py tests/test_declarative_prompt.py -q` all pass (19 skipped, as before).
