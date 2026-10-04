# adversary_declarative0 holes and transpiler issues log

Protocol: `research_loop/menus/TRUSTED_ADDITION_PROTOCOL.md`. Each round runs ONE manual adversary (Sonnet subagent,
label "manual adversary, Sonnet subagent"; a real model adversary needs credentials:
`uv run python -m research_loop.adversary.run --config adversary_declarative0 --spec-style declarative`). It writes at
least 10 candidates in the shapes of that round's queries and judges each with
`uv run python -m research_loop.adversary.run --config adversary_declarative0 --spec-style declarative --candidate F.json`
(`research_loop/adversary/judge_declarative.py`). A hole = Verus accepts a body against the emitted spec AND the run
differs from DuckDB in a way SQL defines. Holes and transpiler issues go to the transpiler agent (addcd33571290f391) with
SQL, spec excerpt and both outputs; each is pinned as a fixture or test.

Data caveat on every line: the SEC data in this repo is SYNTHETIC (`synth_tiny.py`), not real EDGAR.

Trusted statements added by this loop: none. (Any result that depends on a trusted statement is marked as such.)

| Round | Candidate | Status | Finding | Sent to transpiler agent | Pinned as |
|---|---|---|---|---|---|
