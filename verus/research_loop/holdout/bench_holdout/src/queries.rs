//! Holdout query kernels: bare (naive) hot paths + data loaders.

use std::collections::HashMap;

use crate::loader::{bool_at, str_at, u32_at, u64_at, TableLoader};

// --- literals (mirror holdout/queries.py) ---
pub const H1_LO: u32 = 1_996_0101;
pub const H1_HI: u32 = 1_996_1231;
pub const H2_LO: u32 = 1_995_0101;
pub const H2_HI: u32 = 1_999_1231;
pub const H3_REGION: u32 = 2;
pub const H5_LO_QTY: u32 = 5;
pub const H5_HI_QTY: u32 = 30;
pub const H5_LO_DISC: u32 = 2;
pub const H5_HI_DISC: u32 = 4;
pub const H5_LO_SHIP: u32 = 1_994_0301;
pub const H5_HI_SHIP: u32 = 1_994_0630;
pub const H6_ORDER_BEFORE: u32 = 1_994_0315;
pub const H6_SHIP_AFTER: u32 = 1_994_0315;
pub const H7_SHIP_BEFORE: u32 = 1_997_0601;
pub const H8_LO: u32 = 1_992_0101;
pub const H8_HI: u32 = 1_992_0630;
pub const H9_LO: u32 = 1_995_0201;
pub const H9_HI: u32 = 1_995_0207;
pub const H10_LO: u32 = 1_996_0101;
pub const H10_HI: u32 = 1_996_1231;
pub const H11_REGION: u32 = 0;
pub const H13_FORM: &str = "8-K";
pub const H13_CIK_PREFIX: &str = "10";
pub const H15_LO_QTY: u32 = 8;
pub const H15_HI_QTY: u32 = 25;
pub const H15_LO_DISC: u32 = 3;
pub const H15_HI_DISC: u32 = 5;
pub const H15_LO_SHIP: u32 = 1_994_0401;
pub const H15_HI_SHIP: u32 = 1_994_0430;
pub const H16_SHIP_BEFORE: u32 = 1_997_0801;
pub const H17_ORDER_BEFORE: u32 = 1_994_0201;
pub const H17_SHIP_AFTER: u32 = 1_994_0201;
pub const H18_SHIPMODE: &str = "RAIL";
pub const H19_LO: u32 = 1_995_0101;
pub const H19_HI: u32 = 1_995_1231;
pub const H20_PRIORITY: &str = "3-MEDIUM";
pub const H21_LO_DISC: u32 = 2;
pub const H21_HI_DISC: u32 = 4;
pub const H21_LO_QTY: u32 = 20;
pub const H21_HI_QTY: u32 = 35;
pub const H21_LO_DATE: u32 = 1_993_0801;
pub const H21_HI_DATE: u32 = 1_993_1231;
pub const H23_LO_DATE: u32 = 1_994_0101;
pub const H23_HI_DATE: u32 = 1_994_1231;
pub const H23_MIN_DISC: u32 = 8;
pub const H25_LO_QTY: u32 = 10;
pub const H25_HI_QTY: u32 = 40;
pub const H25_LO_DISC: u32 = 3;
pub const H25_HI_DISC: u32 = 6;
pub const H25_LO_SHIP: u32 = 1_995_0601;
pub const H25_HI_SHIP: u32 = 1_995_0831;
pub const H25_RETURNFLAG: &str = "N";
pub const ZONE_ROWS: usize = 8192;

// --- data structs + loaders ---

pub struct ScanSkew {
    pub dates: Vec<u32>,
    pub regions: Vec<u32>,
    pub amounts: Vec<u64>,
}

pub fn load_scan_skew(path: &str) -> ScanSkew {
    let mut ld = TableLoader::open(path);
    let mut dates = Vec::new();
    let mut regions = Vec::new();
    let mut amounts = Vec::new();
    ld.read_all(|idx, f| {
        dates.push(u32_at(idx, f, "EVENT_DATE"));
        regions.push(u32_at(idx, f, "REGION"));
        amounts.push(u64_at(idx, f, "AMOUNT"));
    });
    ScanSkew {
        dates,
        regions,
        amounts,
    }
}

pub struct ZipfJoin {
    pub left_keys: Vec<u32>,
    pub left_regions: Vec<u32>,
    pub left_amounts: Vec<u64>,
    pub right_keys: Vec<u32>,
    pub right_regions: Vec<u32>,
}

