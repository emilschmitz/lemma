#![allow(warnings, unconditional_panic)]
#![allow(nonstandard_style)]
#![cfg_attr(any(), rustfmt::skip)]

pub mod _module {
    pub use ::dafny_runtime::Sequence;
    pub use ::std::rc::Rc;
    pub use ::dafny_runtime::DafnyInt;
    pub use ::dafny_runtime::int;
    pub use ::dafny_runtime::DafnyChar;
    pub use ::dafny_runtime::euclidian_modulo;
    pub use ::dafny_runtime::string_of;
    pub use ::dafny_runtime::integer_range;
    pub use ::dafny_runtime::Zero;
    pub use ::dafny_runtime::DafnyPrintWrapper;
    pub use ::std::fmt::Debug;
    pub use ::std::fmt::Formatter;
    pub use ::std::fmt::Result;
    pub use ::dafny_runtime::DafnyPrint;
    pub use ::std::cmp::PartialEq;
    pub use ::std::cmp::Eq;
    pub use ::std::hash::Hash;
    pub use ::std::hash::Hasher;
    pub use ::std::convert::AsRef;

    pub struct _default {}

    impl _default {
        /// working_query.dfy(3,1)
        pub fn MethodSpec(data: &Sequence<Rc<Row>>) -> DafnyInt {
            let mut _accumulator: DafnyInt = int!(0);
            let mut _r0 = data.clone();
            'TAIL_CALL_START: loop {
                let data = _r0;
                if data.cardinality() == int!(0) {
                    return int!(0) + _accumulator.clone();
                } else {
                    let mut row: Rc<Row> = data.get(&int!(0));
                    let mut tail: Sequence<Rc<Row>> = data.drop(&int!(1));
                    let mut term: DafnyInt = if row.LO_ORDERDATE().clone() >= int!(b"19930101") && row.LO_ORDERDATE().clone() <= int!(b"19931231") && row.LO_DISCOUNT().clone() >= int!(1) && row.LO_DISCOUNT().clone() <= int!(3) && row.LO_QUANTITY().clone() < int!(25) {
                            row.LO_EXTENDEDPRICE().clone() * row.LO_DISCOUNT().clone()
                        } else {
                            int!(0)
                        };
                    _accumulator = _accumulator.clone() + term.clone();
                    let mut _in0: Sequence<Rc<Row>> = tail.clone();
                    _r0 = _in0.clone();
                    continue 'TAIL_CALL_START;
                }
            }
        }
        /// working_query.dfy(11,1)
        pub fn RunQuery(data: &Sequence<Rc<Row>>) -> DafnyInt {
            let mut res: DafnyInt = int!(0);
            let mut i: DafnyInt = int!(0);
            while i.clone() < data.cardinality() {
                let mut row: Rc<Row> = data.get(&i);
                let mut term: DafnyInt;
                if row.LO_ORDERDATE().clone() >= int!(b"19930101") && row.LO_ORDERDATE().clone() <= int!(b"19931231") && row.LO_DISCOUNT().clone() >= int!(1) && row.LO_DISCOUNT().clone() <= int!(3) && row.LO_QUANTITY().clone() < int!(25) {
                    term = row.LO_EXTENDEDPRICE().clone() * row.LO_DISCOUNT().clone();
                } else {
                    term = int!(0);
                };
                res = res.clone() + term.clone();
                i = i.clone() + int!(1);
            };
            return res.clone();
        }
        /// working_query.dfy(28,1)
        pub fn Main(_noArgsParameter: &Sequence<Sequence<DafnyChar>>) -> () {
            let mut data: Sequence<Rc<Row>> = {
                    let _initializer = {
                            Rc::new(move |i: &DafnyInt| -> Rc<Row>{
            Rc::new(Row::Row {
                    LO_ORDERKEY: int!(1) + euclidian_modulo(i.clone(), int!(100)),
                    LO_LINENUMBER: int!(1) + euclidian_modulo(i.clone(), int!(100)),
                    LO_CUSTKEY: int!(1) + euclidian_modulo(i.clone(), int!(100)),
                    LO_PARTKEY: int!(1) + euclidian_modulo(i.clone(), int!(100)),
                    LO_SUPPKEY: int!(1) + euclidian_modulo(i.clone(), int!(100)),
                    LO_ORDERDATE: int!(b"19930101") + euclidian_modulo(i.clone(), int!(365)),
                    LO_ORDERPRIORITY: if euclidian_modulo(i.clone(), int!(2)) == int!(0) {
                            string_of("1-URGENT")
                        } else {
                            string_of("2-HIGH")
                        },
                    LO_SHIPPRIORITY: int!(1) + euclidian_modulo(i.clone(), int!(100)),
                    LO_QUANTITY: euclidian_modulo(i.clone(), int!(50)),
                    LO_EXTENDEDPRICE: int!(1000) + euclidian_modulo(i.clone(), int!(1000)),
                    LO_ORDTOTALPRICE: int!(1000) + euclidian_modulo(i.clone(), int!(1000)),
                    LO_DISCOUNT: euclidian_modulo(i.clone(), int!(10)),
                    LO_REVENUE: int!(1000) + euclidian_modulo(i.clone(), int!(1000)),
                    LO_SUPPLYCOST: int!(1000) + euclidian_modulo(i.clone(), int!(1000)),
                    LO_TAX: int!(1) + euclidian_modulo(i.clone(), int!(100)),
                    LO_COMMITDATE: int!(1) + euclidian_modulo(i.clone(), int!(100)),
                    LO_SHIPMODE: string_of("dummy"),
                    C_NAME: string_of("dummy"),
                    C_ADDRESS: string_of("dummy"),
                    C_CITY: if euclidian_modulo(i.clone(), int!(2)) == int!(0) {
                            string_of("UNITED KI1")
                        } else {
                            string_of("UNITED KI2")
                        },
                    C_NATION: if euclidian_modulo(i.clone(), int!(5)) == int!(0) {
                            string_of("UNITED STATES")
                        } else {
                            string_of("UNITED KINGDOM")
                        },
                    C_REGION: if euclidian_modulo(i.clone(), int!(2)) == int!(0) {
                            string_of("AMERICA")
                        } else {
                            string_of("ASIA")
                        },
                    C_PHONE: string_of("dummy"),
                    C_MKTSEGMENT: string_of("dummy"),
                    S_NAME: string_of("dummy"),
                    S_ADDRESS: string_of("dummy"),
                    S_CITY: if euclidian_modulo(i.clone(), int!(2)) == int!(0) {
                            string_of("UNITED KI5")
                        } else {
                            string_of("UNITED KI6")
                        },
                    S_NATION: if euclidian_modulo(i.clone(), int!(5)) == int!(0) {
                            string_of("UNITED STATES")
                        } else {
                            string_of("UNITED KINGDOM")
                        },
                    S_REGION: if euclidian_modulo(i.clone(), int!(2)) == int!(0) {
                            string_of("AMERICA")
                        } else {
                            string_of("ASIA")
                        },
                    S_PHONE: string_of("dummy"),
                    P_NAME: string_of("dummy"),
                    P_MFGR: string_of("dummy"),
                    P_CATEGORY: if euclidian_modulo(i.clone(), int!(3)) == int!(0) {
                            string_of("MFGR#12")
                        } else {
                            string_of("MFGR#14")
                        },
                    P_BRAND: if euclidian_modulo(i.clone(), int!(4)) == int!(0) {
                            string_of("MFGR#2221")
                        } else {
                            string_of("MFGR#2222")
                        },
                    P_COLOR: string_of("dummy"),
                    P_TYPE: string_of("dummy"),
                    P_SIZE: int!(1) + euclidian_modulo(i.clone(), int!(100)),
                    P_CONTAINER: string_of("dummy"),
                    D_YEAR: int!(1992) + euclidian_modulo(i.clone(), int!(7)),
                    D_YEARMONTHNUM: int!(1) + euclidian_modulo(i.clone(), int!(100)),
                    D_WEEKNUMINYEAR: int!(1) + euclidian_modulo(i.clone(), int!(52))
                })
        }) as Rc<dyn ::std::ops::Fn(&_) -> _>
                        };
                    integer_range(Zero::zero(), int!(b"50000")).map(move |i| _initializer(&i)).collect::<Sequence<_>>()
                };
            let mut opt_res: DafnyInt;
            let mut _out0: DafnyInt = _default::RunQuery(&data);
            opt_res = _out0.clone();
            print!("{}", DafnyPrintWrapper(&string_of("SUCCESS\n")));
            return ();
        }
    }

    /// working_query.dfy(1,1)
    #[derive(Clone)]
    pub enum Row {
        Row {
            LO_ORDERKEY: DafnyInt,
            LO_LINENUMBER: DafnyInt,
            LO_CUSTKEY: DafnyInt,
            LO_PARTKEY: DafnyInt,
            LO_SUPPKEY: DafnyInt,
            LO_ORDERDATE: DafnyInt,
            LO_ORDERPRIORITY: Sequence<DafnyChar>,
            LO_SHIPPRIORITY: DafnyInt,
            LO_QUANTITY: DafnyInt,
            LO_EXTENDEDPRICE: DafnyInt,
            LO_ORDTOTALPRICE: DafnyInt,
            LO_DISCOUNT: DafnyInt,
            LO_REVENUE: DafnyInt,
            LO_SUPPLYCOST: DafnyInt,
            LO_TAX: DafnyInt,
            LO_COMMITDATE: DafnyInt,
            LO_SHIPMODE: Sequence<DafnyChar>,
            C_NAME: Sequence<DafnyChar>,
            C_ADDRESS: Sequence<DafnyChar>,
            C_CITY: Sequence<DafnyChar>,
            C_NATION: Sequence<DafnyChar>,
            C_REGION: Sequence<DafnyChar>,
            C_PHONE: Sequence<DafnyChar>,
            C_MKTSEGMENT: Sequence<DafnyChar>,
            S_NAME: Sequence<DafnyChar>,
            S_ADDRESS: Sequence<DafnyChar>,
            S_CITY: Sequence<DafnyChar>,
            S_NATION: Sequence<DafnyChar>,
            S_REGION: Sequence<DafnyChar>,
            S_PHONE: Sequence<DafnyChar>,
            P_NAME: Sequence<DafnyChar>,
            P_MFGR: Sequence<DafnyChar>,
            P_CATEGORY: Sequence<DafnyChar>,
            P_BRAND: Sequence<DafnyChar>,
            P_COLOR: Sequence<DafnyChar>,
            P_TYPE: Sequence<DafnyChar>,
            P_SIZE: DafnyInt,
            P_CONTAINER: Sequence<DafnyChar>,
            D_YEAR: DafnyInt,
            D_YEARMONTHNUM: DafnyInt,
            D_WEEKNUMINYEAR: DafnyInt
        }
    }

    impl Row {
        /// Returns a borrow of the field LO_ORDERKEY
        pub fn LO_ORDERKEY(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_ORDERKEY,
            }
        }
        /// Returns a borrow of the field LO_LINENUMBER
        pub fn LO_LINENUMBER(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_LINENUMBER,
            }
        }
        /// Returns a borrow of the field LO_CUSTKEY
        pub fn LO_CUSTKEY(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_CUSTKEY,
            }
        }
        /// Returns a borrow of the field LO_PARTKEY
        pub fn LO_PARTKEY(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_PARTKEY,
            }
        }
        /// Returns a borrow of the field LO_SUPPKEY
        pub fn LO_SUPPKEY(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_SUPPKEY,
            }
        }
        /// Returns a borrow of the field LO_ORDERDATE
        pub fn LO_ORDERDATE(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_ORDERDATE,
            }
        }
        /// Returns a borrow of the field LO_ORDERPRIORITY
        pub fn LO_ORDERPRIORITY(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_ORDERPRIORITY,
            }
        }
        /// Returns a borrow of the field LO_SHIPPRIORITY
        pub fn LO_SHIPPRIORITY(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_SHIPPRIORITY,
            }
        }
        /// Returns a borrow of the field LO_QUANTITY
        pub fn LO_QUANTITY(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_QUANTITY,
            }
        }
        /// Returns a borrow of the field LO_EXTENDEDPRICE
        pub fn LO_EXTENDEDPRICE(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_EXTENDEDPRICE,
            }
        }
        /// Returns a borrow of the field LO_ORDTOTALPRICE
        pub fn LO_ORDTOTALPRICE(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_ORDTOTALPRICE,
            }
        }
        /// Returns a borrow of the field LO_DISCOUNT
        pub fn LO_DISCOUNT(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_DISCOUNT,
            }
        }
        /// Returns a borrow of the field LO_REVENUE
        pub fn LO_REVENUE(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_REVENUE,
            }
        }
        /// Returns a borrow of the field LO_SUPPLYCOST
        pub fn LO_SUPPLYCOST(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_SUPPLYCOST,
            }
        }
        /// Returns a borrow of the field LO_TAX
        pub fn LO_TAX(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_TAX,
            }
        }
        /// Returns a borrow of the field LO_COMMITDATE
        pub fn LO_COMMITDATE(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_COMMITDATE,
            }
        }
        /// Returns a borrow of the field LO_SHIPMODE
        pub fn LO_SHIPMODE(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => LO_SHIPMODE,
            }
        }
        /// Returns a borrow of the field C_NAME
        pub fn C_NAME(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => C_NAME,
            }
        }
        /// Returns a borrow of the field C_ADDRESS
        pub fn C_ADDRESS(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => C_ADDRESS,
            }
        }
        /// Returns a borrow of the field C_CITY
        pub fn C_CITY(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => C_CITY,
            }
        }
        /// Returns a borrow of the field C_NATION
        pub fn C_NATION(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => C_NATION,
            }
        }
        /// Returns a borrow of the field C_REGION
        pub fn C_REGION(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => C_REGION,
            }
        }
        /// Returns a borrow of the field C_PHONE
        pub fn C_PHONE(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => C_PHONE,
            }
        }
        /// Returns a borrow of the field C_MKTSEGMENT
        pub fn C_MKTSEGMENT(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => C_MKTSEGMENT,
            }
        }
        /// Returns a borrow of the field S_NAME
        pub fn S_NAME(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => S_NAME,
            }
        }
        /// Returns a borrow of the field S_ADDRESS
        pub fn S_ADDRESS(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => S_ADDRESS,
            }
        }
        /// Returns a borrow of the field S_CITY
        pub fn S_CITY(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => S_CITY,
            }
        }
        /// Returns a borrow of the field S_NATION
        pub fn S_NATION(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => S_NATION,
            }
        }
        /// Returns a borrow of the field S_REGION
        pub fn S_REGION(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => S_REGION,
            }
        }
        /// Returns a borrow of the field S_PHONE
        pub fn S_PHONE(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => S_PHONE,
            }
        }
        /// Returns a borrow of the field P_NAME
        pub fn P_NAME(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => P_NAME,
            }
        }
        /// Returns a borrow of the field P_MFGR
        pub fn P_MFGR(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => P_MFGR,
            }
        }
        /// Returns a borrow of the field P_CATEGORY
        pub fn P_CATEGORY(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => P_CATEGORY,
            }
        }
        /// Returns a borrow of the field P_BRAND
        pub fn P_BRAND(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => P_BRAND,
            }
        }
        /// Returns a borrow of the field P_COLOR
        pub fn P_COLOR(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => P_COLOR,
            }
        }
        /// Returns a borrow of the field P_TYPE
        pub fn P_TYPE(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => P_TYPE,
            }
        }
        /// Returns a borrow of the field P_SIZE
        pub fn P_SIZE(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => P_SIZE,
            }
        }
        /// Returns a borrow of the field P_CONTAINER
        pub fn P_CONTAINER(&self) -> &Sequence<DafnyChar> {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => P_CONTAINER,
            }
        }
        /// Returns a borrow of the field D_YEAR
        pub fn D_YEAR(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => D_YEAR,
            }
        }
        /// Returns a borrow of the field D_YEARMONTHNUM
        pub fn D_YEARMONTHNUM(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => D_YEARMONTHNUM,
            }
        }
        /// Returns a borrow of the field D_WEEKNUMINYEAR
        pub fn D_WEEKNUMINYEAR(&self) -> &DafnyInt {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => D_WEEKNUMINYEAR,
            }
        }
    }

    impl Debug
        for Row {
        fn fmt(&self, f: &mut Formatter) -> Result {
            DafnyPrint::fmt_print(self, f, true)
        }
    }

    impl DafnyPrint
        for Row {
        fn fmt_print(&self, _formatter: &mut Formatter, _in_seq: bool) -> std::fmt::Result {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => {
                    write!(_formatter, "Row.Row(")?;
                    DafnyPrint::fmt_print(LO_ORDERKEY, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_LINENUMBER, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_CUSTKEY, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_PARTKEY, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_SUPPKEY, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_ORDERDATE, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_ORDERPRIORITY, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_SHIPPRIORITY, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_QUANTITY, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_EXTENDEDPRICE, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_ORDTOTALPRICE, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_DISCOUNT, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_REVENUE, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_SUPPLYCOST, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_TAX, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_COMMITDATE, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(LO_SHIPMODE, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(C_NAME, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(C_ADDRESS, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(C_CITY, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(C_NATION, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(C_REGION, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(C_PHONE, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(C_MKTSEGMENT, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(S_NAME, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(S_ADDRESS, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(S_CITY, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(S_NATION, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(S_REGION, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(S_PHONE, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(P_NAME, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(P_MFGR, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(P_CATEGORY, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(P_BRAND, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(P_COLOR, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(P_TYPE, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(P_SIZE, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(P_CONTAINER, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(D_YEAR, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(D_YEARMONTHNUM, _formatter, false)?;
                    write!(_formatter, ", ")?;
                    DafnyPrint::fmt_print(D_WEEKNUMINYEAR, _formatter, false)?;
                    write!(_formatter, ")")?;
                    Ok(())
                },
            }
        }
    }

    impl PartialEq
        for Row {
        fn eq(&self, other: &Self) -> bool {
            match (
                    self,
                    other
                ) {
                (Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, }, Row::Row{LO_ORDERKEY: _2_LO_ORDERKEY, LO_LINENUMBER: _2_LO_LINENUMBER, LO_CUSTKEY: _2_LO_CUSTKEY, LO_PARTKEY: _2_LO_PARTKEY, LO_SUPPKEY: _2_LO_SUPPKEY, LO_ORDERDATE: _2_LO_ORDERDATE, LO_ORDERPRIORITY: _2_LO_ORDERPRIORITY, LO_SHIPPRIORITY: _2_LO_SHIPPRIORITY, LO_QUANTITY: _2_LO_QUANTITY, LO_EXTENDEDPRICE: _2_LO_EXTENDEDPRICE, LO_ORDTOTALPRICE: _2_LO_ORDTOTALPRICE, LO_DISCOUNT: _2_LO_DISCOUNT, LO_REVENUE: _2_LO_REVENUE, LO_SUPPLYCOST: _2_LO_SUPPLYCOST, LO_TAX: _2_LO_TAX, LO_COMMITDATE: _2_LO_COMMITDATE, LO_SHIPMODE: _2_LO_SHIPMODE, C_NAME: _2_C_NAME, C_ADDRESS: _2_C_ADDRESS, C_CITY: _2_C_CITY, C_NATION: _2_C_NATION, C_REGION: _2_C_REGION, C_PHONE: _2_C_PHONE, C_MKTSEGMENT: _2_C_MKTSEGMENT, S_NAME: _2_S_NAME, S_ADDRESS: _2_S_ADDRESS, S_CITY: _2_S_CITY, S_NATION: _2_S_NATION, S_REGION: _2_S_REGION, S_PHONE: _2_S_PHONE, P_NAME: _2_P_NAME, P_MFGR: _2_P_MFGR, P_CATEGORY: _2_P_CATEGORY, P_BRAND: _2_P_BRAND, P_COLOR: _2_P_COLOR, P_TYPE: _2_P_TYPE, P_SIZE: _2_P_SIZE, P_CONTAINER: _2_P_CONTAINER, D_YEAR: _2_D_YEAR, D_YEARMONTHNUM: _2_D_YEARMONTHNUM, D_WEEKNUMINYEAR: _2_D_WEEKNUMINYEAR, }) => {
                    LO_ORDERKEY == _2_LO_ORDERKEY && LO_LINENUMBER == _2_LO_LINENUMBER && LO_CUSTKEY == _2_LO_CUSTKEY && LO_PARTKEY == _2_LO_PARTKEY && LO_SUPPKEY == _2_LO_SUPPKEY && LO_ORDERDATE == _2_LO_ORDERDATE && LO_ORDERPRIORITY == _2_LO_ORDERPRIORITY && LO_SHIPPRIORITY == _2_LO_SHIPPRIORITY && LO_QUANTITY == _2_LO_QUANTITY && LO_EXTENDEDPRICE == _2_LO_EXTENDEDPRICE && LO_ORDTOTALPRICE == _2_LO_ORDTOTALPRICE && LO_DISCOUNT == _2_LO_DISCOUNT && LO_REVENUE == _2_LO_REVENUE && LO_SUPPLYCOST == _2_LO_SUPPLYCOST && LO_TAX == _2_LO_TAX && LO_COMMITDATE == _2_LO_COMMITDATE && LO_SHIPMODE == _2_LO_SHIPMODE && C_NAME == _2_C_NAME && C_ADDRESS == _2_C_ADDRESS && C_CITY == _2_C_CITY && C_NATION == _2_C_NATION && C_REGION == _2_C_REGION && C_PHONE == _2_C_PHONE && C_MKTSEGMENT == _2_C_MKTSEGMENT && S_NAME == _2_S_NAME && S_ADDRESS == _2_S_ADDRESS && S_CITY == _2_S_CITY && S_NATION == _2_S_NATION && S_REGION == _2_S_REGION && S_PHONE == _2_S_PHONE && P_NAME == _2_P_NAME && P_MFGR == _2_P_MFGR && P_CATEGORY == _2_P_CATEGORY && P_BRAND == _2_P_BRAND && P_COLOR == _2_P_COLOR && P_TYPE == _2_P_TYPE && P_SIZE == _2_P_SIZE && P_CONTAINER == _2_P_CONTAINER && D_YEAR == _2_D_YEAR && D_YEARMONTHNUM == _2_D_YEARMONTHNUM && D_WEEKNUMINYEAR == _2_D_WEEKNUMINYEAR
                },
                _ => {
                    false
                },
            }
        }
    }

    impl Eq
        for Row {}

    impl Hash
        for Row {
        fn hash<_H: Hasher>(&self, _state: &mut _H) {
            match self {
                Row::Row{LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY, LO_ORDERDATE, LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY, LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE, LO_SUPPLYCOST, LO_TAX, LO_COMMITDATE, LO_SHIPMODE, C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT, S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE, P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER, D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR, } => {
                    Hash::hash(LO_ORDERKEY, _state);
                    Hash::hash(LO_LINENUMBER, _state);
                    Hash::hash(LO_CUSTKEY, _state);
                    Hash::hash(LO_PARTKEY, _state);
                    Hash::hash(LO_SUPPKEY, _state);
                    Hash::hash(LO_ORDERDATE, _state);
                    Hash::hash(LO_ORDERPRIORITY, _state);
                    Hash::hash(LO_SHIPPRIORITY, _state);
                    Hash::hash(LO_QUANTITY, _state);
                    Hash::hash(LO_EXTENDEDPRICE, _state);
                    Hash::hash(LO_ORDTOTALPRICE, _state);
                    Hash::hash(LO_DISCOUNT, _state);
                    Hash::hash(LO_REVENUE, _state);
                    Hash::hash(LO_SUPPLYCOST, _state);
                    Hash::hash(LO_TAX, _state);
                    Hash::hash(LO_COMMITDATE, _state);
                    Hash::hash(LO_SHIPMODE, _state);
                    Hash::hash(C_NAME, _state);
                    Hash::hash(C_ADDRESS, _state);
                    Hash::hash(C_CITY, _state);
                    Hash::hash(C_NATION, _state);
                    Hash::hash(C_REGION, _state);
                    Hash::hash(C_PHONE, _state);
                    Hash::hash(C_MKTSEGMENT, _state);
                    Hash::hash(S_NAME, _state);
                    Hash::hash(S_ADDRESS, _state);
                    Hash::hash(S_CITY, _state);
                    Hash::hash(S_NATION, _state);
                    Hash::hash(S_REGION, _state);
                    Hash::hash(S_PHONE, _state);
                    Hash::hash(P_NAME, _state);
                    Hash::hash(P_MFGR, _state);
                    Hash::hash(P_CATEGORY, _state);
                    Hash::hash(P_BRAND, _state);
                    Hash::hash(P_COLOR, _state);
                    Hash::hash(P_TYPE, _state);
                    Hash::hash(P_SIZE, _state);
                    Hash::hash(P_CONTAINER, _state);
                    Hash::hash(D_YEAR, _state);
                    Hash::hash(D_YEARMONTHNUM, _state);
                    Hash::hash(D_WEEKNUMINYEAR, _state)
                },
            }
        }
    }

    impl AsRef<Row>
        for Row {
        fn as_ref(&self) -> &Self {
            self
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