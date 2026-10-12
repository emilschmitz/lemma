# Experiments

One TOML per experiment: `[settings]` (keys of `lemma.toml`, laid over it) and `[[run]]` entries (`model`, `query`, `duckdb_path`, `assumption_package`).
`query` and `assumption_package` are repo-relative and must be tracked and unchanged at HEAD (queries live in `configs/queries/`); `duckdb_path` is a data path whose sha256 is recorded.

Run (after committing the file; the tree must be clean, untracked files included):

    uv run python research_loop/scripts/container_batch.py --experiment configs/experiments/opus_none_stats.toml

The rule: every number that may be reported comes from a run whose config is entirely in the commit. No `LEMMA_*` environment or CLI overrides
(the batch refuses and lists them), the batch pins one SHA and stops if HEAD changes. The manifest records the SHA, the experiment file's blob,
the effective config with sources, the database sha256 and the agent image digest.
