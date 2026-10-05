---
name: lemma-assumptions
description: Get a Lemma assumption package (row/value/string caps, unique keys, nullable columns, join caps) from the user's own DuckDB, have the user approve every claim, check it, and run Lemma under it. Use when the user wants to run Lemma on their data or asks about assumptions/caps.
---

# Lemma assumptions from your data

A Lemma proof is IF-THEN: IF the data obeys the declared bounds, THEN the program computes the SQL.
The assumptions are the **user's claims about their data**. A wrong claim makes the proofs vacuous.
You propose; the user decides. Never accept a number on the user's behalf.

1. **Profile** (read-only on the DuckDB; add `--join a.x=b.y` for each FK-looking pair the user names):
   ```bash
   uv run python -m research_loop.assumption_packages.profile --db <duckdb> --name <pkg> --out <pkg>.json
   ```
   Defaults: row, distinct and join caps = measured x4 rounded up to a power of two; value caps = next power of
   two above the measured max; `--margin N` / `--value-margin N` change the factors. Writes `<pkg>.json` and
   `<pkg>.md` (the report).
2. **Present the report to the user in plain language**, grouped by table. For EACH cap say: the measured value,
   the proposed cap, what happens if data exceeds it (load fails), and the cost of a looser one (wider integers,
   harder proofs, slower code). Ask whether future data can exceed it (growth, outliers, new units, longer text).
3. **Get explicit approval or an edit for every item.** Specifically ask about:
   - every cap (rows, values, string lengths, distinct counts, join sizes);
   - every **NOT NULL** claim (a column with no NULL today is declared to never hold one) and every nullable column;
   - every **unique key**. Keys are only proposals (`proposals.unique_keys` in the JSON, not in the package). Add an
     approved one by hand under the table as `"unique_keys": [["col", ...]]`.
   Apply the user's edits to `<pkg>.json`. Do not proceed on silence or a blanket "looks fine"; list what is
   still unapproved.
4. **Check** it against the database (lists each violated bound with the measured value; non-zero exit on failure):
   ```bash
   uv run python -m research_loop.assumption_packages.check --package <pkg>.json --db <duckdb>
   ```
5. **Run Lemma** under it: `LEMMA_ASSUMPTION_PACKAGE=<pkg>.json` (a path, or the name of a file in
   `research_loop/assumption_packages/registry/`). Run commands are in the README Quick start.

Data growth past a cap fails loudly at load time (the loader re-checks every bound on the pinned columns); it never
runs a proof that no longer applies. When data grows or changes, re-run steps 1-4 and have the user re-approve.
