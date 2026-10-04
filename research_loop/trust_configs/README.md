# Trust configs

Named switches over **existing** `LEMMA_*` environment flags — not a fork of transpile logic.

- **`product`** — today's product-path defaults (`LEMMA_FAST_TRUSTEDS=0`, parallel/vector/spill/fold-slot axiomatic off). Applying it must not change what those flags mean.
- **`fast`** — same as product but `LEMMA_FAST_TRUSTEDS=1` (legacy speed menu B). Not the adversary target.
- **`adversary_imperativespec0`** — menu under test. Sets `LEMMA_EXACT_SUM=1`: scalar `SUM` is `Option<u128>` (`None` when no row matches, otherwise the mathematical sum). Product leaves that flag unset and keeps the old `u64` fold. Not the fast menu.

- **`adversary_declarative0`** — the declarative-spec sibling (`transpiler="declarative"`, `LEMMA_SPEC_STYLE=declarative`). Same flag philosophy: no fast/parallel/vector/spill/fold-slot trusteds, exact semantics. vstd-provided threads and hash maps are allowed on every menu; nothing we implement as trusted is. Speed bar: `LEMMA_SPEED_BAR_MULT` (default 1.0).

The `transpiler` field names which emitter the config belongs to: `"product"` → `verus_transpiler`; `"declarative"` → `declarative_spec` (would be a separate config file if added).

Use `apply_trust_config(name)` or set `LEMMA_TRUST_CONFIG`. Do not edit `lemma_flags.py` from these modules.

## Menu profiles (`research_loop/menu_profile.py`)

A trust config is only the env flags. A **menu profile** names everything the agent optimizes and is
selected by `LEMMA_MENU` (production loop) or `--menu` (`scripts/run_container_agent.py`): `style`
(`imperative` | `declarative`; moves emitter, assembler, admission, workspace, measure together),
`trusted_set` (`rocketship` = this file's `product`, `fast`, `adversary_imperativespec0`,
`declarative_default`; it also selects the declarative host lemma block and its lemma index from one
registry, `declarative_spec/trusted_sets.py`), `assumption_package`, `agent`, `speed_bar_mult`.
Profiles: `rocketship`, `adversary_imperativespec0`, `fast`, `adversary_declarative0`. Each axis can be
overridden alone (env var or launcher flag); contradicting the profile needs `--allow-override`; a trusted
set from the other style always fails. The resolved selection is printed and recorded in the run manifest.

## Optional: `LEMMA_PARALLEL_VSTD=1` (declarative menus)

Not part of any menu's env (opt-in per run). The emitted `run_query` also receives `<table>_arc: &std::sync::Arc<Cols_<table>>` with
`requires **<table>_arc == *<table>` (the host `main` passes the same object twice) and the `ensures` are unchanged. The agent may then
use vstd `thread::spawn` / `JoinHandle::join` (vstd's own, not trusted code of ours) on row ranges; see `declarative_spec/parallel.py` and
the verified example `tests/fixtures/declarative_proofs/parallel_ungrouped_sum.rs`.
