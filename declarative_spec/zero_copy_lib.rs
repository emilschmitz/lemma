// LEMMA_ZERO_COPY: a column borrowed from pinned DuckDB result chunks. Verified host code, no `external_body`, no `assume`.
// The chunks have arbitrary lengths (DuckDB result chunks are at most 2048 rows and are NOT all full), `offs` are their start rows.
// Its view is the concatenation of the chunks, so every spec statement `t.c@[i]` of the emitted spec keeps its meaning.
// The slices are `'static`: the pin is leaked, never destroyed (ZC-1 item 2), so a column can be shared with spawned threads (`Arc`).
// What the lemma does not know, and the loader (`main`, plain Rust) checks and the proposal states: that each slice is the column's
// values in that chunk, alive and unmutated for the whole call (research_loop/menus/zero_copy_lease_PROPOSAL.md).
pub struct PinnedCol<T: 'static> {
    pub n: usize,
    pub chunks: Vec<&'static [T]>,
    pub offs: Vec<usize>,
}

impl<T: 'static> PinnedCol<T> {
    pub open spec fn off(&self, k: int) -> int {
        self.offs@[k] as int
    }

    pub open spec fn wf(&self) -> bool {
        &&& self.offs@.len() == self.chunks@.len() + 1
        &&& self.off(0) == 0
        &&& self.off(self.chunks@.len() as int) == self.n as int
        &&& forall|k: int| #![trigger self.offs@[k + 1]] 0 <= k < self.chunks@.len() ==> self.off(k + 1) == self.off(k) + self.chunks@[k]@.len()
        &&& forall|k: int| #![trigger self.chunks@[k]@.len()] 0 <= k < self.chunks@.len() ==> self.chunks@[k]@.len() > 0
    }

    pub open spec fn in_chunk(&self, k: int, i: int) -> bool {
        0 <= k < self.chunks@.len() && self.off(k) <= i < self.off(k + 1)
    }

    pub open spec fn chunk_of(&self, i: int) -> int {
        choose|k: int| self.in_chunk(k, i)
    }
}

impl<T: 'static> View for PinnedCol<T> {
    type V = Seq<T>;

    open spec fn view(&self) -> Seq<T> {
        Seq::new(self.n as nat, |i: int| self.chunks@[self.chunk_of(i)]@[i - self.off(self.chunk_of(i))])
    }
}

pub proof fn lemma_offs_mono<T: 'static>(c: &PinnedCol<T>, k: int, l: int)
    requires
        c.wf(),
        0 <= k <= l <= c.chunks@.len(),
    ensures
        c.off(k) <= c.off(l),
    decreases l - k,
{
    if k < l {
        lemma_offs_mono(c, k, l - 1);
        let m = l - 1;
        assert(c.off(m + 1) == c.off(m) + c.chunks@[m]@.len());
        assert(m + 1 == l);
    }
}

/// A column has at most one chunk per row (chunks are non-empty), so the chunk count is bounded by the row count.
pub proof fn lemma_chunk_count<T: 'static>(c: &PinnedCol<T>, k: int)
    requires
        c.wf(),
        0 <= k <= c.chunks@.len(),
    ensures
        c.off(k) >= k,
    decreases k,
{
    if k > 0 {
        lemma_chunk_count(c, k - 1);
        let m = k - 1;
        assert(c.off(m + 1) == c.off(m) + c.chunks@[m]@.len());
        assert(c.chunks@[m]@.len() > 0);
    }
}

/// Row `offs[k] + j` of the column is cell `j` of chunk `k`.
pub proof fn lemma_cell<T: 'static>(c: &PinnedCol<T>, k: int, j: int)
    requires
        c.wf(),
        0 <= k < c.chunks@.len(),
        0 <= j < c.chunks@[k]@.len(),
    ensures
        0 <= c.off(k) + j < c.n as int,
        c@[c.off(k) + j] == c.chunks@[k]@[j],
{
    let g = c.off(k) + j;
    assert(c.off(k + 1) == c.off(k) + c.chunks@[k]@.len());
    lemma_offs_mono(c, k + 1, c.chunks@.len() as int);
    lemma_offs_mono(c, 0, k);
    assert(c.in_chunk(k, g));
    let k2 = c.chunk_of(g);
    assert(c.in_chunk(k2, g));
    if k2 < k {
        lemma_offs_mono(c, k2 + 1, k);
        assert(false);
    } else if k2 > k {
        lemma_offs_mono(c, k + 1, k2);
        assert(false);
    }
    assert(k2 == k);
}

impl<T: Copy + 'static> PinnedCol<T> {
    /// The chunk that holds row `i`, by binary search over the chunk start rows.
    pub fn find_chunk(&self, i: usize) -> (k: usize)
        requires
            self.wf(),
            i < self.n,
        ensures
            self.in_chunk(k as int, i as int),
    {
        let mut lo: usize = 0;
        let mut hi: usize = self.chunks.len();
        proof {
            assert(self.n as int == self.off(hi as int));
        }
        while hi - lo > 1
            invariant
                self.wf(),
                lo < hi <= self.chunks@.len(),
                self.off(lo as int) <= i as int,
                (i as int) < self.off(hi as int),
            decreases hi - lo,
        {
            let mid = lo + (hi - lo) / 2;
            if self.offs[mid] <= i {
                lo = mid;
            } else {
                hi = mid;
            }
        }
        proof {
            assert(hi == lo + 1);
        }
        lo
    }

    /// Random access: row `i` of the column. O(log chunks).
    pub fn get(&self, i: usize) -> (r: T)
        requires
            self.wf(),
            i < self.n,
        ensures
            r == self@[i as int],
    {
        let k = self.find_chunk(i);
        let j = i - self.offs[k];
        proof {
            assert(self.off(k as int + 1) == self.off(k as int) + self.chunks@[k as int]@.len());
            lemma_cell(self, k as int, j as int);
        }
        let c: &[T] = self.chunks[k];
        c[j]
    }
}
