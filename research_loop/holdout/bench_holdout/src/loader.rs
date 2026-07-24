//! Pipe-delimited .tbl loaders for holdout datasets.

use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader, Read};

pub fn strip_quotes(s: &str) -> &str {
    s.trim_matches('"')
}

pub struct TableLoader {
    rdr: BufReader<File>,
    idx: HashMap<String, usize>,
}

impl TableLoader {
    pub fn open(tbl: &str) -> Self {
        let f = File::open(tbl).expect("open .tbl");
        let mut rdr = BufReader::new(f);
        let mut hdr = String::new();
        rdr.read_line(&mut hdr).unwrap();
        let mut idx = HashMap::new();
        for (i, c) in hdr.split('|').enumerate() {
            idx.insert(c.trim().to_uppercase(), i);
        }
        Self { rdr, idx }
    }

    pub fn read_all<F>(&mut self, mut row: F)
    where
        F: FnMut(&HashMap<String, usize>, &[&str]),
    {
        for line in self.rdr.by_ref().lines() {
            let line = line.unwrap();
            let fields: Vec<&str> = line.split('|').collect();
            if fields.is_empty() {
                continue;
            }
            row(&self.idx, &fields);
        }
    }
}

#[inline]
pub fn u32_at(idx: &HashMap<String, usize>, fields: &[&str], name: &str) -> u32 {
    fields
        .get(*idx.get(&name.to_uppercase()).expect("missing col"))
        .and_then(|s| s.parse().ok())
        .unwrap_or(0)
}

#[inline]
pub fn u64_at(idx: &HashMap<String, usize>, fields: &[&str], name: &str) -> u64 {
    fields
        .get(*idx.get(&name.to_uppercase()).expect("missing col"))
        .and_then(|s| s.parse().ok())
        .unwrap_or(0)
}

#[inline]
pub fn str_at(idx: &HashMap<String, usize>, fields: &[&str], name: &str) -> String {
    let s = fields
        .get(*idx.get(&name.to_uppercase()).expect("missing col"))
        .copied()
        .unwrap_or("");
    strip_quotes(s).to_string()
}

#[inline]
pub fn bool_at(idx: &HashMap<String, usize>, fields: &[&str], name: &str) -> bool {
    u32_at(idx, fields, name) != 0
}
