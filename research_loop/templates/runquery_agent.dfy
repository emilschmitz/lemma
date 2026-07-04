// Agent workspace — edit ONLY inside the braces below.
// Do not add method, function, lemma, class, or module declarations.
// Do not change requires/ensures (the host injects ValidCols + ensures).
//
// Engine is schema-general: use cols.Get<COL> / EqAt<COL> from the transpiled spec only.
// Never assume SSB or any fixed dataset in patterns you invent for reusable bodies.
{
  // Scalar SUM example:
  // res := 0 as NativeU64;
  // var i := cols.n();
  // while i > 0
  //   invariant 0 <= i <= cols.n()
  //   invariant res as int == MethodSpecHelper(cols, i) as int
  // { i := i - 1; ... }
  //
  // 2-key GROUP BY (NativeU64 values) — use NativeAggMap + ghost map:
  // var agg := new NativeAggMap();
  // ghost var g: map<(NativeU32, string), NativeU64> := map[];
  // ... invariant g == MethodSpecHelper(cols, i) && agg.Snapshot() matches g ...
  // ValidCols_Get<col>(cols, i); term := ((rev as int) as NativeU64); agg.Add(k0, k1, term as NativeI64);
  // res := agg.ToU64Map();
}
