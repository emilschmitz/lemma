//! Dictionary encoding helpers (ingest-time; always available).

use std::collections::HashMap;

/// Dense dictionary encoding of a string column.
///
/// Returns `(codes, dict)` where `dict[codes[i] as usize]` is the string at row `i`.
/// Stable row order: first occurrence of each distinct string gets the next code.
pub fn encode_dictionary_str(col: &[String]) -> (Vec<u32>, Vec<String>) {
    let mut index: HashMap<&str, u32> = HashMap::new();
    let mut dict: Vec<String> = Vec::new();
    let mut codes = Vec::with_capacity(col.len());
    for s in col {
        let code = if let Some(&c) = index.get(s.as_str()) {
            c
        } else {
            let c = dict.len() as u32;
            index.insert(s.as_str(), c);
            dict.push(s.clone());
            c
        };
        codes.push(code);
    }
    (codes, dict)
}

/// Decode one row from dictionary-encoded strings.
pub fn decode_dict_str(codes: &[u32], dict: &[String], i: usize) -> Option<String> {
    if i >= codes.len() {
        return None;
    }
    let code = codes[i] as usize;
    dict.get(code).cloned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encode_roundtrip() {
        let col = vec![
            "a".to_string(),
            "b".to_string(),
            "a".to_string(),
            "c".to_string(),
            "b".to_string(),
        ];
        let (codes, dict) = encode_dictionary_str(&col);
        assert_eq!(dict, vec!["a", "b", "c"]);
        assert_eq!(codes, vec![0, 1, 0, 2, 1]);
        for (i, s) in col.iter().enumerate() {
            assert_eq!(decode_dict_str(&codes, &dict, i).as_deref(), Some(s.as_str()));
        }
    }
}
