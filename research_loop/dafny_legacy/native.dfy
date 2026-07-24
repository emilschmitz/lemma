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

  method {:extern} {:axiom} ToU64Map() returns (m: map<(NativeU32, string), NativeU64>)
    ensures forall k :: k in Snapshot() ==> k in m && m[k] as int == Snapshot()[k] as int
    ensures forall k :: k in m ==> k in Snapshot()
}

class {:extern "NativeAggStrMap"} NativeAggStrMap {
  function {:extern} Snapshot(): map<(string, string), NativeU64>

  constructor {:extern} {:axiom} ()
    ensures Snapshot() == map[]

  method {:extern} {:axiom} Add(k0: string, k1: string, delta: NativeU64)
    modifies this
    ensures Snapshot() == old(Snapshot())[(k0, k1) := AddU64(
      if (k0, k1) in old(Snapshot()) then old(Snapshot())[(k0, k1)] else 0 as NativeU64,
      delta)]

  method {:extern} ToMap() returns (m: map<(string, string), NativeU64>)
    ensures m == Snapshot()
}
