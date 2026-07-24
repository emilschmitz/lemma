// Auto-assembled RunQuery (exec hot path — plain Rust, no postprocessor).
use crate::cols::Cols;
use lemma_native::{add_u64, mul_u64_u32};

pub fn format_result(res: &u64) -> String {
    format!("RESULT: {}", res)
}

// Host contract: requires valid_cols(cols); ensures res == method_spec(cols)
pub fn run_query(cols: &Cols) -> u64 {
    let n = cols.n;
        let mut acc: u64 = 0;
        for i in 0..n {
            let q = cols.lo_quantity[i];
            if q < 25
                && (1_993_0101 <= cols.lo_orderdate[i] && cols.lo_orderdate[i] <= 1_993_1231)
                && (1 <= cols.lo_discount[i] && cols.lo_discount[i] <= 3)
            {
                acc = add_u64(acc, mul_u64_u32(cols.lo_extendedprice[i], cols.lo_discount[i]));
            }
        }
        acc
}
