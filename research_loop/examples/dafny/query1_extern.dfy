newtype native_u32 = x: int | 0 <= x < 4294967296
newtype native_u64 = x: int | 0 <= x < 18446744073709551616

datatype Row = Row(
    lo_orderdate: native_u32,
    lo_discount: native_u32,
    lo_quantity: native_u32,
    lo_extendedprice: native_u32
)

method RunQuery(data: seq<Row>) returns (revenue: native_u64)
    requires forall i :: 0 <= i < |data| ==> (data[i].lo_extendedprice as int) < 100000000
    requires forall i :: 0 <= i < |data| ==> (data[i].lo_discount as int) <= 10
{
    var sum: native_u64 := 0;
    var i: nat := 0;
    
    while i < |data|
        invariant i <= |data|
        invariant 0 <= (sum as int) < 18446744073709551616
    {
        assert (data[i].lo_extendedprice as int) < 100000000;
        assert (data[i].lo_discount as int) <= 10;
        
        var row := data[i];
        var od := row.lo_orderdate;
        var disc := row.lo_discount;
        var quant := row.lo_quantity;
        var price := row.lo_extendedprice;
        
        if od >= 19930101 && od <= 19931231 
           && disc >= 1 && disc <= 3 
           && quant < 25 
        {
            var prod := (price as native_u64) * (disc as native_u64);
            if (sum as int) + (prod as int) < 18446744073709551616 {
                sum := ((sum as int) + (prod as int)) as native_u64;
            }
        }
        i := i + 1;
    }
    return sum;
}
