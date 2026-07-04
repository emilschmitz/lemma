type uint64 = x: int | 0 <= x < 18446744073709551616
type uint32 = x: int | 0 <= x < 4294967296

datatype Row = Row(LO_ORDERKEY: bv32, LO_LINENUMBER: bv32, LO_CUSTKEY: bv32, LO_PARTKEY: bv32, LO_SUPPKEY: bv32, LO_ORDERDATE: bv32, LO_ORDERPRIORITY: string, LO_SHIPPRIORITY: bv32, LO_QUANTITY: bv32, LO_EXTENDEDPRICE: bv64, LO_ORDTOTALPRICE: bv64, LO_DISCOUNT: bv32, LO_REVENUE: bv64, LO_SUPPLYCOST: bv64, LO_TAX: bv32, LO_COMMITDATE: bv32, LO_SHIPMODE: string, C_NAME: string, C_ADDRESS: string, C_CITY: string, C_NATION: string, C_REGION: string, C_PHONE: string, C_MKTSEGMENT: string, S_NAME: string, S_ADDRESS: string, S_CITY: string, S_NATION: string, S_REGION: string, S_PHONE: string, P_NAME: string, P_MFGR: string, P_CATEGORY: string, P_BRAND: string, P_COLOR: string, P_TYPE: string, P_SIZE: bv32, P_CONTAINER: string, D_YEAR: bv32, D_YEARMONTHNUM: bv32, D_WEEKNUMINYEAR: bv32)

function MethodSpec(data: seq<Row>): map<(string, string, bv32), int>
{
  if |data| == 0 then map[] else var tailMap := MethodSpec(data[1..]);
  var row := data[0];
  if (((row.C_REGION == "ASIA" && row.S_REGION == "ASIA") && row.LO_ORDERDATE >= 19920101) && row.LO_ORDERDATE <= 19971231) then
    var key := (row.C_NATION, row.S_NATION, row.D_YEAR);
    var val := if key in tailMap then tailMap[key] else 0;
    tailMap[key := val + (row.LO_REVENUE as int)]
  else
    tailMap
}

method RunQuery(data: seq<Row>) returns (res: map<(string, string, bv32), int>)
  ensures res == MethodSpec(data)
{
  res := map[];
  var i := |data|;
  while i > 0
    invariant 0 <= i <= |data|
    invariant res == MethodSpec(data[i..])
  {
    i := i - 1;
    var row := data[i];
    var key := (row.C_NATION, row.S_NATION, row.D_YEAR);
    res := res[key := (if key in res then res[key] else 0) + (row.LO_REVENUE as int)];
  }
}


method {:verify false} Main() {
  var data := seq(50000, i => Row((1 + (i % 100)) as bv32, (1 + (i % 100)) as bv32, (1 + (i % 100)) as bv32, (1 + (i % 100)) as bv32, (1 + (i % 100)) as bv32, (19930101 + (i % 365)) as bv32, if i % 2 == 0 then "1-URGENT" else "2-HIGH", (1 + (i % 100)) as bv32, (i % 50) as bv32, (1000 + (i % 1000)) as bv64, (1000 + (i % 1000)) as bv64, (i % 10) as bv32, (1000 + (i % 1000)) as bv64, (1000 + (i % 1000)) as bv64, (1 + (i % 100)) as bv32, (1 + (i % 100)) as bv32, "dummy", "dummy", "dummy", if i % 2 == 0 then "UNITED KI1" else "UNITED KI2", if i % 5 == 0 then "UNITED STATES" else "UNITED KINGDOM", if i % 2 == 0 then "AMERICA" else "ASIA", "dummy", "dummy", "dummy", "dummy", if i % 2 == 0 then "UNITED KI5" else "UNITED KI6", if i % 5 == 0 then "UNITED STATES" else "UNITED KINGDOM", if i % 2 == 0 then "AMERICA" else "ASIA", "dummy", "dummy", "dummy", if i % 3 == 0 then "MFGR#12" else "MFGR#14", if i % 4 == 0 then "MFGR#2221" else "MFGR#2222", "dummy", "dummy", (1 + (i % 100)) as bv32, "dummy", (1992 + (i % 7)) as bv32, (1 + (i % 100)) as bv32, (1 + (i % 52)) as bv32));
  var opt_res := RunQuery(data);
  print "SUCCESS\n";
}

