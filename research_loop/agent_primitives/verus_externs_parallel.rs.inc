// === Agent primitives: parallel scan/agg (LEMMA_ENABLE_PARALLEL=1 or LEMMA_FAST_TRUSTEDS=1) ===
//
// Exec bodies may use std::thread (chunked wrapping reduce). We are not proving the parallel
// implementation; we trust result == serial_wrapping_spec(...) — see agent_primitives/tests/equiv.rs.

pub open spec fn par_sum_u64_spec(vals: Seq<u64>) -> u64 {
    par_sum_u64_fold(vals, 0, 0)
}

pub open spec fn par_sum_u64_fold(vals: Seq<u64>, i: int, acc: u64) -> u64
    decreases vals.len() - i,
{
    if i >= vals.len() {
        acc
    } else {
        par_sum_u64_fold(vals, i + 1, wrapping_add_u64(acc, vals[i]))
    }
}

pub open spec fn par_filter_sum_u64_pair_len(col: Seq<u64>, mask: Seq<bool>) -> int {
    if col.len() < mask.len() {
        col.len()
    } else {
        mask.len()
    }
}

pub open spec fn par_filter_sum_u64_spec(col: Seq<u64>, mask: Seq<bool>) -> u64 {
    par_filter_sum_u64_fold(col, mask, 0, 0)
}

pub open spec fn par_filter_sum_u64_fold(
    col: Seq<u64>,
    mask: Seq<bool>,
    i: int,
    acc: u64,
) -> u64
    decreases par_filter_sum_u64_pair_len(col, mask) - i,
{
    let n = par_filter_sum_u64_pair_len(col, mask);
    if i >= n {
        acc
    } else if mask[i] {
        par_filter_sum_u64_fold(col, mask, i + 1, wrapping_add_u64(acc, col[i]))
    } else {
        par_filter_sum_u64_fold(col, mask, i + 1, acc)
    }
}

pub open spec fn vector_filter_sum_u64_pair_len(dates: Seq<u32>, amounts: Seq<u64>) -> int {
    if dates.len() < amounts.len() {
        dates.len()
    } else {
        amounts.len()
    }
}

pub open spec fn vector_filter_sum_u64_spec(
    dates: Seq<u32>,
    amounts: Seq<u64>,
    lo: u32,
    hi: u32,
) -> u64 {
    vector_filter_sum_u64_fold(dates, amounts, lo, hi, 0, 0)
}

pub open spec fn vector_filter_sum_u64_fold(
    dates: Seq<u32>,
    amounts: Seq<u64>,
    lo: u32,
    hi: u32,
    i: int,
    acc: u64,
) -> u64
    decreases vector_filter_sum_u64_pair_len(dates, amounts) - i,
{
    let n = vector_filter_sum_u64_pair_len(dates, amounts);
    if i >= n {
        acc
    } else {
        let d = dates[i];
        if lo <= d && d <= hi {
            vector_filter_sum_u64_fold(
                dates,
                amounts,
                lo,
                hi,
                i + 1,
                wrapping_add_u64(acc, amounts[i]),
            )
        } else {
            vector_filter_sum_u64_fold(dates, amounts, lo, hi, i + 1, acc)
        }
    }
}

const PAR_CHUNK: usize = 1 << 16;
const PAR_MAX_THREADS: usize = 64;

#[verifier::external_body]
fn par_exec_thread_count(len: usize) -> (n: usize)
    ensures n >= 1,
{
    if len < PAR_CHUNK {
        1
    } else {
        match std::thread::available_parallelism() {
            Ok(p) => {
                let t = p.get();
                if t > PAR_MAX_THREADS {
                    PAR_MAX_THREADS
                } else if t < 1 {
                    1
                } else {
                    t
                }
            }
            Err(_) => 1,
        }
    }
}

#[verifier::external_body]
pub exec fn par_sum_u64(vals: &Vec<u64>) -> (sum: u64)
    ensures sum == par_sum_u64_spec(vals@),
{
    let len = vals.len();
    if len < PAR_CHUNK {
        let mut sum: u64 = 0;
        let mut i: usize = 0;
        while i < len {
            sum = sum.wrapping_add(vals[i]);
            i = i + 1;
        }
        sum
    } else {
        let threads = par_exec_thread_count(len);
        std::thread::scope(|scope| {
            let chunk = (len + threads - 1) / threads;
            let mut handles: Vec<std::thread::ScopedJoinHandle<u64>> = Vec::new();
            let mut t: usize = 0;
            while t < threads {
                let start = t * chunk;
                if start >= len {
                    break;
                }
                let end = if start + chunk < len { start + chunk } else { len };
                handles.push(scope.spawn(|| {
                    let mut partial: u64 = 0;
                    let mut i = start;
                    while i < end {
                        partial = partial.wrapping_add(vals[i]);
                        i = i + 1;
                    }
                    partial
                }));
                t = t + 1;
            }
            let mut sum: u64 = 0;
            for h in handles {
                sum = sum.wrapping_add(h.join().unwrap());
            }
            sum
        })
    }
}

