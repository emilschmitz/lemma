// =============================================================================
// Postprocessor for Dafny→Rust output of the research_loop harness.
//
// WHY THIS EXISTS
//   The Dafny→Rust compiler emits idiomatic Rust that uses Dafny's runtime
//   types (`DafnyInt` = heap-allocated BigInt, `dafny_runtime::Map` =
//   persistent tree map, `Sequence<Rc<Row>>` with `&DafnyInt` keys).  These
//   are correct but ~10× slower than native Rust on OLAP-style queries.  This
//   pass rewrites the emitted Rust so the same Dafny source compiles to
//   `u64`/`usize`/`HashMap`/native slices, with no source changes.
//
// WHAT IT DOES (one bullet per pass)
//   1. STRIP METHODSPEC: MethodSpec is the formal spec — we only want to
//      run RunQuery.  Either we strip it here, or Dafny emits
//      `{:verify false}` for it (preferred).  The strip is kept as a safety
//      net.
//
//   2. TYPE REWRITES:
//        DafnyInt       → u64           (BigInt → native int)
//        Map<…>         → HashMap<…>    (persistent tree → amortized O(1))
//        dafny_runtime::Sequence::cardinality() → …as_usize()
//
//   3. EXPRESSION REWRITES inside RunQuery:
//        x = x.update_index(&k, &v)        → x.insert(k.clone(), v.clone())
//        map![]                            → HashMap::new()
//        m.contains(&k)                    → m.contains_key(&k)
//        int!(N) literal                    → bare N
//        int!(expr)                        → (expr as u64)
//        data.get(&i) where i:usize        → data.get_usize(i)
//
//   4. BLOCK REWRITES inside RunQuery:
//        let mut row: Rc<Row> = data_vec[i].clone()
//          → let row = &data_vec[i];                  (avoids Rc clone)
//        let mut data: Sequence<Rc<Row>> = []
//          → let mut data = dataset::load_dataset(…)  (injects the loader)
//        any `i` or `len` local without a type
//          → : usize  (so data_vec[i] compiles)
//
//   5. TIMING WRAPPER: the RunQuery call in Main is wrapped in
//        let start = Instant::now();
//        let _out = black_box(RunQuery(…));
//        println!("QUERY_LATENCY_US: {}", start.elapsed().as_micros());
//      so the harness can read latency from stdout instead of relying on
//      wall-clock around the subprocess.
//
//   6. EMIT `impl Loadable for Row`: the loader is a static function
//      `dataset::load_dataset<T: Loadable>` that takes a column-name map and
//      a row of fields and constructs T.  This block is the per-schema glue.
//
// WHAT IT DOES NOT DO (and we do not intend to add)
//   - We do not touch the `MethodSpec` body.  The verified mathematical
//     spec is exactly what we trust.
//   - We do not optimize map lookups, predicates, or arithmetic — those are
//     Dafny's job.
//   - We do not strip dead field accessors / Debug / PartialEq / Hash
//     impls — they come from Dafny and removing them risks breaking the
//     `Sequence<Rc<Row>>` plumbing.
// =============================================================================

use std::collections::HashMap;
use std::env;
use std::fs;
use syn::visit::Visit;
use syn::visit_mut::VisitMut;
use syn::{parse_quote, Block, Expr, ItemEnum, Pat, Stmt, Type};
use quote::quote;

// -----------------------------------------------------------------------------
// Section 1: schema extraction (read-only walk)
// -----------------------------------------------------------------------------
// Walk the parsed `syn::File` once, before any mutation, and build a map
// from each Row field name to its Dafny-emitted Rust type ("u32", "u64",
// or "String").  Used by section 6 to emit the `Loadable` impl.

struct SchemaExtractor {
    row_types: HashMap<String, String>,
}

