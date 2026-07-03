#![allow(warnings, unconditional_panic)]
#![allow(nonstandard_style)]
#![cfg_attr(any(), rustfmt::skip)]
pub mod cols_native;
pub mod native_agg;
pub mod native_ops;
/// Flattens all imported externs so that they can be accessed from this module
pub mod _dafny_externs {
    pub use crate::cols_native::*;
    pub use crate::native_agg::*;
    pub use crate::native_ops::*;
}

pub mod _module {
    use crate::_dafny_externs::{ColsNative};
    pub use ::dafny_runtime::Object;
    pub use ::dafny_runtime::int;
    pub use ::dafny_runtime::rd;
    pub use ::dafny_runtime::DafnyInt;
    pub use ::std::default::Default;
    pub use ::dafny_runtime::Sequence;
    pub use ::dafny_runtime::DafnyChar;
    pub use ::dafny_runtime::DafnyPrintWrapper;
    pub use ::dafny_runtime::string_of;
    pub use ::std::cmp::PartialEq;
    pub use ::std::cmp::Eq;
    pub use ::std::hash::Hash;
    pub use ::std::hash::Hasher;
    pub use ::dafny_runtime::DafnyPrint;
    pub use ::std::fmt::Formatter;
    pub use ::std::fmt::Result;
    pub use ::std::ops::Deref;
    pub use ::std::mem::transmute;
    pub use ::std::ops::Add;
    pub use ::std::ops::Sub;
    pub use ::std::ops::Mul;
    pub use ::std::ops::Div;
    pub use ::std::cmp::PartialOrd;
    pub use ::std::option::Option;
    pub use ::std::cmp::Ordering;

    pub struct _default {}

    impl _default {
        pub fn _native_add_u64(a: u64, b: u64) -> u64 {
            crate::native_ops::native_add_u64(a, b)
        }
        pub fn _native_mul_u64_u32(ep: u64, d: u32) -> u64 {
            crate::native_ops::native_mul_u64_u32(ep, d)
        }
        pub fn _native_sub_u64_i64(a: u64, b: u64) -> i64 {
            crate::native_ops::native_sub_u64_i64(a, b)
        }
        pub fn _native_add_i64(a: i64, b: i64) -> i64 {
            crate::native_ops::native_add_i64(a, b)
        }

        /// working_query.dfy(103,1)
        pub fn ValidCols(cols: &Object<ColsNative>) -> bool {
            int!(0) <= rd!(cols).n()
        }
        /// working_query.dfy(108,1)
        pub fn MethodSpecHelper(cols: &Object<ColsNative>, k: &DafnyInt) -> u64 {
            if k.clone() < rd!(cols).n() {
                if rd!(cols).GetD_WEEKNUMINYEAR(k) == 6 && rd!(cols).GetD_YEAR(k) == 1994 && rd!(cols).GetLO_DISCOUNT(k) >= 5 && rd!(cols).GetLO_DISCOUNT(k) <= 7 && rd!(cols).GetLO_QUANTITY(k) >= 26 && rd!(cols).GetLO_QUANTITY(k) <= 35 {
                    _default::_native_add_u64(_default::MethodSpecHelper(cols, &(k.clone() + int!(1))), _default::_native_mul_u64_u32(rd!(cols).GetLO_EXTENDEDPRICE(k), rd!(cols).GetLO_DISCOUNT(k)))
                } else {
                    _default::MethodSpecHelper(cols, &(k.clone() + int!(1)))
                }
            } else {
                0
            }
        }
        /// working_query.dfy(119,1)
        pub fn MethodSpec(cols: &Object<ColsNative>) -> u64 {
            _default::MethodSpecHelper(cols, &int!(0))
        }
        /// working_query.dfy(143,1)
        pub fn RunQuery(cols: &Object<ColsNative>) -> u64 {
            let cols_ref = rd!(cols);
            let mut res: u64 = <u64 as Default>::default();
            res = 0;
            let mut i: usize = cols_ref.n;
            while i > 0 {
                i -= 1;
                let mut week: u32 = cols_ref.GetD_WEEKNUMINYEAR_usize(i);
                let mut yr: u32 = cols_ref.GetD_YEAR_usize(i);
                let mut disc: u32 = cols_ref.GetLO_DISCOUNT_usize(i);
                let mut qty: u32 = cols_ref.GetLO_QUANTITY_usize(i);
                if week == 6 && yr == 1994 && 5 <= disc && disc <= 7 && 26 <= qty && qty <= 35 {
                    let mut ep: u64 = cols_ref.GetLO_EXTENDEDPRICE_usize(i);
                    res = _default::_native_add_u64(res, _default::_native_mul_u64_u32(ep, disc));
                }
            };
            return res;
        }
        /// working_query.dfy(169,1)
        pub fn Main(_noArgsParameter: &Sequence<Sequence<DafnyChar>>) -> () {
            print!("{}", DafnyPrintWrapper(&string_of("SUCCESS\n")));
            return ();
        }
    }

