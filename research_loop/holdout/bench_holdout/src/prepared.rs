//! Fair "new data next week" timing: Prep::new holds load-time state only.
//!
//! Outside timer (ingest): columnar clones, zone maps, dict string codes.
//! Inside `run` (query): zone prune + predicates, join build/probe, agg, terms.

use std::collections::HashMap;

use lemma_agent_primitives::{
    build_zone_map_u32, may_satisfy_range_u32, par_filter_sum_u64, par_probe_sum_u64_multi,
    probe_sum_u64_multi, SmallCardBuckets, ZoneSegmentU32,
};
use rayon::prelude::*;
use rustc_hash::FxHashSet;

use crate::queries::{
    encode_form_type, encode_linestatus, encode_orderpriority, encode_returnflag,
    encode_str_column_dict, gb_stats, h7_bucket, LineitemSlice, OrdersSlice, ScanSkew, SsbFlat,
    StrFilter, ZipfJoin, H1_HI, H1_LO, H10_HI, H10_LO, H11_REGION, H13_CIK_PREFIX, H13_FORM,
    H15_HI_DISC, H15_HI_QTY, H15_HI_SHIP, H15_LO_DISC, H15_LO_QTY, H15_LO_SHIP, H16_SHIP_BEFORE,
    H17_ORDER_BEFORE, H17_SHIP_AFTER, H18_SHIPMODE, H19_HI, H19_LO, H20_PRIORITY, H21_HI_DATE,
    H21_HI_DISC, H21_HI_QTY, H21_LO_DATE, H21_LO_DISC, H21_LO_QTY, H23_HI_DATE, H23_LO_DATE,
    H23_MIN_DISC, H25_HI_DISC, H25_HI_QTY, H25_HI_SHIP, H25_LO_DISC, H25_LO_QTY, H25_LO_SHIP,
    H25_RETURNFLAG, H2_HI, H2_LO, H3_REGION, H5_HI_DISC, H5_HI_QTY, H5_HI_SHIP, H5_LO_DISC,
    H5_LO_QTY, H5_LO_SHIP, H6_ORDER_BEFORE, H6_SHIP_AFTER, H7_SHIP_BEFORE, H8_HI, H8_LO, H9_HI,
    H9_LO, ZONE_ROWS,
};

const PAR_CHUNK: usize = 1 << 16;

pub struct H1LemmaPrep {
    zones: Vec<ZoneSegmentU32>,
    dates: Vec<u32>,
    amounts: Vec<u64>,
}

impl H1LemmaPrep {
    pub fn new(data: &ScanSkew) -> Self {
        Self {
            zones: build_zone_map_u32(&data.dates, ZONE_ROWS),
            dates: data.dates.clone(),
            amounts: data.amounts.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            let n = self.dates.len();
            let mut mask = vec![false; n];
            let mut vals = vec![0u64; n];
            for z in &self.zones {
                if may_satisfy_range_u32(z, H1_LO, H1_HI) {
                    for i in z.start..z.end {
                        let d = self.dates[i];
                        if d >= H1_LO && d <= H1_HI {
                            mask[i] = true;
                            vals[i] = self.amounts[i];
                        }
                    }
                }
            }
            par_filter_sum_u64(&vals, &mask)
        } else {
            let mut sum = 0u64;
            for z in &self.zones {
                if may_satisfy_range_u32(z, H1_LO, H1_HI) {
                    for i in z.start..z.end {
                        let d = self.dates[i];
                        if d >= H1_LO && d <= H1_HI {
                            sum = sum.wrapping_add(self.amounts[i]);
                        }
                    }
                }
            }
            sum
        }
    }
}

pub struct H2LemmaPrep {
    zones: Vec<ZoneSegmentU32>,
    dates: Vec<u32>,
    regions: Vec<u32>,
    amounts: Vec<u64>,
}

impl H2LemmaPrep {
    pub fn new(data: &ScanSkew) -> Self {
        Self {
            zones: build_zone_map_u32(&data.dates, ZONE_ROWS),
            dates: data.dates.clone(),
            regions: data.regions.clone(),
            amounts: data.amounts.clone(),
        }
    }

    pub fn run(&self) -> (usize, u64) {
        let mut buckets = SmallCardBuckets::<12>::new();
        for z in &self.zones {
            if may_satisfy_range_u32(z, H2_LO, H2_HI) {
                for i in z.start..z.end {
                    let d = self.dates[i];
                    if d >= H2_LO && d <= H2_HI {
                        buckets.add(self.regions[i], self.amounts[i]);
                    }
                }
            }
        }
        gb_stats(buckets.buckets())
    }
}

pub struct H3Prep {
    left_keys: Vec<u32>,
    left_regions: Vec<u32>,
    left_amounts: Vec<u64>,
    right_keys: Vec<u32>,
    right_regions: Vec<u32>,
}

impl H3Prep {
    pub fn new(data: &ZipfJoin) -> Self {
        Self {
            left_keys: data.left_keys.clone(),
            left_regions: data.left_regions.clone(),
            left_amounts: data.left_amounts.clone(),
            right_keys: data.right_keys.clone(),
            right_regions: data.right_regions.clone(),
        }
    }

