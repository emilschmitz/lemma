# Lemma

Full DuckDB 1.5.6 plus Lemma: give it a SQL query and your database, an AI agent writes a native program for it, Verus proves the program
computes exactly what the SQL says, and DuckDB runs the proved program from then on.

**You need** Linux x86_64 (glibc >= 2.34), Docker (your user may run containers), [uv](https://docs.astral.sh/uv/), and credentials for one
agent harness (Claude Code login by default, or an API key: `lemma setup --auth api-key` with `ANTHROPIC_API_KEY` exported).

## Install

```bash
tar -xzf lemma-<version>-linux-x86_64.tar.gz
./lemma-<version>-linux-x86_64/install.sh          # ~/.local/bin/lemma, ~/.local/share/lemma/duckdb/
lemma setup                                        # pulls the agent and prover images, tests the sandbox, checks your login
```

Offline machine: `./install.sh --load-images` loads the images shipped in `images/` (when the release has them) instead of pulling.

## First query

```bash
lemma optimize --db my.duckdb --sql "SELECT region, SUM(qty) AS q FROM orders GROUP BY region"
lemma duckdb my.duckdb -c "SELECT region, SUM(qty) AS q FROM orders GROUP BY region; SELECT * FROM lemma_last_query();"
lemma list                                         # installed executors; lemma remove KEY
```

`lemma duckdb` is a complete DuckDB 1.5.6 CLI (`~/.local/share/lemma/duckdb/duckdb`: CREATE TABLE, joins, `read_csv`, every DuckDB
feature) with Lemma mode on: a query with a proved executor runs the proved program (`lemma_last_query()` says `engine = lemma`), and a
query without one is an error rather than silently DuckDB's answer. `SET lemma_route_unproved = true` lets DuckDB answer those (labelled
`engine = duckdb`), `SET lemma_mode = false` is plain DuckDB. From your own DuckDB 1.5.6:
`duckdb -unsigned my.duckdb`, then `LOAD '<home>/.local/share/lemma/duckdb/lemma.duckdb_extension'; SET lemma_mode = true;` (the full path;
`lemma duckdb` prints it).

More: https://github.com/emilschmitz/lemma (README "Quick start").
