// === HAVING map peel: vstd HashMapWithView / StringHashMap are single-field newtypes ===
// over std::collections::HashMap (same layout fact vstd uses). Transmute stays inside
// these helpers only. Semantic HAVING ensures live on apply_having_filter_exec_* (res@).
#[repr(C)]
struct HashMapWithViewPeel<K, V> {
    m: std::collections::HashMap<K, V>,
}

#[repr(C)]
struct StringHashMapPeel<V> {
    m: std::collections::HashMap<String, V>,
}

#[verifier::external_body]
pub exec fn hashmap_with_view_unwrap<K, V>(
    hm: HashMapWithView<K, V>,
) -> (m: std::collections::HashMap<K, V>)
    where
        K: vstd::view::View + std::cmp::Eq + std::hash::Hash,
{
    let peeled: HashMapWithViewPeel<K, V> = unsafe { std::mem::transmute(hm) };
    peeled.m
}

#[verifier::external_body]
pub exec fn hashmap_with_view_wrap<K, V>(
    m: std::collections::HashMap<K, V>,
) -> (hm: HashMapWithView<K, V>)
    where
        K: vstd::view::View + std::cmp::Eq + std::hash::Hash,
{
    let peeled = HashMapWithViewPeel { m };
    unsafe { std::mem::transmute(peeled) }
}

#[verifier::external_body]
pub exec fn string_hashmap_unwrap<V>(
    hm: StringHashMap<V>,
) -> (m: std::collections::HashMap<String, V>)
{
    let peeled: StringHashMapPeel<V> = unsafe { std::mem::transmute(hm) };
    peeled.m
}

#[verifier::external_body]
pub exec fn string_hashmap_wrap<V>(
    m: std::collections::HashMap<String, V>,
) -> (hm: StringHashMap<V>)
{
    let peeled = StringHashMapPeel { m };
    unsafe { std::mem::transmute(peeled) }
}
