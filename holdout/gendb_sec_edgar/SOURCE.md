# Provenance

Copied from [SolidLao/GenDB](https://github.com/SolidLao/GenDB) `benchmarks/sec-edgar/`
(paper [arXiv:2603.02081](https://arxiv.org/abs/2603.02081) §4.1–4.2).

Immanuel Trummer pointed at the paper’s custom-benchmark procedure; the published
repo implements it here (see `generate_queries.py`).

**Note:** The paper text says “SQLSmith + diversity sampling.” The committed
generator is **template-based random SQL** + filter + greedy diversity sampling
(set-cover style), not a literal `sqlsmith` binary. We treat this artifact as
the legitimate GenDB method.

License: follow upstream GenDB repository terms.

## Verification against upstream (2026-10-07)

Shallow clone of SolidLao/GenDB at commit `0ccf053ade163137775cd2e9c6e1288ea89d524b` (2026-06-08):
- `benchmarks/sec-edgar/queries.sql` (the six) and `queries_all.sql` (the pool) are **byte-identical** to ours.
- `generate_queries.py`: the template-based query generator (everything that produces the random SQL) is identical; ours differs only in plumbing
  (the validity filter and feature extraction moved into `query_filter.py`). The unmodified upstream script is kept for reference in
  `upstream/generate_queries_upstream.py`.
- The string "sqlsmith" does not occur anywhere in the upstream repository (all 3,755 files). The paper says "SQLSmith + diversity sampling", but the released
  generator is template-based random SQL with a DuckDB validity filter and greedy diversity sampling. So "the same as GenDB" means this generator.
  A literal SQLSmith run would produce a different, unreleased query population, so it would not be comparable with GenDB's six.
