//! Adversarial equivalence: every `par_*` / experimental path must match its serial oracle.

use lemma_agent_primitives::{
    build_hashset_u32, build_hashset_u32_spill, par_filter_sum_u64, par_probe_sum_u64,
    par_probe_sum_u64_morsel, par_probe_sum_u64_multi, par_small_card_filter_sum, par_sum_u64,
    partitioned_build_hashset_u32, probe_sum_u64, probe_sum_u64_multi, serial_filter_sum_u64,
    serial_filter_sum_u64_range, serial_sum_u64, simd_filter_sum_u64_range, small_card_filter_sum,
    vector_filter_sum_u64, MAX_SMALL_CARD_BUCKETS,
};
use std::collections::HashMap;

const SIZES: &[usize] = &[0, 1, 100, 100_000, 300_000];

fn lcg_u64(seed: u64, i: usize) -> u64 {
  let x = seed.wrapping_add(i as u64).wrapping_mul(1_103_515_245);
  x ^ (x >> 17)
}

fn lcg_u32(seed: u64, i: usize) -> u32 {
  lcg_u64(seed, i) as u32
}

fn lcg_bool(seed: u64, i: usize) -> bool {
  lcg_u64(seed.wrapping_add(0x9e37), i) & 1 == 0
}

fn make_u64_vec(n: usize, seed: u64) -> Vec<u64> {
  (0..n).map(|i| lcg_u64(seed, i)).collect()
}

fn make_u32_vec(n: usize, seed: u64) -> Vec<u32> {
  (0..n).map(|i| lcg_u32(seed, i)).collect()
}

fn make_mask(n: usize, seed: u64, all: Option<bool>) -> Vec<bool> {
  match all {
    Some(v) => vec![v; n],
    None => (0..n).map(|i| lcg_bool(seed, i)).collect(),
  }
}

#[test]
fn par_sum_equiv_serial() {
  for &n in SIZES {
    let vals = make_u64_vec(n, 0xA11CE);
    assert_eq!(par_sum_u64(&vals), serial_sum_u64(&vals), "n={n}");
  }
}

#[test]
fn par_filter_sum_equiv_serial() {
  for &n in SIZES {
    for &(col_extra, mask_extra) in &[(0, 0), (5, 0), (0, 7), (3, 11)] {
      let col = make_u64_vec(n + col_extra, 0xF117E0);
      let mask = make_mask(n + mask_extra, 0xCAFE, None);
      let got = par_filter_sum_u64(&col, &mask);
      let want = serial_filter_sum_u64(&col, &mask);
      assert_eq!(got, want, "n={n} col_extra={col_extra} mask_extra={mask_extra}");
    }
  }
}

#[test]
fn par_filter_sum_mask_extremes() {
  for &n in &[0usize, 1, 10_000, 200_000] {
    let col = make_u64_vec(n, 0xBEEF);
    for all in [false, true] {
      let mask = make_mask(n, 0, Some(all));
      assert_eq!(
        par_filter_sum_u64(&col, &mask),
        serial_filter_sum_u64(&col, &mask),
        "n={n} all={all}"
      );
    }
  }
}

#[test]
fn par_probe_sum_equiv_serial() {
  for &n in SIZES {
    let keys = make_u32_vec(n, 0xDEAD);
    let vals = make_u64_vec(n, 0xBEEF);
    let build_keys: Vec<u32> = (0..32).map(|i| lcg_u32(0xB00D, i) % 128).collect();
    let build = build_hashset_u32(&build_keys, 64);
    for &(k_extra, v_extra) in &[(0, 0), (4, 0), (0, 9), (2, 13)] {
      let keys = {
        let mut k = keys.clone();
        k.extend(make_u32_vec(k_extra, 0x1234));
        k
      };
      let vals = {
        let mut v = vals.clone();
        v.extend(make_u64_vec(v_extra, 0x5678));
        v
      };
      assert_eq!(
        par_probe_sum_u64(&keys, &vals, &build),
        probe_sum_u64(&keys, &vals, &build),
        "n={n} k_extra={k_extra} v_extra={v_extra}"
      );
    }
  }
}