pub fn load_zipf_join(left: &str, right: &str) -> ZipfJoin {
    let mut ld = TableLoader::open(left);
    let mut left_keys = Vec::new();
    let mut left_regions = Vec::new();
    let mut left_amounts = Vec::new();
    ld.read_all(|idx, f| {
        left_keys.push(u32_at(idx, f, "KEY"));
        left_regions.push(u32_at(idx, f, "REGION"));
        left_amounts.push(u64_at(idx, f, "AMOUNT"));
    });
    let mut ld = TableLoader::open(right);
    let mut right_keys = Vec::new();
    let mut right_regions = Vec::new();
    ld.read_all(|idx, f| {
        right_keys.push(u32_at(idx, f, "KEY"));
        right_regions.push(u32_at(idx, f, "REGION"));
    });
    ZipfJoin {
        left_keys,
        left_regions,
        left_amounts,
        right_keys,
        right_regions,
    }
}

pub struct StrFilter {
    pub forms: Vec<String>,
    pub ciks: Vec<String>,
    pub amounts: Vec<u64>,
    pub active: Vec<bool>,
}

pub fn load_str_filter(path: &str) -> StrFilter {
    let mut ld = TableLoader::open(path);
    let mut forms = Vec::new();
    let mut ciks = Vec::new();
    let mut amounts = Vec::new();
    let mut active = Vec::new();
    ld.read_all(|idx, f| {
        forms.push(str_at(idx, f, "FORM_TYPE"));
        ciks.push(str_at(idx, f, "CIK"));
        amounts.push(u64_at(idx, f, "AMOUNT"));
        active.push(bool_at(idx, f, "ACTIVE"));
    });
    StrFilter {
        forms,
        ciks,
        amounts,
        active,
    }
}

pub struct LineitemSlice {
    pub orderkeys: Vec<u32>,
    pub quantities: Vec<u32>,
    pub discounts: Vec<u32>,
    pub shipdates: Vec<u32>,
    pub extendedprices: Vec<u64>,
    pub returnflags: Vec<String>,
    pub linestatuses: Vec<String>,
    pub shipmodes: Vec<String>,
}

pub fn load_lineitem(path: &str) -> LineitemSlice {
    let mut ld = TableLoader::open(path);
    let mut orderkeys = Vec::new();
    let mut quantities = Vec::new();
    let mut discounts = Vec::new();
    let mut shipdates = Vec::new();
    let mut extendedprices = Vec::new();
    let mut returnflags = Vec::new();
    let mut linestatuses = Vec::new();
    let mut shipmodes = Vec::new();
    ld.read_all(|idx, f| {
        orderkeys.push(u32_at(idx, f, "L_ORDERKEY"));
        quantities.push(u32_at(idx, f, "L_QUANTITY"));
        discounts.push(u32_at(idx, f, "L_DISCOUNT"));
        shipdates.push(u32_at(idx, f, "L_SHIPDATE"));
        extendedprices.push(u64_at(idx, f, "L_EXTENDEDPRICE"));
        returnflags.push(str_at(idx, f, "L_RETURNFLAG"));
        linestatuses.push(str_at(idx, f, "L_LINESTATUS"));
        shipmodes.push(str_at(idx, f, "L_SHIPMODE"));
    });
    LineitemSlice {
        orderkeys,
        quantities,
        discounts,
        shipdates,
        extendedprices,
        returnflags,
        linestatuses,
        shipmodes,
    }
}

pub struct OrdersSlice {
    pub orderkeys: Vec<u32>,
    pub orderdates: Vec<u32>,
    pub totalprices: Vec<u64>,
    pub priorities: Vec<String>,
}

pub fn load_orders(path: &str) -> OrdersSlice {
    let mut ld = TableLoader::open(path);
    let mut orderkeys = Vec::new();
    let mut orderdates = Vec::new();
    let mut totalprices = Vec::new();
    let mut priorities = Vec::new();
    ld.read_all(|idx, f| {
        orderkeys.push(u32_at(idx, f, "O_ORDERKEY"));
        orderdates.push(u32_at(idx, f, "O_ORDERDATE"));
        totalprices.push(u64_at(idx, f, "O_TOTALPRICE"));
        priorities.push(str_at(idx, f, "O_ORDERPRIORITY"));
    });
    OrdersSlice {
        orderkeys,
        orderdates,
        totalprices,
        priorities,
    }
}

pub struct SsbFlat {
    pub orderdates: Vec<u32>,
    pub quantities: Vec<u32>,
    pub discounts: Vec<u32>,
    pub revenues: Vec<u64>,
    pub orderpriorities: Vec<String>,
}

