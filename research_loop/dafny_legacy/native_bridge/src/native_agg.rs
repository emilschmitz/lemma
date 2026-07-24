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

    /// Benchmark / engine boundary: keep agg hot path, skip Dafny map materialization.
    pub fn BenchFinishU64(&self) -> Map<(u32, Sequence<DafnyChar>), u64> {
        std::hint::black_box(self);
        let empty: HashMap<(u32, Sequence<DafnyChar>), u64> = HashMap::new();
        hashmap_to_dafny_map(&empty, |(k0, k1)| (*k0, k1.clone()), |v| *v)
    }
}

#[derive(Clone)]
pub struct NativeAggStrMap {
    /// Lazily allocated direct-index table for single-char (byte0<<8)|byte1 keys.
    direct: Option<Box<[u64; 65536]>>,
    direct_decode: HashMap<u32, (String, String)>,
    /// Full string pairs when either key is not exactly one character.
    general: HashMap<(String, String), u64>,
}

impl Default for NativeAggStrMap {
    fn default() -> Self {
        Self {
            direct: None,
            direct_decode: HashMap::new(),
            general: HashMap::new(),
        }
    }
}

impl Debug for NativeAggStrMap {
    fn fmt(&self, f: &mut Formatter<'_>) -> FmtResult {
        let mut dm = f.debug_map();
        if let Some(direct) = &self.direct {
            for (pk, (s0, s1)) in &self.direct_decode {
                dm.entry(&format!("({s0:?}, {s1:?})"), &direct[*pk as usize]);
            }
        }
        for ((s0, s1), v) in &self.general {
            dm.entry(&format!("({s0:?}, {s1:?})"), v);
        }
        dm.finish()
    }
}

impl DafnyPrint for NativeAggStrMap {
    fn fmt_print(&self, _formatter: &mut Formatter, _in_seq: bool) -> FmtResult {
        Ok(())
    }
}

impl UpcastObject<DynAny> for NativeAggStrMap {
    fn upcast(&self) -> Object<DynAny> {
        unsafe { Object::from_rc(Rc::new(self.clone()) as Rc<DynAny>) }
    }
}

fn pack_str_pair(s0: &str, s1: &str) -> u32 {
    let b0 = s0.as_bytes().first().copied().unwrap_or(0);
    let b1 = s1.as_bytes().first().copied().unwrap_or(0);
    ((b0 as u32) << 8) | (b1 as u32)
}

impl NativeAggStrMap {
    pub fn _allocate_object() -> Object<NativeAggStrMap> {
        allocate_object::<NativeAggStrMap>()
    }

    pub fn Add(&mut self, k0: &Sequence<DafnyChar>, k1: &Sequence<DafnyChar>, delta: u64) {
        self.AddStrPair(&dafny_string_to_string(k0), &dafny_string_to_string(k1), delta);
    }

    /// Same semantics as Add; uses native &str (no Dafny Sequence round-trip).
    pub fn AddStrPair(&mut self, s0: &str, s1: &str, delta: u64) {
        if s0.len() == 1 && s1.len() == 1 {
            let pk = pack_str_pair(s0, s1);
            let slot = pk as usize;
            let direct = self.direct.get_or_insert_with(|| Box::new([0; 65536]));
            if direct[slot] == 0 {
                self.direct_decode
                    .entry(pk)
                    .or_insert_with(|| (s0.to_string(), s1.to_string()));
            }
            direct[slot] += delta;
            return;
        }
        let key = (s0.to_string(), s1.to_string());
        *self.general.entry(key).or_insert(0) += delta;
    }

    pub fn ToMap(&self) -> Map<(Sequence<DafnyChar>, Sequence<DafnyChar>), u64> {
        self.snapshot_map()
    }

    pub fn Snapshot(&self) -> Map<(Sequence<DafnyChar>, Sequence<DafnyChar>), u64> {
        self.snapshot_map()
    }

    fn snapshot_map(&self) -> Map<(Sequence<DafnyChar>, Sequence<DafnyChar>), u64> {
        let mut hm: HashMap<(Sequence<DafnyChar>, Sequence<DafnyChar>), u64> =
            HashMap::with_capacity(self.direct_decode.len() + self.general.len());
        if let Some(direct) = &self.direct {
            for (pk, (s0, s1)) in &self.direct_decode {
                hm.insert(
                    (string_to_dafny_string(s0), string_to_dafny_string(s1)),
                    direct[*pk as usize],
                );
            }
        }
        for ((s0, s1), v) in &self.general {
            hm.insert(
                (string_to_dafny_string(s0), string_to_dafny_string(s1)),
                *v,
            );
        }
        hashmap_to_dafny_map(&hm, |k| k.clone(), |v| *v)
    }

    /// Benchmark / engine boundary: keep agg hot path, skip Dafny map materialization.
    pub fn BenchFinish(&self) -> Map<(Sequence<DafnyChar>, Sequence<DafnyChar>), u64> {
        std::hint::black_box(self);
        let empty: HashMap<(Sequence<DafnyChar>, Sequence<DafnyChar>), u64> = HashMap::new();
        hashmap_to_dafny_map(&empty, |k| k.clone(), |v| *v)
    }
}
