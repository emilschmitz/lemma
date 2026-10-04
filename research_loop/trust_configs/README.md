# Trust configs

Named switches over **existing** `LEMMA_*` environment flags — not a fork of transpile logic.

- **`product`** — today's product-path defaults (`LEMMA_FAST_TRUSTEDS=0`, parallel/vector/spill/fold-slot axiomatic off). Applying it must not change what those flags mean.
- **`fast`** — same as product but `LEMMA_FAST_TRUSTEDS=1` (legacy speed menu B). Not the adversary target.
- **`adversary_imperativespec0`** — menu under test. Sets `LEMMA_EXACT_SUM=1`: scalar `SUM` is `Option<u128>` (`None` when no row matches, otherwise the mathematical sum). Product leaves that flag unset and keeps the old `u64` fold. Not the fast menu.

The `transpiler` field names which emitter the config belongs to: `"product"` → `verus_transpiler`; `"declarative"` → `declarative_spec` (would be a separate config file if added).

Use `apply_trust_config(name)` or set `LEMMA_TRUST_CONFIG`. Do not edit `lemma_flags.py` from these modules.
