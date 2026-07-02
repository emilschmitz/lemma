"""Pytest coverage for RunQuery admission (NativeAggMap linearity)."""
from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.admit_runquery import NativeAggMode, admit_runquery, extract_runquery_body
from research_loop.benchmark_runqueries import Q1_RUNQUERY, Q11_RUNQUERY, RUNQUERIES

ROOT = Path(__file__).resolve().parents[1]
POC_ALIAS = ROOT / "research_loop" / "poc_alias" / "q.dfy"


def wrap(runquery: str) -> str:
    return f"// spec\n{runquery}\nmethod Main() {{}}\n"


# ---------------------------------------------------------------------------
# Benign / benchmark cases
# ---------------------------------------------------------------------------


def test_scalar_q1_none():
    r = admit_runquery(wrap(Q1_RUNQUERY))
    assert r.ok
    assert r.native_agg == NativeAggMode.NONE


def test_q11_benchmark_fast():
    r = admit_runquery(wrap(Q11_RUNQUERY))
    assert r.ok, r.violations
    assert r.native_agg == NativeAggMode.FAST
    assert r.allow_fast_native_agg


@pytest.mark.parametrize("idx", sorted(RUNQUERIES.keys()))
def test_benchmark_runquery_admits(idx: int):
    r = admit_runquery(wrap(RUNQUERIES[idx]))
    assert r.ok, f"Q{idx}: {r.violations}"
    if idx == 11:
        assert r.native_agg == NativeAggMode.FAST
    else:
        assert r.native_agg in (NativeAggMode.NONE, NativeAggMode.FAST)


def test_map_only_no_native_agg():
    rq = """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeU64>)
{
  res := map[];
  var i := cols.n();
  while i > 0 { i := i - 1; }
}
"""
    r = admit_runquery(wrap(rq))
    assert r.ok
    assert r.native_agg == NativeAggMode.NONE


def test_no_runquery():
    r = admit_runquery("method Main() {}")
    assert not r.ok
    assert "not found" in r.violations[0]


# ---------------------------------------------------------------------------
# Known adversarial patterns (must reject; strict=True is the default)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,body,needle",
    [
        (
            "var alias := agg",
            """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  var alias := agg;
  res := agg.ToMap();
}
""",
            "alias",
        ),
        (
            "typed declare then assign",
            """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  var alias: NativeAggMap;
  alias := agg;
  res := agg.ToMap();
}
""",
            "alias",
        ),
        (
            "typed init alias",
            """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  var alias: NativeAggMap := agg;
  res := agg.ToMap();
}
""",
            "alias",
        ),
        (
            "ghost alias",
            """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  ghost var alias := agg;
  res := agg.ToMap();
}
""",
            "alias",
        ),
        (
            "tuple stores agg",
            """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  var pair: (NativeAggMap, int) := (agg, 0);
  pair.0.Add(1 as NativeU32, "x", 1 as NativeI64);
  res := agg.ToMap();
}
""",
            "tuple",
        ),
        (
            "two new",
            """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var a := new NativeAggMap();
  var b := new NativeAggMap();
  res := a.ToMap();
}
""",
            "multiple",
        ),
        (
            "pass to helper",
            """
method Bump(a: NativeAggMap) { }
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  Bump(agg);
  res := agg.ToMap();
}
""",
            "passed to",
        ),
        (
            "field stores agg",
            """
class Box { var agg: NativeAggMap }
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  var box := new Box();
  box.agg := agg;
  agg.Add(1 as NativeU32, "x", 1 as NativeI64);
  res := agg.ToMap();
}
""",
            "box.agg",
        ),
        (
            "array slot stores agg",
            """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  var arr: array<NativeAggMap> := new NativeAggMap[1];
  arr[0] := agg;
  agg.Add(1 as NativeU32, "x", 1 as NativeI64);
  res := agg.ToMap();
}
""",
            "arr[0]",
        ),
        (
            "reassign between holders",
            """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  var other := new NativeAggMap();
  agg := other;
  res := agg.ToMap();
}
""",
            "multiple",
        ),
    ],
)
def test_strict_rejects_adversarial(name: str, body: str, needle: str):
    r = admit_runquery(wrap(body))
    assert not r.ok, name
    assert r.native_agg == NativeAggMode.SLOW, name
    assert any(needle in v.lower() for v in r.violations), (name, r.violations)


def test_poc_alias_file_rejected():
    """Real malicious PoC must not slip through commented skeleton decoys."""
    src = POC_ALIAS.read_text()
    r = admit_runquery(src)
    assert not r.ok, r.violations
    assert r.native_agg == NativeAggMode.SLOW
    assert any("alias" in v.lower() for v in r.violations)


def test_commented_skeleton_does_not_shadow_real_runquery():
    """Line-commented `// method RunQuery` skeleton must not hide the real method."""
    src = """
// method RunQuery(cols: Cols) returns (res: map<..., NativeI64>)
// {
//   var agg := new NativeAggMap();
//   res := agg.ToMap();
// }

method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  var alias := agg;
  res := agg.ToMap();
}
method Main() {}
"""
    body = extract_runquery_body(src)
    assert body is not None
    assert "alias := agg" in body
    r = admit_runquery(src)
    assert not r.ok


def test_multiple_runquery_definitions_rejected():
    src = """
method RunQuery(cols: Cols) returns (r: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  r := agg.ToMap();
}
method RunQuery(cols: Cols) returns (r: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  r := agg.ToMap();
}
"""
    r = admit_runquery(src)
    assert not r.ok
    assert any("multiple RunQuery" in v for v in r.violations)


# ---------------------------------------------------------------------------
# Decoys that must stay FAST
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  // new NativeAggMap()
  var agg := new NativeAggMap();
  res := agg.ToMap();
}
""",
        """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  ghost var s := "new NativeAggMap()";
  res := agg.ToMap();
}
""",
        """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  /* var alias := agg; */
  var agg := new NativeAggMap();
  res := agg.ToMap();
}
""",
    ],
)
def test_decoys_remain_fast(body: str):
    r = admit_runquery(wrap(body))
    assert r.ok, r.violations
    assert r.native_agg == NativeAggMode.FAST


def test_non_strict_allows_slow():
    """strict=False exists only for tests; production must not use it."""
    bad = """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>) {
  var agg := new NativeAggMap();
  var alias := agg;
  res := agg.ToMap();
}
"""
    r = admit_runquery(wrap(bad), strict=False)
    assert r.ok
    assert r.native_agg == NativeAggMode.SLOW
    assert not r.allow_fast_native_agg
