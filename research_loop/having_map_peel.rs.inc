// === HAVING map peel structs (private layout; transmute only inside apply_having_filter_exec_*) ===
// vstd HashMapWithView / StringHashMap are single-field newtypes over std::collections::HashMap.
#[repr(C)]
struct HashMapWithViewPeel<K, V> {
    m: std::collections::HashMap<K, V>,
}

#[repr(C)]
struct StringHashMapPeel<V> {
    m: std::collections::HashMap<String, V>,
}