pub fn load_ssb_flat(path: &str) -> SsbFlat {
    let mut ld = TableLoader::open(path);
    let mut orderdates = Vec::new();
    let mut quantities = Vec::new();
    let mut discounts = Vec::new();
    let mut revenues = Vec::new();
    let mut orderpriorities = Vec::new();
    ld.read_all(|idx, f| {
        orderdates.push(u32_at(idx, f, "LO_ORDERDATE"));
        quantities.push(u32_at(idx, f, "LO_QUANTITY"));
        discounts.push(u32_at(idx, f, "LO_DISCOUNT"));
        revenues.push(u64_at(idx, f, "LO_REVENUE"));
        orderpriorities.push(str_at(idx, f, "LO_ORDERPRIORITY"));
    });
    SsbFlat {
        orderdates,
        quantities,
        discounts,
        revenues,
        orderpriorities,
    }
}

// --- helpers ---

pub fn gb_stats(buckets: &[u64]) -> (usize, u64) {
    let mut groups = 0usize;
    let mut checksum = 0u64;
    for &v in buckets {
        if v != 0 {
            groups += 1;
            checksum = checksum.wrapping_add(v);
        }
    }
    (groups, checksum)
}

pub fn format_gb(groups: usize, checksum: u64) -> String {
    format!("RESULT: groups={} checksum={}", groups, checksum)
}

/// Encode TPC-H returnflag byte → 0..2 (N/R/A); unknown → None.
#[inline(always)]
pub fn encode_returnflag(s: &str) -> Option<usize> {
    match s.as_bytes().first().copied()? {
        b'N' => Some(0),
        b'R' => Some(1),
        b'A' => Some(2),
        _ => None,
    }
}

/// Encode TPC-H linestatus byte → 0..1 (O/F); unknown → None.
#[inline(always)]
pub fn encode_linestatus(s: &str) -> Option<usize> {
    match s.as_bytes().first().copied()? {
        b'O' => Some(0),
        b'F' => Some(1),
        _ => None,
    }
}

#[inline(always)]
pub fn h7_bucket(rf: usize, ls: usize) -> usize {
    rf * 2 + ls
}

/// Encode order priority string → dense bucket 0..4.
#[inline(always)]
pub fn encode_orderpriority(s: &str) -> Option<u32> {
    match s {
        "1-URGENT" => Some(0),
        "2-HIGH" => Some(1),
        "3-MEDIUM" => Some(2),
        "4-NOT SPECIFIED" => Some(3),
        "5-LOW" => Some(4),
        _ => None,
    }
}

/// Encode SEC form type → dense 0..7 (holdout generator set); unknown → 255.
#[inline(always)]
pub fn encode_form_type(s: &str) -> u8 {
    match s {
        "10-K" => 0,
        "10-Q" => 1,
        "8-K" => 2,
        "DEF 14A" => 3,
        "S-1" => 4,
        "424B2" => 5,
        "13F-HR" => 6,
        "NPORT-P" => 7,
        _ => 255,
    }
}

/// Dense dictionary encoding of a string column (ingest-time).
pub fn encode_str_column_dict(values: &[String]) -> (Vec<u8>, HashMap<String, u8>) {
    let mut dict = HashMap::new();
    let mut next = 0u8;
    let mut codes = Vec::with_capacity(values.len());
    for s in values {
        let code = *dict.entry(s.clone()).or_insert_with(|| {
            let c = next;
            next = next.wrapping_add(1);
            c
        });
        codes.push(code);
    }
    (codes, dict)
}

pub fn format_h7(groups: usize, checksum: u64) -> String {
    format_gb(groups, checksum)
}

// --- shared bare helpers ---

pub fn q6_bare(
    li: &LineitemSlice,
    lo_qty: u32,
    hi_qty: u32,
    lo_disc: u32,
    hi_disc: u32,
    lo_ship: u32,
    hi_ship: u32,
) -> u64 {
    let mut sum = 0u64;
    for i in 0..li.shipdates.len() {
        let qty = li.quantities[i];
        let disc = li.discounts[i];
        let ship = li.shipdates[i];
        if qty >= lo_qty
            && qty <= hi_qty
            && disc >= lo_disc
            && disc <= hi_disc
            && ship >= lo_ship
            && ship <= hi_ship
        {
            sum = sum.wrapping_add(li.extendedprices[i].wrapping_mul(disc as u64));
        }
    }
    sum
}

