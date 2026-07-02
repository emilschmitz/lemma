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
    pub use ::dafny_runtime::Object;
    pub use ::dafny_runtime::int;
    pub use ::dafny_runtime::rd;
    pub use ::dafny_runtime::DafnyInt;
    pub use ::dafny_runtime::Map;
    pub use ::dafny_runtime::Sequence;
    pub use ::dafny_runtime::DafnyChar;
    pub use ::dafny_runtime::string_of;
    pub use ::dafny_runtime::map;
    pub use ::dafny_runtime::MaybePlacebo;
    pub use ::dafny_runtime::euclidian_modulo;
    pub use ::std::cmp::PartialEq;
    pub use ::std::cmp::Eq;
    pub use ::std::hash::Hash;
    pub use ::std::hash::Hasher;
    pub use ::std::default::Default;
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
        /// q.dfy(103,1)
        pub fn ValidCols(cols: &Object<ColsNative>) -> bool {
            int!(0) <= rd!(cols).n()
        }
        /// q.dfy(108,1)
        pub fn MethodSpecHelper(cols: &Object<ColsNative>, k: &DafnyInt) -> Map<(u32, Sequence<DafnyChar>), i64> {
            if k.clone() < rd!(cols).n() {
                let mut tail: Map<(u32, Sequence<DafnyChar>), i64> = _default::MethodSpecHelper(cols, &(k.clone() + int!(1)));
                if rd!(cols).EqAtC_REGION(k, &string_of("AMERICA")) && rd!(cols).EqAtS_REGION(k, &string_of("AMERICA")) && rd!(cols).EqAtP_MFGR(k, &string_of("MFGR#1")) {
                    let mut key: (u32, Sequence<DafnyChar>) = (
                            rd!(cols).GetD_YEAR(k),
                            rd!(cols).GetC_NATION(k)
                        );
                    let mut val: i64 = if tail.contains(&key) {
                            tail.get(&key)
                        } else {
                            0
                        };
                    tail.update_index(&key, &_default::_native_add_i64(val, _default::_native_sub_u64_i64(rd!(cols).GetLO_REVENUE(k), rd!(cols).GetLO_SUPPLYCOST(k))))
                } else {
                    tail.clone()
                }
            } else {
                map![] as Map<(u32, Sequence<DafnyChar>), i64>
            }
        }
        /// q.dfy(125,1)
        pub fn MethodSpec(cols: &Object<ColsNative>) -> Map<(u32, Sequence<DafnyChar>), i64> {
            _default::MethodSpecHelper(cols, &int!(0))
        }
        /// q.dfy(159,1)
        pub fn RunQuery(cols: &Object<ColsNative>) -> Map<(u32, Sequence<DafnyChar>), i64> {
            let mut res = MaybePlacebo::<Map<(u32, Sequence<DafnyChar>), i64>>::new();
            let mut agg: Object<NativeAggMap>;
            let mut _nw0: Object<NativeAggMap> = NativeAggMap::_allocate_object();
            agg = _nw0.clone();
            let mut alias: Object<NativeAggMap> = agg.clone();
            let mut i: DafnyInt = rd!(cols).n();
            while int!(0) < i.clone() {
                i = i.clone() - int!(1);
                if rd!(cols).EqAtC_REGION(&i, &string_of("AMERICA")) && rd!(cols).EqAtS_REGION(&i, &string_of("AMERICA")) && rd!(cols).EqAtP_MFGR(&i, &string_of("MFGR#1")) {
                    let mut yr: u32 = rd!(cols).GetD_YEAR(&i);
                    let mut nation: Sequence<DafnyChar> = rd!(cols).GetC_NATION(&i);
                    let mut key: (u32, Sequence<DafnyChar>) = (
                            yr,
                            nation.clone()
                        );
                    let mut term: i64 = _default::_native_sub_u64_i64(rd!(cols).GetLO_REVENUE(&i), rd!(cols).GetLO_SUPPLYCOST(&i));
                    if euclidian_modulo(int!(yr), int!(2)) == int!(0) {
                        rd!(agg).Add(yr, &nation, term)
                    } else {
                        rd!(alias).Add(yr, &nation, term)
                    }
                }
            };
            let mut _out0: Map<(u32, Sequence<DafnyChar>), i64> = rd!(agg).ToMap();
            res = MaybePlacebo::from(_out0.clone());
            return res.read();
        }
        /// q.dfy(198,1)
        pub fn Main(_noArgsParameter: &Sequence<Sequence<DafnyChar>>) -> () {
            return ();
        }
    }

    /// q.dfy(4,1)
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

    /// q.dfy(5,1)
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

    /// q.dfy(6,1)
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
fn main() {
  let args: Vec<String> = ::std::env::args().collect();
  let dafny_args =
    ::dafny_runtime::dafny_runtime_conversions::vec_to_dafny_sequence(
    &args, |s| 
  ::dafny_runtime::dafny_runtime_conversions::unicode_chars_true::string_to_dafny_string(s));
  crate::_module::_default::Main(&dafny_args);
}