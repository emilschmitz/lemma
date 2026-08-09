//! Host-owned shell — edit ONLY between AGENT_BODY_START/END.
//! Cols / method_spec / valid_cols live in context/ro/spec.rs (not inlined).

use vstd::prelude::*;
// Types below are provided when host assembles with spec.rs.

verus! {

pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
// AGENT_BODY_START
    // TODO: implement hot path to match method_spec (see context/ro/spec.rs)
    0u64
// AGENT_BODY_END
}

} // verus!
