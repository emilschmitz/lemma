mod loader;
mod prepared;
mod queries;

use std::env;
use std::time::Instant;

use prepared::{
    H10LemmaPrep, H11Prep, H12Prep, H13LemmaPrep, H14LemmaPrep, H15LemmaPrep, H16LemmaPrep,
    H17Prep, H18LemmaPrep, H19LemmaPrep, H1LemmaPrep, H20LemmaPrep, H21LemmaPrep, H22LemmaPrep,
    H23LemmaPrep, H24LemmaPrep, H25LemmaPrep, H2LemmaPrep, H3Prep, H4LemmaPrep, H5LemmaPrep,
    H6Prep, H7LemmaPrep, H8LemmaPrep, H9LemmaPrep,
};
use queries::{
    format_gb, format_h7, h1_bare, h10_bare, h12_bare, h13_bare, h14_bare, h15_bare, h16_bare,
    h17_bare, h18_bare, h19_bare, h2_bare, h20_bare, h21_bare, h22_bare, h23_bare, h24_bare,
    h25_bare, h4_bare, h5_bare, h6_bare, h7_bare, h8_bare, h9_bare, load_lineitem, load_orders,
    load_scan_skew, load_ssb_flat, load_str_filter, load_zipf_join,
};

fn is_mt(mode: &str) -> bool {
    mode == "mt"
}

fn is_lemma(impl_name: &str) -> bool {
    impl_name == "lemma"
}

const WARMUP: usize = 3;
const TIMED_ITERS: usize = 5;