    fn build_and_probe(&self) -> (Vec<u32>, Vec<u64>, HashMap<u32, u32>) {
        let mut right_counts: HashMap<u32, u32> = HashMap::new();
        for i in 0..self.right_keys.len() {
            if self.right_regions[i] == H3_REGION {
                *right_counts.entry(self.right_keys[i]).or_insert(0) += 1;
            }
        }
        let mut probe_keys = Vec::new();
        let mut probe_vals = Vec::new();
        for i in 0..self.left_keys.len() {
            if self.left_regions[i] == H3_REGION {
                probe_keys.push(self.left_keys[i]);
                probe_vals.push(self.left_amounts[i]);
            }
        }
        (probe_keys, probe_vals, right_counts)
    }

    pub fn run_bare(&self) -> u64 {
        let (probe_keys, probe_vals, right_counts) = self.build_and_probe();
        let mut sum = 0u64;
        for i in 0..probe_keys.len() {
            if let Some(&cnt) = right_counts.get(&probe_keys[i]) {
                sum = sum.wrapping_add(probe_vals[i].wrapping_mul(cnt as u64));
            }
        }
        sum
    }

    pub fn run_lemma(&self, mt: bool) -> u64 {
        let (probe_keys, probe_vals, right_counts) = self.build_and_probe();
        if mt {
            par_probe_sum_u64_multi(&probe_keys, &probe_vals, &right_counts)
        } else {
            probe_sum_u64_multi(&probe_keys, &probe_vals, &right_counts)
        }
    }
}

pub struct H4LemmaPrep {
    forms: Vec<u8>,
    ciks: Vec<String>,
    amounts: Vec<u64>,
    active: Vec<bool>,
    form_target: u8,
}

impl H4LemmaPrep {
    pub fn new(data: &StrFilter) -> Self {
        Self {
            forms: data.forms.iter().map(|s| encode_form_type(s)).collect(),
            ciks: data.ciks.clone(),
            amounts: data.amounts.clone(),
            active: data.active.clone(),
            form_target: encode_form_type("10-K"),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            self.forms
                .par_chunks(PAR_CHUNK)
                .zip(self.ciks.par_chunks(PAR_CHUNK))
                .zip(self.amounts.par_chunks(PAR_CHUNK))
                .zip(self.active.par_chunks(PAR_CHUNK))
                .map(|(((forms, ciks), amounts), active)| {
                    let mut sum = 0u64;
                    for i in 0..forms.len() {
                        if forms[i] == self.form_target
                            && ciks[i].starts_with("00")
                            && active[i]
                        {
                            sum = sum.wrapping_add(amounts[i]);
                        }
                    }
                    sum
                })
                .reduce(|| 0u64, |a, b| a.wrapping_add(b))
        } else {
            let mut sum = 0u64;
            for i in 0..self.forms.len() {
                if self.forms[i] == self.form_target
                    && self.ciks[i].starts_with("00")
                    && self.active[i]
                {
                    sum = sum.wrapping_add(self.amounts[i]);
                }
            }
            sum
        }
    }
}

pub struct H5LemmaPrep {
    zones: Vec<ZoneSegmentU32>,
    quantities: Vec<u32>,
    discounts: Vec<u32>,
    shipdates: Vec<u32>,
    extendedprices: Vec<u64>,
}

impl H5LemmaPrep {
    pub fn new(li: &LineitemSlice) -> Self {
        Self {
            zones: build_zone_map_u32(&li.shipdates, ZONE_ROWS),
            quantities: li.quantities.clone(),
            discounts: li.discounts.clone(),
            shipdates: li.shipdates.clone(),
            extendedprices: li.extendedprices.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            let n = self.shipdates.len();
            let mut mask = vec![false; n];
            let mut terms = vec![0u64; n];
            for z in &self.zones {
                if may_satisfy_range_u32(z, H5_LO_SHIP, H5_HI_SHIP) {
                    for i in z.start..z.end {
                        let qty = self.quantities[i];
                        let disc = self.discounts[i];
                        let ship = self.shipdates[i];
                        if qty >= H5_LO_QTY
                            && qty <= H5_HI_QTY
                            && disc >= H5_LO_DISC
                            && disc <= H5_HI_DISC
                            && ship >= H5_LO_SHIP
                            && ship <= H5_HI_SHIP
                        {
                            mask[i] = true;
                            terms[i] = self.extendedprices[i].wrapping_mul(disc as u64);
                        }
                    }
                }
            }
            par_filter_sum_u64(&terms, &mask)
        } else {
            let mut sum = 0u64;
            for z in &self.zones {
                if may_satisfy_range_u32(z, H5_LO_SHIP, H5_HI_SHIP) {
                    for i in z.start..z.end {
                        let qty = self.quantities[i];
                        let disc = self.discounts[i];
                        let ship = self.shipdates[i];
                        if qty >= H5_LO_QTY
                            && qty <= H5_HI_QTY
                            && disc >= H5_LO_DISC
                            && disc <= H5_HI_DISC
                            && ship >= H5_LO_SHIP
                            && ship <= H5_HI_SHIP
                        {
                            sum = sum.wrapping_add(
                                self.extendedprices[i].wrapping_mul(disc as u64),
                            );
                        }
                    }
                }
            }
            sum
        }
    }
}

