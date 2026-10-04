// STREAM-like read-bandwidth probe (unverified measurement tool, not product code).
// Each of T threads sums its own private 256 MiB region of u64 (read-only scan), best of 5.
use std::time::Instant;

fn main() {
    let words_per_thread: usize = (1usize << 28) / 8;
    for t in [1usize, 2, 4, 8] {
        let data: Vec<Vec<u64>> = (0..t)
            .map(|j| (0..words_per_thread).map(|i| (i as u64) ^ (j as u64)).collect())
            .collect();
        let mut best = f64::MAX;
        for _ in 0..5 {
            let t0 = Instant::now();
            let total: u64 = std::thread::scope(|s| {
                let hs: Vec<_> = data
                    .iter()
                    .map(|v| s.spawn(move || v.iter().fold(0u64, |a, &x| a.wrapping_add(x))))
                    .collect();
                hs.into_iter().map(|h| h.join().unwrap()).fold(0u64, |a, x| a.wrapping_add(x))
            });
            std::hint::black_box(total);
            best = best.min(t0.elapsed().as_secs_f64());
        }
        let gib = t as f64 / 4.0;
        println!("read_threads={t} GiB/s={:.1}", gib / best);
    }
    // copy (read+write) single and 8 threads, 512 MiB per thread
    for t in [1usize, 8] {
        let n = (1usize << 27) / 8;
        let src: Vec<Vec<u64>> = (0..t).map(|_| vec![1u64; n]).collect();
        let mut dst: Vec<Vec<u64>> = (0..t).map(|_| vec![0u64; n]).collect();
        let mut best = f64::MAX;
        for _ in 0..5 {
            let t0 = Instant::now();
            std::thread::scope(|s| {
                for (d, sv) in dst.iter_mut().zip(src.iter()) {
                    s.spawn(move || d.copy_from_slice(sv));
                }
            });
            best = best.min(t0.elapsed().as_secs_f64());
        }
        println!("copy_threads={t} GiB/s(read+write counted once)={:.1}", 0.125 * t as f64 / best);
    }
}
