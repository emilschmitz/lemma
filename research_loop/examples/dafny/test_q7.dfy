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
