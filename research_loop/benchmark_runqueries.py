"""Hand-written optimized RunQuery bodies for SSB benchmark queries (1-indexed).

Picked at random (seed=42) for expansion: Q2, Q3, Q5, Q6, Q10, Q13.
Patterns: NativeU64 scalar loops (AddU64/MulU64U32), NativeAggMap+ghost for 2-key group-by,
Dafny map + native ops for 3-key group-by (NativeAggMap is 2-key i64-only today).
"""

# Q1 — SSB Q1.1 (baseline)
Q1_RUNQUERY = """
method RunQuery(cols: Cols) returns (res: NativeU64)
  requires ValidCols(cols)
  ensures res == MethodSpec(cols)
{
  res := 0 as NativeU64;
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant res as int == MethodSpecHelper(cols, i) as int
  {
    i := i - 1;
    var od := cols.GetLO_ORDERDATE(i);
    var disc := cols.GetLO_DISCOUNT(i);
    var qty := cols.GetLO_QUANTITY(i);
    if 19930101 <= od && od <= 19931231 && 1 <= disc && disc <= 3 && qty < 25 {
      var ep := cols.GetLO_EXTENDEDPRICE(i);
      res := AddU64(res, MulU64U32(ep, disc));
    }
  }
}
"""

# Q2 — SSB Q1.2
Q2_RUNQUERY = """
method RunQuery(cols: Cols) returns (res: NativeU64)
  requires ValidCols(cols)
  ensures res == MethodSpec(cols)
{
  res := 0 as NativeU64;
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant res as int == MethodSpecHelper(cols, i) as int
  {
    i := i - 1;
    var od := cols.GetLO_ORDERDATE(i);
    var disc := cols.GetLO_DISCOUNT(i);
    var qty := cols.GetLO_QUANTITY(i);
    if 19940101 <= od && od <= 19940131 && 4 <= disc && disc <= 6
       && 26 <= qty && qty <= 35
    {
      var ep := cols.GetLO_EXTENDEDPRICE(i);
      res := AddU64(res, MulU64U32(ep, disc));
    }
  }
}
"""

# Q3 — SSB Q1.3
Q3_RUNQUERY = """
method RunQuery(cols: Cols) returns (res: NativeU64)
  requires ValidCols(cols)
  ensures res == MethodSpec(cols)
{
  res := 0 as NativeU64;
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant res as int == MethodSpecHelper(cols, i) as int
  {
    i := i - 1;
    var week := cols.GetD_WEEKNUMINYEAR(i);
    var yr := cols.GetD_YEAR(i);
    var disc := cols.GetLO_DISCOUNT(i);
    var qty := cols.GetLO_QUANTITY(i);
    if week == 6 && yr == 1994 && 5 <= disc && disc <= 7
       && 26 <= qty && qty <= 35
    {
      var ep := cols.GetLO_EXTENDEDPRICE(i);
      res := AddU64(res, MulU64U32(ep, disc));
    }
  }
}
"""

# Q4 — SSB Q2.1 (2-key group-by; NativeAggMap + ghost u64 map)
Q4_RUNQUERY = """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeU64>)
  requires ValidCols(cols)
  ensures res == MethodSpec(cols)
{
  var agg := new NativeAggMap();
  ghost var g: map<(NativeU32, string), NativeU64> := map[];
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant g == MethodSpecHelper(cols, i)
    invariant forall k :: k in g ==> k in agg.Snapshot() && agg.Snapshot()[k] as int == g[k] as int
    invariant forall k :: k in agg.Snapshot() ==> k in g
  {
    i := i - 1;
    if cols.EqAtP_CATEGORY(i, "MFGR#12") && cols.EqAtS_REGION(i, "AMERICA")
    {
      var yr := cols.GetD_YEAR(i);
      var brand := cols.GetP_BRAND(i);
      var key := (yr, brand);
      var rev := cols.GetLO_REVENUE(i);
      ValidCols_GetLO_REVENUE(cols, i);
      var term := ((rev as int) as NativeU64);
      agg.Add(yr, brand, term as NativeI64);
      ghost var prev := if key in g then g[key] else 0 as NativeU64;
      g := g[key := AddU64(prev, term)];
    }
  }
  res := agg.ToU64Map();
}
"""

# Q5 — SSB Q2.2 (2-key group-by; NativeAggMap + ghost u64 map)
Q5_RUNQUERY = """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeU64>)
  requires ValidCols(cols)
  ensures res == MethodSpec(cols)
{
  var agg := new NativeAggMap();
  ghost var g: map<(NativeU32, string), NativeU64> := map[];
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant g == MethodSpecHelper(cols, i)
    invariant forall k :: k in g ==> k in agg.Snapshot() && agg.Snapshot()[k] as int == g[k] as int
    invariant forall k :: k in agg.Snapshot() ==> k in g
  {
    i := i - 1;
    if cols.EqAtP_BRAND(i, "MFGR#2221") && cols.GetP_SIZE(i) >= 10
       && cols.EqAtS_REGION(i, "ASIA")
    {
      var yr := cols.GetD_YEAR(i);
      var brand := cols.GetP_BRAND(i);
      var key := (yr, brand);
      var rev := cols.GetLO_REVENUE(i);
      ValidCols_GetLO_REVENUE(cols, i);
      var term := ((rev as int) as NativeU64);
      agg.Add(yr, brand, term as NativeI64);
      ghost var prev := if key in g then g[key] else 0 as NativeU64;
      g := g[key := AddU64(prev, term)];
    }
  }
  res := agg.ToU64Map();
}
"""

