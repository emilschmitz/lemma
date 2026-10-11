# Verus guide index (generated)

One line per guide page: title and section headings. `grep -n 'decreases' GUIDE_INDEX.md`, then Read the page.

guide/SUMMARY.md: Summary | Getting started | Tutorial: Fundamentals | Tutorial: Proof Development | Tutorial: Verification and Rust | Installation, configuration, and tooling | Reference
guide/assert-mut-ref.md: Assertions about mutable references
guide/assert_assume.md: Using assert and assume to develop proofs
guide/assert_by.md: Hiding local proofs with `assert(...) by { ... }` | Motivation | Enter `assert(...) by { ... }` | Underlying mechanism | Difference from auxiliary lemmas
guide/assert_by_compute.md: Proofs by Computation | Motivation | Enter Proof by Computation | Current Limitations | See Also
guide/binary_search.md: Example: binary search | Proving that the loop invariant is maintained | Helping the automation succeed
guide/bitvec.md: Bit vectors and bitwise operations | Invoking the `bit_vector` prover mode. | How the `bit_vector` solver works and what it's good at | Examples and tips
guide/break.md: Loops with break
guide/breaking_proofs_into_pieces.md: Breaking proofs into smaller pieces | Motivation | Moving a subproof to a lemma | Dividing a proof into parts 1, 2, ..., n
guide/broadcast_proof.md: Adding Ambient Facts to the Proof Environment with `broadcast` | Experimental broadcast lemma usage information
guide/calc.md: Structured Proofs by Calculation | Motivation | `calc!`ulations, to Reduce Redundant Redundancy | Using Different Relations for Intermediate Steps
guide/call-from-unverified-code.md: Calling verified code from unverified code | Requirements on the Drop trait | Warning
guide/calling-unverified-from-verified.md: Calling unverified code from verified code | Specifications without proof | Applying specifications to _existing_ library functions | Making Verus aware of types | Adding specifications for external traits
guide/calling-verified-from-unverified.md: Calling verified code from unverified code
guide/cargo_verus.md: Using Verus via Cargo | Prerequisites | Starting a new project | Binary project | Library project | Updating an existing Rust project to support Verus | The Verus prelude | Cargo.toml configuration | Subcommands | Verify all of the root crates, but not their dependencies | Verify my_crate, but not i
guide/checklist.md: Checklist: What to do when proofs go wrong
guide/complex_ownership.md: Unsafe code & complex ownership
guide/concurrency.md: Concurrency
guide/const.md: const declarations | `spec` consts | `proof` and `exec` consts | `spec/exec` consts | Using an `exec const` in a `spec` or `proof` context | Trouble-shooting overflow errors
guide/container_bst.md: Verifying a container library
guide/container_bst_all_source.md: Full source for the examples | First draft | Version with type invariants | Version with generic key type and Clone implementation
guide/container_bst_clone.md: Implementing Clone | Full source
guide/container_bst_first_draft.md: A simple binary search tree | The implementation | Full source
guide/container_bst_generic.md: Making it generic | Defining a "total order" | Full source
guide/container_bst_mut_refs.md: Mutable references in a container | A detour through `Vec` | A resolution lemma for `TreeMap`
guide/container_bst_type_invariant.md: Encapsulating well-formedness with type invariants | Full source
guide/contributed.md: Contributed Extensions
guide/datatypes.md: Datatypes: Structs and Enums
guide/datatypes_enum.md: Enum | Identifying a variant with the `is` operator | Accessing fields with the arrow operator | matches with &&, ==>, and &&&
guide/datatypes_struct.md: Struct
guide/develop_proofs.md: Developing Proofs
guide/equality.md: Equality
guide/erasure.md: Ghost Erasure | `Cargo.toml` configuration
guide/exec_attr.md: Verus attributes for executable code | When to use `#[verus_spec]` instead of the `verus!` macro | Adding specifications to a function | Adding verification hints | Adding proofs inside function | More examples and tests
guide/exec_closures.md: Closures | Preconditions and postconditions on a closure | Closure capturing
guide/exec_funs_as_values.md: Passing functions as values
guide/exec_lib.md: Executable libraries: Vec
guide/exec_spec.md: Producing executable code from spec functions with the `exec_spec_verified!` and `exec_spec_unverified!` macros | Unverified translations of `vstd` functions within the `exec_spec_verified!` and `exec_spec_unverified!` macros | The `exec_spec_verified!` macro | The `exec_spec_unverified!` macro | Co
guide/exec_termination.md: Lightweight termination checking
guide/exec_to_spec.md: Automatically producing a spec function for executable code | Limitations | Related
guide/exists.md: exists and choose | choose
guide/extensional_equality.md: Equality via extensionality | Extensional equality for structs and enums | Deep extensional equality
guide/external_trait_specifications.md: External trait specifications | Soundness warning | Basic external trait specification | External trait extension (spec helper functions) | The `obeys_*` pattern in `vstd` | Rules and restrictions
guide/features.md: Supported Rust Features
guide/for.md: For Loops
guide/forall.md: forall and triggers | Valid triggers and invalid triggers | Good triggers and  bad triggers
guide/getting_started.md: Getting Started
guide/getting_started_cmd_line.md: Getting started on the command line | 1. Install Verus. | 2. Verify a sample program. | 3. Compile the program | 4. Learn more about Verus
guide/getting_started_vscode.md: Getting started with VSCode | 1. Create a Rust crate | 2. Install verus-analyzer via VSCode | 3. Open your workspace in VSCode. | 4. Disable rust-analyzer | 5. Test that Verus is working. | 6. Learn more about the verus-analyzer extension. | 7. Learn more about Verus
guide/ghost_vs_exec.md: Ghost code vs. exec code | Producing exec code from spec code (and vice versa)
guide/guarantees.md: Understanding the guarantees of a verified program
guide/higher-order-fns.md: Higher-order executable functions
guide/ide_support.md: IDE Support for Verus | Quickstart Emacs
guide/induction.md: Recursive exec and proof functions, proofs by induction | Towards an imperative implementation: mutation and tail recursion | Proofs by induction
guide/install-singular.md: Installing and configuring Singular
guide/integers.md: Integer types | Using integer types in specifications | Integer constants | Integer coercions using "as" | Integer arithmetic
guide/interacting-with-unverified-code.md: Interacting with unverified code
guide/interior_mutability.md: Interior Mutability
guide/invariants.md: Devising Loop Invariants | Example 1: Fibonacci | Example 2: Account Balance
guide/iterator-specs.md: Iterator Specifications for a Custom Type
guide/iterators.md: Iterators | Ghost State in For Loops
guide/lex_mutual.md: Lexicographic decreases clauses | Mutual recursion
guide/llmforverusproof.md: Using LLMs to Help Write Verus Proofs | Quick Start: Recommended Setup | Use a Coding Agent | Provide Verus Resources | Provide a Verus Binary | Use a Cheat Checker | Understand Model Capabilities and Costs | LLM Proofs May Be Verbose | LLMs as Collaborators | Summary
guide/llms.md: Using LLMs to Help Develop Verus Projects
guide/logatom-call.md: Calling a logically atomic function | Handling the abort case | Invariant masks | Running examples
guide/logatom-open.md: Invoking the linearization point | The resolves check | Invariant masks | Running examples
guide/logatom-spec.md: Atomic specifications | The abort case | The predicate type | Running examples
guide/logatom.md: Logical atomicity | Running examples | Main concepts | Previous & related work
guide/memory-safety.md: Memory safety is conditional on verification
guide/modes.md: Specification code, proof code, executable code
guide/multitriggers.md: Multiple variables, multiple triggers, matching loops | Multiple triggers | Matching loops: what they are and to avoid them
guide/mutable-references.md: Mutable references | Function specifications | Returning mutable borrows | More examples | Specs about borrowed data | Working with loops | The `has_resolved` operator: When mutable references are "done" | Advanced application: Building a list
guide/mutation-references-borrowing.md: Mutation, references, and borrowing | Rust review | Borrowing in Verus
guide/nonlinear.md: Integers: Nonlinear Arithmetic | 1. Invoking a specialized solver: `nonlinear_arith` | 2. Proving Ring-based Properties: `integer_ring` | 3. Combining `integer_ring` and `nonlinear_arith`.
guide/opaque.md: Modules, hiding, opaque, reveal
guide/operators.md: Expressions and operators for specifications | Chained inequalities | Logical implication | Conjunction and disjunction | Accessing fields of a `struct` or `enum`
guide/overflow.md: Proving Absence of Overflow
guide/overview.md: Verus overview | This guide
guide/performance.md: Meausuring verification performance
guide/pervasive.md: Basic libraries | Some syntactic sugar: spec_index and view
guide/pointers.md: 
guide/prefix-and-or.md: Prefix and/or (`&&&` and `|||`)
guide/profiling.md: Quantifier Profiling
guide/projects.md: Project Setup and Development
guide/proof_functions.md: proof functions | proof blocks | assert-by
guide/quantproofs.md: Proofs about forall and exists | Proving forall with assert-by | Using exists with choose
guide/quants.md: Quantifiers
guide/recursion.md: Recursive functions, decreases, fuel | Fuel and reasoning about recursive functions
guide/recursion_loops.md: Recursion and loops
guide/ref-extensional-equality.md: Extensional equality (`=~=` and `=~~=`)
guide/reference-as.md: Coercion with `as` | Syntax | Coercions on integer types and `char` | Coercions on pointers
guide/reference-assert-by-prover.md: assert ... by(...)
guide/reference-assert-by.md: assert ... by
guide/reference-assert-forall-by.md: assert forall ... by
guide/reference-assert.md: `assert`
guide/reference-assume-specification.md: assume_specification
guide/reference-assume.md: `assume`
guide/reference-at-sign.md: The view function `@`
guide/reference-attributes.md: Attributes | `#![all_triggers]` | `#[verifier::allow_complex_invariants]` | `#![verifier::allow_in_spec]` | `#[verifier::atomic]` | `#![auto]` | `#[verifier::external]` | `#[verifier::external_body]` | `#[verifier::ext_equal]` | `#[verifier::inline]` | `#[verifier::loop_isolation]` | `#[verifier::me
guide/reference-chained-op.md: Chained operators
guide/reference-decreases-to.md: `decreases_to!`
guide/reference-decreases.md: decreases ... when ... via ... | Overview
guide/reference-exec-signature.md: Exec fn signature | Function specification | Function arguments
guide/reference-flag-record.md: Record flag
guide/reference-global.md: The "global" directive | With `usize` and `isize`
guide/reference-has.md: The `has` operator
guide/reference-implication.md: Implication (`==>`, `<==`, and `<==>`)
guide/reference-is.md: The `is` operator
guide/reference-matches.md: The `matches` operator
guide/reference-opens-invariants.md: opens_invariants
guide/reference-pointers-cells.md: Pointers and cells
guide/reference-proof-signature.md: Proof fn signature | Function specification | Function arguments | Function prover mode
guide/reference-prover-mode-bit-vector.md: The `bit_vector` prover mode | Solver operation
guide/reference-prover-mode-compute.md: The compute mode
guide/reference-prover-mode-integer-ring.md: The `integer_ring` solver
guide/reference-prover-mode-nonlinear.md: The nonlinear solver | Solver operation
guide/reference-recommends.md: recommends
guide/reference-returns.md: returns | With the `#![verifier::allow_in_spec]` attribute
guide/reference-reveal-hide.md: `reveal`, `reveal_with_fuel`, `hide`
guide/reference-reveal-strlit.md: `reveal_strlit`
guide/reference-signature-fnonce.md: Specifications on FnOnce
guide/reference-signature-inheritance.md: Signature inheritance
guide/reference-spec-index.md: Spec index operator []
guide/reference-spec-signature.md: Spec fn signature | The `recommends` clause | The `decreases` clause | The openness clause | The `uninterp` specifier
guide/reference-specification-language.md: Specification language
guide/reference-type-invariants.md: Type invariants
guide/reference-types.md: Mathematical interpretations of types | Integer types | Bool | Char | Box (`Box<T>`) | Shared reference (`&T`) | Mutable reference (`&mut T`) | Raw Pointer (`*const T` and `*mut T`) | `String` and `str`
guide/reference-unions.md: Unions
guide/reference-unwind-sig.md: Unwinding signature | Example | Restrictions with invariants | Drops
guide/reference-var-modes.md: Variable modes | Variable modes and function modes | Using `tracked` and `ghost` variables from a `proof` function. | Using `tracked` and `ghost` variables from an `exec` function. | Cheat sheet
guide/requires_ensures.md: Preconditions (requires clauses) | Postconditions (ensures clauses) | assert and assume | Executable code and ghost code
guide/smt_failures.md: SMT solving and automation
guide/smt_perf_overview.md: Managing proof performance and why it's critical
guide/spec-arithmetic.md: Arithmetic in spec code | More advanced arithmetic
guide/spec-bit-ops.md: Bit operators | Reasoning about bit operators
guide/spec-choose.md: Such that (`choose`)
guide/spec-equality.md: Spec equality (`==`)
guide/spec-expressions.md: Spec expressions | Syntax
guide/spec-operator-precedence.md: Operator Precedence
guide/spec-quantifiers.md: Spec quantifiers (`forall`, `exists`)
guide/spec-rust-subset.md: Rust subset
guide/spec_closures.md: Spec Closures
guide/spec_functions.md: spec functions
guide/spec_lib.md: Specification libraries: Seq, Set, ISet, Map, IMap | Constructing and using Seq, Set, ISet, Map, and IMap | Proving properties of Seq, Set, ISet, Map, and IMap
guide/spec_vs_proof.md: spec functions vs. proof functions | Determinism | recommends
guide/specs.md: Basic specifications
guide/static.md: Static items
guide/strings.md: Strings
guide/syntax.md: Verus Syntax
guide/tcb.md: Assumptions and trusted components
guide/traits.md: Traits | Trait function specifications | Extending specifications in implementations | Generic vs. concrete dispatch | Spec and proof functions | The `View` trait | `default_ensures`: specifications for default function implementations | Common `vstd` trait specifications | External trait specificat
guide/triangle.md: Putting It All Together
guide/trigger-annotations.md: Trigger annotations | Terminology: trigger groups and trigger expressions | Selecting trigger groups | Trigger logging
guide/verus_macro_intro.md: The verus! macro
guide/verusdoc.md: Documentation with Rustdoc | Run rustdoc. | Note the VERUSDOC environment variable. | Run the post-processor.
guide/vstd.md: Libraries
guide/while.md: Loops and invariants