    /// working_query.dfy(4,1)
    #[derive(Clone, Copy)]
    #[repr(transparent)]
    pub struct _u32(pub u32);

    impl PartialEq
        for _u32 {
        fn eq(&self, other: &Self) -> bool {
            self.0 == other.0
        }
    }

    impl Eq
        for _u32 {}

    impl Hash
        for _u32 {
        fn hash<_H: Hasher>(&self, _state: &mut _H) {
            Hash::hash(&self.0, _state)
        }
    }

    impl _u32 {
        /// Constraint check
        pub fn is(_source: u32) -> bool {
            return true;
        }
    }

    impl Default
        for _u32 {
        /// An element of _u32
        fn default() -> Self {
            _u32(Default::default())
        }
    }

    impl DafnyPrint
        for _u32 {
        /// For Dafny print statements
        fn fmt_print(&self, _formatter: &mut Formatter, in_seq: bool) -> Result {
            DafnyPrint::fmt_print(&self.0, _formatter, in_seq)
        }
    }

    impl Deref
        for _u32 {
        type Target = u32;
        fn deref(&self) -> &Self::Target {
            &self.0
        }
    }

    impl _u32 {
        /// SAFETY: The newtype is marked as transparent
        pub fn _from_ref(o: &u32) -> &Self {
            unsafe {
                transmute(o)
            }
        }
    }

    impl Add
        for _u32 {
        type Output = _u32;
        fn add(self, other: Self) -> Self {
            _u32(self.0 + other.0)
        }
    }

    impl Sub
        for _u32 {
        type Output = _u32;
        fn sub(self, other: Self) -> Self {
            _u32(self.0 - other.0)
        }
    }

    impl Mul
        for _u32 {
        type Output = _u32;
        fn mul(self, other: Self) -> Self {
            _u32(self.0 * other.0)
        }
    }

    impl Div
        for _u32 {
        type Output = _u32;
        fn div(self, other: Self) -> Self {
            _u32(self.0 / other.0)
        }
    }