impl<'ast> Visit<'ast> for SchemaExtractor {
    fn visit_item_enum(&mut self, i: &'ast ItemEnum) {
        if i.ident == "Row" {
            for variant in &i.variants {
                if variant.ident == "Row" {
                    if let syn::Fields::Named(fields_named) = &variant.fields {
                        for field in &fields_named.named {
                            if let Some(ident) = &field.ident {
                                let ty_str = quote!(#field).to_string();
                                let clean_ty = if ty_str.contains("Sequence") {
                                    "String"
                                } else if ty_str.contains("u64") {
                                    "u64"
                                } else {
                                    "u32"
                                };
                                self.row_types.insert(ident.to_string(), clean_ty.into());
                            }
                        }
                    }
                }
            }
        }
        syn::visit::visit_item_enum(self, i);
    }
}

// -----------------------------------------------------------------------------
// Section 2: early-exit if the file has no RunQuery
// -----------------------------------------------------------------------------

fn file_has_run_query(content: &str) -> bool {
    content.contains("fn RunQuery")
}

// -----------------------------------------------------------------------------
// Section 3: the actual rewrites
// -----------------------------------------------------------------------------
// One struct, one visitor impl, organized top-to-bottom in the same order
// as the file's section list above.  Any future rewrite belongs in one of
// the clearly-marked `// ==` blocks below.

struct PostProcessor {
    /// Name of the loop-row variable, learned at runtime by spotting the
    /// `let mut row: Rc<Row> = data_vec[i].clone()` initializer.  Used to
    /// rewrite the assignment to `let row = &data_vec[i];`.
    row_var: String,
    /// Path to the .tbl file (or anything else dataset.rs knows how to
    /// read) that the harness wants Main to load.
    tbl_path_str: String,
}

impl VisitMut for PostProcessor {
    // == type rewrites =====================================================
    fn visit_type_mut(&mut self, ty: &mut Type) {
        let ty_str = quote!(#ty).to_string().replace(' ', "");
        if ty_str == "DafnyInt" {
            *ty = parse_quote!(u64);
        } else if ty_str.starts_with("Map<") {
            if let Type::Path(type_path) = ty {
                if let Some(segment) = type_path.path.segments.last_mut() {
                    segment.ident = syn::Ident::new("HashMap", proc_macro2::Span::call_site());
                    *ty = parse_quote!(::std::collections::#segment);
                }
            }
        }
        syn::visit_mut::visit_type_mut(self, ty);
    }

    // == expression rewrites ==============================================
    fn visit_expr_mut(&mut self, expr: &mut Expr) {
        // x = x.update_index(&k, &v)  →  x.insert(k.clone(), v.clone())
        if let Expr::Assign(assign) = expr {
            if let Expr::MethodCall(call) = &*assign.right {
                if call.method == "update_index" && call.args.len() == 2 {
                    let receiver = &call.receiver;
                    let left = quote!(#assign.left).to_string().replace(' ', "");
                    let rec = quote!(#receiver).to_string().replace(' ', "");
                    if left == rec {
                        let mut k = arg_expr(&call.args[0]);
                        let mut v = arg_expr(&call.args[1]);
                        self.visit_expr_mut(&mut k);
                        self.visit_expr_mut(&mut v);
                        *expr = parse_quote!(#receiver.insert(#k.clone(), #v.clone()));
                        return;
                    }
                }
            }
        }

        // map![]  →  HashMap::new()
        if let Expr::Macro(m) = expr {
            if m.mac.path.is_ident("map") && m.mac.tokens.is_empty() {
                *expr = parse_quote!(::std::collections::HashMap::new());
                return;
            }
        }

        // m.contains(&k)  →  m.contains_key(&k)
        if let Expr::MethodCall(call) = expr {
            if call.method == "contains" && call.args.len() == 1 {
                call.method = syn::Ident::new("contains_key", proc_macro2::Span::call_site());
            }
        }

        // int!(N)  →  bare N
        // int!(expr)  →  (expr as u64)
        if let Expr::Macro(m) = expr {
            if m.mac.path.is_ident("int") {
                let toks1 = m.mac.tokens.clone();
                if let Ok(lit) = syn::parse2::<syn::LitInt>(toks1) {
                    *expr = Expr::Lit(syn::ExprLit {
                        attrs: vec![],
                        lit: syn::Lit::Int(syn::LitInt::new(lit.base10_digits(), proc_macro2::Span::call_site())),
                    });
                } else {
                    let toks2 = m.mac.tokens.clone();
                    if let Ok(mut inner) = syn::parse2::<Expr>(toks2) {
                        self.visit_expr_mut(&mut inner);
                        *expr = parse_quote!((#inner as u64));
                    }
                }
                return;
            }
        }

        // data.get(&i) where i is a plain ident  →  data.get_usize(i)
        if let Expr::MethodCall(call) = expr {
            if call.method == "get" && call.args.len() == 1 {
                if let Expr::Reference(r) = &call.args[0] {
                    if let Expr::Path(p) = &*r.expr {
                        if p.path.is_ident("i") {
                            call.method = syn::Ident::new("get_usize", proc_macro2::Span::call_site());
                            call.args[0] = *r.expr.clone();
                        }
                    }
                }
            }
        }

        // .cardinality()  →  .cardinality().as_usize()
        if let Expr::MethodCall(call) = expr {
            if call.method == "cardinality" {
                let mut recv = call.receiver.clone();
                self.visit_expr_mut(&mut recv);
                *expr = parse_quote!(#recv.cardinality().as_usize());
                return;
            }
        }

        syn::visit_mut::visit_expr_mut(self, expr);
    }

    // == block rewrites ====================================================
    fn visit_block_mut(&mut self, block: &mut Block) {
        let mut new_stmts = Vec::new();
        for mut stmt in block.stmts.drain(..) {
            // 3a. learn the loop-row name, and rewrite
            //     `let mut row: Rc<Row> = data_vec[i].clone()`
            //   → `let row = &data_vec[i];`
            if let Some((row_ident, vec_ident)) = detect_row_init(&stmt) {
                self.row_var = row_ident.to_string();
                stmt = parse_quote!(let mut #row_ident = &#vec_ident[i];);
            }

            // 3b. inject the data loader
            //     `let mut data: Sequence<Rc<Row>> = []`
            //   → `let mut data = dataset::load_dataset(…)`
            if is_mock_data_decl(&stmt) {
                let p = &self.tbl_path_str;
                stmt = parse_quote! {
                    let mut data: Sequence<Rc<Row>> = crate::dataset::load_dataset::<Row>(#p, 50000);
                };
            }

            // 3c. force `i` and `len` to `usize` so `data_vec[i]` compiles
            force_index_to_usize(&mut stmt);

            // 3d. wrap RunQuery call in Instant timing
            if let Stmt::Local(local) = &stmt {
                if let Some(init) = &local.init {
                    if is_run_query_call(&init.expr) {
                        let pat = &local.pat;
                        let q = &init.expr;
                        let block: Block = parse_quote! {{
                            let start = ::std::time::Instant::now();
                            let #pat = ::std::hint::black_box(#q);
                            let elapsed_us = start.elapsed().as_micros();
                            println!("QUERY_LATENCY_US: {}", elapsed_us);
                        }};
                        // The freshly-built timing block contains the original
                        // `let mut _out: DafnyInt = …`; we need to walk it so
                        // the type rewrite (DafnyInt → u64) reaches the local's
                        // type annotation.
                        for mut s in block.stmts {
                            self.visit_stmt_mut(&mut s);
                            new_stmts.push(s);
                        }
                        continue;
                    }
                }
            }

            // 3e. recurse into the statement's children
            self.visit_stmt_mut(&mut stmt);
            new_stmts.push(stmt);
        }
        block.stmts = new_stmts;
    }

    // Override `visit_local_mut` so type annotations on `let` bindings get
    // the DafnyInt→u64 / Map→HashMap rewrite too.
    fn visit_local_mut(&mut self, local: &mut syn::Local) {
        // The default `visit_local_mut` doesn't visit the local's type
        // annotation; we have to do it explicitly.  syn represents the
        // optional type as a `Box<Type>` directly on the `Local` node.
        syn::visit_mut::visit_local_mut(self, local);
    }

    // == strip MethodSpec (safety net; transpiler also emits {:verify false})
    fn visit_item_impl_mut(&mut self, i: &mut syn::ItemImpl) {
        i.items.retain(|item| {
            !matches!(item, syn::ImplItem::Fn(f) if f.sig.ident == "MethodSpec")
        });
        syn::visit_mut::visit_item_impl_mut(self, i);
    }
}

// -----------------------------------------------------------------------------
// Section 4: small helpers used by the visitor
// -----------------------------------------------------------------------------

/// If `arg` is `&expr`, return a clone of `expr`; otherwise return a clone
/// of `arg` itself.  The Dafny compiler emits `&k` and `&v` for the
/// `update_index` arguments; we want the inner expression.
fn arg_expr(arg: &Expr) -> Expr {
    if let Expr::Reference(r) = arg {
        (*r.expr).clone()
    } else {
        arg.clone()
    }
}

/// Returns `Some((row_ident, vec_ident))` if `stmt` is the canonical
/// `let mut row: Rc<Row> = data_vec[i].clone()` initializer that the
/// Dafny compiler emits for `var row := data[i]` inside a loop.  Returns
/// `None` otherwise.
fn detect_row_init(stmt: &Stmt) -> Option<(syn::Ident, syn::Ident)> {
    let Stmt::Local(local) = stmt else { return None };
    let local_str = quote!(#local).to_string().replace(' ', "");
    if !(local_str.contains("Rc<Row>=") && local_str.contains("_vec[i].clone()")) {
        return None;
    }
    let row_ident = match &local.pat {
        Pat::Ident(pi) => pi.ident.clone(),
        Pat::Type(pt) => match &*pt.pat {
            Pat::Ident(pi) => pi.ident.clone(),
            _ => return None,
        },
        _ => return None,
    };
    let init = local.init.as_ref()?;
    let init_expr = &init.expr;
    let init_str = quote!(#init_expr).to_string();
    let pos = init_str.find("_vec")?;
    let prefix = init_str[..pos].trim();
    // The variable holding the sequence ends in `_vec` (Dafny's convention).
    // Strip the trailing `_vec` to get the bare ident.
    let base = prefix.rsplit(' ').next()?;
    let vec_ident = syn::Ident::new(&format!("{}_vec", base), proc_macro2::Span::call_site());
    Some((row_ident, vec_ident))
}

/// Returns `true` for `let mut data: ...` / `let data: ...` / `= []`
/// style declarations that the harness's Main uses to mock an empty input.
fn is_mock_data_decl(stmt: &Stmt) -> bool {
    let Stmt::Local(local) = stmt else { return false };
    let s = quote!(#local).to_string().replace(' ', "");
    s.starts_with("letmutdata") || s.starts_with("letdata")
}

/// If `stmt` is `let i: DafnyInt = …` or `let i = …` (no type annotation),
/// wrap the pattern in `Pat::Type(usize)` so the binding becomes
/// `let i: usize = …` (or `let mut i: usize = …` if originally mutable).
/// Dafny's compiler leaves these as `DafnyInt` which can't index `Vec<T>`.
fn force_index_to_usize(stmt: &mut Stmt) {
    let Stmt::Local(local) = stmt else { return };
    // Extract the identifier AND its mutability from whatever the original
    // pattern shape is (`i`, `mut i`, `i: T`, `mut i: T`).
    let (ident, mutability) = match &local.pat {
        Pat::Ident(pi) => (pi.ident.clone(), pi.mutability),
        Pat::Type(pt) => match &*pt.pat {
            Pat::Ident(pi) => (pi.ident.clone(), pi.mutability),
            _ => return,
        },
        _ => return,
    };
    if ident != "i" && ident != "len" {
        return;
    }
    let pi = syn::PatIdent {
        attrs: vec![],
        by_ref: None,
        mutability,
        ident: ident.clone(),
        subpat: None,
    };
    local.pat = Pat::Type(syn::PatType {
        attrs: vec![],
        pat: Box::new(Pat::Ident(pi)),
        colon_token: syn::token::Colon::default(),
        ty: Box::new(parse_quote!(usize)),
    });
}

/// Returns `true` if the expression is a call to `RunQuery`.  Used to
/// detect the harness's `let opt_res := RunQuery(data);` line in Main.
fn is_run_query_call(expr: &Expr) -> bool {
    if let Expr::Call(c) = expr {
        if let Expr::Path(p) = &*c.func {
            return p.path.segments.last().map(|s| s.ident == "RunQuery").unwrap_or(false);
        }
    }
    false
}

// -----------------------------------------------------------------------------
// Section 5: emit the `impl Loadable for Row` glue
// -----------------------------------------------------------------------------
// The static `dataset::load_dataset<T: Loadable>(…)` in the project reads
// the .tbl file and hands us a slice of column fields.  Per schema, we
// need an `impl Loadable for Row` that knows how to build a `Row` from
// those fields.  This block generates that impl from the extracted
// `SchemaExtractor` output.

fn build_loadable_impl(row_types: &HashMap<String, String>) -> String {
    let mut body = String::new();
    for (field, t) in row_types {
        let col = field.to_uppercase();
        let access = format!("f[ci[\"{}\"]]", col);
        if t == "String" {
            body += &format!("            {}: string_of({}),\n", field, access);
        } else {
            body += &format!("            {}: {}.parse::<{}>().unwrap(),\n", field, access, t);
        }
    }
    format!(
        r#"
    impl crate::dataset::Loadable for crate::_module::Row {{
        fn from_fields(f: &[&str], ci: &std::collections::HashMap<String, usize>) -> Self {{
            crate::_module::Row::Row {{
{body}            }}
        }}
    }}
"#,
    )
}

// -----------------------------------------------------------------------------
// Section 6: main
// -----------------------------------------------------------------------------

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: postprocessor <working_query.rs> [tbl_path]");
        std::process::exit(1);
    }
    let file_path = args[1].clone();
    let tbl_path = if args.len() >= 3 {
        args[2].clone()
    } else {
        "ssb-dbgen/lineorder_flat.tbl".to_string()
    };

    let content = fs::read_to_string(&file_path).expect("read input");
    if !file_has_run_query(&content) {
        return; // nothing to do
    }

    // 1. extract schema
    let mut syntax = syn::parse_file(&content).expect("parse rust");
    let mut extractor = SchemaExtractor { row_types: HashMap::new() };
    extractor.visit_file(&syntax);

    // 2. apply rewrites
    let mut proc = PostProcessor { row_var: "row".into(), tbl_path_str: tbl_path };
    proc.visit_file_mut(&mut syntax);

    // 3. emit glue
    let mut out = quote!(#syntax).to_string();
    // `mod dataset;` has to go *after* the inner attributes (`#![allow(...)]`)
    // and right before `pub mod _module`.  Inner attributes must be at the
    // very top of a file/module — placing `mod` ahead of them is a syntax
    // error.
    if let Some(pos) = out.find("pub mod _module") {
        out.insert_str(pos, "mod dataset; ");
    } else {
        out = format!("mod dataset;\n{}", out);
    }
    if let Some(pos) = out.find("pub enum Row") {
        if let Some(end) = out[pos..].find("} }") {
            out.insert_str(pos + end + 3, &build_loadable_impl(&extractor.row_types));
        }
    }

    fs::write(&file_path, out).expect("write output");
}
