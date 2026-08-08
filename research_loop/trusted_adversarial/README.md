# Adversarial tests for TRUSTED Verus externs

One integration test file per `#[verifier::external_body]` exec helper.

```bash
cd research_loop/trusted_adversarial
cargo test
cargo test --features parallel   # via dependency features if needed
```

Rule: **≥10 diverse** cases per extern (edges, empty, overflow/wrap, Unicode, mismatches, length skew).
