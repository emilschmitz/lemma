proof fn lemma_shift(s: Seq<OutRow>, x: OutRow, i: int, k: (int, (bool, int)))
    requires
        0 <= i,
    ensures
        out_copies(s.insert(0, x), i + 1, k) == out_copies(s, i, k),
    decreases s.len() - i,
{
    if i < s.len() {
        lemma_shift(s, x, i + 1, k);
        assert(s.insert(0, x)[i + 1] == s[i]);
    }
}
