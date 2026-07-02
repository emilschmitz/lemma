use dafny_runtime::{
    dafny_runtime_conversions::unicode_chars_true::{dafny_string_to_string, string_to_dafny_string},
    allocate_object, DynAny, DafnyChar, DafnyInt, DafnyPrint, Object, Rc, Sequence, UpcastObject,
};
use std::fmt::{Debug, Formatter, Result as FmtResult};
use std::sync::Arc;

#[derive(Clone, Default)]
pub struct ColsNative {
    pub n: usize,
    pub lo_orderkey: Arc<Vec<u32>>,
    pub lo_linenumber: Arc<Vec<u32>>,
    pub lo_custkey: Arc<Vec<u32>>,
    pub lo_partkey: Arc<Vec<u32>>,
    pub lo_suppkey: Arc<Vec<u32>>,
    pub lo_orderdate: Arc<Vec<u32>>,
    pub lo_orderpriority: Arc<Vec<String>>,
    pub lo_shippriority: Arc<Vec<u32>>,
    pub lo_quantity: Arc<Vec<u32>>,
    pub lo_extendedprice: Arc<Vec<u64>>,
    pub lo_ordtotalprice: Arc<Vec<u64>>,
    pub lo_discount: Arc<Vec<u32>>,
    pub lo_revenue: Arc<Vec<u64>>,
    pub lo_supplycost: Arc<Vec<u64>>,
    pub lo_tax: Arc<Vec<u32>>,
    pub lo_commitdate: Arc<Vec<u32>>,
    pub lo_shipmode: Arc<Vec<String>>,
    pub c_name: Arc<Vec<String>>,
    pub c_address: Arc<Vec<String>>,
    pub c_city: Arc<Vec<String>>,
    pub c_nation: Arc<Vec<String>>,
    pub c_region: Arc<Vec<String>>,
    pub c_phone: Arc<Vec<String>>,
    pub c_mktsegment: Arc<Vec<String>>,
    pub s_name: Arc<Vec<String>>,
    pub s_address: Arc<Vec<String>>,
    pub s_city: Arc<Vec<String>>,
    pub s_nation: Arc<Vec<String>>,
    pub s_region: Arc<Vec<String>>,
    pub s_phone: Arc<Vec<String>>,
    pub p_name: Arc<Vec<String>>,
    pub p_mfgr: Arc<Vec<String>>,
    pub p_category: Arc<Vec<String>>,
    pub p_brand: Arc<Vec<String>>,
    pub p_color: Arc<Vec<String>>,
    pub p_type: Arc<Vec<String>>,
    pub p_size: Arc<Vec<u32>>,
    pub p_container: Arc<Vec<String>>,
    pub d_year: Arc<Vec<u32>>,
    pub d_yearmonthnum: Arc<Vec<u32>>,
    pub d_weeknuminyear: Arc<Vec<u32>>,
}

impl Debug for ColsNative {
    fn fmt(&self, f: &mut Formatter<'_>) -> FmtResult {
        f.debug_struct("ColsNative").field("n", &self.n).finish()
    }
}

impl DafnyPrint for ColsNative {
    fn fmt_print(&self, _f: &mut Formatter, _in_seq: bool) -> FmtResult {
        Ok(())
    }
}

impl UpcastObject<DynAny> for ColsNative {
    fn upcast(&self) -> Object<DynAny> {
        unsafe { Object::from_rc(Rc::new(self.clone()) as Rc<DynAny>) }
    }
}

impl ColsNative {
    pub fn _allocate_object() -> Object<ColsNative> {
        allocate_object::<ColsNative>()
    }

    pub fn n(&self) -> DafnyInt {
        DafnyInt::from(self.n)
    }

    pub fn GetLO_ORDERKEY(&self, i: &DafnyInt) -> u32 {
        self.lo_orderkey[usize::from(i.clone())]
    }

