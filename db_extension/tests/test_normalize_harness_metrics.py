"""Declarative failures store the text on compiler_error, not error."""

from db_extension.verus_bridge import normalize_harness_metrics


def test_declarative_compiler_error_reaches_the_agent() -> None:
    out = normalize_harness_metrics(
        {
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": "assume( is rejected",
        }
    )
    assert out["status"] == "FAILURE"
    assert out["compiler_error"] == "assume( is rejected"


def test_imperative_error_field_still_wins() -> None:
    out = normalize_harness_metrics(
        {
            "status": "FAILURE",
            "proof_verified": False,
            "error": "rustc E0425",
            "compiler_error": "unused",
        }
    )
    assert out["compiler_error"] == "rustc E0425"