pub struct H6Prep {
    zones: Vec<ZoneSegmentU32>,
    li_orderkeys: Vec<u32>,
    li_shipdates: Vec<u32>,
    li_extendedprices: Vec<u64>,
    ord_orderkeys: Vec<u32>,
    ord_orderdates: Vec<u32>,
}

impl H6Prep {
    pub fn new(li: &LineitemSlice, ord: &OrdersSlice) -> Self {
        Self {
            zones: build_zone_map_u32(&li.shipdates, ZONE_ROWS),
            li_orderkeys: li.orderkeys.clone(),
            li_shipdates: li.shipdates.clone(),
            li_extendedprices: li.extendedprices.clone(),
            ord_orderkeys: ord.orderkeys.clone(),
            ord_orderdates: ord.orderdates.clone(),
        }
    }

    pub fn run_lemma(&self, mt: bool) -> u64 {
        let mut order_set =
            FxHashSet::with_capacity_and_hasher(self.ord_orderkeys.len(), Default::default());
        for i in 0..self.ord_orderkeys.len() {
            if self.ord_orderdates[i] < H6_ORDER_BEFORE {
                order_set.insert(self.ord_orderkeys[i]);
            }
        }

        if mt {
            self.zones
                .par_iter()
                .filter(|z| may_satisfy_range_u32(z, H6_SHIP_AFTER + 1, u32::MAX))
                .map(|z| {
                    let mut sum = 0u64;
                    for i in z.start..z.end {
                        if self.li_shipdates[i] > H6_SHIP_AFTER
                            && order_set.contains(&self.li_orderkeys[i])
                        {
                            sum = sum.wrapping_add(self.li_extendedprices[i]);
                        }
                    }
                    sum
                })
                .reduce(|| 0u64, |a, b| a.wrapping_add(b))
        } else {
            let mut sum = 0u64;
            for z in &self.zones {
                if may_satisfy_range_u32(z, H6_SHIP_AFTER + 1, u32::MAX) {
                    for i in z.start..z.end {
                        if self.li_shipdates[i] > H6_SHIP_AFTER
                            && order_set.contains(&self.li_orderkeys[i])
                        {
                            sum = sum.wrapping_add(self.li_extendedprices[i]);
                        }
                    }
                }
            }
            sum
        }
    }
}

pub struct H7LemmaPrep {
    rf: Vec<u8>,
    ls: Vec<u8>,
    quantities: Vec<u32>,
    shipdates: Vec<u32>,
}

impl H7LemmaPrep {
    pub fn new(li: &LineitemSlice) -> Self {
        let n = li.shipdates.len();
        let mut rf = vec![255u8; n];
        let mut ls = vec![255u8; n];
        for i in 0..n {
            if let (Some(r), Some(s)) = (
                encode_returnflag(&li.returnflags[i]),
                encode_linestatus(&li.linestatuses[i]),
            ) {
                rf[i] = r as u8;
                ls[i] = s as u8;
            }
        }
        Self {
            rf,
            ls,
            quantities: li.quantities.clone(),
            shipdates: li.shipdates.clone(),
        }
    }

    #[inline(always)]
    pub fn run(&self) -> (usize, u64) {
        let mut buckets = [0u64; 6];
        let n = self.shipdates.len();
        for i in 0..n {
            if self.shipdates[i] <= H7_SHIP_BEFORE && self.rf[i] != 255 {
                let b = h7_bucket(self.rf[i] as usize, self.ls[i] as usize);
                buckets[b] = buckets[b].wrapping_add(self.quantities[i] as u64);
            }
        }
        gb_stats(&buckets)
    }
}

pub struct H8LemmaPrep {
    zones: Vec<ZoneSegmentU32>,
    dates: Vec<u32>,
}

impl H8LemmaPrep {
    pub fn new(data: &ScanSkew) -> Self {
        Self {
            zones: build_zone_map_u32(&data.dates, ZONE_ROWS),
            dates: data.dates.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            let n = self.dates.len();
            let mut mask = vec![false; n];
            let ones = vec![1u64; n];
            for z in &self.zones {
                if may_satisfy_range_u32(z, H8_LO, H8_HI) {
                    for i in z.start..z.end {
                        let d = self.dates[i];
                        if d >= H8_LO && d <= H8_HI {
                            mask[i] = true;
                        }
                    }
                }
            }
            par_filter_sum_u64(&ones, &mask)
        } else {
            let mut cnt = 0u64;
            for z in &self.zones {
                if may_satisfy_range_u32(z, H8_LO, H8_HI) {
                    for i in z.start..z.end {
                        let d = self.dates[i];
                        if d >= H8_LO && d <= H8_HI {
                            cnt += 1;
                        }
                    }
                }
            }
            cnt
        }
    }
}

pub struct H9LemmaPrep {
    zones: Vec<ZoneSegmentU32>,
    dates: Vec<u32>,
    amounts: Vec<u64>,
}

