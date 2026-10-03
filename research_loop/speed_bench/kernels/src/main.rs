//! Hardware-close speed kernels for the fixed speed_bench generator.
//!
//! On this generator every aggregate fits in i64 with ordinary addition (amounts are
//! 0..999, N is far below i64 limits). Wrapping arithmetic is used only where the
//! mathematical result is still exact on this data — not a license to wrap on adversarial
//! inputs. Trust config: `hardware` / product transpiler.

use std::env;
use std::fs::File;
use std::io::{self, Read};
use std::time::Instant;

struct Cols {
    n: usize,
    k: Vec<i32>,
    k2: Vec<i32>,
    d: Vec<i32>,
    flag: Vec<i32>,
    amount: Vec<i64>,
    dim_id: Vec<i32>,
    dim_w: Vec<i64>,
}

fn read_u32(r: &mut impl Read) -> io::Result<u32> {
    let mut b = [0u8; 4];
    r.read_exact(&mut b)?;
    Ok(u32::from_le_bytes(b))
}

fn read_u64(r: &mut impl Read) -> io::Result<u64> {
    let mut b = [0u8; 8];
    r.read_exact(&mut b)?;
    Ok(u64::from_le_bytes(b))
}

fn read_i32(r: &mut impl Read) -> io::Result<i32> {
    Ok(read_u32(r)? as i32)
}

fn read_i64(r: &mut impl Read) -> io::Result<i64> {
    Ok(read_u64(r)? as i64)
}

fn load_cols(path: &str) -> io::Result<Cols> {
    let mut f = File::open(path)?;
    let mut magic = [0u8; 4];
    f.read_exact(&mut magic)?;
    if &magic != b"LMSP" {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "bad magic"));
    }
    let n = read_u64(&mut f)? as usize;
    let mut k = Vec::with_capacity(n);
    let mut k2 = Vec::with_capacity(n);
    let mut d = Vec::with_capacity(n);
    let mut flag = Vec::with_capacity(n);
    let mut amount = Vec::with_capacity(n);
    let mut dim_id = Vec::with_capacity(n);
    for _ in 0..n {
        k.push(read_i32(&mut f)?);
        k2.push(read_i32(&mut f)?);
        d.push(read_i32(&mut f)?);
        flag.push(read_i32(&mut f)?);
        amount.push(read_i64(&mut f)?);
        dim_id.push(read_i32(&mut f)?);
    }
    let m = read_u64(&mut f)? as usize;
    let mut dim_w = vec![0i64; 1000];
    for _ in 0..m {
        let id = read_i32(&mut f)? as usize;
        let w = read_i64(&mut f)?;
        if id < 1000 {
            dim_w[id] = w;
        }
    }
    Ok(Cols {
        n,
        k,
        k2,
        d,
        flag,
        amount,
        dim_id,
        dim_w,
    })
}

type Row = Vec<i64>;

fn run_kernel(query_id: &str, c: &Cols) -> Vec<Row> {
    match query_id {
        "q01_filter_sum" => {
            let mut sum: i64 = 0;
            for i in 0..c.n {
                let di = c.d[i];
                if di >= 100 && di <= 500 {
                    sum += c.amount[i];
                }
            }
            vec![vec![sum]]
        }
        "q02_filter_count" => {
            let mut cnt: i64 = 0;
            for i in 0..c.n {
                if c.flag[i] == 1 {
                    cnt += 1;
                }
            }
            vec![vec![cnt]]
        }
        "q03_group_sum" => {
            let mut sums = [0i64; 32];
            let mut seen = [false; 32];
            for i in 0..c.n {
                let ki = c.k[i] as usize;
                seen[ki] = true;
                sums[ki] += c.amount[i];
            }
            let mut out = Vec::new();
            for k in 0..32 {
                if seen[k] {
                    out.push(vec![k as i64, sums[k]]);
                }
            }
            out
        }
        "q04_group_count" => {
            let mut counts = [0i64; 32];
            let mut seen = [false; 32];
            for i in 0..c.n {
                let ki = c.k[i] as usize;
                seen[ki] = true;
                counts[ki] += 1;
            }
            let mut out = Vec::new();
            for k in 0..32 {
                if seen[k] {
                    out.push(vec![k as i64, counts[k]]);
                }
            }
            out
        }
        "q05_two_pred_sum" => {
            let mut sum: i64 = 0;
            for i in 0..c.n {
                if c.d[i] >= 100 && c.flag[i] == 1 {
                    sum += c.amount[i];
                }
            }
            vec![vec![sum]]
        }
        "q06_distinct" => {
            let mut seen = [0u8; 1000];
            for i in 0..c.n {
                seen[c.dim_id[i] as usize] = 1;
            }
            let mut cnt: i64 = 0;
            for v in seen {
                if v == 1 {
                    cnt += 1;
                }
            }
            vec![vec![cnt]]
        }
        "q07_join_sum" => {
            let mut sum: i64 = 0;
            for i in 0..c.n {
                let w = c.dim_w[c.dim_id[i] as usize];
                sum += c.amount[i] * w;
            }
            vec![vec![sum]]
        }
        "q08_range_count" => {
            let mut cnt: i64 = 0;
            for i in 0..c.n {
                let di = c.d[i];
                if di >= 0 && di <= 100 {
                    cnt += 1;
                }
            }
            vec![vec![cnt]]
        }
        "q09_group_two" => {
            let mut sums = [[0i64; 8]; 32];
            let mut seen = [[false; 8]; 32];
            for i in 0..c.n {
                let ki = c.k[i] as usize;
                let k2i = c.k2[i] as usize;
                seen[ki][k2i] = true;
                sums[ki][k2i] += c.amount[i];
            }
            let mut out = Vec::new();
            for k in 0..32 {
                for k2 in 0..8 {
                    if seen[k][k2] {
                        out.push(vec![k as i64, k2 as i64, sums[k][k2]]);
                    }
                }
            }
            out
        }
        "q10_top" => {
            let mut sums = [0i64; 32];
            for i in 0..c.n {
                sums[c.k[i] as usize] += c.amount[i];
            }
            let mut pairs: Vec<(i64, i64)> = (0..32).map(|k| (k as i64, sums[k])).collect();
            pairs.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
            pairs
                .into_iter()
                .take(5)
                .map(|(k, s)| vec![k, s])
                .collect()
        }
        _ => panic!("unknown query_id"),
    }
}

fn fmt_rows(rows: &[Row]) -> String {
    let mut parts: Vec<String> = Vec::new();
    for row in rows {
        let cells: Vec<String> = row.iter().map(|v| v.to_string()).collect();
        parts.push(format!("[{}]", cells.join(",")));
    }
    format!("[{}]", parts.join(","))
}

fn median_us(mut samples: Vec<u64>) -> u64 {
    samples.sort_unstable();
    samples[samples.len() / 2]
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: speed_kernels <query_id> <cols.bin>");
        std::process::exit(1);
    }
    let query_id = &args[1];
    let cols = load_cols(&args[2]).expect("load cols.bin");

    for _ in 0..2 {
        let _ = run_kernel(query_id, &cols);
    }
    let mut samples = Vec::with_capacity(5);
    for _ in 0..5 {
        let t0 = Instant::now();
        let _ = run_kernel(query_id, &cols);
        samples.push(t0.elapsed().as_micros() as u64);
    }
    let rows = run_kernel(query_id, &cols);
    let med = median_us(samples);
    println!("RESULT:{}", fmt_rows(&rows));
    println!("MEDIAN_US:{}", med);
}