pub fn join_date_bare(
    li: &LineitemSlice,
    ord: &OrdersSlice,
    order_before: u32,
    ship_after: u32,
) -> u64 {
    let mut order_map: HashMap<u32, u32> = HashMap::with_capacity(ord.orderkeys.len());
    for i in 0..ord.orderkeys.len() {
        order_map.insert(ord.orderkeys[i], ord.orderdates[i]);
    }
    let mut sum = 0u64;
    for i in 0..li.orderkeys.len() {
        if let Some(&od) = order_map.get(&li.orderkeys[i]) {
            if od < order_before && li.shipdates[i] > ship_after {
                sum = sum.wrapping_add(li.extendedprices[i]);
            }
        }
    }
    sum
}

/// Naive two-key group-by on lineitem (HashMap + String clones).
pub fn gb_lineitem_bare(li: &LineitemSlice, ship_before: u32) -> (usize, u64) {
    let mut acc: HashMap<(String, String), u64> = HashMap::new();
    for i in 0..li.shipdates.len() {
        if li.shipdates[i] <= ship_before {
            let key = (li.returnflags[i].clone(), li.linestatuses[i].clone());
            *acc.entry(key).or_insert(0) += li.quantities[i] as u64;
        }
    }
    let checksum = acc.values().fold(0u64, |a, b| a.wrapping_add(*b));
    (acc.len(), checksum)
}

// --- bare kernels ---

pub fn h1_bare(data: &ScanSkew) -> u64 {
    let mut sum = 0u64;
    for i in 0..data.dates.len() {
        let d = data.dates[i];
        if d >= H1_LO && d <= H1_HI {
            sum = sum.wrapping_add(data.amounts[i]);
        }
    }
    sum
}

pub fn h2_bare(data: &ScanSkew) -> (usize, u64) {
    let mut acc = [0u64; 12];
    for i in 0..data.dates.len() {
        let d = data.dates[i];
        if d >= H2_LO && d <= H2_HI {
            let r = data.regions[i] as usize;
            if r < 12 {
                acc[r] = acc[r].wrapping_add(data.amounts[i]);
            }
        }
    }
    gb_stats(&acc)
}

pub fn h4_bare(data: &StrFilter) -> u64 {
    let mut sum = 0u64;
    for i in 0..data.forms.len() {
        if data.forms[i] == "10-K" && data.ciks[i].starts_with("00") && data.active[i] {
            sum = sum.wrapping_add(data.amounts[i]);
        }
    }
    sum
}

pub fn h5_bare(li: &LineitemSlice) -> u64 {
    q6_bare(
        li,
        H5_LO_QTY,
        H5_HI_QTY,
        H5_LO_DISC,
        H5_HI_DISC,
        H5_LO_SHIP,
        H5_HI_SHIP,
    )
}

pub fn h6_bare(li: &LineitemSlice, ord: &OrdersSlice) -> u64 {
    join_date_bare(li, ord, H6_ORDER_BEFORE, H6_SHIP_AFTER)
}

pub fn h7_bare(li: &LineitemSlice) -> (usize, u64) {
    gb_lineitem_bare(li, H7_SHIP_BEFORE)
}

pub fn h8_bare(data: &ScanSkew) -> u64 {
    let mut cnt = 0u64;
    for i in 0..data.dates.len() {
        let d = data.dates[i];
        if d >= H8_LO && d <= H8_HI {
            cnt += 1;
        }
    }
    cnt
}

pub fn h9_bare(data: &ScanSkew) -> u64 {
    let mut sum = 0u64;
    for i in 0..data.dates.len() {
        let d = data.dates[i];
        if d >= H9_LO && d <= H9_HI {
            sum = sum.wrapping_add(data.amounts[i]);
        }
    }
    sum
}

pub fn h10_bare(data: &ScanSkew) -> u64 {
    let mut sum = 0u64;
    for i in 0..data.dates.len() {
        let d = data.dates[i];
        if d >= H10_LO && d <= H10_HI {
            sum = sum.wrapping_add(data.amounts[i]);
        }
    }
    sum
}

pub fn h12_bare(data: &ZipfJoin) -> (usize, u64) {
    let mut right: HashMap<(u32, u32), u32> = HashMap::new();
    for i in 0..data.right_keys.len() {
        *right
            .entry((data.right_keys[i], data.right_regions[i]))
            .or_insert(0) += 1;
    }
    let mut acc = [0u64; 5];
    for i in 0..data.left_keys.len() {
        let k = data.left_keys[i];
        let r = data.left_regions[i];
        if let Some(&cnt) = right.get(&(k, r)) {
            let idx = r as usize;
            if idx < 5 {
                acc[idx] = acc[idx].wrapping_add(data.left_amounts[i].wrapping_mul(cnt as u64));
            }
        }
    }
    gb_stats(&acc)
}

