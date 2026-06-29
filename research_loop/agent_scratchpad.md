# Agent Optimization Scratchpad

## Design Hypothesis
- Process elements iteratively in O(N) linear time.
- Accumulate the sum using suffix verification state `res + MethodSpec(data[i..]) == MethodSpec(data)`.

## Correctness & Proof Strategy
- Standard inductive invariant on the suffix slice of the sequence.

## Optimized Code Variant
```dafny
method RunQuery(data: seq<Row>) returns (res: int)
  ensures res == MethodSpec(data)
{
  res := 0;
  var i := 0;
  while i < |data|
    invariant 0 <= i <= |data|
    invariant res + MethodSpec(data[i..]) == MethodSpec(data)
  {
    var row := data[i];
    var term := if ((((row.LO_ORDERDATE >= 19930101 && row.LO_ORDERDATE <= 19931231) && row.LO_DISCOUNT >= 1) && row.LO_DISCOUNT <= 3) && row.LO_QUANTITY < 25) then row.LO_EXTENDEDPRICE * row.LO_DISCOUNT else 0;
    res := res + term;
    i := i + 1;
  }
}
```
