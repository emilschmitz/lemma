// Agent workspace — edit ONLY between the markers below.
// Do not add method, function, lemma, class, or module declarations.
// Do not change requires/ensures (the host injects ValidCols + ensures).
//
// Engine is schema-general: use cols.Get<COL> / EqAt<COL> from the transpiled spec only.
// Never assume a fixed dataset in patterns you invent for reusable bodies.
// <<<LEMMA_RUNQUERY_BODY>>>
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
  // ValidCols_Get<col>(cols, i); term := ((rev as int) as NativeU64);
  // cols.AggPush_<U32COL>_<STRCOL>(agg, i, term as NativeI64);  // see transpiled spec
  // res := agg.ToU64Map();
}
// <<<END_LEMMA_RUNQUERY_BODY>>>
