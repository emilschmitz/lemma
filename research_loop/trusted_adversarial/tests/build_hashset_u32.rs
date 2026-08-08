//! Adversarial tests for TRUSTED `build_hashset_u32` (`ensures true` — weak contract).
//!
//! We try to falsify membership / completeness vs input keys; capacity_hint is advisory only.

use lemma_agent_primitives::hash_join::build_hashset_u32;
use std::collections::HashSet;

fn expected_unique(keys: &[u32]) -> HashSet<u32> {
    keys.iter().copied().collect()
}

fn assert_membership_complete(keys: &[u32], set: &HashSet<u32>) {
  for &k in keys {
    assert!(set.contains(&k), "missing key {k} from {:?}", keys);
  }
  let want = expected_unique(keys);
  assert_eq!(set.len(), want.len(), "set size mismatch for keys {:?}", keys);
  for k in want {
    assert!(set.contains(&k), "extra/missing after size check: {k}");
  }
}

#[test]
fn empty_keys_yields_empty_set() {
  let keys: [u32; 0] = [];
  let set = build_hashset_u32(&keys, 0);
  assert!(set.is_empty());
  assert_membership_complete(&keys, &set);
}

#[test]
fn empty_keys_with_huge_capacity_hint() {
  let keys: [u32; 0] = [];
  let set = build_hashset_u32(&keys, 1_000_000);
  assert!(set.is_empty());
  assert_membership_complete(&keys, &set);
}

#[test]
fn single_key_membership() {
  let keys = [42u32];
  let set = build_hashset_u32(&keys, 0);
  assert_membership_complete(&keys, &set);
  assert_eq!(set.len(), 1);
}

#[test]
fn multiple_unique_keys_complete() {
  let keys = [1u32, 2, 3, 4, 5];
  let set = build_hashset_u32(&keys, 8);
  assert_membership_complete(&keys, &set);
}

#[test]
fn duplicate_keys_collapse_to_unique() {
  let keys = [7u32, 7, 7, 3, 3];
  let set = build_hashset_u32(&keys, 4);
  assert_membership_complete(&keys, &set);
  assert_eq!(set.len(), 2);
}

#[test]
fn all_keys_identical_many_dups() {
  let keys: Vec<u32> = (0..10_000).map(|_| 99u32).collect();
  let set = build_hashset_u32(&keys, 0);
  assert_membership_complete(&keys, &set);
  assert_eq!(set.len(), 1);
  assert!(set.contains(&99));
}

#[test]
fn capacity_hint_zero_still_complete() {
  let keys = [10u32, 20, 30];
  let set = build_hashset_u32(&keys, 0);
  assert_membership_complete(&keys, &set);
}

#[test]
fn capacity_hint_smaller_than_len_still_complete() {
  let keys = [1u32, 2, 3, 4];
  let set = build_hashset_u32(&keys, 1);
  assert_membership_complete(&keys, &set);
}

#[test]
fn capacity_hint_huge_still_complete() {
  // Large advisory hint (not usize::MAX — see holes: that panics in hashbrown).
  let keys = [100u32, 200, 300];
  let set = build_hashset_u32(&keys, 10_000_000);
  assert_membership_complete(&keys, &set);
}

#[test]
fn max_u32_and_zero_edges() {
  let keys = [0u32, u32::MAX, 0, u32::MAX];
  let set = build_hashset_u32(&keys, 2);
  assert_membership_complete(&keys, &set);
  assert_eq!(set.len(), 2);
}

#[test]
fn large_unique_key_stream() {
  let keys: Vec<u32> = (0..5_000).collect();
  let set = build_hashset_u32(&keys, 0);
  assert_membership_complete(&keys, &set);
  assert_eq!(set.len(), 5_000);
}

#[test]
fn interleaved_dups_preserve_unique_count() {
  let keys = [5u32, 1, 5, 2, 1, 2, 5, 9];
  let set = build_hashset_u32(&keys, keys.len());
  assert_membership_complete(&keys, &set);
  assert_eq!(set.len(), 4);
}

#[test]
fn no_spurious_members_for_absent_keys() {
  let keys = [11u32, 22, 33];
  let set = build_hashset_u32(&keys, 16);
  assert_membership_complete(&keys, &set);
  for absent in [44u32, 55, 66] {
    assert!(!set.contains(&absent), "spurious member {absent}");
  }
}