    pub fn GetLO_ORDERKEY_usize(&self, i: usize) -> u32 {
        self.lo_orderkey[i]
    }
    pub fn GetLO_LINENUMBER(&self, i: &DafnyInt) -> u32 {
        self.lo_linenumber[usize::from(i.clone())]
    }

    pub fn GetLO_LINENUMBER_usize(&self, i: usize) -> u32 {
        self.lo_linenumber[i]
    }
    pub fn GetLO_CUSTKEY(&self, i: &DafnyInt) -> u32 {
        self.lo_custkey[usize::from(i.clone())]
    }

    pub fn GetLO_CUSTKEY_usize(&self, i: usize) -> u32 {
        self.lo_custkey[i]
    }
    pub fn GetLO_PARTKEY(&self, i: &DafnyInt) -> u32 {
        self.lo_partkey[usize::from(i.clone())]
    }

    pub fn GetLO_PARTKEY_usize(&self, i: usize) -> u32 {
        self.lo_partkey[i]
    }
    pub fn GetLO_SUPPKEY(&self, i: &DafnyInt) -> u32 {
        self.lo_suppkey[usize::from(i.clone())]
    }

    pub fn GetLO_SUPPKEY_usize(&self, i: usize) -> u32 {
        self.lo_suppkey[i]
    }
    pub fn GetLO_ORDERDATE(&self, i: &DafnyInt) -> u32 {
        self.lo_orderdate[usize::from(i.clone())]
    }