impl H9LemmaPrep {
    pub fn new(data: &ScanSkew) -> Self {
        Self {
            zones: build_zone_map_u32(&data.dates, ZONE_ROWS),
            dates: data.dates.clone(),
            amounts: data.amounts.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            let n = self.dates.len();
            let mut mask = vec![false; n];
            let mut vals = vec![0u64; n];
            for z in &self.zones {
                if may_satisfy_range_u32(z, H9_LO, H9_HI) {
                    for i in z.start..z.end {
                        let d = self.dates[i];
                        if d >= H9_LO && d <= H9_HI {
                            mask[i] = true;
                            vals[i] = self.amounts[i];
                        }
                    }
                }
            }
            par_filter_sum_u64(&vals, &mask)
        } else {
            let mut sum = 0u64;
            for z in &self.zones {
                if may_satisfy_range_u32(z, H9_LO, H9_HI) {
                    for i in z.start..z.end {
                        let d = self.dates[i];
                        if d >= H9_LO && d <= H9_HI {
                            sum = sum.wrapping_add(self.amounts[i]);
                        }
                    }
                }
            }
            sum
        }
    }
}

pub struct H10LemmaPrep {
    zones: Vec<ZoneSegmentU32>,
    dates: Vec<u32>,
    amounts: Vec<u64>,
}

impl H10LemmaPrep {
    pub fn new(data: &ScanSkew) -> Self {
        Self {
            zones: build_zone_map_u32(&data.dates, ZONE_ROWS),
            dates: data.dates.clone(),
            amounts: data.amounts.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            let n = self.dates.len();
            let mut mask = vec![false; n];
            let mut vals = vec![0u64; n];
            for z in &self.zones {
                if may_satisfy_range_u32(z, H10_LO, H10_HI) {
                    for i in z.start..z.end {
                        let d = self.dates[i];
                        if d >= H10_LO && d <= H10_HI {
                            mask[i] = true;
                            vals[i] = self.amounts[i];
                        }
                    }
                }
            }
            par_filter_sum_u64(&vals, &mask)
        } else {
            let mut sum = 0u64;
            for z in &self.zones {
                if may_satisfy_range_u32(z, H10_LO, H10_HI) {
                    for i in z.start..z.end {
                        let d = self.dates[i];
                        if d >= H10_LO && d <= H10_HI {
                            sum = sum.wrapping_add(self.amounts[i]);
                        }
                    }
                }
            }
            sum
        }
    }
}

pub struct H11Prep {
    left_keys: Vec<u32>,
    left_regions: Vec<u32>,
    left_amounts: Vec<u64>,
    right_keys: Vec<u32>,
    right_regions: Vec<u32>,
}

impl H11Prep {
    pub fn new(data: &ZipfJoin) -> Self {
        Self {
            left_keys: data.left_keys.clone(),
            left_regions: data.left_regions.clone(),
            left_amounts: data.left_amounts.clone(),
            right_keys: data.right_keys.clone(),
            right_regions: data.right_regions.clone(),
        }
    }

    fn build_and_probe(&self) -> (Vec<u32>, Vec<u64>, HashMap<u32, u32>) {
        let mut right_counts: HashMap<u32, u32> = HashMap::new();
        for i in 0..self.right_keys.len() {
            if self.right_regions[i] == H11_REGION {
                *right_counts.entry(self.right_keys[i]).or_insert(0) += 1;
            }
        }
        let mut probe_keys = Vec::new();
        let mut probe_vals = Vec::new();
        for i in 0..self.left_keys.len() {
            if self.left_regions[i] == H11_REGION {
                probe_keys.push(self.left_keys[i]);
                probe_vals.push(self.left_amounts[i]);
            }
        }
        (probe_keys, probe_vals, right_counts)
    }

    pub fn run_bare(&self) -> u64 {
        let (probe_keys, probe_vals, right_counts) = self.build_and_probe();
        let mut sum = 0u64;
        for i in 0..probe_keys.len() {
            if let Some(&cnt) = right_counts.get(&probe_keys[i]) {
                sum = sum.wrapping_add(probe_vals[i].wrapping_mul(cnt as u64));
            }
        }
        sum
    }

    pub fn run_lemma(&self, mt: bool) -> u64 {
        let (probe_keys, probe_vals, right_counts) = self.build_and_probe();
        if mt {
            par_probe_sum_u64_multi(&probe_keys, &probe_vals, &right_counts)
        } else {
            probe_sum_u64_multi(&probe_keys, &probe_vals, &right_counts)
        }
    }
}

pub struct H12Prep {
    left_keys: Vec<u32>,
    left_regions: Vec<u32>,
    left_amounts: Vec<u64>,
    right_keys: Vec<u32>,
    right_regions: Vec<u32>,
}

impl H12Prep {
    pub fn new(data: &ZipfJoin) -> Self {
        Self {
            left_keys: data.left_keys.clone(),
            left_regions: data.left_regions.clone(),
            left_amounts: data.left_amounts.clone(),
            right_keys: data.right_keys.clone(),
            right_regions: data.right_regions.clone(),
        }
    }

