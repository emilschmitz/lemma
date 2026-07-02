// Extern building blocks: trusted specs (axioms on heap mutators), Rust implements behavior.
// RunQuery is fully verified against MethodSpec.

newtype {:extern "u32"} NativeU32 = x: int | 0 <= x < 4294967296
newtype {:extern "u64"} NativeU64 = x: int | 0 <= x < 18446744073709551616
newtype {:extern "i64"} NativeI64 = x: int | -9223372036854775808 <= x < 9223372036854775808

function {:extern "native_add_u64"} AddU64(a: NativeU64, b: NativeU64): NativeU64
  ensures (AddU64(a, b) as int) == (a as int) + (b as int)

function {:extern "native_mul_u64_u32"} MulU64U32(ep: NativeU64, d: NativeU32): NativeU64
  ensures (MulU64U32(ep, d) as int) == (ep as int) * (d as int)

function {:extern "native_sub_u64_i64"} SubU64ToI64(a: NativeU64, b: NativeU64): NativeI64
  ensures (SubU64ToI64(a, b) as int) == (a as int) - (b as int)

function {:extern "native_add_i64"} AddI64(a: NativeI64, b: NativeI64): NativeI64
  ensures (AddI64(a, b) as int) == (a as int) + (b as int)

class {:extern "NativeAggMap"} NativeAggMap {
  function {:extern} Snapshot(): map<(NativeU32, string), NativeI64>

  constructor {:extern} {:axiom} ()
    ensures Snapshot() == map[]

  method {:extern} {:axiom} Add(k0: NativeU32, k1: string, delta: NativeI64)
    modifies this
    ensures Snapshot() == old(Snapshot())[(k0, k1) := AddI64(
      if (k0, k1) in old(Snapshot()) then old(Snapshot())[(k0, k1)] else 0 as NativeI64,
      delta)]

  method {:extern} ToMap() returns (m: map<(NativeU32, string), NativeI64>)
    ensures m == Snapshot()
}

class {:extern "ColsNative"} Cols {
  function {:extern} n(): int
  function {:extern} GetLO_ORDERKEY(i: int): NativeU32
  function {:extern} GetLO_LINENUMBER(i: int): NativeU32
  function {:extern} GetLO_CUSTKEY(i: int): NativeU32
  function {:extern} GetLO_PARTKEY(i: int): NativeU32
  function {:extern} GetLO_SUPPKEY(i: int): NativeU32
  function {:extern} GetLO_ORDERDATE(i: int): NativeU32
  function {:extern} GetLO_ORDERPRIORITY(i: int): string
  function {:extern} EqAtLO_ORDERPRIORITY(i: int, lit: string): bool
  function {:extern} GetLO_SHIPPRIORITY(i: int): NativeU32
  function {:extern} GetLO_QUANTITY(i: int): NativeU32
  function {:extern} GetLO_EXTENDEDPRICE(i: int): NativeU64
  function {:extern} GetLO_ORDTOTALPRICE(i: int): NativeU64
  function {:extern} GetLO_DISCOUNT(i: int): NativeU32
  function {:extern} GetLO_REVENUE(i: int): NativeU64
  function {:extern} GetLO_SUPPLYCOST(i: int): NativeU64
  function {:extern} GetLO_TAX(i: int): NativeU32
  function {:extern} GetLO_COMMITDATE(i: int): NativeU32
  function {:extern} GetLO_SHIPMODE(i: int): string
  function {:extern} EqAtLO_SHIPMODE(i: int, lit: string): bool
  function {:extern} GetC_NAME(i: int): string
  function {:extern} EqAtC_NAME(i: int, lit: string): bool
  function {:extern} GetC_ADDRESS(i: int): string
  function {:extern} EqAtC_ADDRESS(i: int, lit: string): bool
  function {:extern} GetC_CITY(i: int): string
  function {:extern} EqAtC_CITY(i: int, lit: string): bool
  function {:extern} GetC_NATION(i: int): string
  function {:extern} EqAtC_NATION(i: int, lit: string): bool
  function {:extern} GetC_REGION(i: int): string
  function {:extern} EqAtC_REGION(i: int, lit: string): bool
  function {:extern} GetC_PHONE(i: int): string
  function {:extern} EqAtC_PHONE(i: int, lit: string): bool
  function {:extern} GetC_MKTSEGMENT(i: int): string
  function {:extern} EqAtC_MKTSEGMENT(i: int, lit: string): bool
  function {:extern} GetS_NAME(i: int): string
  function {:extern} EqAtS_NAME(i: int, lit: string): bool
  function {:extern} GetS_ADDRESS(i: int): string
  function {:extern} EqAtS_ADDRESS(i: int, lit: string): bool
  function {:extern} GetS_CITY(i: int): string
  function {:extern} EqAtS_CITY(i: int, lit: string): bool
  function {:extern} GetS_NATION(i: int): string
  function {:extern} EqAtS_NATION(i: int, lit: string): bool
  function {:extern} GetS_REGION(i: int): string
  function {:extern} EqAtS_REGION(i: int, lit: string): bool
  function {:extern} GetS_PHONE(i: int): string
  function {:extern} EqAtS_PHONE(i: int, lit: string): bool
  function {:extern} GetP_NAME(i: int): string
  function {:extern} EqAtP_NAME(i: int, lit: string): bool
  function {:extern} GetP_MFGR(i: int): string
  function {:extern} EqAtP_MFGR(i: int, lit: string): bool
  function {:extern} GetP_CATEGORY(i: int): string
  function {:extern} EqAtP_CATEGORY(i: int, lit: string): bool
  function {:extern} GetP_BRAND(i: int): string
  function {:extern} EqAtP_BRAND(i: int, lit: string): bool
  function {:extern} GetP_COLOR(i: int): string
  function {:extern} EqAtP_COLOR(i: int, lit: string): bool
  function {:extern} GetP_TYPE(i: int): string
  function {:extern} EqAtP_TYPE(i: int, lit: string): bool
  function {:extern} GetP_SIZE(i: int): NativeU32
  function {:extern} GetP_CONTAINER(i: int): string
  function {:extern} EqAtP_CONTAINER(i: int, lit: string): bool
  function {:extern} GetD_YEAR(i: int): NativeU32
  function {:extern} GetD_YEARMONTHNUM(i: int): NativeU32
  function {:extern} GetD_WEEKNUMINYEAR(i: int): NativeU32
}

