# Lemma

Verified query synthesis. Give it a SQL query and a database; an AI agent writes a native Rust
`run_query`, **Verus proves it computes exactly what the SQL says**, and the proved program is compiled
and timed against DuckDB. Inspired by [GenDB](https://arxiv.org/pdf/2603.02081), with a proof in place of
tests.

https://github.com/user-attachments/assets/7f7891c7-5ef6-406b-882b-8e01134ed37c

## How it works

```
SQL + catalog -> spec (transpiler) -> agent writes run_query -> Verus proves it meets the spec
              -> assemble -> compile -> run against DuckDB's data, timed vs DuckDB
```

- **Spec.** The transpiler turns the SQL into a Verus specification. It is the ground truth. It must be
  a real specification, never `arbitrary()` or a vacuous trusted stub. If a query cannot get a real
  spec, transpiling fails loudly.
- **Agent.** It edits only the marked `run_query` body (and proof helpers). It cannot add `assume`,
  `external_body` or other trusted code. The host rejects those and reassembles the file itself.
- **Proof.** Verus checks the body against the spec. A proof error is a proof error, not a timeout.
- **Execution.** The proved binary reads real columns and its output rows are checked against DuckDB.

Two spec styles share one pipeline, container and agent (`LEMMA_SPEC_STYLE`, default `declarative`):

| Style | Spec | Where |
|---|---|---|
| `declarative` (default) | `ensures` states what the result must satisfy | `declarative_spec/` |
| `imperative` | a recursive fold the body must match | `verus_transpiler/` |

The declarative path covers joins, group-by, HAVING, subqueries, NULLs (validity vectors),
dictionary-encoded strings, DECIMAL/DATE, float aggregates (as exact reals; rounding is an accepted
error), ratios, and a parallel path built on vstd threads.

## Trust

What is trusted is listed in [docs/TRUSTED_FAMILIES.md](docs/TRUSTED_FAMILIES.md): the host's fixed
helper bridges, the float idealization (a small fixed set of lemmas) and one IEEE division lemma. Adding any new
trusted item needs a written proposal and a separate adversary review
([protocol](research_loop/menus/TRUSTED_ADDITION_PROTOCOL.md)). Data assumptions (for example column
bounds) are checked against the real database. Limitations are in
[docs/paper/article_draft.md](docs/paper/article_draft.md).

## Quick start

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), Rust,
[Verus](research_loop/scripts/install_verus.md), and Docker for the agent sandbox.

```bash
./scripts/setup.sh
uv run python research_loop/harness.py -q 1 --dataset-size 50000
```

Run the agent in the sandbox (network off, only `api.anthropic.com` allowed; log in with Claude Code
on the host first, or pass `ANTHROPIC_API_KEY`):

```bash
uv run python research_loop/scripts/run_container_agent.py --style declarative \
    --menu adversary_declarative0 --agent claude-haiku-4-5-20251001 \
    --query-sql "SELECT SUM(line) AS total FROM pre WHERE line > 5"
```

Verus is memory hungry. Run it through `scripts/ram/verus_guarded.sh`, which caps concurrent runs and memory.

## Layout

| Path | Role |
|---|---|
| `declarative_spec/` | declarative emitter, parallel/dictionary/NULL support, prompt, assemble |
| `verus_transpiler/` | imperative transpiler |
| `research_loop/` | harness, menus (profiles), assumption packages, agent sandbox, scripts |
| `db_extension/` | optimizer loop, MCP host the agent calls, DuckDB bridge |
| `docker/agent/` | sandbox image and entrypoint |
| `holdout/` | GenDB SEC EDGAR and TPC-H data and queries |
| `tests/` | tests and verified example bodies (`tests/fixtures/declarative_proofs/`) |
| `docs/` | trusted families, verification chain, paper draft |

## Status

Research code, in progress. The declarative emitter produces specs for all of the GenDB SEC corpus on a
DECIMAL schema. Typechecking and per-shape reference proofs cover it; a corpus-wide check of every spec's
meaning against DuckDB is not done. Speedups against all-core DuckDB are measured per query shape, with
the prover labelled (manual Sonnet subagent or real Claude Code in the container). Some shapes win by
several times, selective scans do not yet. See `research_loop/menus/` for logs and verdicts.
