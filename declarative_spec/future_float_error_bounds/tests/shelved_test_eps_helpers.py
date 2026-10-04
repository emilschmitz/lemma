"""SHELVED (not collected: the file name has no `test_` prefix). The host-side epsilon check of the old sum-error lemma."""

from declarative_spec.future_float_error_bounds.error_bounds import host_error_exceeds_eps


def test_host_error_exceeds_eps_small_bound_false() -> None:
    assert host_error_exceeds_eps(10, 100, "0.000001") is False


def test_host_error_exceeds_eps_huge_bound_true() -> None:
    assert host_error_exceeds_eps(10**6, 10**18, "0.000001") is True


def test_host_error_exceeds_eps_invalid_bound() -> None:
    assert host_error_exceeds_eps(2**52, 1, "1.0") is True
