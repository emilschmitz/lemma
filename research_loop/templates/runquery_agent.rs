//! Host-owned shell — edit ONLY between AGENT_EDIT_START/END.
//! MethodSpec + Trusted: context/ro/spec.rs (read-only; do not redefine).

use vstd::prelude::*;
// Types below are provided when host assembles with spec.rs.

verus! {

// AGENT_EDIT_START
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    // TODO: implement hot path to match method_spec (see context/ro/spec.rs)
    0u64
}
// AGENT_EDIT_END

} // verus!