    pub fn run_lemma(&self) -> (usize, u64) {
        let mut right_counts: HashMap<(u32, u32), u32> = HashMap::new();
        for i in 0..self.right_keys.len() {
            *right_counts
                .entry((self.right_keys[i], self.right_regions[i]))
                .or_insert(0) += 1;
        }
        let mut buckets = SmallCardBuckets::<5>::new();
        for i in 0..self.left_keys.len() {
            let k = self.left_keys[i];
            let r = self.left_regions[i];
            if let Some(&cnt) = right_counts.get(&(k, r)) {
                buckets.add(r, self.left_amounts[i].wrapping_mul(cnt as u64));
            }
        }
        gb_stats(buckets.buckets())
    }
}

pub struct H13LemmaPrep {
    forms: Vec<u8>,
    ciks: Vec<String>,
    amounts: Vec<u64>,
    active: Vec<bool>,
    form_target: u8,
}

impl H13LemmaPrep {
    pub fn new(data: &StrFilter) -> Self {
        Self {
            forms: data.forms.iter().map(|s| encode_form_type(s)).collect(),
            ciks: data.ciks.clone(),
            amounts: data.amounts.clone(),
            active: data.active.clone(),
            form_target: encode_form_type(H13_FORM),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            self.forms
                .par_chunks(PAR_CHUNK)
                .zip(self.ciks.par_chunks(PAR_CHUNK))
                .zip(self.amounts.par_chunks(PAR_CHUNK))
                .zip(self.active.par_chunks(PAR_CHUNK))
                .map(|(((forms, ciks), amounts), active)| {
                    let mut sum = 0u64;
                    for i in 0..forms.len() {
                        if forms[i] == self.form_target
                            && ciks[i].starts_with(H13_CIK_PREFIX)
                            && active[i]
                        {
                            sum = sum.wrapping_add(amounts[i]);
                        }
                    }
                    sum
                })
                .reduce(|| 0u64, |a, b| a.wrapping_add(b))
        } else {
            let mut sum = 0u64;
            for i in 0..self.forms.len() {
                if self.forms[i] == self.form_target
                    && self.ciks[i].starts_with(H13_CIK_PREFIX)
                    && self.active[i]
                {
                    sum = sum.wrapping_add(self.amounts[i]);
                }
            }
            sum
        }
    }
}

pub struct H14LemmaPrep {
    active: Vec<bool>,
}

impl H14LemmaPrep {
    pub fn new(data: &StrFilter) -> Self {
        Self {
            active: data.active.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            let n = self.active.len();
            let ones = vec![1u64; n];
            let mask: Vec<bool> = self.active.clone();
            par_filter_sum_u64(&ones, &mask)
        } else {
            let mut cnt = 0u64;
            for i in 0..self.active.len() {
                if self.active[i] {
                    cnt += 1;
                }
            }
            cnt
        }
    }
}

pub struct H15LemmaPrep {
    zones: Vec<ZoneSegmentU32>,
    quantities: Vec<u32>,
    discounts: Vec<u32>,
    shipdates: Vec<u32>,
    extendedprices: Vec<u64>,
}

impl H15LemmaPrep {
    pub fn new(li: &LineitemSlice) -> Self {
        Self {
            zones: build_zone_map_u32(&li.shipdates, ZONE_ROWS),
            quantities: li.quantities.clone(),
            discounts: li.discounts.clone(),
            shipdates: li.shipdates.clone(),
            extendedprices: li.extendedprices.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            self.zones
                .par_iter()
                .filter(|z| may_satisfy_range_u32(z, H15_LO_SHIP, H15_HI_SHIP))
                .map(|z| {
                    let mut sum = 0u64;
                    for i in z.start..z.end {
                        let qty = self.quantities[i];
                        let disc = self.discounts[i];
                        let ship = self.shipdates[i];
                        if qty >= H15_LO_QTY
                            && qty <= H15_HI_QTY
                            && disc >= H15_LO_DISC
                            && disc <= H15_HI_DISC
                            && ship >= H15_LO_SHIP
                            && ship <= H15_HI_SHIP
                        {
                            sum = sum.wrapping_add(self.extendedprices[i].wrapping_mul(disc as u64));
                        }
                    }
                    sum
                })
                .reduce(|| 0u64, |a, b| a.wrapping_add(b))
        } else {
            let mut sum = 0u64;
            for z in &self.zones {
                if may_satisfy_range_u32(z, H15_LO_SHIP, H15_HI_SHIP) {
                    for i in z.start..z.end {
                        let qty = self.quantities[i];
                        let disc = self.discounts[i];
                        let ship = self.shipdates[i];
                        if qty >= H15_LO_QTY
                            && qty <= H15_HI_QTY
                            && disc >= H15_LO_DISC
                            && disc <= H15_HI_DISC
                            && ship >= H15_LO_SHIP
                            && ship <= H15_HI_SHIP
                        {
                            sum = sum.wrapping_add(
                                self.extendedprices[i].wrapping_mul(disc as u64),
                            );
                        }
                    }
                }
            }
            sum
        }
    }
}

