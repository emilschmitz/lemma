// Generated exec Cols (plain Rust — not compiled with Verus).
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};

fn strip_quotes(s: &str) -> &str {
    s.trim_matches('"')
}

#[derive(Clone, Debug)]
pub struct Cols {
    pub n: usize,
    pub lo_orderdate: Vec<u32>,
    pub lo_quantity: Vec<u32>,
    pub lo_extendedprice: Vec<u64>,
    pub lo_discount: Vec<u32>,
}

impl Cols {
    pub fn load_from_tbl(path: &str, limit: usize) -> Self {
        let f = File::open(path).expect("open .tbl");
        let mut rdr = BufReader::new(f);
        let mut hdr = String::new();
        rdr.read_line(&mut hdr).unwrap();
        let mut name_to_idx: HashMap<String, usize> = HashMap::new();
        for (i, c) in hdr.split('|').enumerate() {
            name_to_idx.insert(c.trim().to_uppercase(), i);
        }
    let lo_orderdate_i = *name_to_idx.get("LO_ORDERDATE").expect("missing col LO_ORDERDATE");
    let lo_quantity_i = *name_to_idx.get("LO_QUANTITY").expect("missing col LO_QUANTITY");
    let lo_extendedprice_i = *name_to_idx.get("LO_EXTENDEDPRICE").expect("missing col LO_EXTENDEDPRICE");
    let lo_discount_i = *name_to_idx.get("LO_DISCOUNT").expect("missing col LO_DISCOUNT");

        let mut lo_orderdate: Vec<u32> = Vec::new();
        let mut lo_quantity: Vec<u32> = Vec::new();
        let mut lo_extendedprice: Vec<u64> = Vec::new();
        let mut lo_discount: Vec<u32> = Vec::new();

        for line in rdr.lines().take(limit) {
            let line = line.unwrap();
            let f: Vec<&str> = line.split('|').collect();
            if f.is_empty() {
                continue;
            }
        lo_orderdate.push(f[lo_orderdate_i].parse::<u32>().unwrap());
        lo_quantity.push(f[lo_quantity_i].parse::<u32>().unwrap());
        lo_extendedprice.push(f[lo_extendedprice_i].parse::<u64>().unwrap());
        lo_discount.push(f[lo_discount_i].parse::<u32>().unwrap());
        }

        let n = lo_orderdate.len();
        Self {
            n,
            lo_orderdate,
            lo_quantity,
            lo_extendedprice,
            lo_discount,
        }
    }
}