#[verifier::external_body]
pub exec fn par_filter_sum_u64(col: &Vec<u64>, mask: &Vec<bool>) -> (sum: u64)
    ensures sum == par_filter_sum_u64_spec(col@, mask@),
{
    let n = if col.len() < mask.len() { col.len() } else { mask.len() };
    if n < PAR_CHUNK {
        let mut sum: u64 = 0;
        let mut i: usize = 0;
        while i < n {
            if mask[i] {
                sum = sum.wrapping_add(col[i]);
            }
            i = i + 1;
        }
        sum
    } else {
        let threads = par_exec_thread_count(n);
        std::thread::scope(|scope| {
            let chunk = (n + threads - 1) / threads;
            let mut handles: Vec<std::thread::ScopedJoinHandle<u64>> = Vec::new();
            let mut t: usize = 0;
            while t < threads {
                let start = t * chunk;
                if start >= n {
                    break;
                }
                let end = if start + chunk < n { start + chunk } else { n };
                handles.push(scope.spawn(|| {
                    let mut partial: u64 = 0;
                    let mut i = start;
                    while i < end {
                        if mask[i] {
                            partial = partial.wrapping_add(col[i]);
                        }
                        i = i + 1;
                    }
                    partial
                }));
                t = t + 1;
            }
            let mut sum: u64 = 0;
            for h in handles {
                sum = sum.wrapping_add(h.join().unwrap());
            }
            sum
        })
    }
}

#[verifier::external_body]
pub exec fn par_probe_sum_u64(
    probe_keys: &Vec<u32>,
    values: &Vec<u64>,
    build: &HashSetWithView<u32>,
) -> (sum: u64)
    ensures sum == probe_sum_u64_spec(probe_keys@, values@, build@),
{
    let n = if probe_keys.len() < values.len() {
        probe_keys.len()
    } else {
        values.len()
    };
    if n < PAR_CHUNK {
        let mut sum: u64 = 0;
        let mut i: usize = 0;
        while i < n {
            if build.contains(&probe_keys[i]) {
                sum = sum.wrapping_add(values[i]);
            }
            i = i + 1;
        }
        sum
    } else {
        // Read-only contains across std threads; wrapping reduce ≡ serial probe_sum_u64_spec.
        let threads = par_exec_thread_count(n);
        std::thread::scope(|scope| {
            let chunk = (n + threads - 1) / threads;
            let mut handles: Vec<std::thread::ScopedJoinHandle<u64>> = Vec::new();
            let mut t: usize = 0;
            while t < threads {
                let start = t * chunk;
                if start >= n {
                    break;
                }
                let end = if start + chunk < n { start + chunk } else { n };
                handles.push(scope.spawn(|| {
                    let mut partial: u64 = 0;
                    let mut i = start;
                    while i < end {
                        if build.contains(&probe_keys[i]) {
                            partial = partial.wrapping_add(values[i]);
                        }
                        i = i + 1;
                    }
                    partial
                }));
                t = t + 1;
            }
            let mut sum: u64 = 0;
            for h in handles {
                sum = sum.wrapping_add(h.join().unwrap());
            }
            sum
        })
    }
}

#[verifier::external_body]
pub exec fn vector_filter_sum_u64(
    dates: &Vec<u32>,
    amounts: &Vec<u64>,
    lo: u32,
    hi: u32,
) -> (sum: u64)
    ensures sum == vector_filter_sum_u64_spec(dates@, amounts@, lo, hi),
{
    let n = if dates.len() < amounts.len() {
        dates.len()
    } else {
        amounts.len()
    };
    if n < PAR_CHUNK {
        let mut sum: u64 = 0;
        let mut i: usize = 0;
        while i < n {
            let d = dates[i];
            if lo <= d && d <= hi {
                sum = sum.wrapping_add(amounts[i]);
            }
            i = i + 1;
        }
        sum
    } else {
        let threads = par_exec_thread_count(n);
        std::thread::scope(|scope| {
            let chunk = (n + threads - 1) / threads;
            let mut handles: Vec<std::thread::ScopedJoinHandle<u64>> = Vec::new();
            let mut t: usize = 0;
            while t < threads {
                let start = t * chunk;
                if start >= n {
                    break;
                }
                let end = if start + chunk < n { start + chunk } else { n };
                handles.push(scope.spawn(|| {
                    let mut partial: u64 = 0;
                    let mut i = start;
                    while i < end {
                        let d = dates[i];
                        if lo <= d && d <= hi {
                            partial = partial.wrapping_add(amounts[i]);
                        }
                        i = i + 1;
                    }
                    partial
                }));
                t = t + 1;
            }
            let mut sum: u64 = 0;
            for h in handles {
                sum = sum.wrapping_add(h.join().unwrap());
            }
            sum
        })
    }
}