pub struct H16LemmaPrep {
    rf: Vec<u8>,
    ls: Vec<u8>,
    quantities: Vec<u32>,
    shipdates: Vec<u32>,
}

impl H16LemmaPrep {
    pub fn new(li: &LineitemSlice) -> Self {
        let n = li.shipdates.len();
        let mut rf = vec![255u8; n];
        let mut ls = vec![255u8; n];
        for i in 0..n {
            if let (Some(r), Some(s)) = (
                encode_returnflag(&li.returnflags[i]),
                encode_linestatus(&li.linestatuses[i]),
            ) {
                rf[i] = r as u8;
                ls[i] = s as u8;
            }
        }
        Self {
            rf,
            ls,
            quantities: li.quantities.clone(),
            shipdates: li.shipdates.clone(),
        }
    }

    pub fn run(&self) -> (usize, u64) {
        let mut buckets = [0u64; 6];
        let n = self.shipdates.len();
        for i in 0..n {
            if self.shipdates[i] <= H16_SHIP_BEFORE && self.rf[i] != 255 {
                let b = h7_bucket(self.rf[i] as usize, self.ls[i] as usize);
                buckets[b] = buckets[b].wrapping_add(self.quantities[i] as u64);
            }
        }
        gb_stats(&buckets)
    }
}

pub struct H17Prep {
    zones: Vec<ZoneSegmentU32>,
    li_orderkeys: Vec<u32>,
    li_shipdates: Vec<u32>,
    li_extendedprices: Vec<u64>,
    ord_orderkeys: Vec<u32>,
    ord_orderdates: Vec<u32>,
}

impl H17Prep {
    pub fn new(li: &LineitemSlice, ord: &OrdersSlice) -> Self {
        Self {
            zones: build_zone_map_u32(&li.shipdates, ZONE_ROWS),
            li_orderkeys: li.orderkeys.clone(),
            li_shipdates: li.shipdates.clone(),
            li_extendedprices: li.extendedprices.clone(),
            ord_orderkeys: ord.orderkeys.clone(),
            ord_orderdates: ord.orderdates.clone(),
        }
    }

    pub fn run_lemma(&self, mt: bool) -> u64 {
        let mut order_set =
            FxHashSet::with_capacity_and_hasher(self.ord_orderkeys.len(), Default::default());
        for i in 0..self.ord_orderkeys.len() {
            if self.ord_orderdates[i] < H17_ORDER_BEFORE {
                order_set.insert(self.ord_orderkeys[i]);
            }
        }

        if mt {
            self.zones
                .par_iter()
                .filter(|z| may_satisfy_range_u32(z, H17_SHIP_AFTER + 1, u32::MAX))
                .map(|z| {
                    let mut sum = 0u64;
                    for i in z.start..z.end {
                        if self.li_shipdates[i] > H17_SHIP_AFTER
                            && order_set.contains(&self.li_orderkeys[i])
                        {
                            sum = sum.wrapping_add(self.li_extendedprices[i]);
                        }
                    }
                    sum
                })
                .reduce(|| 0u64, |a, b| a.wrapping_add(b))
        } else {
            let mut sum = 0u64;
            for z in &self.zones {
                if may_satisfy_range_u32(z, H17_SHIP_AFTER + 1, u32::MAX) {
                    for i in z.start..z.end {
                        if self.li_shipdates[i] > H17_SHIP_AFTER
                            && order_set.contains(&self.li_orderkeys[i])
                        {
                            sum = sum.wrapping_add(self.li_extendedprices[i]);
                        }
                    }
                }
            }
            sum
        }
    }
}

pub struct H18LemmaPrep {
    shipmode_codes: Vec<u8>,
    shipmode_target: u8,
    extendedprices: Vec<u64>,
}

impl H18LemmaPrep {
    pub fn new(li: &LineitemSlice) -> Self {
        let (shipmode_codes, dict) = encode_str_column_dict(&li.shipmodes);
        let shipmode_target = dict.get(H18_SHIPMODE).copied().unwrap_or(255);
        Self {
            shipmode_codes,
            shipmode_target,
            extendedprices: li.extendedprices.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            self.shipmode_codes
                .par_chunks(PAR_CHUNK)
                .zip(self.extendedprices.par_chunks(PAR_CHUNK))
                .map(|(codes, prices)| {
                    let mut sum = 0u64;
                    for i in 0..codes.len() {
                        if codes[i] == self.shipmode_target {
                            sum = sum.wrapping_add(prices[i]);
                        }
                    }
                    sum
                })
                .reduce(|| 0u64, |a, b| a.wrapping_add(b))
        } else {
            let mut sum = 0u64;
            for i in 0..self.shipmode_codes.len() {
                if self.shipmode_codes[i] == self.shipmode_target {
                    sum = sum.wrapping_add(self.extendedprices[i]);
                }
            }
            sum
        }
    }
}

pub struct H19LemmaPrep {
    zones: Vec<ZoneSegmentU32>,
    orderdates: Vec<u32>,
    totalprices: Vec<u64>,
}

