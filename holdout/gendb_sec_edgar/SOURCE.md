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