fn time_loop<F: FnMut() -> String>(mut f: F) -> (u128, String) {
    for _ in 0..WARMUP {
        let _ = f();
    }
    let mut times = [0u128; TIMED_ITERS];
    let mut last = String::new();
    for t in &mut times {
        let t0 = Instant::now();
        last = f();
        *t = t0.elapsed().as_micros();
    }
    times.sort();
    (times[times.len() / 2], last)
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let query = args.get(1).map(|s| s.as_str()).unwrap_or("H1");
    let impl_name = args.get(2).map(|s| s.as_str()).unwrap_or("lemma");
    let mode = args.get(3).map(|s| s.as_str()).unwrap_or("st");
    let mt = is_mt(mode);
    let lemma = is_lemma(impl_name);

    if mt {
        std::env::set_var("LEMMA_ENABLE_PARALLEL", "1");
        if env::var("RAYON_NUM_THREADS").is_err() {
            let n = std::thread::available_parallelism()
                .map(|p| p.get())
                .unwrap_or(1);
            std::env::set_var("RAYON_NUM_THREADS", n.to_string());
        }
    } else {
        std::env::set_var("RAYON_NUM_THREADS", "1");
    }

    let (us, result) = match query {
        "H1" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H1 needs tbl path");
            let data = load_scan_skew(path);
            if lemma {
                let prep = H1LemmaPrep::new(&data);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h1_bare(&data)))
            }
        }
        "H2" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H2 needs tbl path");
            let data = load_scan_skew(path);
            if lemma {
                let prep = H2LemmaPrep::new(&data);
                time_loop(|| {
                    let (g, c) = prep.run();
                    format_gb(g, c)
                })
            } else {
                time_loop(|| {
                    let (g, c) = h2_bare(&data);
                    format_gb(g, c)
                })
            }
        }
        "H3" => {
            let left = args.get(4).map(|s| s.as_str()).expect("H3 needs left tbl");
            let right = args.get(5).map(|s| s.as_str()).expect("H3 needs right tbl");
            let data = load_zipf_join(left, right);
            let prep = H3Prep::new(&data);
            time_loop(|| {
                let v = if lemma {
                    prep.run_lemma(mt)
                } else {
                    prep.run_bare()
                };
                format!("RESULT: {}", v)
            })
        }
        "H4" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H4 needs tbl path");
            let data = load_str_filter(path);
            if lemma {
                let prep = H4LemmaPrep::new(&data);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h4_bare(&data)))
            }
        }
        "H5" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H5 needs tbl path");
            let li = load_lineitem(path);
            if lemma {
                let prep = H5LemmaPrep::new(&li);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h5_bare(&li)))
            }
        }
        "H6" => {
            let li_path = args.get(4).map(|s| s.as_str()).expect("H6 needs lineitem");
            let ord_path = args.get(5).map(|s| s.as_str()).expect("H6 needs orders");
            let li = load_lineitem(li_path);
            let ord = load_orders(ord_path);
            if lemma {
                let prep = H6Prep::new(&li, &ord);
                time_loop(|| format!("RESULT: {}", prep.run_lemma(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h6_bare(&li, &ord)))
            }
        }
        "H7" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H7 needs tbl path");
            let li = load_lineitem(path);
            if lemma {
                let prep = H7LemmaPrep::new(&li);
                time_loop(|| {
                    let (g, c) = prep.run();
                    format_h7(g, c)
                })
            } else {
                time_loop(|| {
                    let (g, c) = h7_bare(&li);
                    format_h7(g, c)
                })
            }
        }
        "H8" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H8 needs tbl path");
            let data = load_scan_skew(path);
            if lemma {
                let prep = H8LemmaPrep::new(&data);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h8_bare(&data)))
            }
        }
        "H9" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H9 needs tbl path");
            let data = load_scan_skew(path);
            if lemma {
                let prep = H9LemmaPrep::new(&data);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h9_bare(&data)))
            }
        }
        "H10" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H10 needs tbl path");
            let data = load_scan_skew(path);
            if lemma {
                let prep = H10LemmaPrep::new(&data);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h10_bare(&data)))
            }
        }
        "H11" => {
            let left = args.get(4).map(|s| s.as_str()).expect("H11 needs left tbl");
            let right = args.get(5).map(|s| s.as_str()).expect("H11 needs right tbl");
            let data = load_zipf_join(left, right);
            let prep = H11Prep::new(&data);
            time_loop(|| {
                let v = if lemma {
                    prep.run_lemma(mt)
                } else {
                    prep.run_bare()
                };
                format!("RESULT: {}", v)
            })
        }
        "H12" => {
            let left = args.get(4).map(|s| s.as_str()).expect("H12 needs left tbl");
            let right = args.get(5).map(|s| s.as_str()).expect("H12 needs right tbl");
            let data = load_zipf_join(left, right);
            if lemma {
                let prep = H12Prep::new(&data);
                time_loop(|| {
                    let (g, c) = prep.run_lemma();
                    format_gb(g, c)
                })
            } else {
                time_loop(|| {
                    let (g, c) = h12_bare(&data);
                    format_gb(g, c)
                })
            }
        }
        "H13" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H13 needs tbl path");
            let data = load_str_filter(path);
            if lemma {
                let prep = H13LemmaPrep::new(&data);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h13_bare(&data)))
            }
        }
        "H14" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H14 needs tbl path");
            let data = load_str_filter(path);
            if lemma {
                let prep = H14LemmaPrep::new(&data);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h14_bare(&data)))
            }
        }
        "H15" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H15 needs tbl path");
            let li = load_lineitem(path);
            if lemma {
                let prep = H15LemmaPrep::new(&li);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h15_bare(&li)))
            }
        }
        "H16" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H16 needs tbl path");
            let li = load_lineitem(path);
            if lemma {
                let prep = H16LemmaPrep::new(&li);
                time_loop(|| {
                    let (g, c) = prep.run();
                    format_h7(g, c)
                })
            } else {
                time_loop(|| {
                    let (g, c) = h16_bare(&li);
                    format_h7(g, c)
                })
            }
        }
        "H17" => {
            let li_path = args.get(4).map(|s| s.as_str()).expect("H17 needs lineitem");
            let ord_path = args.get(5).map(|s| s.as_str()).expect("H17 needs orders");
            let li = load_lineitem(li_path);
            let ord = load_orders(ord_path);
            if lemma {
                let prep = H17Prep::new(&li, &ord);
                time_loop(|| format!("RESULT: {}", prep.run_lemma(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h17_bare(&li, &ord)))
            }
        }
        "H18" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H18 needs tbl path");
            let li = load_lineitem(path);
            if lemma {
                let prep = H18LemmaPrep::new(&li);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h18_bare(&li)))
            }
        }
        "H19" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H19 needs tbl path");
            let ord = load_orders(path);
            if lemma {
                let prep = H19LemmaPrep::new(&ord);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h19_bare(&ord)))
            }
        }
        "H20" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H20 needs tbl path");
            let ord = load_orders(path);
            if lemma {
                let prep = H20LemmaPrep::new(&ord);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h20_bare(&ord)))
            }
        }
        "H21" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H21 needs tbl path");
            let data = load_ssb_flat(path);
            if lemma {
                let prep = H21LemmaPrep::new(&data);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h21_bare(&data)))
            }
        }
        "H22" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H22 needs tbl path");
            let data = load_ssb_flat(path);
            if lemma {
                let prep = H22LemmaPrep::new(&data);
                time_loop(|| {
                    let (g, c) = prep.run();
                    format_gb(g, c)
                })
            } else {
                time_loop(|| {
                    let (g, c) = h22_bare(&data);
                    format_gb(g, c)
                })
            }
        }
        "H23" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H23 needs tbl path");
            let data = load_ssb_flat(path);
            if lemma {
                let prep = H23LemmaPrep::new(&data);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h23_bare(&data)))
            }
        }
        "H24" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H24 needs tbl path");
            let ord = load_orders(path);
            if lemma {
                let prep = H24LemmaPrep::new(&ord);
                time_loop(|| {
                    let (g, c) = prep.run();
                    format_gb(g, c)
                })
            } else {
                time_loop(|| {
                    let (g, c) = h24_bare(&ord);
                    format_gb(g, c)
                })
            }
        }
        "H25" => {
            let path = args.get(4).map(|s| s.as_str()).expect("H25 needs tbl path");
            let li = load_lineitem(path);
            if lemma {
                let prep = H25LemmaPrep::new(&li);
                time_loop(|| format!("RESULT: {}", prep.run(mt)))
            } else {
                time_loop(|| format!("RESULT: {}", h25_bare(&li)))
            }
        }
        other => panic!("unknown query {other}"),
    };

    println!("QUERY_LATENCY_US: {}", us);
    println!("{result}");
}