impl H19LemmaPrep {
    pub fn new(ord: &OrdersSlice) -> Self {
        Self {
            zones: build_zone_map_u32(&ord.orderdates, ZONE_ROWS),
            orderdates: ord.orderdates.clone(),
            totalprices: ord.totalprices.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            let n = self.orderdates.len();
            let mut mask = vec![false; n];
            let mut vals = vec![0u64; n];
            for z in &self.zones {
                if may_satisfy_range_u32(z, H19_LO, H19_HI) {
                    for i in z.start..z.end {
                        let d = self.orderdates[i];
                        if d >= H19_LO && d <= H19_HI {
                            mask[i] = true;
                            vals[i] = self.totalprices[i];
                        }
                    }
                }
            }
            par_filter_sum_u64(&vals, &mask)
        } else {
            let mut sum = 0u64;
            for z in &self.zones {
                if may_satisfy_range_u32(z, H19_LO, H19_HI) {
                    for i in z.start..z.end {
                        let d = self.orderdates[i];
                        if d >= H19_LO && d <= H19_HI {
                            sum = sum.wrapping_add(self.totalprices[i]);
                        }
                    }
                }
            }
            sum
        }
    }
}

pub struct H20LemmaPrep {
    priorities: Vec<u8>,
    priority_target: u8,
    totalprices: Vec<u64>,
}

impl H20LemmaPrep {
    pub fn new(ord: &OrdersSlice) -> Self {
        let priorities: Vec<u8> = ord
            .priorities
            .iter()
            .map(|s| encode_orderpriority(s).map(|c| c as u8).unwrap_or(255))
            .collect();
        let priority_target = encode_orderpriority(H20_PRIORITY).unwrap() as u8;
        Self {
            priorities,
            priority_target,
            totalprices: ord.totalprices.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            self.priorities
                .par_chunks(PAR_CHUNK)
                .zip(self.totalprices.par_chunks(PAR_CHUNK))
                .map(|(codes, prices)| {
                    let mut sum = 0u64;
                    for i in 0..codes.len() {
                        if codes[i] == self.priority_target {
                            sum = sum.wrapping_add(prices[i]);
                        }
                    }
                    sum
                })
                .reduce(|| 0u64, |a, b| a.wrapping_add(b))
        } else {
            let mut sum = 0u64;
            for i in 0..self.priorities.len() {
                if self.priorities[i] == self.priority_target {
                    sum = sum.wrapping_add(self.totalprices[i]);
                }
            }
            sum
        }
    }
}

pub struct H21LemmaPrep {
    zones: Vec<ZoneSegmentU32>,
    orderdates: Vec<u32>,
    quantities: Vec<u32>,
    discounts: Vec<u32>,
    revenues: Vec<u64>,
}

impl H21LemmaPrep {
    pub fn new(data: &SsbFlat) -> Self {
        Self {
            zones: build_zone_map_u32(&data.orderdates, ZONE_ROWS),
            orderdates: data.orderdates.clone(),
            quantities: data.quantities.clone(),
            discounts: data.discounts.clone(),
            revenues: data.revenues.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            let n = self.orderdates.len();
            let mut mask = vec![false; n];
            let mut vals = vec![0u64; n];
            for z in &self.zones {
                if may_satisfy_range_u32(z, H21_LO_DATE, H21_HI_DATE) {
                    for i in z.start..z.end {
                        let d = self.orderdates[i];
                        let qty = self.quantities[i];
                        let disc = self.discounts[i];
                        if d >= H21_LO_DATE
                            && d <= H21_HI_DATE
                            && qty >= H21_LO_QTY
                            && qty <= H21_HI_QTY
                            && disc >= H21_LO_DISC
                            && disc <= H21_HI_DISC
                        {
                            mask[i] = true;
                            vals[i] = self.revenues[i];
                        }
                    }
                }
            }
            par_filter_sum_u64(&vals, &mask)
        } else {
            let mut sum = 0u64;
            for z in &self.zones {
                if may_satisfy_range_u32(z, H21_LO_DATE, H21_HI_DATE) {
                    for i in z.start..z.end {
                        let d = self.orderdates[i];
                        let qty = self.quantities[i];
                        let disc = self.discounts[i];
                        if d >= H21_LO_DATE
                            && d <= H21_HI_DATE
                            && qty >= H21_LO_QTY
                            && qty <= H21_HI_QTY
                            && disc >= H21_LO_DISC
                            && disc <= H21_HI_DISC
                        {
                            sum = sum.wrapping_add(self.revenues[i]);
                        }
                    }
                }
            }
            sum
        }
    }
}

pub struct H22LemmaPrep {
    orderpriorities: Vec<String>,
    revenues: Vec<u64>,
}

impl H22LemmaPrep {
    pub fn new(data: &SsbFlat) -> Self {
        Self {
            orderpriorities: data.orderpriorities.clone(),
            revenues: data.revenues.clone(),
        }
    }

    pub fn run(&self) -> (usize, u64) {
        let mut buckets = SmallCardBuckets::<5>::new();
        for i in 0..self.orderpriorities.len() {
            if let Some(b) = encode_orderpriority(&self.orderpriorities[i]) {
                buckets.add(b, self.revenues[i]);
            }
        }
        gb_stats(buckets.buckets())
    }
}

