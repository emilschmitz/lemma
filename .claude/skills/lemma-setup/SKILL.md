---
name: lemma-setup
description: Walk a user through installing Lemma, running `lemma setup`, and proving a first query with `lemma optimize` (no data assumptions by default; the assumption step is optional and unmaintained). Use when the user wants to get started with Lemma, install it, set it up, or optimize their first query.
---

# Lemma: install, setup, first optimized query

Run the steps with the `lemma` CLI, one at a time, and read its output to the user. Every LLM agent Lemma starts runs in a Docker
sandbox (network off, only the model API allowed), never on this machine.

## Secrets: hard rules

- NEVER ask the user to paste an API key, token or password into this chat, and never type one into a command yourself.
- NEVER print, `echo`, `cat` or `env | grep` a credential, and never write one to a file.
- First ask which agent harness the user has credentials for: Claude Code (default), OpenAI Codex CLI (`--harness codex`) or Google Gemini CLI (`--harness gemini`).
- If credentials are missing, tell the user to do it themselves in their own terminal:
  - login path: `claude login` (Claude Code) or `codex login` (Codex), then continue. Gemini: a free personal Google login is refused by Google for the Gemini CLI; use an API key;
  - API-key path: export the harness's key in the shell that launches this session (`ANTHROPIC_API_KEY`, `CODEX_API_KEY` or `GEMINI_API_KEY`; the CLI passes it to the container by name only), then `lemma setup [--harness codex|gemini] --auth api-key`.
- Harnesses and auth paths never switch silently. `lemma setup --harness claude|codex|gemini --auth login|api-key [--model M]` saves the choice; `lemma status` shows harness, model and auth.

## Steps

1. **Prerequisites.** Docker installed with a reachable daemon (`docker info` works without sudo), Python 3.11+, uv. If `docker info` fails, show the user its error and the fix `lemma setup` prints (start the daemon; join the `docker` group); do not use sudo for them.
2. **Install** from the Lemma checkout: `uv tool install --editable .` (gives the `lemma` command).
3. **Setup:** `lemma setup` (or `lemma setup --auth api-key`, or `lemma setup --harness codex --auth api-key`, `lemma setup --harness gemini --auth api-key`). It checks Docker, builds or verifies the image `lemma-agent:<harness>`, runs the sandbox self-test (a non-allowlisted host must be refused, the model API must be reachable), fetches libduckdb and checks that the chosen credential exists. It is safe to re-run. Stop on any `lemma:` error line and fix that before going on; a failed self-test means the sandbox is not safe, so do not work around it.
4. **Assumptions: skip by default.** Since 2026-10-17 `lemma.toml` has `assumptions = false`: the proof makes no claim about the user's data (exact integers; the program may DECLINE a query, e.g. on overflow, and a declined query is reported as DECLINED, not as a result). Tell the user that. Only if they deliberately set `assumptions = true` (the UNMAINTAINED assumption-package path) do they run `lemma assumptions --db PATH`. Then: a proof is IF-THEN: IF the data obeys these bounds THEN the program computes the SQL. The bounds are the USER's claims about their data. The command shows each one (measured value, proposed cap, what breaks if data exceeds it) and asks y/N; the user must answer each in their own terminal (it needs a real terminal; there is no blanket yes). Explain each claim in plain language first, and ask whether future data could exceed it. See the `lemma-assumptions` skill for the detail.
5. **First query:** `lemma optimize --db PATH --sql query.sql`. It costs model money (the agent runs for up to an hour of wall time; `max_budget_usd` in `lemma.toml` caps spend per query for Claude Code only, because Codex and Gemini CLI report no cost: their runs are capped by time only). Tell the user that, and use a small query first. A `?` placeholder takes `--params VALUE...`.
6. **Check:** `lemma status` lists the cached executors, `$LEMMA_HOME/executors/<sha256 of normalized SQL>/` holds `manifest.json`, `query.sql`, the verified source in `proved/`, and the binary when the run kept one. `lib.so` is still pending (the in-DuckDB mode is built separately). For many queries, drop `.sql` files into `$LEMMA_HOME/queue/` and run `lemma optimize --queue --db PATH`.

If `lemma optimize` stops saying there is no approved assumption package, `assumptions = true` is set: either run the exact `lemma assumptions --db ...` command it prints, or go back to the default `assumptions = false`. If it reports DECLINED, the proved program refused this data (for example an overflow); nothing was installed. If any step fails, quote the error to the user; never retry with a weaker sandbox or another credential path.