# Q6 — SSB Q2.3
Q6_RUNQUERY = """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeU64>)
  requires ValidCols(cols)
  ensures res == MethodSpec(cols)
{
  res := map[];
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant res == MethodSpecHelper(cols, i)
  {
    i := i - 1;
    if cols.EqAtP_BRAND(i, "MFGR#2221") && cols.EqAtS_REGION(i, "EUROPE") {
      var yr := cols.GetD_YEAR(i);
      var brand := cols.GetP_BRAND(i);
      var key := (yr, brand);
      var val := if key in res then res[key] else (0 as NativeU64);
      res := res[key := AddU64(val, cols.GetLO_REVENUE(i))];
    }
  }
}
"""

# Q10 — SSB Q3.4 (3-key group-by)
Q10_RUNQUERY = """
method RunQuery(cols: Cols) returns (res: map<(string, string, NativeU32), NativeU64>)
  requires ValidCols(cols)
  ensures res == MethodSpec(cols)
{
  res := map[];
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant res == MethodSpecHelper(cols, i)
  {
    i := i - 1;
    var od := cols.GetLO_ORDERDATE(i);
    if cols.EqAtC_CITY(i, "UNITED KI1") && cols.EqAtS_CITY(i, "UNITED KI5")
       && 19971201 <= od && od <= 19971231
    {
      var ccity := cols.GetC_CITY(i);
      var scity := cols.GetS_CITY(i);
      var yr := cols.GetD_YEAR(i);
      var key := (ccity, scity, yr);
      var val := if key in res then res[key] else (0 as NativeU64);
      res := res[key := AddU64(val, cols.GetLO_REVENUE(i))];
    }
  }
}
"""

# Q11 — SSB Q4.1 (NativeAggMap + ghost)
Q11_RUNQUERY = """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>)
  requires ValidCols(cols)
  ensures res == MethodSpec(cols)
  requires forall j :: 0 <= j < cols.n() ==>
    -9223372036854775808 <= SubU64ToI64(cols.GetLO_REVENUE(j), cols.GetLO_SUPPLYCOST(j)) as int
      < 9223372036854775808
{
  var agg := new NativeAggMap();
  ghost var g: map<(NativeU32, string), NativeI64> := map[];
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant g == MethodSpecHelper(cols, i)
    invariant agg.Snapshot() == g
    invariant forall k :: k in g ==>
      -9223372036854775808 <= g[k] as int < 9223372036854775808
  {
    i := i - 1;
    if cols.EqAtC_REGION(i, "AMERICA") && cols.EqAtS_REGION(i, "AMERICA")
       && cols.EqAtP_MFGR(i, "MFGR#1")
    {
      var yr := cols.GetD_YEAR(i);
      var nation := cols.GetC_NATION(i);
      var key := (yr, nation);
      var term := SubU64ToI64(cols.GetLO_REVENUE(i), cols.GetLO_SUPPLYCOST(i));
      agg.Add(yr, nation, term);
      ghost var prev := if key in g then g[key] else 0 as NativeI64;
      g := g[key := AddI64(prev, term)];
    }
  }
  res := agg.ToMap();
}
"""

# Q13 — SSB Q4.3 (3-key group-by, profit)
Q13_RUNQUERY = """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string, string), NativeI64>)
  requires ValidCols(cols)
  ensures res == MethodSpec(cols)
  requires forall j :: 0 <= j < cols.n() ==>
    -9223372036854775808 <= SubU64ToI64(cols.GetLO_REVENUE(j), cols.GetLO_SUPPLYCOST(j)) as int
      < 9223372036854775808
{
  res := map[];
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant res == MethodSpecHelper(cols, i)
    invariant forall k :: k in res ==>
      -9223372036854775808 <= res[k] as int < 9223372036854775808
  {
    i := i - 1;
    var od := cols.GetLO_ORDERDATE(i);
    if cols.EqAtC_REGION(i, "AMERICA") && cols.EqAtS_NATION(i, "UNITED STATES")
       && 19970101 <= od && od <= 19971231 && cols.EqAtP_CATEGORY(i, "MFGR#14")
    {
      var yr := cols.GetD_YEAR(i);
      var snation := cols.GetS_NATION(i);
      var pcat := cols.GetP_CATEGORY(i);
      var key := (yr, snation, pcat);
      var term := SubU64ToI64(cols.GetLO_REVENUE(i), cols.GetLO_SUPPLYCOST(i));
      var prev := if key in res then res[key] else 0 as NativeI64;
      res := res[key := AddI64(prev, term)];
    }
  }
}
"""

# Random sample (seed=42): Q2, Q3, Q5, Q6, Q10, Q13
RANDOM_SIX = [2, 3, 5, 6, 10, 13]

RUNQUERIES: dict[int, str] = {
    1: Q1_RUNQUERY,
    2: Q2_RUNQUERY,
    3: Q3_RUNQUERY,
    4: Q4_RUNQUERY,
    5: Q5_RUNQUERY,
    6: Q6_RUNQUERY,
    10: Q10_RUNQUERY,
    11: Q11_RUNQUERY,
    13: Q13_RUNQUERY,
}
