use vstd::prelude::*;

verus! {

pub const LEMMA_MAX_ROWS: usize = 2_000_000;

pub struct Cols {
    pub n: usize,
    pub d: Vec<u32>,
    pub amount: Vec<u64>,
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

    pub open spec fn get_amount(self, i: int) -> u64 {
        self.amount[i as int]
    }

    #[verifier::external_body]
    pub exec fn get_amount_exec(&self, i: usize) -> (res: u64)
        requires
            i < self.n,
        ensures
            res == self.get_amount(i as int),
    {
        self.amount[i]
    }
}

pub open spec fn valid_cols(cols: &Cols) -> bool {
    &&& cols.n <= LEMMA_MAX_ROWS
    &&& cols.d.len() == cols.n
    &&& cols.amount.len() == cols.n
}

pub open spec fn sum_count_helper(cols: &Cols, k: int) -> (int, int)
    recommends
        0 <= k && k <= cols.n,
        valid_cols(cols),
    decreases cols.n - k,
{
    if k < cols.n {
        let (s, c) = sum_count_helper(cols, k + 1);
        if cols.get_d(k) >= 100 && cols.get_d(k) <= 500 {
            (s + (cols.get_amount(k) as int), c + 1)
        } else {
            (s, c)
        }
    } else {
        (0, 0)
    }
}

pub open spec fn method_spec(cols: &Cols) -> Option<u128>
    recommends
        valid_cols(cols),
{
    let (s, c) = sum_count_helper(cols, 0);
    if c == 0 {
        None
    } else {
        Some(s as u128)
    }
}

proof fn lemma_rows_fit()
    ensures
        (LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX,
{
    assert((LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX) by (compute_only);
}

pub exec fn run_query(cols: &Cols) -> (res: Option<u128>)
    requires
        valid_cols(cols),
    ensures
        res == method_spec(cols),
{
    let mut sum: u128 = 0;
    let mut cnt: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            sum as int == sum_count_helper(cols, i as int).0,
            cnt as int == sum_count_helper(cols, i as int).1,
            cnt <= (cols.n - i) as u64,
            sum <= ((cols.n - i) as u128) * (u64::MAX as u128),
        decreases i,
    {
        i = i - 1;
        let d = cols.get_d_exec(i);
        let a = cols.get_amount_exec(i);
        if d >= 100 && d <= 500 {
            assert(sum <= ((cols.n - (i + 1)) as u128) * (u64::MAX as u128));
            proof {
                lemma_rows_fit();
            }
            assert(a as u128 <= u64::MAX as u128);
            assert(sum + (a as u128) <= ((cols.n - i) as u128) * (u64::MAX as u128)) by (nonlinear_arith)
                requires
                    sum <= ((cols.n - (i + 1)) as u128) * (u64::MAX as u128),
                    a as u128 <= u64::MAX as u128,
                    (cols.n - i) as u128 == (cols.n - (i + 1)) as u128 + 1,
            {
            };
            assert(((cols.n - i) as u128) * (u64::MAX as u128) <= u128::MAX) by (nonlinear_arith)
                requires
                    cols.n <= LEMMA_MAX_ROWS,
                    i < cols.n,
                    (LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX,
            {
            };
            sum = sum + (a as u128);
            cnt = cnt + 1;
        }
        assert(sum as int == sum_count_helper(cols, i as int).0);
        assert(cnt as int == sum_count_helper(cols, i as int).1);
    }
    if cnt == 0 {
        None
    } else {
        Some(sum)
    }
}

}

fn main() {
    let n: usize = 2_000_000;
    let mut d = Vec::with_capacity(n);
    let mut amount = Vec::with_capacity(n);
    for i in 0..n {
        d.push((i % 10000) as u32);
        amount.push(((i as u64) * 17) % 1000);
    }
    let cols = Cols { n, d, amount };
    for _ in 0..2 {
        let _ = run_query(&cols);
    }
    let mut samples = Vec::with_capacity(5);
    let mut last = None;
    for _ in 0..5 {
        let t0 = std::time::Instant::now();
        last = Some(run_query(&cols));
        samples.push(t0.elapsed().as_micros());
    }
    samples.sort();
    println!("RESULT:{:?}", last.unwrap());
    println!("MEDIAN_US:{}", samples[samples.len() / 2]);
}