pub fn h13_bare(data: &StrFilter) -> u64 {
    let mut sum = 0u64;
    for i in 0..data.forms.len() {
        if data.forms[i] == H13_FORM
            && data.ciks[i].starts_with(H13_CIK_PREFIX)
            && data.active[i]
        {
            sum = sum.wrapping_add(data.amounts[i]);
        }
    }
    sum
}

pub fn h14_bare(data: &StrFilter) -> u64 {
    let mut cnt = 0u64;
    for i in 0..data.active.len() {
        if data.active[i] {
            cnt += 1;
        }
    }
    cnt
}

pub fn h15_bare(li: &LineitemSlice) -> u64 {
    q6_bare(
        li,
        H15_LO_QTY,
        H15_HI_QTY,
        H15_LO_DISC,
        H15_HI_DISC,
        H15_LO_SHIP,
        H15_HI_SHIP,
    )
}

pub fn h16_bare(li: &LineitemSlice) -> (usize, u64) {
    gb_lineitem_bare(li, H16_SHIP_BEFORE)
}

pub fn h17_bare(li: &LineitemSlice, ord: &OrdersSlice) -> u64 {
    join_date_bare(li, ord, H17_ORDER_BEFORE, H17_SHIP_AFTER)
}

pub fn h18_bare(li: &LineitemSlice) -> u64 {
    let mut sum = 0u64;
    for i in 0..li.shipmodes.len() {
        if li.shipmodes[i] == H18_SHIPMODE {
            sum = sum.wrapping_add(li.extendedprices[i]);
        }
    }
    sum
}

pub fn h19_bare(ord: &OrdersSlice) -> u64 {
    let mut sum = 0u64;
    for i in 0..ord.orderdates.len() {
        let d = ord.orderdates[i];
        if d >= H19_LO && d <= H19_HI {
            sum = sum.wrapping_add(ord.totalprices[i]);
        }
    }
    sum
}

pub fn h20_bare(ord: &OrdersSlice) -> u64 {
    let mut sum = 0u64;
    for i in 0..ord.priorities.len() {
        if ord.priorities[i] == H20_PRIORITY {
            sum = sum.wrapping_add(ord.totalprices[i]);
        }
    }
    sum
}

pub fn h21_bare(data: &SsbFlat) -> u64 {
    let mut sum = 0u64;
    for i in 0..data.orderdates.len() {
        let d = data.orderdates[i];
        let qty = data.quantities[i];
        let disc = data.discounts[i];
        if disc >= H21_LO_DISC
            && disc <= H21_HI_DISC
            && qty >= H21_LO_QTY
            && qty <= H21_HI_QTY
            && d >= H21_LO_DATE
            && d <= H21_HI_DATE
        {
            sum = sum.wrapping_add(data.revenues[i]);
        }
    }
    sum
}

pub fn h22_bare(data: &SsbFlat) -> (usize, u64) {
    let mut acc = [0u64; 5];
    for i in 0..data.orderpriorities.len() {
        if let Some(b) = encode_orderpriority(&data.orderpriorities[i]) {
            acc[b as usize] = acc[b as usize].wrapping_add(data.revenues[i]);
        }
    }
    gb_stats(&acc)
}

pub fn h23_bare(data: &SsbFlat) -> u64 {
    let mut sum = 0u64;
    for i in 0..data.orderdates.len() {
        let d = data.orderdates[i];
        if d >= H23_LO_DATE && d <= H23_HI_DATE && data.discounts[i] >= H23_MIN_DISC {
            sum = sum.wrapping_add(data.revenues[i]);
        }
    }
    sum
}

pub fn h24_bare(ord: &OrdersSlice) -> (usize, u64) {
    let mut acc = vec![0u64; 1000];
    for i in 0..ord.orderkeys.len() {
        let b = (ord.orderkeys[i] % 1000) as usize;
        acc[b] = acc[b].wrapping_add(ord.totalprices[i]);
    }
    gb_stats(&acc)
}

pub fn h25_bare(li: &LineitemSlice) -> u64 {
    let mut sum = 0u64;
    for i in 0..li.shipdates.len() {
        let qty = li.quantities[i];
        let disc = li.discounts[i];
        let ship = li.shipdates[i];
        if qty >= H25_LO_QTY
            && qty <= H25_HI_QTY
            && disc >= H25_LO_DISC
            && disc <= H25_HI_DISC
            && ship >= H25_LO_SHIP
            && ship <= H25_HI_SHIP
            && li.returnflags[i] == H25_RETURNFLAG
        {
            sum = sum.wrapping_add(li.extendedprices[i]);
        }
    }
    sum
}
