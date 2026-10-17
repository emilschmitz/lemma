// Test helper (tests/test_zero_copy_order.py): pin a SELECT through the zero-copy C-API code and print every cell in pin order.
include!("../../research_loop/zero_copy_ffi.rs");

// probe <db> <sql> [ro|rw]  : pin, print meta then one line per row with every column's cell as a decimal integer (i128 widened)
fn main() {
    let a: Vec<String> = std::env::args().collect();
    let db = zc_duck::open(&a[1], true);
    let pin = zc_duck::pin(&db, &a[2]);
    println!("META rows {} chunks {}", pin.rows, pin.cols[0].ptrs.len());
    for (c, col) in pin.cols.iter().enumerate() {
        println!("COL {} type {} width {} scale {} elem {}", c, col.type_id, col.dec_width, col.dec_scale, col.elem_bytes);
    }
    let lens: Vec<usize> = pin.cols[0].ptrs.iter().map(|x| x.1).collect();
    println!("LENS {:?}", &lens[..lens.len().min(12)]);
    let nrows = pin.rows;
    let mut out = String::new();
    for k in 0..pin.cols[0].ptrs.len() {
        for j in 0..pin.cols[0].ptrs[k].1 {
            for col in pin.cols.iter() {
                let (p, _l) = col.ptrs[k];
                let v: i128 = unsafe {
                    match col.elem_bytes {
                        1 => *(p as *const i8).add(j) as i128,
                        2 => *(p as *const i16).add(j) as i128,
                        4 => *(p as *const i32).add(j) as i128,
                        8 => *(p as *const i64).add(j) as i128,
                        _ => *(p as *const i128).add(j),
                    }
                };
                out.push_str(&format!("{} ", v));
            }
            out.push('\n');
        }
    }
    let _ = nrows;
    print!("{}", out);
}
