pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut res: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),
            res <= (cols.n - i) as u64,
        decreases i,
    {
        i = i - 1;
        assert(res <= (cols.n - (i + 1)) as u64);
        let line = cols.get_line_exec(i);
        if line > 0 {
            proof {
                lemma_u64_add_one_fit(res, cols.n);
            }
            res = add_u64(res, 1);
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}