    impl PartialOrd
        for _u32 {
        fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
            PartialOrd::partial_cmp(&self.0, &other.0)
        }
    }

    /// working_query.dfy(5,1)
    #[derive(Clone, Copy)]
    #[repr(transparent)]
    pub struct _u64(pub u64);

    impl PartialEq
        for _u64 {
        fn eq(&self, other: &Self) -> bool {
            self.0 == other.0
        }
    }

    impl Eq
        for _u64 {}

    impl Hash
        for _u64 {
        fn hash<_H: Hasher>(&self, _state: &mut _H) {
            Hash::hash(&self.0, _state)
        }
    }

    impl _u64 {
        /// Constraint check
        pub fn is(_source: u64) -> bool {
            return true;
        }
    }

    impl Default
        for _u64 {
        /// An element of _u64
        fn default() -> Self {
            _u64(Default::default())
        }
    }

    impl DafnyPrint
        for _u64 {
        /// For Dafny print statements
        fn fmt_print(&self, _formatter: &mut Formatter, in_seq: bool) -> Result {
            DafnyPrint::fmt_print(&self.0, _formatter, in_seq)
        }
    }

    impl Deref
        for _u64 {
        type Target = u64;
        fn deref(&self) -> &Self::Target {
            &self.0
        }
    }

    impl _u64 {
        /// SAFETY: The newtype is marked as transparent
        pub fn _from_ref(o: &u64) -> &Self {
            unsafe {
                transmute(o)
            }
        }
    }

    impl Add
        for _u64 {
        type Output = _u64;
        fn add(self, other: Self) -> Self {
            _u64(self.0 + other.0)
        }
    }

    impl Sub
        for _u64 {
        type Output = _u64;
        fn sub(self, other: Self) -> Self {
            _u64(self.0 - other.0)
        }
    }

    impl Mul
        for _u64 {
        type Output = _u64;
        fn mul(self, other: Self) -> Self {
            _u64(self.0 * other.0)
        }
    }

    impl Div
        for _u64 {
        type Output = _u64;
        fn div(self, other: Self) -> Self {
            _u64(self.0 / other.0)
        }
    }

    impl PartialOrd
        for _u64 {
        fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
            PartialOrd::partial_cmp(&self.0, &other.0)
        }
    }

    /// working_query.dfy(6,1)
    #[derive(Clone, Copy)]
    #[repr(transparent)]
    pub struct _i64(pub i64);

    impl PartialEq
        for _i64 {
        fn eq(&self, other: &Self) -> bool {
            self.0 == other.0
        }
    }

    impl Eq
        for _i64 {}

    impl Hash
        for _i64 {
        fn hash<_H: Hasher>(&self, _state: &mut _H) {
            Hash::hash(&self.0, _state)
        }
    }

    impl _i64 {
        /// Constraint check
        pub fn is(_source: i64) -> bool {
            return true;
        }
    }

    impl Default
        for _i64 {
        /// An element of _i64
        fn default() -> Self {
            _i64(Default::default())
        }
    }

    impl DafnyPrint
        for _i64 {
        /// For Dafny print statements
        fn fmt_print(&self, _formatter: &mut Formatter, in_seq: bool) -> Result {
            DafnyPrint::fmt_print(&self.0, _formatter, in_seq)
        }
    }

    impl Deref
        for _i64 {
        type Target = i64;
        fn deref(&self) -> &Self::Target {
            &self.0
        }
    }

    impl _i64 {
        /// SAFETY: The newtype is marked as transparent
        pub fn _from_ref(o: &i64) -> &Self {
            unsafe {
                transmute(o)
            }
        }
    }

    impl Add
        for _i64 {
        type Output = _i64;
        fn add(self, other: Self) -> Self {
            _i64(self.0 + other.0)
        }
    }

    impl Sub
        for _i64 {
        type Output = _i64;
        fn sub(self, other: Self) -> Self {
            _i64(self.0 - other.0)
        }
    }

    impl Mul
        for _i64 {
        type Output = _i64;
        fn mul(self, other: Self) -> Self {
            _i64(self.0 * other.0)
        }
    }

    impl Div
        for _i64 {
        type Output = _i64;
        fn div(self, other: Self) -> Self {
            _i64(self.0 / other.0)
        }
    }

    impl PartialOrd
        for _i64 {
        fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
            PartialOrd::partial_cmp(&self.0, &other.0)
        }
    }
}