pub struct H23LemmaPrep {
    zones: Vec<ZoneSegmentU32>,
    orderdates: Vec<u32>,
    discounts: Vec<u32>,
    revenues: Vec<u64>,
}

impl H23LemmaPrep {
    pub fn new(data: &SsbFlat) -> Self {
        Self {
            zones: build_zone_map_u32(&data.orderdates, ZONE_ROWS),
            orderdates: data.orderdates.clone(),
            discounts: data.discounts.clone(),
            revenues: data.revenues.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            let n = self.orderdates.len();
            let mut mask = vec![false; n];
            let mut vals = vec![0u64; n];
            for z in &self.zones {
                if may_satisfy_range_u32(z, H23_LO_DATE, H23_HI_DATE) {
                    for i in z.start..z.end {
                        let d = self.orderdates[i];
                        if d >= H23_LO_DATE
                            && d <= H23_HI_DATE
                            && self.discounts[i] >= H23_MIN_DISC
                        {
                            mask[i] = true;
                            vals[i] = self.revenues[i];
                        }
                    }
                }
            }
            par_filter_sum_u64(&vals, &mask)
        } else {
            let mut sum = 0u64;
            for z in &self.zones {
                if may_satisfy_range_u32(z, H23_LO_DATE, H23_HI_DATE) {
                    for i in z.start..z.end {
                        let d = self.orderdates[i];
                        if d >= H23_LO_DATE
                            && d <= H23_HI_DATE
                            && self.discounts[i] >= H23_MIN_DISC
                        {
                            sum = sum.wrapping_add(self.revenues[i]);
                        }
                    }
                }
            }
            sum
        }
    }
}

pub struct H24LemmaPrep {
    orderkeys: Vec<u32>,
    totalprices: Vec<u64>,
}

impl H24LemmaPrep {
    pub fn new(ord: &OrdersSlice) -> Self {
        Self {
            orderkeys: ord.orderkeys.clone(),
            totalprices: ord.totalprices.clone(),
        }
    }

    pub fn run(&self) -> (usize, u64) {
        let mut buckets = SmallCardBuckets::<1000>::new();
        for i in 0..self.orderkeys.len() {
            buckets.add(self.orderkeys[i] % 1000, self.totalprices[i]);
        }
        gb_stats(buckets.buckets())
    }
}

pub struct H25LemmaPrep {
    zones: Vec<ZoneSegmentU32>,
    quantities: Vec<u32>,
    discounts: Vec<u32>,
    shipdates: Vec<u32>,
    returnflags: Vec<u8>,
    returnflag_target: u8,
    extendedprices: Vec<u64>,
}

impl H25LemmaPrep {
    pub fn new(li: &LineitemSlice) -> Self {
        let returnflags: Vec<u8> = li
            .returnflags
            .iter()
            .map(|s| encode_returnflag(s).map(|c| c as u8).unwrap_or(255))
            .collect();
        let returnflag_target = encode_returnflag(H25_RETURNFLAG).unwrap() as u8;
        Self {
            zones: build_zone_map_u32(&li.shipdates, ZONE_ROWS),
            quantities: li.quantities.clone(),
            discounts: li.discounts.clone(),
            shipdates: li.shipdates.clone(),
            returnflags,
            returnflag_target,
            extendedprices: li.extendedprices.clone(),
        }
    }

    pub fn run(&self, mt: bool) -> u64 {
        if mt {
            self.zones
                .par_iter()
                .filter(|z| may_satisfy_range_u32(z, H25_LO_SHIP, H25_HI_SHIP))
                .map(|z| {
                    let mut sum = 0u64;
                    for i in z.start..z.end {
                        let qty = self.quantities[i];
                        let disc = self.discounts[i];
                        let ship = self.shipdates[i];
                        if qty >= H25_LO_QTY
                            && qty <= H25_HI_QTY
                            && disc >= H25_LO_DISC
                            && disc <= H25_HI_DISC
                            && ship >= H25_LO_SHIP
                            && ship <= H25_HI_SHIP
                            && self.returnflags[i] == self.returnflag_target
                        {
                            sum = sum.wrapping_add(self.extendedprices[i]);
                        }
                    }
                    sum
                })
                .reduce(|| 0u64, |a, b| a.wrapping_add(b))
        } else {
            let mut sum = 0u64;
            for z in &self.zones {
                if may_satisfy_range_u32(z, H25_LO_SHIP, H25_HI_SHIP) {
                    for i in z.start..z.end {
                        let qty = self.quantities[i];
                        let disc = self.discounts[i];
                        let ship = self.shipdates[i];
                        if qty >= H25_LO_QTY
                            && qty <= H25_HI_QTY
                            && disc >= H25_LO_DISC
                            && disc <= H25_HI_DISC
                            && ship >= H25_LO_SHIP
                            && ship <= H25_HI_SHIP
                            && self.returnflags[i] == self.returnflag_target
                        {
                            sum = sum.wrapping_add(self.extendedprices[i]);
                        }
                    }
                }
            }
            sum
        }
    }
}