    pub fn GetLO_ORDERDATE_usize(&self, i: usize) -> u32 {
        self.lo_orderdate[i]
    }
    pub fn GetLO_ORDERPRIORITY(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.lo_orderpriority[usize::from(i.clone())])
    }

    pub fn GetLO_ORDERPRIORITY_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.lo_orderpriority[i])
    }

    pub fn GetLO_ORDERPRIORITY_str_ref(&self, i: usize) -> &str {
        &self.lo_orderpriority[i]
    }

    pub fn EqAtLO_ORDERPRIORITY(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.lo_orderpriority[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtLO_ORDERPRIORITY_usize(&self, i: usize, lit: &str) -> bool {
        self.lo_orderpriority[i] == lit
    }
    pub fn GetLO_SHIPPRIORITY(&self, i: &DafnyInt) -> u32 {
        self.lo_shippriority[usize::from(i.clone())]
    }

    pub fn GetLO_SHIPPRIORITY_usize(&self, i: usize) -> u32 {
        self.lo_shippriority[i]
    }
    pub fn GetLO_QUANTITY(&self, i: &DafnyInt) -> u32 {
        self.lo_quantity[usize::from(i.clone())]
    }

    pub fn GetLO_QUANTITY_usize(&self, i: usize) -> u32 {
        self.lo_quantity[i]
    }
    pub fn GetLO_EXTENDEDPRICE(&self, i: &DafnyInt) -> u64 {
        self.lo_extendedprice[usize::from(i.clone())]
    }

    pub fn GetLO_EXTENDEDPRICE_usize(&self, i: usize) -> u64 {
        self.lo_extendedprice[i]
    }
    pub fn GetLO_ORDTOTALPRICE(&self, i: &DafnyInt) -> u64 {
        self.lo_ordtotalprice[usize::from(i.clone())]
    }

    pub fn GetLO_ORDTOTALPRICE_usize(&self, i: usize) -> u64 {
        self.lo_ordtotalprice[i]
    }
    pub fn GetLO_DISCOUNT(&self, i: &DafnyInt) -> u32 {
        self.lo_discount[usize::from(i.clone())]
    }

    pub fn GetLO_DISCOUNT_usize(&self, i: usize) -> u32 {
        self.lo_discount[i]
    }
    pub fn GetLO_REVENUE(&self, i: &DafnyInt) -> u64 {
        self.lo_revenue[usize::from(i.clone())]
    }

    pub fn GetLO_REVENUE_usize(&self, i: usize) -> u64 {
        self.lo_revenue[i]
    }
    pub fn GetLO_SUPPLYCOST(&self, i: &DafnyInt) -> u64 {
        self.lo_supplycost[usize::from(i.clone())]
    }

    pub fn GetLO_SUPPLYCOST_usize(&self, i: usize) -> u64 {
        self.lo_supplycost[i]
    }
    pub fn GetLO_TAX(&self, i: &DafnyInt) -> u32 {
        self.lo_tax[usize::from(i.clone())]
    }

    pub fn GetLO_TAX_usize(&self, i: usize) -> u32 {
        self.lo_tax[i]
    }
    pub fn GetLO_COMMITDATE(&self, i: &DafnyInt) -> u32 {
        self.lo_commitdate[usize::from(i.clone())]
    }

    pub fn GetLO_COMMITDATE_usize(&self, i: usize) -> u32 {
        self.lo_commitdate[i]
    }
    pub fn GetLO_SHIPMODE(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.lo_shipmode[usize::from(i.clone())])
    }

    pub fn GetLO_SHIPMODE_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.lo_shipmode[i])
    }

    pub fn GetLO_SHIPMODE_str_ref(&self, i: usize) -> &str {
        &self.lo_shipmode[i]
    }

    pub fn EqAtLO_SHIPMODE(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.lo_shipmode[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtLO_SHIPMODE_usize(&self, i: usize, lit: &str) -> bool {
        self.lo_shipmode[i] == lit
    }
    pub fn GetC_NAME(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_name[usize::from(i.clone())])
    }

    pub fn GetC_NAME_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_name[i])
    }

    pub fn GetC_NAME_str_ref(&self, i: usize) -> &str {
        &self.c_name[i]
    }

    pub fn EqAtC_NAME(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.c_name[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtC_NAME_usize(&self, i: usize, lit: &str) -> bool {
        self.c_name[i] == lit
    }
    pub fn GetC_ADDRESS(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_address[usize::from(i.clone())])
    }

    pub fn GetC_ADDRESS_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_address[i])
    }

    pub fn GetC_ADDRESS_str_ref(&self, i: usize) -> &str {
        &self.c_address[i]
    }

    pub fn EqAtC_ADDRESS(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.c_address[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtC_ADDRESS_usize(&self, i: usize, lit: &str) -> bool {
        self.c_address[i] == lit
    }
    pub fn GetC_CITY(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_city[usize::from(i.clone())])
    }

    pub fn GetC_CITY_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_city[i])
    }

    pub fn GetC_CITY_str_ref(&self, i: usize) -> &str {
        &self.c_city[i]
    }

    pub fn EqAtC_CITY(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.c_city[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtC_CITY_usize(&self, i: usize, lit: &str) -> bool {
        self.c_city[i] == lit
    }
    pub fn GetC_NATION(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_nation[usize::from(i.clone())])
    }

    pub fn GetC_NATION_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_nation[i])
    }

    pub fn GetC_NATION_str_ref(&self, i: usize) -> &str {
        &self.c_nation[i]
    }

    pub fn EqAtC_NATION(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.c_nation[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtC_NATION_usize(&self, i: usize, lit: &str) -> bool {
        self.c_nation[i] == lit
    }
    pub fn GetC_REGION(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_region[usize::from(i.clone())])
    }

    pub fn GetC_REGION_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_region[i])
    }

    pub fn GetC_REGION_str_ref(&self, i: usize) -> &str {
        &self.c_region[i]
    }

    pub fn EqAtC_REGION(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.c_region[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtC_REGION_usize(&self, i: usize, lit: &str) -> bool {
        self.c_region[i] == lit
    }
    pub fn GetC_PHONE(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_phone[usize::from(i.clone())])
    }

    pub fn GetC_PHONE_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_phone[i])
    }

    pub fn GetC_PHONE_str_ref(&self, i: usize) -> &str {
        &self.c_phone[i]
    }

    pub fn EqAtC_PHONE(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.c_phone[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtC_PHONE_usize(&self, i: usize, lit: &str) -> bool {
        self.c_phone[i] == lit
    }
    pub fn GetC_MKTSEGMENT(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_mktsegment[usize::from(i.clone())])
    }

    pub fn GetC_MKTSEGMENT_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.c_mktsegment[i])
    }

    pub fn GetC_MKTSEGMENT_str_ref(&self, i: usize) -> &str {
        &self.c_mktsegment[i]
    }

    pub fn EqAtC_MKTSEGMENT(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.c_mktsegment[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtC_MKTSEGMENT_usize(&self, i: usize, lit: &str) -> bool {
        self.c_mktsegment[i] == lit
    }
    pub fn GetS_NAME(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.s_name[usize::from(i.clone())])
    }

    pub fn GetS_NAME_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.s_name[i])
    }

    pub fn GetS_NAME_str_ref(&self, i: usize) -> &str {
        &self.s_name[i]
    }

    pub fn EqAtS_NAME(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.s_name[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtS_NAME_usize(&self, i: usize, lit: &str) -> bool {
        self.s_name[i] == lit
    }
    pub fn GetS_ADDRESS(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.s_address[usize::from(i.clone())])
    }

    pub fn GetS_ADDRESS_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.s_address[i])
    }

    pub fn GetS_ADDRESS_str_ref(&self, i: usize) -> &str {
        &self.s_address[i]
    }

    pub fn EqAtS_ADDRESS(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.s_address[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtS_ADDRESS_usize(&self, i: usize, lit: &str) -> bool {
        self.s_address[i] == lit
    }
    pub fn GetS_CITY(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.s_city[usize::from(i.clone())])
    }

    pub fn GetS_CITY_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.s_city[i])
    }

    pub fn GetS_CITY_str_ref(&self, i: usize) -> &str {
        &self.s_city[i]
    }

    pub fn EqAtS_CITY(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.s_city[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtS_CITY_usize(&self, i: usize, lit: &str) -> bool {
        self.s_city[i] == lit
    }
    pub fn GetS_NATION(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.s_nation[usize::from(i.clone())])
    }

    pub fn GetS_NATION_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.s_nation[i])
    }

    pub fn GetS_NATION_str_ref(&self, i: usize) -> &str {
        &self.s_nation[i]
    }

    pub fn EqAtS_NATION(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.s_nation[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtS_NATION_usize(&self, i: usize, lit: &str) -> bool {
        self.s_nation[i] == lit
    }
    pub fn GetS_REGION(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.s_region[usize::from(i.clone())])
    }

    pub fn GetS_REGION_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.s_region[i])
    }

    pub fn GetS_REGION_str_ref(&self, i: usize) -> &str {
        &self.s_region[i]
    }

    pub fn EqAtS_REGION(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.s_region[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtS_REGION_usize(&self, i: usize, lit: &str) -> bool {
        self.s_region[i] == lit
    }
    pub fn GetS_PHONE(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.s_phone[usize::from(i.clone())])
    }

    pub fn GetS_PHONE_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.s_phone[i])
    }

    pub fn GetS_PHONE_str_ref(&self, i: usize) -> &str {
        &self.s_phone[i]
    }

    pub fn EqAtS_PHONE(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.s_phone[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtS_PHONE_usize(&self, i: usize, lit: &str) -> bool {
        self.s_phone[i] == lit
    }
    pub fn GetP_NAME(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_name[usize::from(i.clone())])
    }

    pub fn GetP_NAME_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_name[i])
    }

    pub fn GetP_NAME_str_ref(&self, i: usize) -> &str {
        &self.p_name[i]
    }

    pub fn EqAtP_NAME(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.p_name[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtP_NAME_usize(&self, i: usize, lit: &str) -> bool {
        self.p_name[i] == lit
    }
    pub fn GetP_MFGR(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_mfgr[usize::from(i.clone())])
    }

    pub fn GetP_MFGR_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_mfgr[i])
    }

    pub fn GetP_MFGR_str_ref(&self, i: usize) -> &str {
        &self.p_mfgr[i]
    }

    pub fn EqAtP_MFGR(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.p_mfgr[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtP_MFGR_usize(&self, i: usize, lit: &str) -> bool {
        self.p_mfgr[i] == lit
    }
    pub fn GetP_CATEGORY(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_category[usize::from(i.clone())])
    }

    pub fn GetP_CATEGORY_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_category[i])
    }

    pub fn GetP_CATEGORY_str_ref(&self, i: usize) -> &str {
        &self.p_category[i]
    }

    pub fn EqAtP_CATEGORY(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.p_category[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtP_CATEGORY_usize(&self, i: usize, lit: &str) -> bool {
        self.p_category[i] == lit
    }
    pub fn GetP_BRAND(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_brand[usize::from(i.clone())])
    }

    pub fn GetP_BRAND_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_brand[i])
    }

    pub fn GetP_BRAND_str_ref(&self, i: usize) -> &str {
        &self.p_brand[i]
    }

    pub fn EqAtP_BRAND(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.p_brand[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtP_BRAND_usize(&self, i: usize, lit: &str) -> bool {
        self.p_brand[i] == lit
    }
    pub fn GetP_COLOR(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_color[usize::from(i.clone())])
    }

    pub fn GetP_COLOR_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_color[i])
    }

    pub fn GetP_COLOR_str_ref(&self, i: usize) -> &str {
        &self.p_color[i]
    }

    pub fn EqAtP_COLOR(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.p_color[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtP_COLOR_usize(&self, i: usize, lit: &str) -> bool {
        self.p_color[i] == lit
    }
    pub fn GetP_TYPE(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_type[usize::from(i.clone())])
    }

    pub fn GetP_TYPE_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_type[i])
    }

    pub fn GetP_TYPE_str_ref(&self, i: usize) -> &str {
        &self.p_type[i]
    }

    pub fn EqAtP_TYPE(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.p_type[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtP_TYPE_usize(&self, i: usize, lit: &str) -> bool {
        self.p_type[i] == lit
    }
    pub fn GetP_SIZE(&self, i: &DafnyInt) -> u32 {
        self.p_size[usize::from(i.clone())]
    }

    pub fn GetP_SIZE_usize(&self, i: usize) -> u32 {
        self.p_size[i]
    }
    pub fn GetP_CONTAINER(&self, i: &DafnyInt) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_container[usize::from(i.clone())])
    }

    pub fn GetP_CONTAINER_usize(&self, i: usize) -> Sequence<DafnyChar> {
        string_to_dafny_string(&self.p_container[i])
    }

    pub fn GetP_CONTAINER_str_ref(&self, i: usize) -> &str {
        &self.p_container[i]
    }

    pub fn EqAtP_CONTAINER(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {
        self.p_container[usize::from(i.clone())] == dafny_string_to_string(lit)
    }

    pub fn EqAtP_CONTAINER_usize(&self, i: usize, lit: &str) -> bool {
        self.p_container[i] == lit
    }
    pub fn GetD_YEAR(&self, i: &DafnyInt) -> u32 {
        self.d_year[usize::from(i.clone())]
    }

    pub fn GetD_YEAR_usize(&self, i: usize) -> u32 {
        self.d_year[i]
    }
    pub fn GetD_YEARMONTHNUM(&self, i: &DafnyInt) -> u32 {
        self.d_yearmonthnum[usize::from(i.clone())]
    }

    pub fn GetD_YEARMONTHNUM_usize(&self, i: usize) -> u32 {
        self.d_yearmonthnum[i]
    }
    pub fn GetD_WEEKNUMINYEAR(&self, i: &DafnyInt) -> u32 {
        self.d_weeknuminyear[usize::from(i.clone())]
    }

    pub fn GetD_WEEKNUMINYEAR_usize(&self, i: usize) -> u32 {
        self.d_weeknuminyear[i]
    }
}
