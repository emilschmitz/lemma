use dafny_runtime::{
    dafny_runtime_conversions::hashmap_to_dafny_map,
    dafny_runtime_conversions::unicode_chars_true::{dafny_string_to_string, string_to_dafny_string},
    allocate_object, DynAny, Map, Object, Rc, Sequence, DafnyChar, DafnyPrint, UpcastObject,
};
use std::collections::HashMap;
use std::fmt::{Debug, Formatter, Result as FmtResult};

#[derive(Clone, Default)]
pub struct NativeAggMap {
    /// Outer key: u32 group component; inner key: string group component.
    pub inner: HashMap<u32, HashMap<String, i64>>,
}

impl Debug for NativeAggMap {
    fn fmt(&self, f: &mut Formatter<'_>) -> FmtResult {
        let mut dm = f.debug_map();
        for (y, bucket) in &self.inner {
            for (s, v) in bucket {
                dm.entry(&format!("({y}, {s:?})"), v);
            }
        }
        dm.finish()
    }
}

impl DafnyPrint for NativeAggMap {
    fn fmt_print(&self, _formatter: &mut Formatter, _in_seq: bool) -> FmtResult {
        Ok(())
    }
}

impl UpcastObject<DynAny> for NativeAggMap {
    fn upcast(&self) -> Object<DynAny> {
        unsafe { Object::from_rc(Rc::new(self.clone()) as Rc<DynAny>) }
    }
}

impl NativeAggMap {
    pub fn _allocate_object() -> Object<NativeAggMap> {
        allocate_object::<NativeAggMap>()
    }

    pub fn Add(&mut self, k0: u32, k1: &Sequence<DafnyChar>, delta: i64) {
        self.AddStrKey(k0, &dafny_string_to_string(k1), delta);
    }

    /// Same semantics as Add; uses native &str (no Dafny Sequence round-trip).
    pub fn AddStrKey(&mut self, k0: u32, k1: &str, delta: i64) {
        let bucket = self.inner.entry(k0).or_default();
        match bucket.get_mut(k1) {
            Some(v) => *v += delta,
            None => {
                bucket.insert(k1.to_string(), delta);
            }
        }
    }

    pub fn ToMap(&self) -> Map<(u32, Sequence<DafnyChar>), i64> {
        self.snapshot_map()
    }

    pub fn ToU64Map(&self) -> Map<(u32, Sequence<DafnyChar>), u64> {
        let mut hm: HashMap<(u32, Sequence<DafnyChar>), u64> =
            HashMap::with_capacity(self.group_count());
        for (y, bucket) in &self.inner {
            for (s, v) in bucket {
                hm.insert((*y, string_to_dafny_string(s)), *v as u64);
            }
        }
        hashmap_to_dafny_map(&hm, |k| k.clone(), |v| *v)
    }

    pub fn Snapshot(&self) -> Map<(u32, Sequence<DafnyChar>), i64> {
        self.snapshot_map()
    }

    fn group_count(&self) -> usize {
        self.inner.values().map(|m| m.len()).sum()
    }

    fn snapshot_map(&self) -> Map<(u32, Sequence<DafnyChar>), i64> {
        let mut hm: HashMap<(u32, Sequence<DafnyChar>), i64> =
            HashMap::with_capacity(self.group_count());
        for (y, bucket) in &self.inner {
            for (s, v) in bucket {
                hm.insert((*y, string_to_dafny_string(s)), *v);
            }
        }
        hashmap_to_dafny_map(&hm, |k| k.clone(), |v| *v)
    }
}
