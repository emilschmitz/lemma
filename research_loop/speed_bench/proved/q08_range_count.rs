use vstd::prelude::*;

verus! {

pub const LEMMA_MAX_ROWS: usize = 2_000_000;

pub struct Cols {
    pub n: usize,
    pub d: Vec<u32>,
}

impl Cols {
    pub open spec fn get_d(self, i: int) -> u32 {
        self.d[i as int]
    }

    #[verifier::external_body]
    pub exec fn get_d_exec(&self, i: usize) -> (res: u32)
        requires
            i < self.n,
        ensures
            res == self.get_d(i as int),
    {
        self.d[i]
    }
}

pub open spec fn valid_cols(cols: &Cols) -> bool {
    &&& cols.n <= LEMMA_MAX_ROWS
    &&& cols.d.len() == cols.n
}

pub open spec fn method_spec_helper(cols: &Cols, k: int) -> u64
    recommends
        0 <= k && k <= cols.n,
        valid_cols(cols),
    decreases cols.n - k,
{
    if k < cols.n {
        if cols.get_d(k) >= 0 && cols.get_d(k) <= 100 {
            (method_spec_helper(cols, k + 1) as int + 1u64 as int) as u64
        } else {
            method_spec_helper(cols, k + 1)
        }
    } else {
        0u64
    }
}

pub open spec fn method_spec(cols: &Cols) -> u64
    recommends
        valid_cols(cols),
{
    method_spec_helper(cols, 0)
}

proof fn lemma_count_fits()
    ensures
        (LEMMA_MAX_ROWS as u64) < u64::MAX,
{
    assert((LEMMA_MAX_ROWS as u64) < u64::MAX) by (compute_only);
}

pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires
        valid_cols(cols),
    ensures
        res == method_spec(cols),
{
    let mut cnt: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            cnt == method_spec_helper(cols, i as int),
            cnt <= (cols.n - i) as u64,
        decreases i,
    {
        i = i - 1;
        let d = cols.get_d_exec(i);
        if d <= 100 {
            proof {
                lemma_count_fits();
            }
            assert(d as int >= 0);
            assert(cnt <= (cols.n - (i + 1)) as u64);
            assert(cnt as int + 1 <= (cols.n - i) as int);
            assert((cols.n - i) as int <= LEMMA_MAX_ROWS as int);
            assert(cnt as int + 1 < u64::MAX as int);
            cnt = cnt + 1;
        }
        assert(cnt == method_spec_helper(cols, i as int));
    }
    cnt
}

}

fn main() {
    let n: usize = 2_000_000;
    let mut d = Vec::with_capacity(n);
    for i in 0..n {
        d.push((i % 10000) as u32);
    }
    let cols = Cols { n, d };
    for _ in 0..2 {
        let _ = run_query(&cols);
    }
    let mut samples = Vec::with_capacity(5);
    let mut last = 0u64;
    for _ in 0..5 {
        let t0 = std::time::Instant::now();
        last = run_query(&cols);
        samples.push(t0.elapsed().as_micros());
    }
    samples.sort();
    println!("RESULT:{last}");
    println!("MEDIAN_US:{}", samples[samples.len() / 2]);
}
