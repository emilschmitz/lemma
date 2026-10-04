use vstd::prelude::*;
use vstd::thread::*;

verus! {

pub const LEMMA_MAX_ROWS: usize = 2_000_000;

// ---- identical to proved/q01_filter_sum.rs ----
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

// ---- the single-threaded fold (same loop/invariants), returning the pair ----
pub exec fn chunk_fold(cols: &Cols) -> (res: (u128, u64))
    requires
        valid_cols(cols),
    ensures
        res.0 as int == sum_count_helper(cols, 0).0,
        res.1 as int == sum_count_helper(cols, 0).1,
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
    (sum, cnt)
}

// ---- Seq-level spec of the same fold, and concatenation ----
pub open spec fn sc(d: Seq<u32>, a: Seq<u64>) -> (int, int)
    decreases d.len(),
{
    if d.len() == 0 || a.len() != d.len() {
        (0, 0)
    } else {
        let (s, c) = sc(d.skip(1), a.skip(1));
        if d[0] >= 100 && d[0] <= 500 {
            (s + (a[0] as int), c + 1)
        } else {
            (s, c)
        }
    }
}

pub open spec fn method_spec_seq(d: Seq<u32>, a: Seq<u64>) -> Option<u128> {
    let (s, c) = sc(d, a);
    if c == 0 {
        None
    } else {
        Some(s as u128)
    }
}

proof fn lemma_helper_is_sc(cols: &Cols, k: int)
    requires
        valid_cols(cols),
        0 <= k <= cols.n,
    ensures
        sum_count_helper(cols, k) == sc(cols.d@.skip(k), cols.amount@.skip(k)),
    decreases cols.n - k,
{
    if k < cols.n {
        lemma_helper_is_sc(cols, k + 1);
        assert(cols.d@.skip(k).skip(1) =~= cols.d@.skip(k + 1));
        assert(cols.amount@.skip(k).skip(1) =~= cols.amount@.skip(k + 1));
    }
}

proof fn lemma_sc_add(d1: Seq<u32>, a1: Seq<u64>, d2: Seq<u32>, a2: Seq<u64>)
    requires
        d1.len() == a1.len(),
        d2.len() == a2.len(),
    ensures
        sc(d1 + d2, a1 + a2).0 == sc(d1, a1).0 + sc(d2, a2).0,
        sc(d1 + d2, a1 + a2).1 == sc(d1, a1).1 + sc(d2, a2).1,
    decreases d1.len(),
{
    if d1.len() == 0 {
        assert(d1 + d2 =~= d2);
        assert(a1 + a2 =~= a2);
    } else {
        lemma_sc_add(d1.skip(1), a1.skip(1), d2, a2);
        assert((d1 + d2).skip(1) =~= d1.skip(1) + d2);
        assert((a1 + a2).skip(1) =~= a1.skip(1) + a2);
        assert((d1 + d2)[0] == d1[0]);
        assert((a1 + a2)[0] == a1[0]);
    }
}

proof fn lemma_sc_bound(d: Seq<u32>, a: Seq<u64>)
    requires
        d.len() == a.len(),
    ensures
        0 <= sc(d, a).0 <= (d.len() as int) * (u64::MAX as int),
        0 <= sc(d, a).1 <= d.len(),
    decreases d.len(),
{
    if d.len() > 0 {
        lemma_sc_bound(d.skip(1), a.skip(1));
        assert(((d.len() - 1) as int) * (u64::MAX as int) + u64::MAX as int == (d.len() as int)
            * (u64::MAX as int)) by (nonlinear_arith);
    }
}

pub open spec fn cat_d(cs: Seq<Cols>, w: int) -> Seq<u32>
    decreases w,
{
    if w <= 0 {
        Seq::empty()
    } else {
        cat_d(cs, w - 1) + cs[w - 1].d@
    }
}

pub open spec fn cat_a(cs: Seq<Cols>, w: int) -> Seq<u64>
    decreases w,
{
    if w <= 0 {
        Seq::empty()
    } else {
        cat_a(cs, w - 1) + cs[w - 1].amount@
    }
}