fn load_cols_from_tbl(tbl_path: &str, limit: usize) -> ::dafny_runtime::Object<crate::_dafny_externs::ColsNative> {
    use std::collections::HashMap;
    use std::fs::File;
    use std::io::{BufRead, BufReader};
    use std::sync::Arc;
    use crate::_dafny_externs::ColsNative;
    let mut base = std::env::current_dir().unwrap();
    let mut p = base.join(tbl_path);
    while !p.exists() {
        match base.parent() { Some(par) => { base = par.to_path_buf(); p = base.join(tbl_path); } None => break }
    }
    let mut rdr = BufReader::new(File::open(&p).unwrap());
    let mut hdr = String::new();
    rdr.read_line(&mut hdr).unwrap();
    let mut ci: HashMap<String, usize> = HashMap::new();
    for (i, c) in hdr.split('|').enumerate() { ci.insert(c.trim().to_uppercase(), i); }
    let mut v_lo_orderkey: Vec<u32> = Vec::new();
    let mut v_lo_linenumber: Vec<u32> = Vec::new();
    let mut v_lo_custkey: Vec<u32> = Vec::new();
    let mut v_lo_partkey: Vec<u32> = Vec::new();
    let mut v_lo_suppkey: Vec<u32> = Vec::new();
    let mut v_lo_orderdate: Vec<u32> = Vec::new();
    let mut v_lo_orderpriority: Vec<String> = Vec::new();
    let mut v_lo_shippriority: Vec<u32> = Vec::new();
    let mut v_lo_quantity: Vec<u32> = Vec::new();
    let mut v_lo_extendedprice: Vec<u64> = Vec::new();
    let mut v_lo_ordtotalprice: Vec<u64> = Vec::new();
    let mut v_lo_discount: Vec<u32> = Vec::new();
    let mut v_lo_revenue: Vec<u64> = Vec::new();
    let mut v_lo_supplycost: Vec<u64> = Vec::new();
    let mut v_lo_tax: Vec<u32> = Vec::new();
    let mut v_lo_commitdate: Vec<u32> = Vec::new();
    let mut v_lo_shipmode: Vec<String> = Vec::new();
    let mut v_c_name: Vec<String> = Vec::new();
    let mut v_c_address: Vec<String> = Vec::new();
    let mut v_c_city: Vec<String> = Vec::new();
    let mut v_c_nation: Vec<String> = Vec::new();
    let mut v_c_region: Vec<String> = Vec::new();
    let mut v_c_phone: Vec<String> = Vec::new();
    let mut v_c_mktsegment: Vec<String> = Vec::new();
    let mut v_s_name: Vec<String> = Vec::new();
    let mut v_s_address: Vec<String> = Vec::new();
    let mut v_s_city: Vec<String> = Vec::new();
    let mut v_s_nation: Vec<String> = Vec::new();
    let mut v_s_region: Vec<String> = Vec::new();
    let mut v_s_phone: Vec<String> = Vec::new();
    let mut v_p_name: Vec<String> = Vec::new();
    let mut v_p_mfgr: Vec<String> = Vec::new();
    let mut v_p_category: Vec<String> = Vec::new();
    let mut v_p_brand: Vec<String> = Vec::new();
    let mut v_p_color: Vec<String> = Vec::new();
    let mut v_p_type: Vec<String> = Vec::new();
    let mut v_p_size: Vec<u32> = Vec::new();
    let mut v_p_container: Vec<String> = Vec::new();
    let mut v_d_year: Vec<u32> = Vec::new();
    let mut v_d_yearmonthnum: Vec<u32> = Vec::new();
    let mut v_d_weeknuminyear: Vec<u32> = Vec::new();
    let mut n = 0usize;
    for ln in rdr.lines().take(limit) {
        let line = ln.unwrap();
        let f: Vec<&str> = line.split('|').collect();
        if f.is_empty() { continue; }
        v_lo_orderkey.push(f[ci["LO_ORDERKEY"]].parse::<u32>().unwrap());
        v_lo_linenumber.push(f[ci["LO_LINENUMBER"]].parse::<u32>().unwrap());
        v_lo_custkey.push(f[ci["LO_CUSTKEY"]].parse::<u32>().unwrap());
        v_lo_partkey.push(f[ci["LO_PARTKEY"]].parse::<u32>().unwrap());
        v_lo_suppkey.push(f[ci["LO_SUPPKEY"]].parse::<u32>().unwrap());
        v_lo_orderdate.push(f[ci["LO_ORDERDATE"]].parse::<u32>().unwrap());
        v_lo_orderpriority.push(f[ci["LO_ORDERPRIORITY"]].trim_matches('"').to_string());
        v_lo_shippriority.push(f[ci["LO_SHIPPRIORITY"]].parse::<u32>().unwrap());
        v_lo_quantity.push(f[ci["LO_QUANTITY"]].parse::<u32>().unwrap());
        v_lo_extendedprice.push(f[ci["LO_EXTENDEDPRICE"]].parse::<u64>().unwrap());
        v_lo_ordtotalprice.push(f[ci["LO_ORDTOTALPRICE"]].parse::<u64>().unwrap());
        v_lo_discount.push(f[ci["LO_DISCOUNT"]].parse::<u32>().unwrap());
        v_lo_revenue.push(f[ci["LO_REVENUE"]].parse::<u64>().unwrap());
        v_lo_supplycost.push(f[ci["LO_SUPPLYCOST"]].parse::<u64>().unwrap());
        v_lo_tax.push(f[ci["LO_TAX"]].parse::<u32>().unwrap());
        v_lo_commitdate.push(f[ci["LO_COMMITDATE"]].parse::<u32>().unwrap());
        v_lo_shipmode.push(f[ci["LO_SHIPMODE"]].trim_matches('"').to_string());
        v_c_name.push(f[ci["C_NAME"]].trim_matches('"').to_string());
        v_c_address.push(f[ci["C_ADDRESS"]].trim_matches('"').to_string());
        v_c_city.push(f[ci["C_CITY"]].trim_matches('"').to_string());
        v_c_nation.push(f[ci["C_NATION"]].trim_matches('"').to_string());
        v_c_region.push(f[ci["C_REGION"]].trim_matches('"').to_string());
        v_c_phone.push(f[ci["C_PHONE"]].trim_matches('"').to_string());
        v_c_mktsegment.push(f[ci["C_MKTSEGMENT"]].trim_matches('"').to_string());
        v_s_name.push(f[ci["S_NAME"]].trim_matches('"').to_string());
        v_s_address.push(f[ci["S_ADDRESS"]].trim_matches('"').to_string());
        v_s_city.push(f[ci["S_CITY"]].trim_matches('"').to_string());
        v_s_nation.push(f[ci["S_NATION"]].trim_matches('"').to_string());
        v_s_region.push(f[ci["S_REGION"]].trim_matches('"').to_string());
        v_s_phone.push(f[ci["S_PHONE"]].trim_matches('"').to_string());
        v_p_name.push(f[ci["P_NAME"]].trim_matches('"').to_string());
        v_p_mfgr.push(f[ci["P_MFGR"]].trim_matches('"').to_string());
        v_p_category.push(f[ci["P_CATEGORY"]].trim_matches('"').to_string());
        v_p_brand.push(f[ci["P_BRAND"]].trim_matches('"').to_string());
        v_p_color.push(f[ci["P_COLOR"]].trim_matches('"').to_string());
        v_p_type.push(f[ci["P_TYPE"]].trim_matches('"').to_string());
        v_p_size.push(f[ci["P_SIZE"]].parse::<u32>().unwrap());
        v_p_container.push(f[ci["P_CONTAINER"]].trim_matches('"').to_string());
        v_d_year.push(f[ci["D_YEAR"]].parse::<u32>().unwrap());
        v_d_yearmonthnum.push(f[ci["D_YEARMONTHNUM"]].parse::<u32>().unwrap());
        v_d_weeknuminyear.push(f[ci["D_WEEKNUMINYEAR"]].parse::<u32>().unwrap());
        n += 1;
    }
    ::dafny_runtime::Object::new(ColsNative {
        n,
        lo_orderkey: Arc::new(v_lo_orderkey),
        lo_linenumber: Arc::new(v_lo_linenumber),
        lo_custkey: Arc::new(v_lo_custkey),
        lo_partkey: Arc::new(v_lo_partkey),
        lo_suppkey: Arc::new(v_lo_suppkey),
        lo_orderdate: Arc::new(v_lo_orderdate),
        lo_orderpriority: Arc::new(v_lo_orderpriority),
        lo_shippriority: Arc::new(v_lo_shippriority),
        lo_quantity: Arc::new(v_lo_quantity),
        lo_extendedprice: Arc::new(v_lo_extendedprice),
        lo_ordtotalprice: Arc::new(v_lo_ordtotalprice),
        lo_discount: Arc::new(v_lo_discount),
        lo_revenue: Arc::new(v_lo_revenue),
        lo_supplycost: Arc::new(v_lo_supplycost),
        lo_tax: Arc::new(v_lo_tax),
        lo_commitdate: Arc::new(v_lo_commitdate),
        lo_shipmode: Arc::new(v_lo_shipmode),
        c_name: Arc::new(v_c_name),
        c_address: Arc::new(v_c_address),
        c_city: Arc::new(v_c_city),
        c_nation: Arc::new(v_c_nation),
        c_region: Arc::new(v_c_region),
        c_phone: Arc::new(v_c_phone),
        c_mktsegment: Arc::new(v_c_mktsegment),
        s_name: Arc::new(v_s_name),
        s_address: Arc::new(v_s_address),
        s_city: Arc::new(v_s_city),
        s_nation: Arc::new(v_s_nation),
        s_region: Arc::new(v_s_region),
        s_phone: Arc::new(v_s_phone),
        p_name: Arc::new(v_p_name),
        p_mfgr: Arc::new(v_p_mfgr),
        p_category: Arc::new(v_p_category),
        p_brand: Arc::new(v_p_brand),
        p_color: Arc::new(v_p_color),
        p_type: Arc::new(v_p_type),
        p_size: Arc::new(v_p_size),
        p_container: Arc::new(v_p_container),
        d_year: Arc::new(v_d_year),
        d_yearmonthnum: Arc::new(v_d_yearmonthnum),
        d_weeknuminyear: Arc::new(v_d_weeknuminyear),
    })
}

fn main() {
    use std::time::Instant;
    let cols = load_cols_from_tbl("ssb-dbgen/lineorder_flat.tbl", 50000);
    for run in 0..3 {
        let t0 = Instant::now();
        let _ = crate::_module::_default::RunQuery(&cols);
        let dt = t0.elapsed().as_micros();
        if run == 2 {
            println!("QUERY_LATENCY_US: {}", dt);
        }
    }
}