/// Inner row ids where the string key matches, in increasing order.
pub open spec fn eq_inner_ids(key: Seq<char>, inner: Seq<String>, j: int) -> Seq<usize>
    decreases inner.len() - j,
{
    if j >= inner.len() {
        Seq::empty()
    } else if inner[j]@ == key {
        Seq::<usize>::empty().push(j as usize) + eq_inner_ids(key, inner, j + 1)
    } else {
        eq_inner_ids(key, inner, j + 1)
    }
}

pub open spec fn attach_outer_ids(outer_i: int, ids: Seq<usize>, j: int) -> Seq<(usize, usize)>
    decreases ids.len() - j,
{
    if j >= ids.len() {
        Seq::empty()
    } else {
        Seq::<(usize, usize)>::empty().push((outer_i as usize, ids[j]))
            + attach_outer_ids(outer_i, ids, j + 1)
    }
}

/// Ordered pair list of a string equijoin. Same pairs the serial probe produces.
pub open spec fn serial_eq_pairs_str_spec(outer: Seq<String>, inner: Seq<String>) -> Seq<(usize, usize)> {
    serial_eq_pairs_str_fold(outer, inner, 0)
}

pub open spec fn serial_eq_pairs_str_fold(
    outer: Seq<String>,
    inner: Seq<String>,
    i: int,
) -> Seq<(usize, usize)>
    decreases outer.len() - i,
{
    if i >= outer.len() {
        Seq::empty()
    } else {
        let ids = eq_inner_ids(outer[i]@, inner, 0);
        attach_outer_ids(i, ids, 0) + serial_eq_pairs_str_fold(outer, inner, i + 1)
    }
}

/// Threaded string equijoin. The ensures is the serial pair list, not the schedule.
#[verifier::external_body]
pub exec fn par_equijoin_pairs_str(
    outer: &Vec<String>,
    inner: &Vec<String>,
) -> (pairs: Vec<(usize, usize)>)
    ensures pairs@ == serial_eq_pairs_str_spec(outer@, inner@),
{
    let mut index: std::collections::HashMap<String, Vec<usize>> = std::collections::HashMap::new();
    let mut j: usize = 0;
    while j < inner.len() {
        index.entry(inner[j].clone()).or_insert_with(Vec::new).push(j);
        j = j + 1;
    }
    let n = outer.len();
    if n < PAR_CHUNK {
        let mut pairs: Vec<(usize, usize)> = Vec::new();
        let mut i: usize = 0;
        while i < n {
            match index.get(&outer[i]) {
                Some(ids) => {
                    let mut k: usize = 0;
                    while k < ids.len() {
                        pairs.push((i, ids[k]));
                        k = k + 1;
                    }
                },
                None => {},
            }
            i = i + 1;
        }
        pairs
    } else {
        let threads = par_exec_thread_count(n);
        std::thread::scope(|scope| {
            let chunk = (n + threads - 1) / threads;
            let mut handles: Vec<std::thread::ScopedJoinHandle<Vec<(usize, usize)>>> = Vec::new();
            let mut t: usize = 0;
            while t < threads {
                let start = t * chunk;
                if start >= n {
                    break;
                }
                let end = if start + chunk < n { start + chunk } else { n };
                handles.push(scope.spawn(|| {
                    let mut partial: Vec<(usize, usize)> = Vec::new();
                    let mut i = start;
                    while i < end {
                        match index.get(&outer[i]) {
                            Some(ids) => {
                                let mut k: usize = 0;
                                while k < ids.len() {
                                    partial.push((i, ids[k]));
                                    k = k + 1;
                                }
                            },
                            None => {},
                        }
                        i = i + 1;
                    }
                    partial
                }));
                t = t + 1;
            }
            let mut pairs: Vec<(usize, usize)> = Vec::new();
            for h in handles {
                pairs.extend(h.join().unwrap());
            }
            pairs
        })
    }
}