#[test]
fn par_probe_sum_multi_equiv_serial() {
  for &n in SIZES {
    let keys = make_u32_vec(n, 0xFACE);
    let vals = make_u64_vec(n, 0xC0DE);
    let mut multi = HashMap::new();
    for i in 0..48 {
      let k = lcg_u32(0x600D, i) % 96;
      *multi.entry(k).or_insert(0) += 1 + (i % 3) as u32;
    }
    for &(k_extra, v_extra) in &[(0, 0), (6, 0), (0, 5)] {
      let keys = {
        let mut k = keys.clone();
        k.extend(make_u32_vec(k_extra, 0xABCD));
        k
      };
      let vals = {
        let mut v = vals.clone();
        v.extend(make_u64_vec(v_extra, 0xEF01));
        v
      };
      assert_eq!(
        par_probe_sum_u64_multi(&keys, &vals, &multi),
        probe_sum_u64_multi(&keys, &vals, &multi),
        "n={n} k_extra={k_extra} v_extra={v_extra}"
      );
    }
  }
}

#[test]
fn par_probe_morsel_equiv_serial() {
  for &n in SIZES {
    let keys = make_u32_vec(n, 0xD00D);
    let vals = make_u64_vec(n, 0x600D);
    let build_keys: Vec<u32> = (0..48).map(|i| lcg_u32(0xFEED, i) % 200).collect();
    let build = build_hashset_u32(&build_keys, 128);
    assert_eq!(
      par_probe_sum_u64_morsel(&keys, &vals, &build),
      probe_sum_u64(&keys, &vals, &build),
      "n={n}"
    );
  }
}

#[test]
fn partitioned_build_equiv_serial() {
  for &n in &[0usize, 1, 100, 10_000] {
    let keys = make_u32_vec(n, 0xBA81);
    let want = build_hashset_u32(&keys, n);
    let got = partitioned_build_hashset_u32(&keys, n, 8);
    assert_eq!(got, want, "n={n}");
  }
}

#[test]
fn vector_filter_sum_equiv_serial() {
  for &n in SIZES {
    let dates = make_u32_vec(n, 0xDA7E);
    let amounts = make_u64_vec(n, 0xA0B0);
    let lo = 100_000;
    let hi = 2_000_000_000;
    assert_eq!(
      vector_filter_sum_u64(&dates, &amounts, lo, hi),
      serial_filter_sum_u64_range(&dates, &amounts, lo, hi),
      "n={n}"
    );
    assert_eq!(
      simd_filter_sum_u64_range(&dates, &amounts, lo, hi),
      serial_filter_sum_u64_range(&dates, &amounts, lo, hi),
      "simd n={n}"
    );
  }
}

#[test]
fn spill_hash_equiv_in_memory() {
  for &n in &[0usize, 1, 500, 50_000] {
    let keys = make_u32_vec(n, 0x5F11);
    let want = build_hashset_u32(&keys, n);
    let got = build_hashset_u32_spill(&keys, n, 1);
    assert_eq!(got, want, "n={n}");
  }
}

#[test]
fn par_small_card_filter_sum_equiv_serial() {
  for &n in SIZES {
    for &n_buckets in &[1usize, 4, 16, 64] {
      let keys = make_u32_vec(n, 0x5100);
      let vals = make_u64_vec(n, 0x5200);
      let mask = make_mask(n, 0x5300, None);
      let got = par_small_card_filter_sum(n_buckets, &keys, &vals, &mask);
      let want = small_card_filter_sum(n_buckets, &keys, &vals, &mask);
      assert_eq!(got, want, "n={n} n_buckets={n_buckets}");
      for i in n_buckets..MAX_SMALL_CARD_BUCKETS {
        assert_eq!(got[i], 0, "unused bucket {i}");
      }
    }
  }
}

#[test]
fn par_small_card_oob_keys_skipped() {
  let keys = vec![0u32, 3, 7, 8, 100, u32::MAX];
  let vals = vec![1u64, 2, 4, 8, 16, 32];
  let mask = vec![true; 6];
  let n_buckets = 8;
  let got = par_small_card_filter_sum(n_buckets, &keys, &vals, &mask);
  let want = small_card_filter_sum(n_buckets, &keys, &vals, &mask);
  assert_eq!(got, want);
  assert_eq!(got[0], 1);
  assert_eq!(got[3], 2);
  assert_eq!(got[7], 4);
}

#[test]
fn par_small_card_mismatched_lengths() {
  let keys = make_u32_vec(50, 0xA);
  let vals = make_u64_vec(40, 0xB);
  let mask = make_mask(45, 0xC, None);
  let got = par_small_card_filter_sum(8, &keys, &vals, &mask);
  let want = small_card_filter_sum(8, &keys, &vals, &mask);
  assert_eq!(got, want);
}