pub open spec fn all_valid(cs: Seq<Cols>) -> bool {
    forall|j: int| 0 <= j < cs.len() ==> valid_cols(&#[trigger] cs[j])
}

proof fn lemma_cat_len(cs: Seq<Cols>, w: int)
    requires
        all_valid(cs),
        0 <= w <= cs.len(),
    ensures
        cat_d(cs, w).len() == cat_a(cs, w).len(),
        w < cs.len() ==> cat_d(cs, w + 1).len() == cat_d(cs, w).len() + cs[w].n,
    decreases w,
{
    if w > 0 {
        lemma_cat_len(cs, w - 1);
    }
}

proof fn lemma_cat_prefix_len(cs: Seq<Cols>, w1: int, w2: int)
    requires
        0 <= w1 <= w2 <= cs.len(),
    ensures
        cat_d(cs, w1).len() <= cat_d(cs, w2).len(),
    decreases w2 - w1,
{
    if w1 < w2 {
        lemma_cat_prefix_len(cs, w1 + 1, w2);
    }
}

// What one joined worker returns: its chunk back, plus the partial fold.
pub open spec fn part_ok(c: Cols, ret: (Cols, u128, u64)) -> bool {
    &&& ret.0.d@ == c.d@
    &&& ret.0.amount@ == c.amount@
    &&& ret.0.n == c.n
    &&& ret.1 as int == sc(c.d@, c.amount@).0
    &&& ret.2 as int == sc(c.d@, c.amount@).1
}

/// The parallel result is the SAME statement as the single-threaded ensures: for any whole
/// table whose columns are the concatenation of the chunks, method_spec(whole) is what
/// par_run_query returns.
pub proof fn lemma_same_as_single_threaded(whole: &Cols, d: Seq<u32>, a: Seq<u64>)
    requires
        valid_cols(whole),
        whole.d@ == d,
        whole.amount@ == a,
    ensures
        method_spec(whole) == method_spec_seq(d, a),
{
    lemma_helper_is_sc(whole, 0);
    assert(d.skip(0) =~= d);
    assert(a.skip(0) =~= a);
}

pub open spec fn handle_ok(h: JoinHandle<(Cols, u128, u64)>, c: Cols) -> bool {
    forall|ret: (Cols, u128, u64)| #[trigger] h.predicate(ret) ==> part_ok(c, ret)
}

pub open spec fn same_chunk(a: Cols, b: Cols) -> bool {
    a.d@ == b.d@ && a.amount@ == b.amount@ && a.n == b.n
}

#[verifier::exec_allows_no_decreases_clause]
pub exec fn par_run_query(chunks: &mut Vec<Cols>) -> (res: Option<u128>)
    requires
        all_valid(old(chunks)@),
        cat_d(old(chunks)@, old(chunks)@.len() as int).len() <= LEMMA_MAX_ROWS,
    ensures
        final(chunks)@.len() == old(chunks)@.len(),
        forall|j: int|
            0 <= j < old(chunks)@.len() ==> same_chunk(#[trigger] final(chunks)@[j], old(chunks)@[j]),
        res == method_spec_seq(
            cat_d(old(chunks)@, old(chunks)@.len() as int),
            cat_a(old(chunks)@, old(chunks)@.len() as int),
        ),
{
    let ghost orig = chunks@;
    let w = chunks.len();
    let mut handles: Vec<JoinHandle<(Cols, u128, u64)>> = Vec::new();
    // spawn: pops chunks from the back; handles[m] <-> orig[w-1-m]
    while chunks.len() > 0
        invariant
            all_valid(orig),
            chunks@ == orig.subrange(0, chunks@.len() as int),
            handles@.len() + chunks@.len() == w,
            w == orig.len(),
            forall|m: int|
                0 <= m < handles@.len() ==> handle_ok(#[trigger] handles@[m], orig[w as int - 1 - m]),
        decreases chunks.len(),
    {
        let c = chunks.pop().unwrap();
        let ghost cg = c;
        proof {
            assert(orig[chunks@.len() as int] == c);
            assert(valid_cols(&c));
        }
        let h = spawn(
            move || -> (r: (Cols, u128, u64))
                requires
                    valid_cols(&c),
                ensures
                    part_ok(c, r),
                {
                    let (s, n) = chunk_fold(&c);
                    proof {
                        lemma_helper_is_sc(&c, 0);
                        assert(c.d@.skip(0) =~= c.d@);
                        assert(c.amount@.skip(0) =~= c.amount@);
                    }
                    (c, s, n)
                },
        );
        proof {
            assert(handle_ok(h, cg));
        }
        let ghost old_handles = handles@;
        handles.push(h);
        proof {
            let m = handles@.len() as int - 1;
            assert(handles@[m] == h);
            assert(orig[w as int - 1 - m] == cg);
            assert forall|m2: int| 0 <= m2 < handles@.len() implies handle_ok(
                #[trigger] handles@[m2],
                orig[w as int - 1 - m2],
            ) by {
                if m2 < m {
                    assert(handles@[m2] == old_handles[m2]);
                }
            }
        }
    }
    // join in forward order: handles.pop() yields orig[0], orig[1], ...
    let mut sum: u128 = 0;
    let mut cnt: u64 = 0;
    let mut joined: usize = 0;
    let mut out: Vec<Cols> = Vec::new();
    while handles.len() > 0
        invariant
            all_valid(orig),
            w == orig.len(),
            cat_d(orig, w as int).len() <= LEMMA_MAX_ROWS,
            joined + handles@.len() == w,
            out@.len() == joined,
            forall|j: int| 0 <= j < joined ==> same_chunk(#[trigger] out@[j], orig[j]),
            forall|m: int|
                0 <= m < handles@.len() ==> handle_ok(#[trigger] handles@[m], orig[w as int - 1 - m]),
            sum as int == sc(cat_d(orig, joined as int), cat_a(orig, joined as int)).0,
            cnt as int == sc(cat_d(orig, joined as int), cat_a(orig, joined as int)).1,
        decreases handles.len(),
    {
        let ghost old_handles = handles@;
        let h = handles.pop().unwrap();
        let ghost m = handles@.len() as int;
        assert(h == old_handles[m]);
        assert(handle_ok(h, orig[w as int - 1 - m]));
        let r = match h.join() {
            Ok(r) => r,
            Err(_) => {
                // vstd's join returns Err only on a panicked worker; our workers cannot panic
                // (proved panic-free), but the trusted wrapper does not say so.
                loop {}
            },
        };
        proof {
            assert(part_ok(orig[w as int - 1 - m], r));
            assert(w as int - 1 - m == joined as int);
            lemma_cat_len(orig, joined as int);
            lemma_sc_add(
                cat_d(orig, joined as int),
                cat_a(orig, joined as int),
                orig[joined as int].d@,
                orig[joined as int].amount@,
            );
            assert(cat_d(orig, joined as int + 1) == cat_d(orig, joined as int) + orig[joined as int].d@);
            assert(cat_a(orig, joined as int + 1) == cat_a(orig, joined as int) + orig[joined as int].amount@);
            lemma_sc_bound(cat_d(orig, joined as int + 1), cat_a(orig, joined as int + 1));
            lemma_cat_len(orig, joined as int + 1);
            lemma_cat_prefix_len(orig, joined as int + 1, w as int);
            lemma_rows_fit();
            let ln = cat_d(orig, joined as int + 1).len() as int;
            assert(ln <= LEMMA_MAX_ROWS);
            assert(ln * (u64::MAX as int) <= LEMMA_MAX_ROWS as int * (u64::MAX as int)) by (nonlinear_arith)
                requires ln <= LEMMA_MAX_ROWS, ln >= 0;
        }
        let (c, s, n) = r;
        sum = sum + s;
        cnt = cnt + n;
        out.push(c);
        joined = joined + 1;
        proof {
            assert forall|j: int| 0 <= j < joined implies same_chunk(#[trigger] out@[j], orig[j]) by {
                if j < joined - 1 {
                }
            }
        }
    }
    *chunks = out;
    if cnt == 0 {
        None
    } else {
        Some(sum)
    }
}

}

fn env_usize(key: &str) -> usize {
    std::env::var(key).unwrap().parse().unwrap()
}

fn main() {
    let n = env_usize("SPEED_ROWS");
    let w = env_usize("SPEED_THREADS");
    let mut chunks: Vec<Cols> = Vec::new();
    for j in 0..w {
        let lo = n * j / w;
        let hi = n * (j + 1) / w;
        let mut d = Vec::with_capacity(hi - lo);
        let mut amount = Vec::with_capacity(hi - lo);
        for i in lo..hi {
            d.push((i % 10000) as u32);
            amount.push(((i as u64) * 17) % 1000);
        }
        chunks.push(Cols { n: hi - lo, d, amount });
    }
    for _ in 0..env_usize("SPEED_WARMUP") {
        let _ = par_run_query(&mut chunks);
    }
    let mut samples = Vec::new();
    let mut last = None;
    for _ in 0..env_usize("SPEED_RUNS") {
        let t0 = std::time::Instant::now();
        last = Some(par_run_query(&mut chunks));
        samples.push(t0.elapsed().as_micros());
    }
    samples.sort();
    println!("RESULT:{:?}", last.unwrap());
    println!("SAMPLES_US:{samples:?}");
    println!("MEDIAN_US:{}", samples[samples.len() / 2]);
}