predicate ValidCols(cols: Cols)
{
  0 <= cols.n()
}

function {:verify false} MethodSpecHelper(cols: Cols, k: int): map<(NativeU32, string), NativeI64>
  requires 0 <= k <= cols.n()
  requires ValidCols(cols)
  decreases cols.n() - k
{
  if k < cols.n() then
    var tail := MethodSpecHelper(cols, k + 1);
  if ((cols.EqAtC_REGION(k, "AMERICA") && cols.EqAtS_REGION(k, "AMERICA")) && cols.EqAtP_MFGR(k, "MFGR#1")) then
    var key := (cols.GetD_YEAR(k), cols.GetC_NATION(k));
    var val := if key in tail then tail[key] else (0 as NativeI64);
    tail[key := AddI64(val, SubU64ToI64(cols.GetLO_REVENUE(k), cols.GetLO_SUPPLYCOST(k)))]
  else
    tail
  else map[]
}


function {:verify false} MethodSpec(cols: Cols): map<(NativeU32, string), NativeI64>
  requires ValidCols(cols)
{
  MethodSpecHelper(cols, 0)
}

// === RunQuery skeleton (agent provides the body) ===
// method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>)
//   requires ValidCols(cols)
//   ensures res == MethodSpec(cols)
// {
//   var agg := new NativeAggMap();
//   ghost var g: map<..., NativeI64> := map[];
//   var i := cols.n();
//   while i > 0
//     invariant 0 <= i <= cols.n()
//     invariant g == MethodSpecHelper(cols, i)
//     invariant agg.Snapshot() == g
//   {
//     i := i - 1;
//       // TODO: if <filter using EqAt* for string cols> {
//       //   var k0 := cols.Get<group-int>(i);
//       //   var k1 := cols.Get<group-string>(i);
//       //   var key := (k0, k1);
//       //   var term := <native agg term, e.g. SubU64ToI64(...)>;
//       //   agg.Add(k0, k1, term);  // postprocessor → AddStrKey + str_ref
//       //   ghost var prev := if key in g then g[key] else 0 as NativeI64;
//       //   g := g[key := AddI64(prev, term)];
//       // }
//   }
//   res := agg.ToMap();
// }


method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>)
  requires ValidCols(cols)
  ensures res == MethodSpec(cols)
  requires forall j :: 0 <= j < cols.n() ==>
    -9223372036854775808 <= SubU64ToI64(cols.GetLO_REVENUE(j), cols.GetLO_SUPPLYCOST(j)) as int
      < 9223372036854775808
{
  var agg := new NativeAggMap();
  var alias := agg;
  ghost var g: map<(NativeU32, string), NativeI64> := map[];
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant g == MethodSpecHelper(cols, i)
    invariant agg.Snapshot() == g
    invariant alias.Snapshot() == g
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
      if (yr as int) % 2 == 0 {
        agg.Add(yr, nation, term);
      } else {
        alias.Add(yr, nation, term);
      }
      ghost var prev := if key in g then g[key] else 0 as NativeI64;
      g := g[key := AddI64(prev, term)];
    }
  }
  res := agg.ToMap();
}

method {:verify false} Main() {}
