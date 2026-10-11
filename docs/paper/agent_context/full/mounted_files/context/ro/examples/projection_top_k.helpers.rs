proof fn lemma_tail(s: Seq<OutRow>, p: int, x: OutRow, i: int, k: (int, int))
    requires
        0 <= p <= s.len(),
        p <= i,
    ensures
        out_copies(s.insert(p, x), i + 1, k) == out_copies(s, i, k),
    decreases s.len() - i,
{
    if i < s.len() {
        lemma_tail(s, p, x, i + 1, k);
        assert(s.insert(p, x)[i + 1] == s[i]);
    }
}

proof fn lemma_insert(s: Seq<OutRow>, p: int, x: OutRow, i: int, k: (int, int))
    requires
        0 <= i <= p <= s.len(),
    ensures
        out_copies(s.insert(p, x), i, k) == out_copies(s, i, k) + (if out_key(x) == k { 1int } else { 0int }),
    decreases p - i,
{
    if i < p {
        assert(s.insert(p, x)[i] == s[i]);
        lemma_insert(s, p, x, i + 1, k);
    } else {
        assert(s.insert(p, x)[p] == x);
        lemma_tail(s, p, x, p, k);
    }
}

proof fn lemma_drop(s: Seq<OutRow>, i: int, k: (int, int))
    requires
        s.len() > 0,
        0 <= i,
    ensures
        out_copies(s.drop_last(), i, k) + (if i < s.len() && out_key(s.last()) == k { 1int } else { 0int })
            == out_copies(s, i, k),
    decreases s.len() - i,
{
    if i < s.len() - 1 {
        assert(s.drop_last()[i] == s[i]);
        lemma_drop(s, i + 1, k);
    } else if i == s.len() - 1 {
        assert(s[i] == s.last());
        assert(out_copies(s, i + 1, k) == 0);
        assert(out_copies(s.drop_last(), i, k) == 0);
    }
}
