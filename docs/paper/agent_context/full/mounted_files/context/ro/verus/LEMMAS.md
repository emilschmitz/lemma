# vstd index (generated)

One entry per item. Grep a name or a concept: `grep -n -A6 'lemma_seq_.*subrange' LEMMAS.md`.
Methods are `## Owner::name`: `grep -n -A5 '^## Vec::' LEMMAS.md` lists the Vec exec specs.
Open the file in `vstd/` for the proof body.

## rust_div
- path: vstd/arithmetic/div_mod.rs:20  (spec fn)
- sig: `pub open spec fn rust_div(a: int, b: int) -> int recommends b != 0,`

## rust_rem
- path: vstd/arithmetic/div_mod.rs:33  (spec fn)
- sig: `pub open spec fn rust_rem(a: int, b: int) -> int recommends b != 0,`

## lemma_div_is_div_recursive
- path: vstd/arithmetic/div_mod.rs:81  (proof fn)
- sig: `pub broadcast proof fn lemma_div_is_div_recursive(x: int, d: int)`
- requires: 0 < d,
- ensures: div_recursive(x, d) == #[trigger] (x / d),
- doc: Proof that, for the case of `x / d`, division using `/` is

## lemma_div_by_self
- path: vstd/arithmetic/div_mod.rs:94  (proof fn)
- sig: `pub proof fn lemma_div_by_self(d: int)`
- requires: d != 0,
- ensures: d / d == 1,
- doc: Proof that the quotient of an integer divided by itself is 1,

## lemma_div_of0
- path: vstd/arithmetic/div_mod.rs:104  (proof fn)
- sig: `pub proof fn lemma_div_of0(d: int)`
- requires: d != 0,
- ensures: 0 as int / d == 0,
- doc: Proof that 0 divided by a nonzero integer is 0, specifically `0 / d == 0`.

## lemma_div_basics
- path: vstd/arithmetic/div_mod.rs:116  (proof fn)
- sig: `pub proof fn lemma_div_basics(x: int)`
- ensures: x != 0 as int ==> 0 as int / x == 0, x / 1 == x, x != 0 ==> x / x == 1,
- doc: Proof establishing basic properties of division using `x`: 0

## lemma_div_basics_1
- path: vstd/arithmetic/div_mod.rs:129  (proof fn)
- sig: `pub broadcast proof fn lemma_div_basics_1(x: int)`
- ensures: x != 0 as int ==> #[trigger] (0int / x) == 0,
- doc: Proof for basic property that 0 divided by `x` is 0.

## lemma_div_basics_2
- path: vstd/arithmetic/div_mod.rs:137  (proof fn)
- sig: `pub broadcast proof fn lemma_div_basics_2(x: int)`
- ensures: #[trigger] (x / 1) == x,
- doc: Proof for basic property that `x` divided by 1 is `x`.

## lemma_div_basics_3
- path: vstd/arithmetic/div_mod.rs:145  (proof fn)
- sig: `pub broadcast proof fn lemma_div_basics_3(x: int)`
- ensures: x != 0 ==> #[trigger] (x / x) == 1,
- doc: Proof for basic property that `x` divided by `x` is 1.

## lemma_div_basics_4
- path: vstd/arithmetic/div_mod.rs:153  (proof fn)
- sig: `pub broadcast proof fn lemma_div_basics_4(x: int, y: int)`
- ensures: x >= 0 && y > 0 ==> #[trigger] (x / y) >= 0,
- doc: Proof that dividing any non-negative integer by a positive integer is non-zero.

## lemma_div_basics_5
- path: vstd/arithmetic/div_mod.rs:161  (proof fn)
- sig: `pub broadcast proof fn lemma_div_basics_5(x: int, y: int)`
- ensures: x >= 0 && y > 0 ==> #[trigger] (x / y) <= x,
- doc: Proof that the quotient produced by dividing any non-negative integer `x`

## group_div_basics
- path: vstd/arithmetic/div_mod.rs  (broadcast group)
- members: lemma_div_basics_1 lemma_div_basics_2 lemma_div_basics_3 lemma_div_basics_4 lemma_div_basics_5

## lemma_small_div_converse
- path: vstd/arithmetic/div_mod.rs:182  (proof fn)
- sig: `pub broadcast proof fn lemma_small_div_converse(x: int, d: int)`
- ensures: 0 <= x && 0 < d && #[trigger] (x / d) == 0 ==> x < d,
- doc: Proof that if a dividend is a whole number, the divisor is a

## lemma_div_non_zero
- path: vstd/arithmetic/div_mod.rs:194  (proof fn)
- sig: `pub proof fn lemma_div_non_zero(x: int, d: int)`
- requires: x >= d > 0,
- ensures: #[trigger] (x / d) > 0,
- doc: Proof that division of a positive integer by a positive integer

## lemma_div_is_ordered_by_denominator
- path: vstd/arithmetic/div_mod.rs:213  (proof fn)
- sig: `pub broadcast proof fn lemma_div_is_ordered_by_denominator(x: int, y: int, z: int)`
- requires: 0 <= x, 1 <= y <= z,
- ensures: #[trigger] (x / y) >= #[trigger] (x / z),
- doc: Proof that given two fractions with the same numerator, the order

## lemma_div_is_strictly_smaller
- path: vstd/arithmetic/div_mod.rs:239  (proof fn)
- sig: `pub broadcast proof fn lemma_div_is_strictly_smaller(x: int, d: int)`
- requires: 0 < x, 1 < d,
- ensures: #[trigger] (x / d) < x,
- doc: Proof that a number gets strictly smaller when divided by a number

## lemma_dividing_sums
- path: vstd/arithmetic/div_mod.rs:252  (proof fn)
- sig: `pub broadcast proof fn lemma_dividing_sums(a: int, b: int, d: int, r: int)`
- requires: 0 < d, r == a % d + b % d - (a + b) % d,
- ensures: #![trigger (d * ((a + b) / d) - r), (d * (a / d) + d * (b / d))] d * ((a + b) / d) - r == d * (a / d) + d * (b / d),
- doc: Proof that, given `r == a % d + b % d - (a + b) % d`, `r` can also

## lemma_div_pos_is_pos
- path: vstd/arithmetic/div_mod.rs:268  (proof fn)
- sig: `pub broadcast proof fn lemma_div_pos_is_pos(x: int, d: int)`
- requires: 0 <= x, 0 < d,
- ensures: 0 <= #[trigger] (x / d),
- doc: Proof that dividing a whole number by a natural number will result

## lemma_div_plus_one
- path: vstd/arithmetic/div_mod.rs:287  (proof fn)
- sig: `pub broadcast proof fn lemma_div_plus_one(x: int, d: int)`
- requires: 0 < d,
- ensures: #![trigger (1 + x / d), ((d + x) / d)] 1 + x / d == (d + x) / d,
- doc: Proof that dividing a number then adding 1 gives the same result

## lemma_div_minus_one
- path: vstd/arithmetic/div_mod.rs:300  (proof fn)
- sig: `pub broadcast proof fn lemma_div_minus_one(x: int, d: int)`
- requires: 0 < d,
- ensures: #![trigger (-1 + x / d), ((-d + x) / d)] -1 + x / d == (-d + x) / d,
- doc: Proof that dividing a number then subtracting 1 gives the same result

## lemma_basic_div_specific_divisor
- path: vstd/arithmetic/div_mod.rs:312  (proof fn)
- sig: `pub proof fn lemma_basic_div_specific_divisor(d: int)`
- requires: 0 < d,
- ensures: forall|x: int| 0 <= x < d ==> #[trigger] (x / d) == 0,
- doc: Proof that dividing any non-negative integer less than `d` by `d`

## lemma_basic_div
- path: vstd/arithmetic/div_mod.rs:323  (proof fn)
- sig: `pub broadcast proof fn lemma_basic_div(x: int, d: int)`
- requires: 0 <= x < d,
- ensures: #[trigger] (x / d) == 0,
- doc: Proof that dividing any non-negative integer by a larger integer

## lemma_div_is_ordered
- path: vstd/arithmetic/div_mod.rs:335  (proof fn)
- sig: `pub broadcast proof fn lemma_div_is_ordered(x: int, y: int, z: int)`
- requires: x <= y, 0 < z,
- ensures: #[trigger] (x / z) <= #[trigger] (y / z),
- doc: Proof that numerical order is preserved when dividing two seperate

## lemma_div_decreases
- path: vstd/arithmetic/div_mod.rs:363  (proof fn)
- sig: `pub broadcast proof fn lemma_div_decreases(x: int, d: int)`
- requires: 0 < x, 1 < d,
- ensures: #[trigger] (x / d) < x,
- doc: Proof that dividing an integer by 2 or more results in a quotient

## lemma_div_nonincreasing
- path: vstd/arithmetic/div_mod.rs:376  (proof fn)
- sig: `pub broadcast proof fn lemma_div_nonincreasing(x: int, d: int)`
- requires: 0 <= x, 0 < d,
- ensures: #[trigger] (x / d) <= x,
- doc: Proof that dividing an integer by 1 or more results in a quotient

## lemma_small_mod
- path: vstd/arithmetic/div_mod.rs:389  (proof fn)
- sig: `pub proof fn lemma_small_mod(x: nat, m: nat)`
- requires: x < m, 0 < m,
- ensures: x % m == x,
- doc: Proof that a natural number x divided by a larger natural number

## lemma_breakdown
- path: vstd/arithmetic/div_mod.rs:403  (proof fn)
- sig: `pub broadcast proof fn lemma_breakdown(x: int, y: int, z: int)`
- requires: 0 <= x, 0 < y, 0 < z,
- ensures: #![trigger y * z, x % (y * z), y * ((x / y) % z) + x % y] 0 < y * z, (x % (y * z)) == y * ((x / y) % z) + x % y,
- doc: The remainder of a nonnegative integer `x` divided by the product of two positive integers

## lemma_remainder_upper
- path: vstd/arithmetic/div_mod.rs:468  (proof fn)
- sig: `pub broadcast proof fn lemma_remainder_upper(x: int, d: int)`
- requires: 0 <= x, 0 < d,
- ensures: #![trigger (x - d), (x / d * d)] x - d < x / d * d,
- doc: Proof that the difference between a nonnegative integer `x` and a

## lemma_remainder_lower
- path: vstd/arithmetic/div_mod.rs:484  (proof fn)
- sig: `pub broadcast proof fn lemma_remainder_lower(x: int, d: int)`
- requires: 0 <= x, 0 < d,
- ensures: x >= #[trigger] (x / d * d),
- doc: Proof that the division of a nonnegative integer `x` by a positive

## lemma_remainder
- path: vstd/arithmetic/div_mod.rs:500  (proof fn)
- sig: `pub broadcast proof fn lemma_remainder(x: int, d: int)`
- requires: 0 <= x, 0 < d,
- ensures: 0 <= #[trigger] (x - (x / d * d)) < d,
- doc: Proof that the difference between a nonnegative integer `x` and

## lemma_fundamental_div_mod
- path: vstd/arithmetic/div_mod.rs:515  (proof fn)
- sig: `pub broadcast proof fn lemma_fundamental_div_mod(x: int, d: int)`
- requires: d != 0,
- ensures: x == #[trigger] (d * (x / d) + (x % d)),
- doc: Proof of the fundamental theorem of division and modulo, namely

## lemma_div_denominator
- path: vstd/arithmetic/div_mod.rs:528  (proof fn)
- sig: `pub broadcast proof fn lemma_div_denominator(x: int, c: int, d: int)`
- requires: 0 <= x, 0 < c, 0 < d,
- ensures: c * d != 0, #[trigger] ((x / c) / d) == x / (c * d),
- doc: Proof that dividing `x` by `c * d` is equivalent to first dividing

## lemma_mul_hoist_inequality
- path: vstd/arithmetic/div_mod.rs:628  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_hoist_inequality(x: int, y: int, z: int)`
- requires: 0 <= x, 0 < z,
- ensures: #![trigger (x * (y / z)), ((x * y) / z)] x * (y / z) <= (x * y) / z,
- doc: Proof that multiplying an integer by a fraction is equivalent to

## lemma_indistinguishable_quotients
- path: vstd/arithmetic/div_mod.rs:663  (proof fn)
- sig: `pub broadcast proof fn lemma_indistinguishable_quotients(a: int, b: int, d: int)`
- requires: 0 < d, 0 <= a - a % d <= b < a + d - a % d,
- ensures: #![trigger (a / d), (b / d)] a / d == b / d,
- doc: Proof that for a positive integer `d`, if `a - a % d` is less than

## lemma_truncate_middle
- path: vstd/arithmetic/div_mod.rs:685  (proof fn)
- sig: `pub proof fn lemma_truncate_middle(x: int, b: int, c: int)`
- requires: 0 <= x, 0 < b, 0 < c,
- ensures: #![trigger (b * (x % c))] 0 < b * c, (b * x) % (b * c) == b * (x % c),
- doc: Proof that common factors from the dividend and divisor of a

## lemma_div_multiples_vanish_quotient
- path: vstd/arithmetic/div_mod.rs:722  (proof fn)
- sig: `pub broadcast proof fn lemma_div_multiples_vanish_quotient(x: int, a: int, d: int)`
- requires: 0 < x, 0 <= a, 0 < d,
- ensures: #![trigger a / d, x * a, x * d] 0 < x * d, a / d == (x * a) / (x * d),
- doc: Proof that multiplying the numerator and denominator by an integer

## lemma_round_down
- path: vstd/arithmetic/div_mod.rs:748  (proof fn)
- sig: `pub broadcast proof fn lemma_round_down(a: int, r: int, d: int)`
- requires: 0 < d, a % d == 0, 0 <= r < d,
- ensures: #![trigger (d * ((a + r) / d))] a == d * ((a + r) / d),
- doc: Proof that, since `a % d == 0` and `0 <= r < d`, we can conclude

## lemma_div_multiples_vanish_fancy
- path: vstd/arithmetic/div_mod.rs:763  (proof fn)
- sig: `pub broadcast proof fn lemma_div_multiples_vanish_fancy(x: int, b: int, d: int)`
- requires: 0 < d, 0 <= b < d,
- ensures: #![trigger (d * x + b) / d] (d * x + b) / d == x,
- doc: Proof that, since `0 <= b < d`, we have `(d * x + b) / d == x`.

## lemma_div_multiples_vanish
- path: vstd/arithmetic/div_mod.rs:802  (proof fn)
- sig: `pub broadcast proof fn lemma_div_multiples_vanish(x: int, d: int)`
- requires: 0 < d,
- ensures: #![trigger (d * x) / d] (d * x) / d == x,
- doc: Proof that multiplying an integer by a common numerator and

## lemma_div_by_multiple
- path: vstd/arithmetic/div_mod.rs:815  (proof fn)
- sig: `pub broadcast proof fn lemma_div_by_multiple(b: int, d: int)`
- requires: 0 <= b, 0 < d,
- ensures: #![trigger ((b * d) / d)] (b * d) / d == b,
- doc: Proof that multiplying a whole number by a common numerator and

## lemma_div_by_multiple_is_strongly_ordered
- path: vstd/arithmetic/div_mod.rs:831  (proof fn)
- sig: `pub broadcast proof fn lemma_div_by_multiple_is_strongly_ordered(x: int, y: int, m: int, z: int)`
- requires: x < y, y == m * z, 0 < z,
- ensures: #![trigger x / z, m * z, y / z] x / z < y / z,
- doc: Proof that a dividend that is a positive multiple of a divisor

## lemma_multiply_divide_le
- path: vstd/arithmetic/div_mod.rs:856  (proof fn)
- sig: `pub broadcast proof fn lemma_multiply_divide_le(a: int, b: int, c: int)`
- requires: 0 < b, a <= b * c,
- ensures: #![trigger a / b, b * c] a / b <= c,
- doc: Proof that if an integer is less than or equal to the product of

## lemma_multiply_divide_lt
- path: vstd/arithmetic/div_mod.rs:873  (proof fn)
- sig: `pub broadcast proof fn lemma_multiply_divide_lt(a: int, b: int, c: int)`
- requires: 0 < b, a < b * c,
- ensures: #![trigger a / b, b * c] a / b < c,
- doc: Proof that if an integer is less than the product of two other

## lemma_hoist_over_denominator
- path: vstd/arithmetic/div_mod.rs:899  (proof fn)
- sig: `pub broadcast proof fn lemma_hoist_over_denominator(x: int, j: int, d: nat)`
- requires: 0 < d,
- ensures: #![trigger x / d as int + j] x / d as int + j == (x + j * d) / d as int,
- doc: Proof that adding an integer to a fraction is equivalent to adding

## lemma_part_bound1
- path: vstd/arithmetic/div_mod.rs:926  (proof fn)
- sig: `pub broadcast proof fn lemma_part_bound1(a: int, b: int, c: int)`
- requires: 0 <= a, 0 < b, 0 < c,
- ensures: #![trigger (b * (a / b) % (b * c))] 0 < b * c, (b * (a / b) % (b * c)) <= b * (c - 1),
- doc: Proof that, for nonnegative integer `a` and positive integers `b` and `c`,

## lemma_mod_is_mod_recursive
- path: vstd/arithmetic/div_mod.rs:967  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_is_mod_recursive(x: int, m: int)`
- requires: m > 0,
- ensures: mod_recursive(x, m) == #[trigger] (x % m),
- doc: Proof that computing the modulus using `%` is equivalent to

## lemma_mod_self_0
- path: vstd/arithmetic/div_mod.rs:1026  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_self_0(m: int)`
- requires: m > 0,
- ensures: #[trigger] (m % m) == 0,
- doc: Proof that any integer divided by itself produces a remainder of 0.

## lemma_mod_twice
- path: vstd/arithmetic/div_mod.rs:1036  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_twice(x: int, m: int)`
- requires: m > 0,
- ensures: #[trigger] ((x % m) % m) == x % m,
- doc: Proof that performing `(x % m) % m` gives the same result as simply perfoming `x % m`.

## group_mod_basics
- path: vstd/arithmetic/div_mod.rs  (broadcast group)
- members: lemma_mod_self_0 lemma_mod_twice

## lemma_mod_division_less_than_divisor
- path: vstd/arithmetic/div_mod.rs:1051  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_division_less_than_divisor(x: int, m: int)`
- requires: m > 0,
- ensures: 0 <= #[trigger] (x % m) < m,
- doc: Proof that the remainder of any division will be less than the divisor's value.

## group_mod_properties
- path: vstd/arithmetic/div_mod.rs  (broadcast group)
- members: group_mod_basics lemma_mod_division_less_than_divisor

## lemma_mod_decreases
- path: vstd/arithmetic/div_mod.rs:1067  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_decreases(x: nat, m: nat)`
- requires: 0 < m,
- ensures: #[trigger] (x % m) <= x,
- doc: Proof that when natural number `x` is divided by natural number

## lemma_mod_is_zero
- path: vstd/arithmetic/div_mod.rs:1077  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_is_zero(x: nat, m: nat)`
- requires: x > 0 && m > 0, #[trigger] (x % m) == 0,
- ensures: x >= m,
- doc: Proof that if `x % m` is zero and `x` is positive, then `x >= m`.

## lemma_mod_multiples_basic
- path: vstd/arithmetic/div_mod.rs:1092  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_multiples_basic(x: int, m: int)`
- requires: m > 0,
- ensures: #[trigger] ((x * m) % m) == 0,
- doc: Proof that multiplying by a number then dividing by that same

## lemma_mod_add_multiples_vanish
- path: vstd/arithmetic/div_mod.rs:1108  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_add_multiples_vanish(b: int, m: int)`
- requires: 0 < m,
- ensures: (m + b) % m == #[trigger] (b % m),
- doc: Proof that adding the divisor to the dividend doesn't change the

## lemma_mod_sub_multiples_vanish
- path: vstd/arithmetic/div_mod.rs:1119  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_sub_multiples_vanish(b: int, m: int)`
- requires: 0 < m,
- ensures: (-m + b) % m == #[trigger] (b % m),
- doc: Proof that subtracting the divisor from the dividend doesn't

## lemma_mod_multiples_vanish
- path: vstd/arithmetic/div_mod.rs:1131  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_multiples_vanish(a: int, b: int, m: int)`
- requires: 0 < m,
- ensures: #[trigger] ((m * a + b) % m) == b % m,
- doc: Proof that adding any multiple of the divisor to the dividend will produce the

## lemma_mod_subtraction
- path: vstd/arithmetic/div_mod.rs:1155  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_subtraction(x: nat, s: nat, d: nat)`
- requires: 0 < d, 0 <= s <= x % d,
- ensures: #![trigger ((x - s) % d as int)] x % d - s % d == (x - s) % d as int,
- doc: Proof that modulo distributes over subtraction if the subtracted value is

## lemma_add_mod_noop
- path: vstd/arithmetic/div_mod.rs:1169  (proof fn)
- sig: `pub broadcast proof fn lemma_add_mod_noop(x: int, y: int, m: int)`
- requires: 0 < m,
- ensures: #![trigger (x + y) % m] ((x % m) + (y % m)) % m == (x + y) % m,
- doc: Proof that modulo distributes over addition, provided you do an

## lemma_add_mod_noop_right
- path: vstd/arithmetic/div_mod.rs:1182  (proof fn)
- sig: `pub broadcast proof fn lemma_add_mod_noop_right(x: int, y: int, m: int)`
- requires: 0 < m,
- ensures: #![trigger (x + y) % m] (x + (y % m)) % m == (x + y) % m,
- doc: Proof that describes an expanded and succinct version of modulus

## lemma_sub_mod_noop
- path: vstd/arithmetic/div_mod.rs:1195  (proof fn)
- sig: `pub broadcast proof fn lemma_sub_mod_noop(x: int, y: int, m: int)`
- requires: 0 < m,
- ensures: #![trigger (x - y) % m] ((x % m) - (y % m)) % m == (x - y) % m,
- doc: Proof that modulo distributes over subtraction provided you do an

## lemma_sub_mod_noop_right
- path: vstd/arithmetic/div_mod.rs:1208  (proof fn)
- sig: `pub broadcast proof fn lemma_sub_mod_noop_right(x: int, y: int, m: int)`
- requires: 0 < m,
- ensures: #![trigger ((x - y) % m)] (x - (y % m)) % m == (x - y) % m,
- doc: Proof that describes an expanded and succinct version of modulus

## lemma_mod_adds
- path: vstd/arithmetic/div_mod.rs:1221  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_adds(a: int, b: int, d: int)`
- requires: 0 < d,
- ensures: #![trigger ((a + b) % d)] a % d + b % d == (a + b) % d + d * ((a % d + b % d) / d), (a % d + b % d) < d ==> a % d + b % d == (a + b) % d,
- doc: Proof of two properties of the sum of two remainders with the same dividend:

## lemma_mod_neg_neg
- path: vstd/arithmetic/div_mod.rs:1238  (proof fn)
- sig: `pub proof fn lemma_mod_neg_neg(x: int, d: int)`
- requires: 0 < d,
- ensures: x % d == (x * (1 - d)) % d,
- doc: Proof that the remainder when dividing integer `x` by positive

## lemma_fundamental_div_mod_converse_mod
- path: vstd/arithmetic/div_mod.rs:1333  (proof fn)
- sig: `pub broadcast proof fn lemma_fundamental_div_mod_converse_mod(x: int, d: int, q: int, r: int)`
- requires: d != 0, 0 <= r < d, x == #[trigger] (q * d + r),
- ensures: r == #[trigger] (x % d),
- doc: Proof of the converse of the fundamental property of division and modulo.

## lemma_fundamental_div_mod_converse_div
- path: vstd/arithmetic/div_mod.rs:1349  (proof fn)
- sig: `pub broadcast proof fn lemma_fundamental_div_mod_converse_div(x: int, d: int, q: int, r: int)`
- requires: d != 0, 0 <= r < d, x == #[trigger] (q * d + r),
- ensures: q == #[trigger] (x / d),
- doc: Proof of the converse of the fundamental property of division and modulo.

## lemma_fundamental_div_mod_converse
- path: vstd/arithmetic/div_mod.rs:1365  (proof fn)
- sig: `pub proof fn lemma_fundamental_div_mod_converse(x: int, d: int, q: int, r: int)`
- requires: d != 0, 0 <= r < d, x == q * d + r,
- ensures: r == x % d, q == x / d,
- doc: Proof of the converse of the fundamental property of division and modulo.

## group_fundamental_div_mod_converse
- path: vstd/arithmetic/div_mod.rs  (broadcast group)
- members: lemma_fundamental_div_mod_converse_mod lemma_fundamental_div_mod_converse_div

## lemma_mod_pos_bound
- path: vstd/arithmetic/div_mod.rs:1385  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_pos_bound(x: int, m: int)`
- requires: 0 <= x, 0 < m,
- ensures: 0 <= #[trigger] (x % m) < m,
- doc: Proof that the remainder, when natural number `x` is divided by

## lemma_mod_bound
- path: vstd/arithmetic/div_mod.rs:1397  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_bound(x: int, m: int)`
- requires: 0 < m,
- ensures: 0 <= #[trigger] (x % m) < m,
- doc: Proof that when integer `x` is divided by positive integer `m`,

## lemma_mul_mod_noop_left
- path: vstd/arithmetic/div_mod.rs:1408  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_mod_noop_left(x: int, y: int, m: int)`
- requires: 0 < m,
- ensures: (x % m) * y % m == #[trigger] (x * y % m),
- doc: Proof that the remainder when `x * y` is divided by `m` is

## lemma_mul_mod_noop_right
- path: vstd/arithmetic/div_mod.rs:1420  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_mod_noop_right(x: int, y: int, m: int)`
- requires: 0 < m,
- ensures: x * (y % m) % m == #[trigger] ((x * y) % m),
- doc: Proof that the remainder when `x * y` is divided by `m` is

## lemma_mul_mod_noop_general
- path: vstd/arithmetic/div_mod.rs:1433  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_mod_noop_general(x: int, y: int, m: int)`
- requires: 0 < m,
- ensures: ((x % m) * y) % m == (x * y) % m, (x * (y % m)) % m == (x * y) % m, ((x % m) * (y % m)) % m == #[trigger] ((x * y) % m),
- doc: Proof of various properties about modulo equivalence with respect

## lemma_mul_mod_noop
- path: vstd/arithmetic/div_mod.rs:1449  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_mod_noop(x: int, y: int, m: int)`
- requires: 0 < m,
- ensures: (x % m) * (y % m) % m == #[trigger] ((x * y) % m),
- doc: Proof that modulo distributes over multiplication, provided you do

## lemma_mod_equivalence
- path: vstd/arithmetic/div_mod.rs:1465  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_equivalence(x: int, y: int, m: int)`
- requires: 0 < m,
- ensures: #![trigger (x - y) % m] x % m == y % m <==> (x - y) % m == 0,
- doc: Proof that `x` and `y` are congruent modulo `m` if and only if `x

## is_mod_equivalent
- path: vstd/arithmetic/div_mod.rs:1477  (spec fn)
- sig: `pub open spec fn is_mod_equivalent(x: int, y: int, m: int) -> bool recommends m > 0,`
- doc: This function says that `x` is congruent to `y` modulo `m` if and

## lemma_mod_mul_equivalent
- path: vstd/arithmetic/div_mod.rs:1486  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_mul_equivalent(x: int, y: int, z: int, m: int)`
- requires: m > 0, is_mod_equivalent(x, y, m),
- ensures: #[trigger] is_mod_equivalent(x * z, y * z, m),
- doc: Proof that if `is_mod_equivalent` holds for `x`, `y`, and `m`,

## lemma_mod_ordering
- path: vstd/arithmetic/div_mod.rs:1502  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_ordering(x: int, k: int, d: int)`
- requires: 1 < d, 0 < k,
- ensures: 0 < d * k, x % d <= #[trigger] (x % (d * k)),
- doc: Proof that multiplying the divisor by a positive number can't

## lemma_mod_mod
- path: vstd/arithmetic/div_mod.rs:1551  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_mod(x: int, a: int, b: int)`
- requires: 0 < a, 0 < b,
- ensures: #![trigger (x % (a * b)) % a, x % a] 0 < a * b, (x % (a * b)) % a == x % a,
- doc: Proof that the remainder when `x` is divided by `a * b`, taken

## lemma_part_bound2
- path: vstd/arithmetic/div_mod.rs:1591  (proof fn)
- sig: `pub broadcast proof fn lemma_part_bound2(x: int, y: int, z: int)`
- requires: 0 <= x, 0 < y, 0 < z,
- ensures: y * z > 0, #[trigger] (x % y) % #[trigger] (y * z) < y,
- doc: Proof that `(x % y) % (y * z) < y`.

## lemma_mod_breakdown
- path: vstd/arithmetic/div_mod.rs:1616  (proof fn)
- sig: `pub broadcast proof fn lemma_mod_breakdown(x: int, y: int, z: int)`
- requires: 0 <= x, 0 < y, 0 < z,
- ensures: #![trigger x % (y * z)] y * z > 0, x % (y * z) == y * ((x / y) % z) + x % y,
- doc: Proof of the validity of an expanded form of the modulus operation.

## div_pos
- path: vstd/arithmetic/internals/div_internals.rs:39  (spec fn)
- sig: `pub open spec fn div_pos(x: int, d: int) -> int recommends d > 0,`
- doc: This function recursively computes the quotient resulting from

## div_recursive
- path: vstd/arithmetic/internals/div_internals.rs:63  (spec fn)
- sig: `pub open spec fn div_recursive(x: int, d: int) -> int recommends d != 0,`
- doc: This function recursively computes the quotient resulting from

## lemma_div_basics
- path: vstd/arithmetic/internals/div_internals.rs:77  (proof fn)
- sig: `pub proof fn lemma_div_basics(n: int)`
- requires: n > 0,
- ensures: (n / n) == 1 && -((-n) / n) == 1, forall|x: int| 0 <= x < n <==> #[trigger] (x / n) == 0, forall|x: int| #[trigger] ((x + n) / n) == x / n + 1, forall|x: int| #[trigger] ((x - n) / n) == x / n - 1,
- doc: Proof of basic properties of integer division when the divisor is

## div_auto_plus
- path: vstd/arithmetic/internals/div_internals.rs:99  (spec fn)
- sig: `pub open spec fn div_auto_plus(n: int) -> bool`
- doc: This function says that for any `x` and `y`, there are two

## div_auto_minus
- path: vstd/arithmetic/internals/div_internals.rs:113  (spec fn)
- sig: `pub open spec fn div_auto_minus(n: int) -> bool`
- doc: This function says that for any `x` and `y`, there are two

## div_auto
- path: vstd/arithmetic/internals/div_internals.rs:127  (spec fn)
- sig: `pub open spec fn div_auto(n: int) -> bool recommends n > 0,`
- doc: This function states various properties of integer division when

## lemma_div_auto
- path: vstd/arithmetic/internals/div_internals.rs:234  (proof fn)
- sig: `pub proof fn lemma_div_auto(n: int)`
- requires: n > 0,
- ensures: div_auto(n),
- doc: Proof of `div_auto(n)`, which expresses many useful properties of

## lemma_div_induction_auto
- path: vstd/arithmetic/internals/div_internals.rs:278  (proof fn)
- sig: `pub proof fn lemma_div_induction_auto(n: int, x: int, f: spec_fn(int) -> bool)`
- requires: n > 0, div_auto(n) ==> { &&& (forall|i: int| #[trigger] is_le(0, i) && i < n ==> f(i)) &&& (forall|i: int| #[trigger] is_le(0, i) && f(i) ==> f(i + n)) &&& (forall|i: int| #[trigger] is_le(i + 1, n) && f(i) ==> f(i - n))
- ensures: div_auto(n), f(x),
- doc: This utility function helps prove a mathematical property by

## lemma_div_induction_auto_forall
- path: vstd/arithmetic/internals/div_internals.rs:328  (proof fn)
- sig: `pub proof fn lemma_div_induction_auto_forall(n: int, f: spec_fn(int) -> bool)`
- requires: n > 0, div_auto(n) ==> { &&& (forall|i: int| #[trigger] is_le(0, i) && i < n ==> f(i)) &&& (forall|i: int| #[trigger] is_le(0, i) && f(i) ==> f(i + n)) &&& (forall|i: int| #[trigger] is_le(i + 1, n) && f(i) ==> f(i - n))
- ensures: div_auto(n), forall|i| #[trigger] f(i),
- doc: This utility function helps prove a mathematical property by

## lemma_div_of0
- path: vstd/arithmetic/internals/div_internals_nonlinear.rs:22  (proof fn)
- sig: `pub proof fn lemma_div_of0(d: int)`
- requires: d != 0 as int,
- ensures: 0 as int / d == 0 as int,
- doc: Proof that 0 divided by any given integer `d` is 0

## lemma_div_by_self
- path: vstd/arithmetic/internals/div_internals_nonlinear.rs:31  (proof fn)
- sig: `pub proof fn lemma_div_by_self(d: int)`
- requires: d != 0,
- ensures: d / d == 1,
- doc: Proof that any given integer `d` divided by itself is 1

## lemma_small_div
- path: vstd/arithmetic/internals/div_internals_nonlinear.rs:41  (proof fn)
- sig: `pub proof fn lemma_small_div()`
- ensures: forall|x: int, d: int| 0 <= x < d && d > 0 ==> #[trigger] (x / d) == 0,
- doc: Proof that dividing a non-negative integer by a larger integer results in a quotient of 0

## is_le
- path: vstd/arithmetic/internals/general_internals.rs:25  (spec fn)
- sig: `pub open spec fn is_le(x: int, y: int) -> bool`
- doc: Computes the boolean `x <= y`. This is useful where we want to

## lemma_induction_helper
- path: vstd/arithmetic/internals/general_internals.rs:100  (proof fn)
- sig: `pub proof fn lemma_induction_helper(n: int, f: spec_fn(int) -> bool, x: int)`
- requires: n > 0, forall|i: int| 0 <= i < n ==> #[trigger] f(i), forall|i: int| i >= 0 && #[trigger] f(i) ==> #[trigger] f(add1(i, n)), forall|i: int| i < n && #[trigger] f(i) ==> #[trigger] f(sub1(i, n)),
- ensures: f(x),
- doc: This utility function helps prove a mathematical property by

## mod_recursive
- path: vstd/arithmetic/internals/mod_internals.rs:38  (spec fn)
- sig: `pub open spec fn mod_recursive(x: int, d: int) -> int recommends d > 0,`
- doc: This function performs the modulus operation recursively.

## lemma_mod_induction_forall
- path: vstd/arithmetic/internals/mod_internals.rs:79  (proof fn)
- sig: `pub proof fn lemma_mod_induction_forall(n: int, f: spec_fn(int) -> bool)`
- requires: n > 0, forall|i: int| 0 <= i < n ==> #[trigger] f(i), forall|i: int| i >= 0 && #[trigger] f(i) ==> #[trigger] f(add1(i, n)), forall|i: int| i < n && #[trigger] f(i) ==> #[trigger] f(sub1(i, n)),
- ensures: forall|i| #[trigger] f(i),
- doc: This utility function helps prove a mathematical property by

## lemma_mod_induction_forall2
- path: vstd/arithmetic/internals/mod_internals.rs:120  (proof fn)
- sig: `pub proof fn lemma_mod_induction_forall2(n: int, f: spec_fn(int, int) -> bool)`
- requires: n > 0, forall|i: int, j: int| 0 <= i < n && 0 <= j < n ==> #[trigger] f(i, j), forall|i: int, j: int| i >= 0 && #[trigger] f(i, j) ==> #[trigger] f(add1(i, n), j), forall|i: int, j: int| j >= 0 && #[trigger] f(i, j) ==> #[trigger] f(i, add1(j, n)), forall|i: int, j: int| i < n && #[trigger] f(i, j) ==> #[trigger] f(sub1(i, n), j),
- ensures: forall|i: int, j: int| #[trigger] f(i, j),
- doc: This utility function helps prove a mathematical property of a

## lemma_div_add_denominator
- path: vstd/arithmetic/internals/mod_internals.rs:147  (proof fn)
- sig: `pub proof fn lemma_div_add_denominator(n: int, x: int)`
- requires: n > 0,
- ensures: (x + n) / n == x / n + 1,
- doc: Proof that when dividing, adding the denominator to the numerator

## lemma_div_sub_denominator
- path: vstd/arithmetic/internals/mod_internals.rs:171  (proof fn)
- sig: `pub proof fn lemma_div_sub_denominator(n: int, x: int)`
- requires: n > 0,
- ensures: (x - n) / n == x / n - 1,
- doc: Proof that when dividing, subtracting the denominator from the numerator

## lemma_mod_add_denominator
- path: vstd/arithmetic/internals/mod_internals.rs:196  (proof fn)
- sig: `pub proof fn lemma_mod_add_denominator(n: int, x: int)`
- requires: n > 0,
- ensures: (x + n) % n == x % n,
- doc: Proof that when dividing, adding the denominator to the numerator

## lemma_mod_sub_denominator
- path: vstd/arithmetic/internals/mod_internals.rs:228  (proof fn)
- sig: `pub proof fn lemma_mod_sub_denominator(n: int, x: int)`
- requires: n > 0,
- ensures: (x - n) % n == x % n,
- doc: Proof that when dividing, subtracting the denominator from the

## lemma_mod_below_denominator
- path: vstd/arithmetic/internals/mod_internals.rs:253  (proof fn)
- sig: `pub proof fn lemma_mod_below_denominator(n: int, x: int)`
- requires: n > 0,
- ensures: 0 <= x < n <==> x % n == x,
- doc: Proof that for the given `n` and `x`, `x % n == x` if and only if

## lemma_mod_basics
- path: vstd/arithmetic/internals/mod_internals.rs:277  (proof fn)
- sig: `pub proof fn lemma_mod_basics(n: int)`
- requires: n > 0,
- ensures: forall|x: int| #[trigger] ((x + n) % n) == x % n, forall|x: int| #[trigger] ((x - n) % n) == x % n, forall|x: int| #[trigger] ((x + n) / n) == x / n + 1, forall|x: int| #[trigger] ((x - n) / n) == x / n - 1, forall|x: int| 0 <= x < n <==> #[trigger] (x % n) == x,
- doc: Proof of basic properties of the division given the divisor `n`:

## lemma_quotient_and_remainder
- path: vstd/arithmetic/internals/mod_internals.rs:308  (proof fn)
- sig: `pub proof fn lemma_quotient_and_remainder(x: int, q: int, r: int, n: int)`
- requires: n > 0, 0 <= r < n, x == q * n + r,
- ensures: q == x / n, r == x % n,
- doc: Proof that if `x == q * r + n` and `0 <= r < n`, then `q == x / n`

## mod_auto_plus
- path: vstd/arithmetic/internals/mod_internals.rs:346  (spec fn)
- sig: `pub open spec fn mod_auto_plus(n: int) -> bool recommends n > 0,`
- doc: This function says that for any `x` and `y`, there are two

## mod_auto_minus
- path: vstd/arithmetic/internals/mod_internals.rs:362  (spec fn)
- sig: `pub open spec fn mod_auto_minus(n: int) -> bool recommends n > 0,`
- doc: This function says that for any `x` and `y`, there are two

## mod_auto
- path: vstd/arithmetic/internals/mod_internals.rs:376  (spec fn)
- sig: `pub open spec fn mod_auto(n: int) -> bool recommends n > 0,`
- doc: This function states various useful properties about the modulo

## lemma_mod_auto
- path: vstd/arithmetic/internals/mod_internals.rs:390  (proof fn)
- sig: `pub proof fn lemma_mod_auto(n: int)`
- requires: n > 0,
- ensures: mod_auto(n),
- doc: Proof of `mod_auto(n)`, which states various useful properties

## lemma_mod_induction_auto
- path: vstd/arithmetic/internals/mod_internals.rs:468  (proof fn)
- sig: `pub proof fn lemma_mod_induction_auto(n: int, x: int, f: spec_fn(int) -> bool)`
- requires: n > 0, mod_auto(n) ==> { &&& (forall|i: int| #[trigger] is_le(0, i) && i < n ==> f(i)) &&& (forall|i: int| #[trigger] is_le(0, i) && f(i) ==> f(i + n)) &&& (forall|i: int| #[trigger] is_le(i + 1, n) && f(i) ==> f(i - n))
- ensures: mod_auto(n), f(x),
- doc: This utility function helps prove a mathematical property by

## lemma_mod_induction_auto_forall
- path: vstd/arithmetic/internals/mod_internals.rs:515  (proof fn)
- sig: `pub proof fn lemma_mod_induction_auto_forall(n: int, f: spec_fn(int) -> bool)`
- requires: n > 0, mod_auto(n) ==> { &&& (forall|i: int| #[trigger] is_le(0, i) && i < n ==> f(i)) &&& (forall|i: int| #[trigger] is_le(0, i) && f(i) ==> f(i + n)) &&& (forall|i: int| #[trigger] is_le(i + 1, n) && f(i) ==> f(i - n))
- ensures: mod_auto(n), forall|i| #[trigger] f(i),
- doc: This utility function helps prove a mathematical property by

## modulus
- path: vstd/arithmetic/internals/mod_internals_nonlinear.rs:24  (spec fn)
- sig: `pub open spec fn modulus(x: int, y: int) -> int`
- doc: Computes `x % y`. This is useful where we want to trigger on a

## lemma_fundamental_div_mod
- path: vstd/arithmetic/internals/mod_internals_nonlinear.rs:41  (proof fn)
- sig: `pub proof fn lemma_fundamental_div_mod(x: int, d: int)`
- requires: d != 0,
- ensures: x == d * (x / d) + (x % d),
- doc: Proof of the fundamental theorem of division and modulo: That for

## lemma_small_mod
- path: vstd/arithmetic/internals/mod_internals_nonlinear.rs:59  (proof fn)
- sig: `pub proof fn lemma_small_mod(x: nat, m: nat)`
- requires: x < m, 0 < m,
- ensures: #[trigger] modulus(x as int, m as int) == x as int,
- doc: Proof that a natural number `x` divided by a larger natural number

## lemma_mod_range
- path: vstd/arithmetic/internals/mod_internals_nonlinear.rs:71  (proof fn)
- sig: `pub proof fn lemma_mod_range(x: int, m: int)`
- requires: m > 0,
- ensures: 0 <= #[trigger] modulus(x, m) < m,
- doc: Proof of Euclid's division lemma, i.e., that any integer `x`

## mul_pos
- path: vstd/arithmetic/internals/mul_internals.rs:30  (spec fn)
- sig: `pub open spec fn mul_pos(x: int, y: int) -> int recommends x >= 0,`
- doc: This function performs multiplication recursively. It's only valid

## mul_recursive
- path: vstd/arithmetic/internals/mul_internals.rs:43  (spec fn)
- sig: `pub open spec fn mul_recursive(x: int, y: int) -> int`
- doc: This function performs multiplication recursively.

## lemma_mul_induction
- path: vstd/arithmetic/internals/mul_internals.rs:67  (proof fn)
- sig: `pub proof fn lemma_mul_induction(f: spec_fn(int) -> bool)`
- requires: f(0), forall|i: int| i >= 0 && #[trigger] f(i) ==> #[trigger] f(add1(i, 1)), forall|i: int| i <= 0 && #[trigger] f(i) ==> #[trigger] f(sub1(i, 1)),
- ensures: forall|i: int| #[trigger] f(i),
- doc: This utility function helps prove a mathematical property by

## lemma_mul_commutes
- path: vstd/arithmetic/internals/mul_internals.rs:79  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_commutes(x: int, y: int)`
- ensures: #[trigger] (x * y) == y * x,
- doc: Proof that multiplication is always commutative

## lemma_mul_distributes_plus
- path: vstd/arithmetic/internals/mul_internals.rs:107  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_distributes_plus(x: int, y: int, z: int)`
- ensures: #[trigger] ((x + y) * z) == (x * z + y * z),
- doc: Proof that multiplication distributes over addition and over

## lemma_mul_distributes_minus
- path: vstd/arithmetic/internals/mul_internals.rs:127  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_distributes_minus(x: int, y: int, z: int)`
- ensures: #[trigger] ((x - y) * z) == (x * z - y * z),

## mul_auto
- path: vstd/arithmetic/internals/mul_internals.rs:148  (spec fn)
- sig: `pub open spec fn mul_auto() -> bool`
- doc: This function expresses that multiplication is commutative,

## group_mul_properties_internal
- path: vstd/arithmetic/internals/mul_internals.rs  (broadcast group)
- members: lemma_mul_commutes lemma_mul_distributes_plus lemma_mul_distributes_minus

## lemma_mul_induction_auto
- path: vstd/arithmetic/internals/mul_internals.rs:184  (proof fn)
- sig: `pub proof fn lemma_mul_induction_auto(x: int, f: spec_fn(int) -> bool)`
- requires: mul_auto() ==> { &&& f(0) &&& (forall|i| #[trigger] is_le(0, i) && f(i) ==> f(i + 1)) &&& (forall|i| #[trigger] is_le(i, 0) && f(i) ==> f(i - 1)) },
- ensures: mul_auto(), f(x),
- doc: This utility function helps prove a mathematical property by

## lemma_mul_induction_auto_forall
- path: vstd/arithmetic/internals/mul_internals.rs:216  (proof fn)
- sig: `pub proof fn lemma_mul_induction_auto_forall(f: spec_fn(int) -> bool)`
- requires: mul_auto() ==> { &&& f(0) &&& (forall|i| #[trigger] is_le(0, i) && f(i) ==> f(i + 1)) &&& (forall|i| #[trigger] is_le(i, 0) && f(i) ==> f(i - 1)) },
- ensures: mul_auto(), forall|i| #[trigger] f(i),
- doc: This utility function helps prove a mathematical property by

## lemma_mul_strictly_positive
- path: vstd/arithmetic/internals/mul_internals_nonlinear.rs:27  (proof fn)
- sig: `pub proof fn lemma_mul_strictly_positive(x: int, y: int)`
- ensures: (0 < x && 0 < y) ==> (0 < x * y),
- doc: Proof that multiplying two positive integers `x` and `y` will result in a positive integer

## lemma_mul_nonzero
- path: vstd/arithmetic/internals/mul_internals_nonlinear.rs:35  (proof fn)
- sig: `pub proof fn lemma_mul_nonzero(x: int, y: int)`
- ensures: x * y != 0 <==> x != 0 && y != 0,
- doc: Proof that `x` and `y` are both nonzero if and only if `x * y` is nonzero

## lemma_mul_is_associative
- path: vstd/arithmetic/internals/mul_internals_nonlinear.rs:45  (proof fn)
- sig: `pub proof fn lemma_mul_is_associative(x: int, y: int, z: int)`
- ensures: x * (y * z) == (x * y) * z,
- doc: Proof that multiplication is associative in this specific case,

## lemma_mul_is_distributive_add
- path: vstd/arithmetic/internals/mul_internals_nonlinear.rs:54  (proof fn)
- sig: `pub proof fn lemma_mul_is_distributive_add(x: int, y: int, z: int)`
- ensures: x * (y + z) == x * y + x * z,
- doc: Proof that multiplication distributes over addition in this

## lemma_mul_ordering
- path: vstd/arithmetic/internals/mul_internals_nonlinear.rs:64  (proof fn)
- sig: `pub proof fn lemma_mul_ordering(x: int, y: int)`
- requires: x != 0, y != 0, 0 <= x * y,
- ensures: x * y >= x && x * y >= y,
- doc: Proof that the if the product of two nonzero integers `x` and `y`

## lemma_mul_strict_inequality
- path: vstd/arithmetic/internals/mul_internals_nonlinear.rs:78  (proof fn)
- sig: `pub proof fn lemma_mul_strict_inequality(x: int, y: int, z: int)`
- requires: x < y, z > 0,
- ensures: x * z < y * z,
- doc: Proof that multiplying by a positive integer preserves inequality

## log
- path: vstd/arithmetic/logarithm.rs:38  (spec fn)
- sig: `pub open spec fn log(base: int, pow: int) -> int recommends base > 1, pow >= 0,`
- doc: This function recursively defines the integer logarithm. It's only

## lemma_log0
- path: vstd/arithmetic/logarithm.rs:56  (proof fn)
- sig: `pub proof fn lemma_log0(base: int, pow: int)`
- requires: base > 1, 0 <= pow < base,
- ensures: log(base, pow) == 0,
- doc: Proof that since `pow` is less than `base`, its logarithm in that base is 0.

## lemma_log_s
- path: vstd/arithmetic/logarithm.rs:69  (proof fn)
- sig: `pub broadcast proof fn lemma_log_s(base: int, pow: int)`
- requires: base > 1, pow >= base,
- ensures: #![trigger log(base, div1(pow, base))] pow / base >= 0, log(base, pow) == 1 + log(base, pow / base),
- doc: Proof that since `pow` is greater than or equal to `base`, its

## lemma_log_nonnegative
- path: vstd/arithmetic/logarithm.rs:85  (proof fn)
- sig: `pub proof fn lemma_log_nonnegative(base: int, pow: int)`
- requires: base > 1, 0 <= pow,
- ensures: log(base, pow) >= 0,
- doc: Proof that the integer logarithm is always nonnegative. Specifically,

## lemma_log_is_ordered
- path: vstd/arithmetic/logarithm.rs:102  (proof fn)
- sig: `pub proof fn lemma_log_is_ordered(base: int, pow1: int, pow2: int)`
- requires: base > 1, 0 <= pow1 <= pow2,
- ensures: log(base, pow1) <= log(base, pow2),
- doc: Proof that since `pow1` is less than or equal to `pow2`, the

## lemma_log_pow
- path: vstd/arithmetic/logarithm.rs:124  (proof fn)
- sig: `pub proof fn lemma_log_pow(base: int, n: nat)`
- requires: base > 1,
- ensures: log(base, pow(base, n)) == n,
- doc: Proof that the integer logarithm of `pow(base, n)` in base `base` is `n`.

## lemma_mul_is_mul_recursive
- path: vstd/arithmetic/mul.rs:25  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_is_mul_recursive(x: int, y: int)`
- ensures: #[trigger] (x * y) == mul_recursive(x, y),
- doc: Proof that multiplication using `*` is equivalent to

## lemma_mul_is_mul_pos
- path: vstd/arithmetic/mul.rs:43  (proof fn)
- sig: `pub proof fn lemma_mul_is_mul_pos(x: int, y: int)`
- requires: x >= 0,
- ensures: x * y == mul_pos(x, y),
- doc: Proof that multiplying two positive integers with `*` results in

## lemma_mul_basics
- path: vstd/arithmetic/mul.rs:53  (proof fn)
- sig: `pub proof fn lemma_mul_basics(x: int)`
- ensures: 0 * x == 0, x * 0 == 0, x * 1 == x, 1 * x == x,

## lemma_mul_basics_1
- path: vstd/arithmetic/mul.rs:64  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_basics_1(x: int)`
- ensures: #[trigger] (0 * x) == 0,
- doc: Proof of basic properties of multiplication by `x`, specifically

## lemma_mul_basics_2
- path: vstd/arithmetic/mul.rs:72  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_basics_2(x: int)`
- ensures: #[trigger] (x * 0) == 0,
- doc: Proof of basic properties of multiplication by `x`, specifically

## lemma_mul_basics_3
- path: vstd/arithmetic/mul.rs:80  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_basics_3(x: int)`
- ensures: #[trigger] (x * 1) == x,
- doc: Proof of basic properties of multiplication by `x`, specifically

## lemma_mul_basics_4
- path: vstd/arithmetic/mul.rs:88  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_basics_4(x: int)`
- ensures: #[trigger] (1 * x) == x,
- doc: Proof of basic properties of multiplication by `x`, specifically

## group_mul_basics
- path: vstd/arithmetic/mul.rs  (broadcast group)
- members: lemma_mul_basics_1 lemma_mul_basics_2 lemma_mul_basics_3 lemma_mul_basics_4

## lemma_mul_nonzero
- path: vstd/arithmetic/mul.rs:102  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_nonzero(x: int, y: int)`
- ensures: #[trigger] (x * y) != 0 <==> x != 0 && y != 0,
- doc: Proof that `x * y` is nonzero if and only if both `x` and `y` are nonzero.

## lemma_mul_by_zero_is_zero
- path: vstd/arithmetic/mul.rs:110  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_by_zero_is_zero(x: int)`
- ensures: #![trigger x * 0] #![trigger 0 * x] x * 0 == 0 && 0 * x == 0,
- doc: Proof that any integer multiplied by 0 results in a product of 0.

## lemma_mul_is_associative
- path: vstd/arithmetic/mul.rs:123  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_is_associative(x: int, y: int, z: int)`
- ensures: #![trigger x * (y * z)] #![trigger (x * y) * z] x * (y * z) == (x * y) * z,
- doc: Proof that multiplication is associative, specifically that

## lemma_mul_is_commutative
- path: vstd/arithmetic/mul.rs:134  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_is_commutative(x: int, y: int)`
- ensures: #[trigger] (x * y) == y * x,
- doc: Proof that multiplication is commutative, specifically that

## lemma_mul_ordering
- path: vstd/arithmetic/mul.rs:143  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_ordering(x: int, y: int)`
- requires: x != 0, y != 0, 0 <= x * y,
- ensures: #[trigger] (x * y) >= x && x * y >= y,
- doc: Proof that, since the product of the two integers `x` and `y` is

## lemma_mul_inequality
- path: vstd/arithmetic/mul.rs:164  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_inequality(x: int, y: int, z: int)`
- requires: x <= y, z >= 0,
- ensures: #[trigger] (x * z) <= #[trigger] (y * z),
- doc: Proof that, since `x <= y` and `z >= 0`, `x * z <= y * z`.

## lemma_mul_strict_inequality
- path: vstd/arithmetic/mul.rs:175  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_strict_inequality(x: int, y: int, z: int)`
- requires: x < y, z > 0,
- ensures: #[trigger] (x * z) < #[trigger] (y * z),
- doc: Proof that since `x < y` and `z > 0`, `x * z < y * z`.

## lemma_mul_upper_bound
- path: vstd/arithmetic/mul.rs:188  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_upper_bound(x: int, xbound: int, y: int, ybound: int)`
- requires: x <= xbound, y <= ybound, 0 <= x, 0 <= y,
- ensures: #[trigger] (x * y) <= #[trigger] (xbound * ybound),
- doc: Proof that since `x` is bounded above by `xbound` and `y` is

## lemma_mul_strict_upper_bound
- path: vstd/arithmetic/mul.rs:205  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_strict_upper_bound(x: int, xbound: int, y: int, ybound: int)`
- requires: x < xbound, y < ybound, 0 < x, 0 < y,
- ensures: #[trigger] (x * y) <= #[trigger] ((xbound - 1) * (ybound - 1)),
- doc: Proof that when `x` has an exclusive upper bound `xbound` and `y`

## lemma_mul_left_inequality
- path: vstd/arithmetic/mul.rs:221  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_left_inequality(x: int, y: int, z: int)`
- requires: 0 < x,
- ensures: y <= z ==> #[trigger] (x * y) <= #[trigger] (x * z), y < z ==> x * y < x * z,
- doc: Proof that multiplying the positive integer `x` by respectively

## lemma_mul_equality_converse
- path: vstd/arithmetic/mul.rs:234  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_equality_converse(m: int, x: int, y: int)`
- requires: m != 0, #[trigger] (m * x) == #[trigger] (m * y),
- ensures: x == y,
- doc: Proof that if `x` and `y` have equal results when multiplied by

## lemma_mul_inequality_converse
- path: vstd/arithmetic/mul.rs:248  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_inequality_converse(x: int, y: int, z: int)`
- requires: #[trigger] (x * z) <= #[trigger] (y * z), z > 0,
- ensures: x <= y,
- doc: Proof that since `x * z <= y * z` and `z > 0`, that `x <= y`.

## lemma_mul_strict_inequality_converse
- path: vstd/arithmetic/mul.rs:259  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_strict_inequality_converse(x: int, y: int, z: int)`
- requires: #[trigger] (x * z) < #[trigger] (y * z), z >= 0,
- ensures: x < y,
- doc: Proof that since `x * z < y * z` and `z >= 0`, we know `x < y`.

## lemma_mul_is_distributive_add
- path: vstd/arithmetic/mul.rs:271  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_is_distributive_add(x: int, y: int, z: int)`
- ensures: #[trigger] (x * (y + z)) == x * y + x * z,
- doc: Proof that multiplication distributes over addition, specifically that

## lemma_mul_is_distributive_add_other_way
- path: vstd/arithmetic/mul.rs:280  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_is_distributive_add_other_way(x: int, y: int, z: int)`
- ensures: #[trigger] ((y + z) * x) == y * x + z * x,
- doc: Proof that multiplication distributes over addition, specifically that

## lemma_mul_is_distributive_sub
- path: vstd/arithmetic/mul.rs:290  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_is_distributive_sub(x: int, y: int, z: int)`
- ensures: #[trigger] (x * (y - z)) == x * y - x * z,
- doc: Proof that multiplication distributes over subtraction, specifically that

## lemma_mul_is_distributive_sub_other_way
- path: vstd/arithmetic/mul.rs:301  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_is_distributive_sub_other_way(x: int, y: int, z: int)`
- ensures: #[trigger] ((y - z) * x) == y * x - z * x,
- doc: Proof that multiplication distributes over subtraction when the

## group_mul_is_distributive
- path: vstd/arithmetic/mul.rs  (broadcast group)
- members: lemma_mul_is_distributive_add lemma_mul_is_distributive_add_other_way lemma_mul_is_distributive_sub lemma_mul_is_distributive_sub_other_way

## group_mul_is_commutative_and_distributive
- path: vstd/arithmetic/mul.rs  (broadcast group)
- members: lemma_mul_is_commutative group_mul_is_distributive

## lemma_mul_strictly_positive
- path: vstd/arithmetic/mul.rs:358  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_strictly_positive(x: int, y: int)`
- ensures: (0 < x && 0 < y) ==> (0 < #[trigger] (x * y)),
- doc: Proof that if `x` and `y` are both positive, then their product is

## lemma_mul_strictly_increases
- path: vstd/arithmetic/mul.rs:366  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_strictly_increases(x: int, y: int)`
- requires: 1 < x, 0 < y,
- ensures: y < #[trigger] (x * y),
- doc: Proof that since `x > 1` and `y > 0`, `y < x * y`.

## lemma_mul_increases
- path: vstd/arithmetic/mul.rs:378  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_increases(x: int, y: int)`
- requires: 0 < x, 0 < y,
- ensures: y <= #[trigger] (x * y),
- doc: Proof that since `x` and `y` are both positive, their product is

## lemma_mul_nonnegative
- path: vstd/arithmetic/mul.rs:390  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_nonnegative(x: int, y: int)`
- requires: 0 <= x, 0 <= y,
- ensures: 0 <= #[trigger] (x * y),
- doc: Proof that since `x` and `y` are non-negative, their product is

## lemma_mul_unary_negation
- path: vstd/arithmetic/mul.rs:402  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_unary_negation(x: int, y: int)`
- ensures: #![trigger (-x) * y] #![trigger x * (-y)] (-x) * y == -(x * y) == x * (-y),
- doc: Proof that negating `x` or `y` before multiplying them together

## lemma_mul_cancels_negatives
- path: vstd/arithmetic/mul.rs:413  (proof fn)
- sig: `pub broadcast proof fn lemma_mul_cancels_negatives(x: int, y: int)`
- ensures: #[trigger] (x * y) == (-x) * (-y),
- doc: Proof that multiplying `-x` and `-y` produces the same product as

## group_mul_properties
- path: vstd/arithmetic/mul.rs  (broadcast group)
- members: group_mul_basics lemma_mul_strict_inequality lemma_mul_inequality group_mul_is_commutative_and_distributive lemma_mul_is_associative lemma_mul_ordering lemma_mul_nonzero lemma_mul_nonnegative lemma_mul_strictly_increases lemma_mul_increases

## spec_new
- path: vstd/arithmetic/overflow.rs:111  (spec fn)
- sig: `pub closed spec fn spec_new(v: $uty) -> $cty`
- doc: Creates a new `$cty` instance from a `$uty` value.

## new
- path: vstd/arithmetic/overflow.rs:119  (fn)
- sig: `pub exec fn new(v: $uty) -> (result: Self)`
- ensures: result@ == v,
- doc: Creates a new `$cty` instance from a `$uty` value.

## new_overflowed
- path: vstd/arithmetic/overflow.rs:129  (fn)
- sig: `pub exec fn new_overflowed(Ghost(i): Ghost<int>) -> (result: Self)`
- requires: i > $uty::MAX,
- ensures: result@ == i,
- doc: Creates a new `$cty` instance with an overflowed value.

## spec_is_overflowed
- path: vstd/arithmetic/overflow.rs:140  (spec fn)
- sig: `pub open spec fn spec_is_overflowed(&self) -> bool`
- doc: Checks if the `$cty` instance is overflowed.

## is_overflowed
- path: vstd/arithmetic/overflow.rs:148  (fn)
- sig: `pub exec fn is_overflowed(&self) -> (result: bool)`
- ensures: result == self.spec_is_overflowed()
- doc: Checks if the `$cty` instance is overflowed.

## unwrap
- path: vstd/arithmetic/overflow.rs:159  (fn)
- sig: `pub exec fn unwrap(&self) -> (result: $uty)`
- requires: !self.is_overflowed(),
- ensures: result == self@,
- doc: Unwraps the `$cty` instance to get the `$uty` value.

## to_option
- path: vstd/arithmetic/overflow.rs:171  (fn)
- sig: `pub exec fn to_option(&self) -> (result: Option<$uty>)`
- ensures: match result { Some(v) => self@ == v && v <= $uty::MAX, None => self@ > $uty::MAX, }
- doc: Converts the `$cty` instance to an `Option<$uty>`.

## add_value
- path: vstd/arithmetic/overflow.rs:187  (fn)
- sig: `pub exec fn add_value(&self, v2: $uty) -> (result: Self)`
- ensures: result@ == self@ + v2,
- doc: Adds a `$uty` value to the `$cty` instance.

## add_checked
- path: vstd/arithmetic/overflow.rs:206  (fn)
- sig: `pub exec fn add_checked(&self, v2: &$cty) -> (result: Self)`
- ensures: result@ == self@ + v2@,
- doc: Adds another `$cty` instance to the current

## mul_value
- path: vstd/arithmetic/overflow.rs:228  (fn)
- sig: `pub exec fn mul_value(&self, v2: $uty) -> (result: Self)`
- ensures: result@ == self@ as int * v2 as int,
- doc: Multiplies the `$cty` instance by a `$uty`

## mul_checked
- path: vstd/arithmetic/overflow.rs:260  (fn)
- sig: `pub exec fn mul_checked(&self, v2: &Self) -> (result: Self)`
- ensures: result@ == self@ as int * v2@ as int,
- doc: Multiplies the `$cty` instance by another `$cty` instance.

## pow
- path: vstd/arithmetic/power.rs:43  (spec fn)
- sig: `pub open spec fn pow(b: int, e: nat) -> int`
- doc: This function performs exponentiation recursively, to compute `b`

## lemma_pow0
- path: vstd/arithmetic/power.rs:54  (proof fn)
- sig: `pub broadcast proof fn lemma_pow0(b: int)`
- ensures: #[trigger] pow(b, 0) == 1,
- doc: Proof that the given integer `b` to the power of 0 is 1.

## lemma_pow1
- path: vstd/arithmetic/power.rs:62  (proof fn)
- sig: `pub broadcast proof fn lemma_pow1(b: int)`
- ensures: #[trigger] pow(b, 1) == b,
- doc: Proof that the given integer `b` to the power of 1 is `b`.

## lemma0_pow
- path: vstd/arithmetic/power.rs:83  (proof fn)
- sig: `pub broadcast proof fn lemma0_pow(e: nat)`
- requires: e > 0,
- ensures: #[trigger] pow(0, e) == 0,
- doc: Proof that 0 to the power of the given positive integer `e` is 0.

## lemma1_pow
- path: vstd/arithmetic/power.rs:99  (proof fn)
- sig: `pub broadcast proof fn lemma1_pow(e: nat)`
- ensures: #[trigger] pow(1, e) == 1,
- doc: Proof that 1 to the power of the given natural number `e` is 1.

## lemma_square_is_pow2
- path: vstd/arithmetic/power.rs:113  (proof fn)
- sig: `pub broadcast proof fn lemma_square_is_pow2(x: int)`
- ensures: #[trigger] pow(x, 2) == x * x,
- doc: Proof that taking the given number `x` to the power of 2 produces `x * x`.

## lemma_pow_positive
- path: vstd/arithmetic/power.rs:122  (proof fn)
- sig: `pub broadcast proof fn lemma_pow_positive(b: int, e: nat)`
- requires: b > 0,
- ensures: 0 < #[trigger] pow(b, e),
- doc: Proof that taking the given positive integer `b` to the power of

## lemma_pow_adds
- path: vstd/arithmetic/power.rs:138  (proof fn)
- sig: `pub broadcast proof fn lemma_pow_adds(b: int, e1: nat, e2: nat)`
- ensures: #[trigger] pow(b, e1 + e2) == pow(b, e1) * pow(b, e2),
- doc: Proof that taking an integer `b` to the power of the sum of two

## lemma_pow_sub_add_cancel
- path: vstd/arithmetic/power.rs:179  (proof fn)
- sig: `pub broadcast proof fn lemma_pow_sub_add_cancel(b: int, e1: nat, e2: nat)`
- requires: e1 >= e2,
- ensures: #[trigger] pow(b, (e1 - e2) as nat) * pow(b, e2) == pow(b, e1),
- doc: Proof that if `e1 >= e2`, then `b` to the power of `e1` is equal

## lemma_pow_subtracts
- path: vstd/arithmetic/power.rs:192  (proof fn)
- sig: `pub broadcast proof fn lemma_pow_subtracts(b: int, e1: nat, e2: nat)`
- requires: b > 0, e1 <= e2,
- ensures: pow(b, e1) > 0, #[trigger] pow(b, (e2 - e1) as nat) == pow(b, e2) / pow(b, e1) > 0,
- doc: Proof that, as long as `e1 <= e2`, taking a positive integer `b`

## lemma_pow_multiplies
- path: vstd/arithmetic/power.rs:217  (proof fn)
- sig: `pub broadcast proof fn lemma_pow_multiplies(a: int, b: nat, c: nat)`
- ensures: 0 <= b * c, #[trigger] pow(pow(a, b), c) == pow(a, b * c),
- doc: Proof that `a` to the power of `b * c` is equal to the result of

## lemma_pow_distributes
- path: vstd/arithmetic/power.rs:272  (proof fn)
- sig: `pub broadcast proof fn lemma_pow_distributes(a: int, b: int, e: nat)`
- ensures: #[trigger] pow(a * b, e) == pow(a, e) * pow(b, e),
- doc: Proof that `a * b` to the power of `e` is equal to the product of

## group_pow_properties
- path: vstd/arithmetic/power.rs  (broadcast group)
- members: lemma_pow0 lemma_pow1 lemma_pow_distributes lemma_pow_adds lemma_pow_sub_add_cancel group_mul_properties_internal lemma_mul_increases lemma_mul_strictly_increases

## lemma_pow_strictly_increases
- path: vstd/arithmetic/power.rs:339  (proof fn)
- sig: `pub broadcast proof fn lemma_pow_strictly_increases(b: nat, e1: nat, e2: nat)`
- requires: 1 < b, e1 < e2,
- ensures: #[trigger] pow(b as int, e1) < #[trigger] pow(b as int, e2),
- doc: Proof that a number greater than 1 raised to a power strictly

## lemma_pow_increases
- path: vstd/arithmetic/power.rs:384  (proof fn)
- sig: `pub broadcast proof fn lemma_pow_increases(b: nat, e1: nat, e2: nat)`
- requires: b > 0, e1 <= e2,
- ensures: #[trigger] pow(b as int, e1) <= #[trigger] pow(b as int, e2),
- doc: Proof that a positive number raised to a power increases as the

## lemma_pow_strictly_increases_converse
- path: vstd/arithmetic/power.rs:404  (proof fn)
- sig: `pub broadcast proof fn lemma_pow_strictly_increases_converse(b: nat, e1: nat, e2: nat)`
- requires: b > 0, #[trigger] pow(b as int, e1) < #[trigger] pow(b as int, e2),
- ensures: e1 < e2,
- doc: Proof that if an exponentiation result strictly increases when the

## lemma_pow_increases_converse
- path: vstd/arithmetic/power.rs:421  (proof fn)
- sig: `pub broadcast proof fn lemma_pow_increases_converse(b: nat, e1: nat, e2: nat)`
- requires: 1 < b, #[trigger] pow(b as int, e1) <= #[trigger] pow(b as int, e2),
- ensures: e1 <= e2,
- doc: Proof that if the exponentiation of a number greater than 1

## lemma_pull_out_pows
- path: vstd/arithmetic/power.rs:436  (proof fn)
- sig: `pub broadcast proof fn lemma_pull_out_pows(b: nat, x: nat, y: nat, z: nat)`
- requires: b > 0,
- ensures: 0 <= x * y, 0 <= y * z, #[trigger] pow(pow(b as int, x * y), z) == pow(pow(b as int, x), y * z),
- doc: Proof that `(b^(xy))^z = (b^x)^(yz)`, given that `x * y` and `y *

## lemma_pow_division_inequality
- path: vstd/arithmetic/power.rs:461  (proof fn)
- sig: `pub proof fn lemma_pow_division_inequality(x: nat, b: nat, e1: nat, e2: nat)`
- requires: b > 0, e2 <= e1, x < pow(b as int, e1),
- ensures: pow(b as int, e2) > 0, // also somewhat annoying that division operator needs explicit type casting // because the divisor and dividend need to have the same type #[trigger] (x as int / pow(b as int, e2)) < #[trigger] pow(b as int, (e1 - e2) as nat),
- doc: Proof that if `e2 <= e1` and `x < pow(b, e1)`, then dividing `x`

## lemma_pow_mod
- path: vstd/arithmetic/power.rs:490  (proof fn)
- sig: `pub broadcast proof fn lemma_pow_mod(b: nat, e: nat)`
- requires: b > 0, e > 0,
- ensures: #[trigger] pow(b as int, e) % b as int == 0,
- doc: Proof that `pow(b, e)` modulo `b` is 0.

## lemma_pow_mod_noop
- path: vstd/arithmetic/power.rs:528  (proof fn)
- sig: `pub broadcast proof fn lemma_pow_mod_noop(b: int, e: nat, m: int)`
- requires: m > 0,
- ensures: #[trigger] pow(b % m, e) % m == pow(b, e) % m,
- doc: Proof that exponentiation then modulo produces the same result as

## pow2
- path: vstd/arithmetic/power2.rs:32  (spec fn)
- sig: `pub open spec fn pow2(e: nat) -> nat`
- doc: This function computes 2 to the power of the given natural number `e`.

## is_pow2
- path: vstd/arithmetic/power2.rs:38  (spec fn)
- sig: `pub open spec fn is_pow2(n: int) -> bool`
- doc: Returns true if the given integer is a power of 2 (defined recursively).

## is_pow2_exists
- path: vstd/arithmetic/power2.rs:52  (spec fn)
- sig: `pub open spec fn is_pow2_exists(n: int) -> bool`
- doc: Returns true if the given integer is a power of 2

## is_pow2_equiv
- path: vstd/arithmetic/power2.rs:57  (proof fn)
- sig: `pub broadcast proof fn is_pow2_equiv(n: int)`
- ensures: #![trigger is_pow2(n)] #![trigger is_pow2_exists(n)] is_pow2(n) <==> is_pow2_exists(n),
- doc: Proof that the recursive and existential specifications for `is_pow2` are equivalent.

## lemma_pow2_pos
- path: vstd/arithmetic/power2.rs:122  (proof fn)
- sig: `pub broadcast proof fn lemma_pow2_pos(e: nat)`
- ensures: #[trigger] pow2(e) > 0,
- doc: Proof that 2 to the power of any natural number (specifically,

## lemma_pow2
- path: vstd/arithmetic/power2.rs:130  (proof fn)
- sig: `pub broadcast proof fn lemma_pow2(e: nat)`
- ensures: #[trigger] pow2(e) == pow(2, e) as int,
- doc: Proof that `pow2(e)` is equivalent to `pow(2, e)`.

## lemma_pow2_unfold
- path: vstd/arithmetic/power2.rs:142  (proof fn)
- sig: `pub broadcast proof fn lemma_pow2_unfold(e: nat)`
- requires: e > 0,
- ensures: #[trigger] pow2(e) == 2 * pow2((e - 1) as nat),
- doc: Proof relating 2^e to 2^(e-1).

## lemma_pow2_adds
- path: vstd/arithmetic/power2.rs:154  (proof fn)
- sig: `pub broadcast proof fn lemma_pow2_adds(e1: nat, e2: nat)`
- ensures: #[trigger] pow2(e1 + e2) == pow2(e1) * pow2(e2),
- doc: Proof that `2^(e1 + e2)` is equivalent to `2^e1 * 2^e2`.

## lemma_pow2_subtracts
- path: vstd/arithmetic/power2.rs:165  (proof fn)
- sig: `pub broadcast proof fn lemma_pow2_subtracts(e1: nat, e2: nat)`
- requires: e1 <= e2,
- ensures: #[trigger] pow2((e2 - e1) as nat) == pow2(e2) / pow2(e1) > 0,
- doc: Proof that, as long as `e1 <= e2`, `2^(e2 - e1)` is equivalent to `2^e2 / 2^e1`.

## lemma_pow2_strictly_increases
- path: vstd/arithmetic/power2.rs:178  (proof fn)
- sig: `pub broadcast proof fn lemma_pow2_strictly_increases(e1: nat, e2: nat)`
- requires: e1 < e2,
- ensures: #[trigger] pow2(e1) < #[trigger] pow2(e2),
- doc: Proof that if `e1 < e2` then `2^e1 < 2^e2`.

## array_view
- path: vstd/array.rs:11  (spec fn)
- sig: `pub open spec fn array_view<T, const N: usize>(a: [T; N]) -> Seq<T>`

## lemma_array_index
- path: vstd/array.rs:53  (proof fn)
- sig: `pub broadcast proof fn lemma_array_index<T, const N: usize>(a: [T; N], i: int)`
- requires: 0 <= i < N,
- ensures: #![trigger array_index(a, i)] a[i] == array_view(a)[i],

## array_index_get
- path: vstd/array.rs:76  (fn)
- sig: `pub exec fn array_index_get<T, const N: usize>(ar: &[T; N], i: usize) -> (out: &T)`
- requires: 0 <= i < N,
- ensures: *out == ar@.index(i as int),

## spec_array_as_slice
- path: vstd/array.rs:90  (spec fn)
- sig: `pub uninterp spec fn spec_array_as_slice<T, const N: usize>(ar: &[T; N]) -> (out: &[T])`

## spec_array_iter
- path: vstd/array.rs:103  (spec fn)
- sig: `pub uninterp spec fn spec_array_iter<T, const N: usize>(s: &[T; N]) -> (iter: core::slice::Iter< '_, T, >)`

## axiom_spec_array_iter
- path: vstd/array.rs:108  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_array_iter<T, const N: usize>(s: &[T; N])`
- ensures: #[trigger] spec_array_iter(s).remaining() == s@.as_ref(),

## array_as_slice
- path: vstd/array.rs:135  (fn)
- sig: `pub fn array_as_slice<T, const N: usize>(ar: &[T; N]) -> (out: &[T])`
- ensures: out == spec_array_as_slice(ar), ar@ == out@,

## <[T;N
- path: vstd/array.rs:143  (exec spec, assume_specification)
- sig: `pub assume_specification<T, const N: usize>[ <[T; N]>::as_slice ](ar: &[T; N]) -> (out: &[T])`
- ensures: ar@ == out@,

## spec_array_fill_for_copy_type
- path: vstd/array.rs:148  (spec fn)
- sig: `pub uninterp spec fn spec_array_fill_for_copy_type<T: Copy, const N: usize>(t: T) -> (res: [T; N])`

## array_fill_for_copy_types
- path: vstd/array.rs:164  (fn)
- sig: `pub fn array_fill_for_copy_types<T: Copy, const N: usize>(t: T) -> (res: [T; N])`
- ensures: res == spec_array_fill_for_copy_type::<T, N>(t),

## spec_array_update
- path: vstd/array.rs:178  (spec fn)
- sig: `pub uninterp spec fn spec_array_update<T, const N: usize>(array: [T; N], i: int, t: T) -> [T; N]`

## ref_mut_array_unsizing_coercion
- path: vstd/array.rs:195  (fn)
- sig: `pub fn ref_mut_array_unsizing_coercion<T, const N: usize>(r: &mut [T; N]) -> (out: &mut [T])`
- ensures: out.view() == old(r).view(), final(out).view() == final(r).view(),

## group_array_axioms
- path: vstd/array.rs  (broadcast group)
- members: array_len_matches_n lemma_array_index axiom_spec_array_as_slice axiom_spec_array_fill_for_copy_type axiom_array_ext_equal axiom_spec_array_iter axiom_spec_array_update axiom_array_has_resolved

## view
- path: vstd/atomic.rs:72  (spec fn)
- sig: `pub uninterp spec fn view(self) -> $p_data_ident`

## is_for
- path: vstd/atomic.rs:74  (spec fn)
- sig: `pub open spec fn is_for(&self, patomic: $at_ident) -> bool`

## points_to
- path: vstd/atomic.rs:78  (spec fn)
- sig: `pub open spec fn points_to(&self, v: $value_ty) -> bool`

## value
- path: vstd/atomic.rs:83  (spec fn)
- sig: `pub open spec fn value(&self) -> $value_ty`

## id
- path: vstd/atomic.rs:88  (spec fn)
- sig: `pub open spec fn id(&self) -> AtomicCellId`

## view
- path: vstd/atomic.rs:122  (spec fn)
- sig: `pub uninterp spec fn view(self) -> $p_data_ident <T>`

## is_for
- path: vstd/atomic.rs:124  (spec fn)
- sig: `pub open spec fn is_for(&self, patomic: $at_ident <T>) -> bool`

## points_to
- path: vstd/atomic.rs:128  (spec fn)
- sig: `pub open spec fn points_to(&self, v: $value_ty) -> bool`

## value
- path: vstd/atomic.rs:133  (spec fn)
- sig: `pub open spec fn value(&self) -> $value_ty`

## id
- path: vstd/atomic.rs:138  (spec fn)
- sig: `pub open spec fn id(&self) -> AtomicCellId`

## id
- path: vstd/atomic.rs:153  (spec fn)
- sig: `pub uninterp spec fn id(&self) -> int`

## load
- path: vstd/atomic.rs:168  (fn)
- sig: `pub fn load(&self, Tracked(perm): Tracked<&$p_ident>) -> (ret: $value_ty)`
- requires: equal(self.id(), perm.view().patomic),
- ensures: equal(perm.view().value, ret),

## store
- path: vstd/atomic.rs:181  (fn)
- sig: `pub fn store(&self, Tracked(perm): Tracked<&mut $p_ident>, v: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(final(perm).view().value, v) && equal(self.id(), final(perm).view().patomic),

## compare_exchange
- path: vstd/atomic.rs:194  (fn)
- sig: `pub fn compare_exchange(&self, Tracked(perm): Tracked<&mut $p_ident>, current: $value_ty, new: $value_ty) -> (ret: Result<$value_ty, $value_ty>)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(self.id(), final(perm).view().patomic) && match ret { Result::Ok(r) => current $($addr)* == old(perm).view().value $($addr)* && equal(final(perm).view().value, new)

## compare_exchange_weak
- path: vstd/atomic.rs:218  (fn)
- sig: `pub fn compare_exchange_weak(&self, Tracked(perm): Tracked<&mut $p_ident>, current: $value_ty, new: $value_ty) -> (ret: Result<$value_ty, $value_ty>)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(self.id(), final(perm).view().patomic) && match ret { Result::Ok(r) => current $($addr)* == old(perm).view().value $($addr)* && equal(final(perm).view().value, new)

## swap
- path: vstd/atomic.rs:241  (fn)
- sig: `pub fn swap(&self, Tracked(perm): Tracked<&mut $p_ident>, v: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(final(perm).view().value, v) && equal(old(perm).view().value, ret) && equal(self.id(), final(perm).view().patomic),

## into_inner
- path: vstd/atomic.rs:256  (fn)
- sig: `pub fn into_inner(self, Tracked(perm): Tracked<$p_ident>) -> (ret: $value_ty)`
- requires: equal(self.id(), perm.view().patomic),
- ensures: equal(perm.view().value, ret),

## fetch_add_wrapping
- path: vstd/atomic.rs:280  (fn)
- sig: `pub fn fetch_add_wrapping(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value as int == $modname::wrapping_add(old(perm).view().value, n),

## fetch_sub_wrapping
- path: vstd/atomic.rs:295  (fn)
- sig: `pub fn fetch_sub_wrapping(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value as int == $modname::wrapping_sub(old(perm).view().value, n),

## fetch_add
- path: vstd/atomic.rs:312  (fn)
- sig: `pub fn fetch_add(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic), (<$value_ty>::MIN as int) <= old(perm).view().value + n, old(perm).view().value + n <= (<$value_ty>::MAX as int),
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value == old(perm).view().value + n,

## fetch_sub
- path: vstd/atomic.rs:329  (fn)
- sig: `pub fn fetch_sub(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic), (<$value_ty>::MIN as int) <= old(perm).view().value - n, old(perm).view().value - n <= <$value_ty>::MAX as int,
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value == old(perm).view().value - n,

## fetch_and
- path: vstd/atomic.rs:347  (fn)
- sig: `pub fn fetch_and(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value == (old(perm).view().value & n),

## fetch_or
- path: vstd/atomic.rs:362  (fn)
- sig: `pub fn fetch_or(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value == (old(perm).view().value | n),

## fetch_xor
- path: vstd/atomic.rs:377  (fn)
- sig: `pub fn fetch_xor(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value == (old(perm).view().value ^ n),

## fetch_nand
- path: vstd/atomic.rs:392  (fn)
- sig: `pub fn fetch_nand(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value == !(old(perm).view().value & n),

## fetch_max
- path: vstd/atomic.rs:407  (fn)
- sig: `pub fn fetch_max(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value == (if old(perm).view().value > n { old(perm).view().value } else { n }),

## fetch_min
- path: vstd/atomic.rs:422  (fn)
- sig: `pub fn fetch_min(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value == (if old(perm).view().value < n { old(perm).view().value } else { n }),

## fetch_and
- path: vstd/atomic.rs:445  (fn)
- sig: `pub fn fetch_and(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret) && final(perm).view().patomic == old(perm).view().patomic && final(perm).view().value == (old(perm).view().value && n),

## fetch_or
- path: vstd/atomic.rs:461  (fn)
- sig: `pub fn fetch_or(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret) && final(perm).view().patomic == old(perm).view().patomic && final(perm).view().value == (old(perm).view().value || n),

## fetch_xor
- path: vstd/atomic.rs:477  (fn)
- sig: `pub fn fetch_xor(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret) && final(perm).view().patomic == old(perm).view().patomic && final(perm).view().value == ((old(perm).view().value && !n) || (!old(perm).view().value && n)),

## fetch_nand
- path: vstd/atomic.rs:493  (fn)
- sig: `pub fn fetch_nand(&self, Tracked(perm): Tracked<&mut $p_ident>, n: $value_ty) -> (ret: $value_ty)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret) && final(perm).view().patomic == old(perm).view().patomic && final(perm).view().value == !(old(perm).view().value && n),

## AtomicUpdate::pred
- path: vstd/atomic.rs:661  (spec fn)
- sig: `pub uninterp spec fn pred(self) -> Pred`
- doc: The predicate of the atomic update.

## AtomicUpdate::resolves
- path: vstd/atomic.rs:670  (spec fn)
- sig: `pub uninterp spec fn resolves(self) -> bool`
- doc: A prophesy variable which indicates that an atomic update has been resolved.

## AtomicUpdate::input
- path: vstd/atomic.rs:677  (spec fn)
- sig: `pub uninterp spec fn input(self) -> X`
- doc: A prophesy variable for the input value of the atomic update.

## AtomicUpdate::output
- path: vstd/atomic.rs:684  (spec fn)
- sig: `pub uninterp spec fn output(self) -> Y`
- doc: A prophesy variable for the output value of the atomic update.

## AtomicUpdate::req
- path: vstd/atomic.rs:689  (spec fn)
- sig: `pub open spec fn req(self, x: X) -> bool`

## AtomicUpdate::ens
- path: vstd/atomic.rs:694  (spec fn)
- sig: `pub open spec fn ens(self, x: X, y: Y) -> bool`

## AtomicUpdate::outer_mask
- path: vstd/atomic.rs:699  (spec fn)
- sig: `pub open spec fn outer_mask(self) -> ISet<int>`

## AtomicUpdate::inner_mask
- path: vstd/atomic.rs:704  (spec fn)
- sig: `pub open spec fn inner_mask(self) -> ISet<int>`

## pred_args
- path: vstd/atomic.rs:712  (spec fn)
- sig: `pub uninterp spec fn pred_args<Pred, Args>(pred: Pred) -> Args`

## UpdateControlFlow::is_commit
- path: vstd/atomic.rs:778  (spec fn)
- sig: `pub open spec fn is_commit(self) -> bool`

## UpdateControlFlow::is_abort
- path: vstd/atomic.rs:785  (spec fn)
- sig: `pub open spec fn is_abort(self) -> bool`

## branch_bool
- path: vstd/atomic.rs:842  (spec fn)
- sig: `pub open spec fn branch_bool<T: UpdateTry>(this: T) -> bool`

## atomically
- path: vstd/atomic.rs:851  (fn)
- sig: `pub fn atomically<X, Y: UpdateTry, P: UpdatePredicate<X, Y>>( _body: impl FnOnce(fn (X) -> Y, Ghost<AtomicUpdate<X, Y, P>>),`

## bind_lifetime_internal
- path: vstd/atomic.rs:866  (fn)
- sig: `pub fn bind_lifetime_internal<'a, X: 'a, Y, P>( _block_guard: &'a BlockGuard<AtomicUpdate<X, Y, P>>,`

## try_open_atomic_update_begin
- path: vstd/atomic.rs:876  (fn)
- sig: `pub fn try_open_atomic_update_begin<X, Y: UpdateTry, P: UpdatePredicate<X, Y>>( _atomic_update: AtomicUpdate<X, Y, P>,`

## try_open_atomic_update_end
- path: vstd/atomic.rs:886  (fn)
- sig: `pub fn try_open_atomic_update_end<X, Y: UpdateTry, P: UpdatePredicate<X, Y>>( _guard: BlockGuard<AtomicUpdate<X, Y, P>>, _y: Tracked<Y>,`

## PAtomicPtr::fetch_and
- path: vstd/atomic.rs:1049  (fn)
- sig: `pub fn fetch_and(&self, Tracked(perm): Tracked<&mut PermissionPtr<T>>, n: usize) -> (ret: *mut T)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value@.addr == (old(perm).view().value@.addr & n), final(perm).view().value@.provenance == old(perm).view().value@.provenance, final(perm).view().value@.metadata == old(perm).view().value@.metadata,

## PAtomicPtr::fetch_xor
- path: vstd/atomic.rs:1069  (fn)
- sig: `pub fn fetch_xor(&self, Tracked(perm): Tracked<&mut PermissionPtr<T>>, n: usize) -> (ret: *mut T)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value@.addr == (old(perm).view().value@.addr ^ n), final(perm).view().value@.provenance == old(perm).view().value@.provenance, final(perm).view().value@.metadata == old(perm).view().value@.metadata,

## PAtomicPtr::fetch_or
- path: vstd/atomic.rs:1089  (fn)
- sig: `pub fn fetch_or(&self, Tracked(perm): Tracked<&mut PermissionPtr<T>>, n: usize) -> (ret: *mut T)`
- requires: equal(self.id(), old(perm).view().patomic),
- ensures: equal(old(perm).view().value, ret), final(perm).view().patomic == old(perm).view().patomic, final(perm).view().value@.addr == (old(perm).view().value@.addr | n), final(perm).view().value@.provenance == old(perm).view().value@.provenance, final(perm).view().value@.metadata == old(perm).view().value@.metadata,

## constant
- path: vstd/atomic_ghost.rs:54  (spec fn)
- sig: `pub open spec fn constant(&self) -> K`

## well_formed
- path: vstd/atomic_ghost.rs:58  (spec fn)
- sig: `pub open spec fn well_formed(&self) -> bool`

## load
- path: vstd/atomic_ghost.rs:87  (fn)
- sig: `pub fn load(&self) -> $value_ty`
- requires: self.well_formed(),

## into_inner
- path: vstd/atomic_ghost.rs:94  (fn)
- sig: `pub fn into_inner(self) -> (res: ($value_ty, Tracked<G>))`
- requires: self.well_formed(),
- ensures: Pred::atomic_inv(self.constant(), res.0, res.1@),

## well_formed
- path: vstd/atomic_ghost.rs:147  (spec fn)
- sig: `pub open spec fn well_formed(&self) -> bool`

## constant
- path: vstd/atomic_ghost.rs:151  (spec fn)
- sig: `pub open spec fn constant(&self) -> K`

## load
- path: vstd/atomic_ghost.rs:174  (fn)
- sig: `pub fn load(&self) -> $value_ty`
- requires: self.well_formed(),

## into_inner
- path: vstd/atomic_ghost.rs:181  (fn)
- sig: `pub fn into_inner(self) -> (res: ($value_ty, Tracked<G>))`
- requires: self.well_formed(),
- ensures: Pred::atomic_inv(self.constant(), res.0, res.1@),

## low_bits_mask
- path: vstd/bits.rs:254  (spec fn)
- sig: `pub open spec fn low_bits_mask(n: nat) -> nat`
- doc: Mask with low n bits set.

## lemma_low_bits_mask_unfold
- path: vstd/bits.rs:259  (proof fn)
- sig: `pub broadcast proof fn lemma_low_bits_mask_unfold(n: nat)`
- requires: n > 0,
- ensures: #[trigger] low_bits_mask(n) == 2 * low_bits_mask((n - 1) as nat) + 1,
- doc: Proof relating the n-bit mask to a function of the (n-1)-bit mask.

## lemma_low_bits_mask_is_odd
- path: vstd/bits.rs:280  (proof fn)
- sig: `pub broadcast proof fn lemma_low_bits_mask_is_odd(n: nat)`
- requires: n > 0,
- ensures: #[trigger] (low_bits_mask(n) % 2) == 1,
- doc: Proof that low_bits_mask(n) is odd.

## lemma_low_bits_mask_div2
- path: vstd/bits.rs:299  (proof fn)
- sig: `pub broadcast proof fn lemma_low_bits_mask_div2(n: nat)`
- requires: n > 0,
- ensures: #[trigger] (low_bits_mask(n) / 2) == low_bits_mask((n - 1) as nat),
- doc: Proof that dividing the low n bit mask by 2 gives the low n-1 bit mask.

## lemma_low_bits_mask_values
- path: vstd/bits.rs:310  (proof fn)
- sig: `pub proof fn lemma_low_bits_mask_values()`
- ensures: low_bits_mask(0) == 0x0, low_bits_mask(1) == 0x1, low_bits_mask(2) == 0x3, low_bits_mask(3) == 0x7, low_bits_mask(4) == 0xf,
- doc: Proof establishing the concrete values of all masks of bit sizes from 0 to

## spec_u16_to_le_bytes
- path: vstd/bytes.rs:16  (spec fn)
- sig: `pub closed spec fn spec_u16_to_le_bytes(x: u16) -> Seq<u8>`

## spec_u16_from_le_bytes
- path: vstd/bytes.rs:24  (spec fn)
- sig: `pub closed spec fn spec_u16_from_le_bytes(s: Seq<u8>) -> u16 recommends s.len() == 2,`

## lemma_auto_spec_u16_to_from_le_bytes
- path: vstd/bytes.rs:32  (proof fn)
- sig: `pub proof fn lemma_auto_spec_u16_to_from_le_bytes()`
- ensures: forall|x: u16|

## u16_from_le_bytes
- path: vstd/bytes.rs:79  (fn)
- sig: `pub exec fn u16_from_le_bytes(s: &[u8]) -> (x: u16)`
- requires: s@.len() == 2,
- ensures: x == spec_u16_from_le_bytes(s@),

## u16_to_le_bytes
- path: vstd/bytes.rs:91  (fn)
- sig: `pub exec fn u16_to_le_bytes(x: u16) -> (s: alloc::vec::Vec<u8>)`
- ensures: s@ == spec_u16_to_le_bytes(x), s@.len() == 2,

## spec_u32_to_le_bytes
- path: vstd/bytes.rs:100  (spec fn)
- sig: `pub closed spec fn spec_u32_to_le_bytes(x: u32) -> Seq<u8>`

## spec_u32_from_le_bytes
- path: vstd/bytes.rs:110  (spec fn)
- sig: `pub closed spec fn spec_u32_from_le_bytes(s: Seq<u8>) -> u32 recommends s.len() == 4,`

## lemma_auto_spec_u32_to_from_le_bytes
- path: vstd/bytes.rs:117  (proof fn)
- sig: `pub proof fn lemma_auto_spec_u32_to_from_le_bytes()`
- ensures: forall|x: u32|

## u32_from_le_bytes
- path: vstd/bytes.rs:174  (fn)
- sig: `pub exec fn u32_from_le_bytes(s: &[u8]) -> (x: u32)`
- requires: s@.len() == 4,
- ensures: x == spec_u32_from_le_bytes(s@),

## u32_to_le_bytes
- path: vstd/bytes.rs:186  (fn)
- sig: `pub exec fn u32_to_le_bytes(x: u32) -> (s: alloc::vec::Vec<u8>)`
- ensures: s@ == spec_u32_to_le_bytes(x), s@.len() == 4,

## spec_u64_to_le_bytes
- path: vstd/bytes.rs:195  (spec fn)
- sig: `pub closed spec fn spec_u64_to_le_bytes(x: u64) -> Seq<u8>`

## spec_u64_to_le_bytes_open
- path: vstd/bytes.rs:216  (spec fn)
- sig: `pub open spec fn spec_u64_to_le_bytes_open(x: u64) -> Seq<u8>`

## spec_u64_from_le_bytes
- path: vstd/bytes.rs:230  (spec fn)
- sig: `pub closed spec fn spec_u64_from_le_bytes(s: Seq<u8>) -> u64 recommends s.len() == 8,`

## lemma_auto_spec_u64_to_from_le_bytes
- path: vstd/bytes.rs:246  (proof fn)
- sig: `pub proof fn lemma_auto_spec_u64_to_from_le_bytes()`
- ensures: forall|x: u64| #![trigger spec_u64_to_le_bytes(x)]

## u64_from_le_bytes
- path: vstd/bytes.rs:331  (fn)
- sig: `pub exec fn u64_from_le_bytes(s: &[u8]) -> (x: u64)`
- requires: s@.len() == 8,
- ensures: x == spec_u64_from_le_bytes(s@),

## u64_to_le_bytes
- path: vstd/bytes.rs:343  (fn)
- sig: `pub exec fn u64_to_le_bytes(x: u64) -> (s: alloc::vec::Vec<u8>)`
- ensures: s@ == spec_u64_to_le_bytes(x), s@.len() == 8,

## spec_u128_to_le_bytes
- path: vstd/bytes.rs:352  (spec fn)
- sig: `pub closed spec fn spec_u128_to_le_bytes(x: u128) -> Seq<u8>`

## spec_u128_from_le_bytes
- path: vstd/bytes.rs:374  (spec fn)
- sig: `pub closed spec fn spec_u128_from_le_bytes(s: Seq<u8>) -> u128 recommends s.len() == 16,`

## lemma_auto_spec_u128_to_from_le_bytes
- path: vstd/bytes.rs:398  (proof fn)
- sig: `pub proof fn lemma_auto_spec_u128_to_from_le_bytes()`
- ensures: forall|x: u128|

## u128_from_le_bytes
- path: vstd/bytes.rs:518  (fn)
- sig: `pub exec fn u128_from_le_bytes(s: &[u8]) -> (x: u128)`
- requires: s@.len() == 16,
- ensures: x == spec_u128_from_le_bytes(s@),

## u128_to_le_bytes
- path: vstd/bytes.rs:530  (fn)
- sig: `pub exec fn u128_to_le_bytes(x: u128) -> (s: alloc::vec::Vec<u8>)`
- ensures: s@ == spec_u128_to_le_bytes(x), s@.len() == 16,

## InvCell::predicate
- path: vstd/cell/invcell.rs:95  (spec fn)
- sig: `pub closed spec fn predicate(&self) -> Pred`

## InvCell::inv
- path: vstd/cell/invcell.rs:101  (spec fn)
- sig: `pub open spec fn inv(&self, val: T) -> bool`

## InvCell::new
- path: vstd/cell/invcell.rs:105  (fn)
- sig: `pub fn new(val: T, Ghost(pred): Ghost<Pred>) -> (cell: Self)`
- requires: pred.predicate(val),
- ensures: cell.predicate() == pred,

## InvCell::set
- path: vstd/cell/invcell.rs:116  (fn)
- sig: `pub fn set(&self, val: T)`
- requires: self.inv(val),

## InvCell::replace
- path: vstd/cell/invcell.rs:123  (fn)
- sig: `pub fn replace(&self, val: T) -> (old_val: T)`
- requires: self.inv(val),
- ensures: self.inv(old_val),

## InvCell::get
- path: vstd/cell/invcell.rs:139  (fn)
- sig: `pub fn get(&self) -> (val: T) where T: Copy`
- ensures: self.inv(val),

## InvCell::into_inner
- path: vstd/cell/invcell.rs:155  (fn)
- sig: `pub fn into_inner(self) -> (val: T)`
- ensures: self.inv(val),

## PointsTo::id
- path: vstd/cell/pcell.rs:109  (spec fn)
- sig: `pub uninterp spec fn id(&self) -> CellId`
- doc: The [`CellId`] of the [`PCell`] this permission is associated with.

## PointsTo::value
- path: vstd/cell/pcell.rs:115  (spec fn)
- sig: `pub uninterp spec fn value(&self) -> &T`
- doc: The contents of the cell.

## PCell::id
- path: vstd/cell/pcell.rs:127  (spec fn)
- sig: `pub uninterp spec fn id(&self) -> CellId`
- doc: A unique ID for the cell.

## PCell::borrow
- path: vstd/cell/pcell.rs:145  (fn)
- sig: `pub fn borrow<'a>(&'a self, Tracked(perm): Tracked<&'a PointsTo<T>>) -> (v: &'a T)`
- requires: self.id() == perm.id(),
- ensures: v == perm.value(),

## PCell::borrow_mut
- path: vstd/cell/pcell.rs:159  (fn)
- sig: `pub fn borrow_mut<'a>(&'a self, Tracked(perm): Tracked<&'a mut PointsTo<T>>) -> (v: &'a mut T)`
- requires: self.id() == perm.id(),
- ensures: &*v == old(perm).value(), &*final(v) == final(perm).value(), final(perm).id() == self.id(),

## PCell::into_inner
- path: vstd/cell/pcell.rs:175  (fn)
- sig: `pub fn into_inner(self, Tracked(perm): Tracked<PointsTo<T>>) -> (v: T) where T: Sized`
- requires: self.id() == perm.id(),
- ensures: v == *perm.value(),

## PCell::replace
- path: vstd/cell/pcell.rs:193  (fn)
- sig: `pub fn replace(&self, Tracked(perm): Tracked<&mut PointsTo<T>>, in_v: T) -> (out_v: T) where T: Sized`
- requires: self.id() == old(perm).id(),
- ensures: final(perm).id() == old(perm).id(), *final(perm).value() == in_v, out_v == *old(perm).value(),

## PCell::write
- path: vstd/cell/pcell.rs:210  (fn)
- sig: `pub fn write(&self, Tracked(perm): Tracked<&mut PointsTo<T>>, in_v: T) where T: Sized`
- requires: self.id() == old(perm).id()
- ensures: final(perm).id() == old(perm).id(), *final(perm).value() == in_v,

## PCell::read
- path: vstd/cell/pcell.rs:224  (fn)
- sig: `pub fn read(&self, Tracked(perm): Tracked<&PointsTo<T>>) -> (out_v: T) where T: Copy + Sized`
- requires: self.id() == perm.id()

## PointsTo::id
- path: vstd/cell/pcell_maybe_uninit.rs:59  (spec fn)
- sig: `pub closed spec fn id(&self) -> CellId`
- doc: The [`CellId`] of the [`PCell`] this permission is associated with.

## PointsTo::mem_contents
- path: vstd/cell/pcell_maybe_uninit.rs:64  (spec fn)
- sig: `pub closed spec fn mem_contents(&self) -> MemContents<V>`
- doc: The contents of the cell.

## PointsTo::is_init
- path: vstd/cell/pcell_maybe_uninit.rs:70  (spec fn)
- sig: `pub open spec fn is_init(&self) -> bool`
- doc: Is this cell initialized?

## PointsTo::is_uninit
- path: vstd/cell/pcell_maybe_uninit.rs:76  (spec fn)
- sig: `pub open spec fn is_uninit(&self) -> bool`
- doc: Is this cell uninitialized?

## PointsTo::value
- path: vstd/cell/pcell_maybe_uninit.rs:82  (spec fn)
- sig: `pub open spec fn value(&self) -> V recommends self.is_init(),`
- doc: Value of the cell (if initialized)

## PCell::id
- path: vstd/cell/pcell_maybe_uninit.rs:101  (spec fn)
- sig: `pub closed spec fn id(&self) -> CellId`
- doc: A unique ID for the cell.

## PCell::put
- path: vstd/cell/pcell_maybe_uninit.rs:127  (fn)
- sig: `pub fn put(&self, Tracked(perm): Tracked<&mut PointsTo<V>>, in_v: V)`
- requires: old(perm).id() == self.id(), old(perm).mem_contents() == MemContents::Uninit,
- ensures: final(perm).id() == self.id(), final(perm).mem_contents() == MemContents::Init(in_v),

## PCell::take
- path: vstd/cell/pcell_maybe_uninit.rs:141  (fn)
- sig: `pub fn take(&self, Tracked(perm): Tracked<&mut PointsTo<V>>) -> (out_v: V)`
- requires: self.id() == old(perm).id(), old(perm).is_init(),
- ensures: final(perm).id() == old(perm).id(), final(perm).mem_contents() == MemContents::Uninit, out_v == old(perm).value(),

## PCell::replace
- path: vstd/cell/pcell_maybe_uninit.rs:158  (fn)
- sig: `pub fn replace(&self, Tracked(perm): Tracked<&mut PointsTo<V>>, in_v: V) -> (out_v: V)`
- requires: self.id() == old(perm).id(), old(perm).is_init(),
- ensures: final(perm).id() == old(perm).id(), final(perm).mem_contents() == MemContents::Init(in_v), out_v == old(perm).value(),

## PCell::borrow
- path: vstd/cell/pcell_maybe_uninit.rs:175  (fn)
- sig: `pub fn borrow<'a>(&'a self, Tracked(perm): Tracked<&'a PointsTo<V>>) -> (v: &'a V)`
- requires: self.id() == perm.id(), perm.is_init(),
- ensures: *v == perm.value(),

## PCell::borrow_mut
- path: vstd/cell/pcell_maybe_uninit.rs:190  (fn)
- sig: `pub fn borrow_mut<'a>(&'a self, Tracked(perm): Tracked<&'a mut PointsTo<V>>) -> (v: &'a mut V)`
- requires: self.id() == perm.id(), perm.is_init(),
- ensures: *v == old(perm).value(), final(perm).is_init(), final(perm).value() == *final(v),

## PCell::into_inner
- path: vstd/cell/pcell_maybe_uninit.rs:207  (fn)
- sig: `pub fn into_inner(self, Tracked(perm): Tracked<PointsTo<V>>) -> (v: V)`
- requires: self.id() == perm.id(), perm.is_init(),
- ensures: v == perm.value(),

## PCell::write
- path: vstd/cell/pcell_maybe_uninit.rs:221  (fn)
- sig: `pub fn write(&self, Tracked(perm): Tracked<&mut PointsTo<V>>, in_v: V)`
- requires: self.id() == old(perm).id(),
- ensures: final(perm).id() == old(perm).id(), final(perm).mem_contents() == MemContents::Init(in_v),

## PCell::read
- path: vstd/cell/pcell_maybe_uninit.rs:234  (fn)
- sig: `pub fn read(&self, Tracked(perm): Tracked<&PointsTo<V>>) -> (out_v: V) where V: Copy`
- requires: self.id() == perm.id(), perm.is_init(),

## PointsTo::id
- path: vstd/cell.rs:129  (spec fn)
- sig: `pub uninterp spec fn id(&self) -> CellId`
- doc: The [`CellId`] of the [`PCell`] this permission is associated with.

## PointsTo::mem_contents
- path: vstd/cell.rs:132  (spec fn)
- sig: `pub uninterp spec fn mem_contents(&self) -> MemContents<V>`
- doc: The contents of the cell, either unitialized or initialized to some `V`.

## PointsTo::view
- path: vstd/cell.rs:134  (spec fn)
- sig: `pub open spec fn view(self) -> PointsToData<V>`

## PointsTo::is_init
- path: vstd/cell.rs:140  (spec fn)
- sig: `pub open spec fn is_init(&self) -> bool`
- doc: Is this cell initialized?

## PointsTo::is_uninit
- path: vstd/cell.rs:146  (spec fn)
- sig: `pub open spec fn is_uninit(&self) -> bool`
- doc: Is this cell uninitialized?

## PointsTo::value
- path: vstd/cell.rs:152  (spec fn)
- sig: `pub open spec fn value(&self) -> V recommends self.is_init(),`
- doc: Value of the cell (if initialized)

## PCell::id
- path: vstd/cell.rs:163  (spec fn)
- sig: `pub uninterp spec fn id(&self) -> CellId`
- doc: A unique ID for the cell.

## PCell::put
- path: vstd/cell.rs:188  (fn)
- sig: `pub fn put(&self, Tracked(perm): Tracked<&mut PointsTo<V>>, v: V)`
- requires: old(perm)@ == pcell_points![ self.id() => MemContents::Uninit ],
- ensures: final(perm)@ == pcell_points![ self.id() => MemContents::Init(v) ],

## PCell::take
- path: vstd/cell.rs:203  (fn)
- sig: `pub fn take(&self, Tracked(perm): Tracked<&mut PointsTo<V>>) -> (v: V)`
- requires: self.id() == old(perm)@.pcell, old(perm).is_init(),
- ensures: final(perm).id() == old(perm)@.pcell, final(perm).mem_contents() == MemContents::Uninit, v == old(perm).value(),

## PCell::replace
- path: vstd/cell.rs:223  (fn)
- sig: `pub fn replace(&self, Tracked(perm): Tracked<&mut PointsTo<V>>, in_v: V) -> (out_v: V)`
- requires: self.id() == old(perm)@.pcell, old(perm).is_init(),
- ensures: final(perm).id() == old(perm)@.pcell, final(perm).mem_contents() == MemContents::Init(in_v), out_v == old(perm).value(),

## PCell::borrow
- path: vstd/cell.rs:246  (fn)
- sig: `pub fn borrow<'a>(&'a self, Tracked(perm): Tracked<&'a PointsTo<V>>) -> (v: &'a V)`
- requires: self.id() == perm@.pcell, perm.is_init(),
- ensures: *v == perm.value(),

## PCell::into_inner
- path: vstd/cell.rs:261  (fn)
- sig: `pub fn into_inner(self, Tracked(perm): Tracked<PointsTo<V>>) -> (v: V)`
- requires: self.id() == perm@.pcell, perm.is_init(),
- ensures: v == perm.value(),

## PCell::borrow_mut
- path: vstd/cell.rs:277  (fn)
- sig: `pub fn borrow_mut<'a>(&'a self, Tracked(perm): Tracked<&'a mut PointsTo<V>>) -> (v: &'a mut V)`
- requires: self.id() == perm@.pcell, perm.is_init(),
- ensures: *v == old(perm).value(), final(perm).id() == old(perm).id(), final(perm).is_init(), final(perm).value() == *final(v),

## PCell::write
- path: vstd/cell.rs:297  (fn)
- sig: `pub fn write(&self, Tracked(perm): Tracked<&mut PointsTo<V>>, in_v: V)`
- requires: self.id() == old(perm)@.pcell, old(perm).is_init(),
- ensures: final(perm).id() == old(perm)@.pcell, final(perm).mem_contents() == MemContents::Init(in_v),

## InvCell::inv
- path: vstd/cell.rs:340  (spec fn)
- sig: `pub closed spec fn inv(&self, val: T) -> bool`

## InvCell::new
- path: vstd/cell.rs:344  (fn)
- sig: `pub fn new(val: T, Ghost(f): Ghost<spec_fn(T) -> bool>) -> (cell: Self)`
- requires: f(val),
- ensures: forall|v| f(v) <==> cell.inv(v),

## InvCell::replace
- path: vstd/cell.rs:359  (fn)
- sig: `pub fn replace(&self, val: T) -> (old_val: T)`
- requires: self.inv(val),
- ensures: self.inv(old_val),

## InvCell::get
- path: vstd/cell.rs:378  (fn)
- sig: `pub fn get(&self) -> (val: T)`
- ensures: self.inv(val),

## range_all_spec_rec
- path: vstd/compute.rs:13  (spec fn)
- sig: `pub open spec fn range_all_spec_rec(r: Range<int>, p: spec_fn(int) -> bool) -> bool`

## all_spec_ensures
- path: vstd/compute.rs:29  (proof fn)
- sig: `pub broadcast proof fn all_spec_ensures(r: Range<int>, p: spec_fn(int) -> bool)`
- ensures: #[trigger] r.all_spec(p) ==> (forall|i| r.start <= i < r.end ==> #[trigger] p(i)),

## base_upper_bound_excl
- path: vstd/endian.rs:31  (spec fn)
- sig: `pub open spec fn base_upper_bound_excl<B: Base>(len: nat) -> int`
- doc: The exclusive upper bound on values that can be stored with `len` digits in base [`B::base()`].

## endianness
- path: vstd/endian.rs:62  (spec fn)
- sig: `pub uninterp spec fn endianness() -> Endian`
- doc: Abstracts the endianness of the currently executing hardware.

## EndianNat::in_bounds
- path: vstd/endian.rs:76  (spec fn)
- sig: `pub open spec fn in_bounds(s: Seq<int>) -> bool`
- doc: True when all numbers in `s` are valid digits in the given base.

## EndianNat::wf
- path: vstd/endian.rs:81  (spec fn)
- sig: `pub open spec fn wf(self) -> bool`
- doc: True when all of `self.digits` are valid digits in the given base.

## EndianNat::new
- path: vstd/endian.rs:86  (spec fn)
- sig: `pub open spec fn new(endian: Endian, digits: Seq<int>) -> Self recommends Self::in_bounds(digits),`
- doc: Creates a new `EndianNat` with the given digits and endianness.

## EndianNat::new_default
- path: vstd/endian.rs:94  (spec fn)
- sig: `pub open spec fn new_default(digits: Seq<int>) -> Self recommends Self::in_bounds(digits),`
- doc: Creates a new `EndianNat` with the given digits and the default endianness ([`endianness()`]).

## EndianNat::len
- path: vstd/endian.rs:102  (spec fn)
- sig: `pub open spec fn len(self) -> nat`
- doc: Number of digits in this `EndianNat`.

## EndianNat::index
- path: vstd/endian.rs:107  (spec fn)
- sig: `pub open spec fn index(self, i: int) -> int recommends 0 <= i < self.digits.len(),`
- doc: The `i`th digit in this `EndianNat`.

## EndianNat::first
- path: vstd/endian.rs:115  (spec fn)
- sig: `pub open spec fn first(self) -> nat recommends self.digits.len() > 0,`
- doc: The first digit in this `EndianNat`. Ignores endianness.

## EndianNat::last
- path: vstd/endian.rs:123  (spec fn)
- sig: `pub open spec fn last(self) -> nat recommends self.digits.len() > 0,`
- doc: The last digit in this `EndianNat`. Ignores endianness.

## EndianNat::least
- path: vstd/endian.rs:131  (spec fn)
- sig: `pub open spec fn least(self) -> nat recommends self.digits.len() > 0,`
- doc: The least significant digit in this `EndianNat`.

## EndianNat::most
- path: vstd/endian.rs:142  (spec fn)
- sig: `pub open spec fn most(self) -> nat recommends self.digits.len() > 0,`
- doc: The most significant digit in this `EndianNat`.

## EndianNat::skip
- path: vstd/endian.rs:153  (spec fn)
- sig: `pub open spec fn skip(self, n: nat) -> Self recommends 0 <= n <= self.digits.len(),`
- doc: Constructs an `EndianNat` by skipping the first `n` digits of the original `EndianNat`. Ignores endianness.

## EndianNat::take
- path: vstd/endian.rs:161  (spec fn)
- sig: `pub open spec fn take(self, n: nat) -> Self recommends 0 <= n <= self.digits.len(),`
- doc: Constructs an `EndianNat` by taking only the first `n` digits of the original `EndianNat`. Ignores endianness.

## EndianNat::skip_least
- path: vstd/endian.rs:169  (spec fn)
- sig: `pub open spec fn skip_least(self, n: nat) -> Self recommends 0 <= n <= self.digits.len(),`
- doc: Constructs an `EndianNat` by skipping the least significant `n` digits of the original `EndianNat`.

## EndianNat::skip_most
- path: vstd/endian.rs:180  (spec fn)
- sig: `pub open spec fn skip_most(self, n: nat) -> Self recommends 0 <= n <= self.digits.len(),`
- doc: Constructs an `EndianNat` by skipping the most significant `n` digits of the original `EndianNat`.

## EndianNat::take_least
- path: vstd/endian.rs:191  (spec fn)
- sig: `pub open spec fn take_least(self, n: nat) -> Self recommends 0 <= n <= self.digits.len(),`
- doc: Constructs an `EndianNat` by taking only the least significant `n` digits of the original `EndianNat`.

## EndianNat::take_most
- path: vstd/endian.rs:202  (spec fn)
- sig: `pub open spec fn take_most(self, n: nat) -> Self recommends 0 <= n <= self.digits.len(),`
- doc: Constructs an `EndianNat` by taking only the most significant `n` digits of the original `EndianNat`.

## EndianNat::drop_first
- path: vstd/endian.rs:213  (spec fn)
- sig: `pub open spec fn drop_first(self) -> Self recommends self.len() > 0,`
- doc: Constructs an `EndianNat` by dropping the first digit of the original `EndianNat`. Ignores endianness.

## EndianNat::drop_last
- path: vstd/endian.rs:221  (spec fn)
- sig: `pub open spec fn drop_last(self) -> Self recommends self.len() > 0,`
- doc: Constructs an `EndianNat` by dropping the last digit of the original `EndianNat`. Ignores endianness.

## EndianNat::drop_least
- path: vstd/endian.rs:229  (spec fn)
- sig: `pub open spec fn drop_least(self) -> Self recommends self.len() > 0,`
- doc: Constructs an `EndianNat` by dropping the least significant digit of the original `EndianNat`.

## EndianNat::drop_most
- path: vstd/endian.rs:240  (spec fn)
- sig: `pub open spec fn drop_most(self) -> Self recommends self.len() > 0,`
- doc: Constructs an `EndianNat` by dropping the most significant digits of the original `EndianNat`.

## EndianNat::append
- path: vstd/endian.rs:251  (spec fn)
- sig: `pub open spec fn append(self, other: Self) -> Self recommends self.endian == other.endian,`
- doc: Constructs an `EndianNat` by appending the digits of `other` to the end of the digits of `self`. Ignores endianness.

## EndianNat::append_least
- path: vstd/endian.rs:260  (spec fn)
- sig: `pub open spec fn append_least(self, other: Self) -> Self recommends self.endian == other.endian,`
- doc: Constructs an `EndianNat` by appending the digits of `other` to the digits of `self` in the least significant position

## EndianNat::append_most
- path: vstd/endian.rs:272  (spec fn)
- sig: `pub open spec fn append_most(self, other: Self) -> Self recommends self.endian == other.endian,`
- doc: Constructs an `EndianNat` by appending the digits of `other` to the digits of `self` in the most significant position

## EndianNat::push_first
- path: vstd/endian.rs:283  (spec fn)
- sig: `pub open spec fn push_first(self, n: int) -> Self recommends n < B::base(),`
- doc: Constructs an `EndianNat` by appending `n` to the front of the digits of `self`. Ignores endianness.

## EndianNat::push_last
- path: vstd/endian.rs:291  (spec fn)
- sig: `pub open spec fn push_last(self, n: int) -> Self recommends n < B::base(),`
- doc: Constructs an `EndianNat` by appending `n` to the end of the digits of `self`. Ignores endianness.

## EndianNat::push_least
- path: vstd/endian.rs:299  (spec fn)
- sig: `pub open spec fn push_least(self, n: int) -> Self recommends n < B::base(),`
- doc: Constructs an `EndianNat` by appending `n` to the least significant position in the digits of `self`.

## EndianNat::push_most
- path: vstd/endian.rs:310  (spec fn)
- sig: `pub open spec fn push_most(self, n: int) -> Self recommends n < B::base(),`
- doc: Constructs an `EndianNat` by appending `n` to the most significant position in the digits of `self`.

## EndianNat::to_nat
- path: vstd/endian.rs:322  (spec fn)
- sig: `pub open spec fn to_nat(self) -> nat`
- doc: Converts an `EndianNat` to the natural number that it represents, processing the digits from least significant to most significant, hiding the details of endianness.

## EndianNat::to_nat_properties
- path: vstd/endian.rs:332  (proof fn)
- sig: `pub broadcast proof fn to_nat_properties(self)`
- requires: self.wf(),
- ensures: #[trigger] self.to_nat() < base_upper_bound_excl::<B>(self.len()),

## EndianNat::from_nat
- path: vstd/endian.rs:426  (spec fn)
- sig: `pub open spec fn from_nat(n: nat, len: nat) -> Self recommends n < base_upper_bound_excl::<B>(len),`
- doc: Converts a natural number to an `EndianNat` representation with the specified number of digits (`len`) and default endianness ([`endianness()`]).

## EndianNat::from_nat_properties
- path: vstd/endian.rs:456  (proof fn)
- sig: `pub broadcast proof fn from_nat_properties(n: nat, len: nat)`
- requires: n < base_upper_bound_excl::<B>(len),
- ensures: #![trigger Self::from_nat(n, len)] Self::from_nat(n, len).len() == len, Self::from_nat(n, len).endian == endianness(), Self::from_nat(n, len).wf(),

## EndianNat::from_nat_to_nat
- path: vstd/endian.rs:486  (proof fn)
- sig: `pub broadcast proof fn from_nat_to_nat(n: nat, len: nat)`
- requires: n < base_upper_bound_excl::<B>(len),
- ensures: #[trigger] Self::from_nat(n, len).to_nat() == n,
- doc: Ensures that performing [`from_nat`] and then [`to_nat`] results in the original value,

## EndianNat::to_nat_from_nat
- path: vstd/endian.rs:514  (proof fn)
- sig: `pub broadcast proof fn to_nat_from_nat(endian_nat: Self)`
- requires: endian_nat.wf(), endian_nat.endian == endianness(),
- ensures: #[trigger] Self::from_nat(endian_nat.to_nat(), endian_nat.len()) == endian_nat,
- doc: Ensures that performing [`to_nat`] and then [`from_nat`] results in the original `EndianNat`.

## EndianNat::to_nat_injective
- path: vstd/endian.rs:543  (proof fn)
- sig: `pub broadcast proof fn to_nat_injective(n1: Self, n2: Self)`
- requires: n1.wf(), n2.wf(), n1.endian == endianness(), n2.endian == endianness(), n1.len() == n2.len(),
- ensures: n1 == n2,

## EndianNat::from_nat_injective
- path: vstd/endian.rs:560  (proof fn)
- sig: `pub broadcast proof fn from_nat_injective(n1: nat, len1: nat, n2: nat, len2: nat)`
- requires: n1 < base_upper_bound_excl::<B>(len1), n2 < base_upper_bound_excl::<B>(len2), #[trigger] Self::from_nat(n1, len1) == #[trigger] Self::from_nat(n2, len2),
- ensures: n1 == n2,

## EndianNat::to_nat_most
- path: vstd/endian.rs:576  (spec fn)
- sig: `pub open spec fn to_nat_most(self) -> nat`
- doc: Converts an `EndianNat` to the natural number that it represents, processing the digits from most significant to least significant, hiding the details of endianness.

## EndianNat::to_nat_eq_to_nat_most
- path: vstd/endian.rs:593  (proof fn)
- sig: `pub broadcast proof fn to_nat_eq_to_nat_most(self)`
- requires: self.wf(),
- ensures: #[trigger] self.to_nat() == #[trigger] self.to_nat_most(),
- doc: Ensures that [`to_nat`] and [`to_nat_most`] agree.

## EndianNat::exp
- path: vstd/endian.rs:724  (spec fn)
- sig: `pub open spec fn exp<BIG>() -> nat where BIG: BasePow2, B: CompatibleSmallerBaseFor<BIG>`
- doc: [`B::base()`] to the power of `exp()` is [`BIG::base()`].

## EndianNat::exp_properties
- path: vstd/endian.rs:728  (proof fn)
- sig: `pub broadcast proof fn exp_properties<BIG>() where BIG: BasePow2, B: CompatibleSmallerBaseFor<BIG>,`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- ensures: #![trigger Self::exp()] base_upper_bound_excl::<B>(Self::exp()) == BIG::base(), Self::exp() > 0,

## EndianNat::from_big
- path: vstd/endian.rs:782  (spec fn)
- sig: `pub open spec fn from_big<BIG>(n: EndianNat<BIG>) -> Self where BIG: BasePow2, B: CompatibleSmallerBaseFor<BIG>,`
- doc: Converts an `EndianNat` representation in the "big" base `BIG` to an `EndianNat` representation in the "small" base `B`.

## EndianNat::from_big_properties
- path: vstd/endian.rs:795  (proof fn)
- sig: `pub broadcast proof fn from_big_properties<BIG>(n: EndianNat<BIG>) where BIG: BasePow2, B: CompatibleSmallerBaseFor<BIG>,`
- requires: n.wf(), n.endian == endianness(),
- ensures: #![trigger Self::from_big(n)] Self::from_big(n).wf(), Self::from_big(n).endian == endianness(), Self::from_big(n).len() == n.len() * Self::exp(), Self::from_big(n).to_nat() == n.to_nat(),

## EndianNat::to_big
- path: vstd/endian.rs:833  (spec fn)
- sig: `pub open spec fn to_big<BIG>(n: EndianNat<B>) -> EndianNat<BIG> where BIG: BasePow2, B: CompatibleSmallerBaseFor<BIG>,  recommends n.len() % Self::exp() == 0,`
- doc: Converts an `EndianNat` representation in the "small" base `B` to an `EndianNat` representation in the "big" base `BIG`.

## EndianNat::to_big_properties
- path: vstd/endian.rs:868  (proof fn)
- sig: `pub broadcast proof fn to_big_properties<BIG>(n: EndianNat<B>) where BIG: BasePow2, B: CompatibleSmallerBaseFor<BIG>,`
- requires: n.wf(), n.endian == endianness(), n.len() % Self::exp() == 0,
- ensures: #![trigger Self::to_big(n)] Self::to_big(n).wf(), Self::to_big(n).endian == endianness(), Self::to_big(n).len() == n.len() / Self::exp(), Self::to_big(n).to_nat() == n.to_nat(),

## EndianNat::to_big_from_big
- path: vstd/endian.rs:947  (proof fn)
- sig: `pub broadcast proof fn to_big_from_big<BIG>(n: EndianNat<B>) where BIG: BasePow2, B: CompatibleSmallerBaseFor<BIG>,`
- requires: n.wf(), n.endian == endianness(), n.len() % Self::exp() == 0,
- ensures: #[trigger] Self::from_big(Self::to_big(n)) == n,
- doc: Ensures that performing [`to_big`] and then [`from_big`] results in the original `EndianNat<B>`.

## EndianNat::from_big_to_big
- path: vstd/endian.rs:995  (proof fn)
- sig: `pub broadcast proof fn from_big_to_big<BIG>(n: EndianNat<BIG>) where BIG: BasePow2, B: CompatibleSmallerBaseFor<BIG>,`
- requires: n.wf(), n.endian == endianness(),
- ensures: #[trigger] Self::to_big(Self::from_big(n)) == n,
- doc: Ensures that performing [`from_big`] and then [`to_big`] results in the original `EndianNat<BIG>`.

## EndianNat::to_big_injective
- path: vstd/endian.rs:1051  (proof fn)
- sig: `pub broadcast proof fn to_big_injective<BIG>(n1: EndianNat<B>, n2: EndianNat<B>) where BIG: BasePow2, B: CompatibleSmallerBaseFor<BIG>,`
- requires: n1.wf(), n2.wf(), n1.endian == endianness(), n2.endian == endianness(), n1.len() % Self::exp() == 0,
- ensures: n1 == n2,

## EndianNat::from_big_injective
- path: vstd/endian.rs:1072  (proof fn)
- sig: `pub broadcast proof fn from_big_injective<BIG>(n1: EndianNat<BIG>, n2: EndianNat<BIG>) where BIG: BasePow2, B: CompatibleSmallerBaseFor<BIG>,`
- requires: n1.wf(), n2.wf(), n1.endian == endianness(), n2.endian == endianness(), #[trigger] Self::from_big(n1) == #[trigger] Self::from_big(n2),
- ensures: n1 == n2,

## to_big_from_digits
- path: vstd/endian.rs:1116  (spec fn)
- sig: `pub open spec fn to_big_from_digits<BIG, B>(n: Seq<B>) -> EndianNat<BIG> where BIG: BasePow2, B: CompatibleSmallerBaseFor<BIG> + Integer,`
- doc: Converts a sequence of digits in base `B` in default endianness ([`endianness()`]) to an `EndianNat` in the larger base `BIG`.

## group_endian_nat_axioms
- path: vstd/endian.rs  (broadcast group)
- members: EndianNat::from_nat_properties EndianNat::to_nat_properties EndianNat::from_nat_to_nat EndianNat::to_nat_from_nat EndianNat::to_nat_injective EndianNat::from_nat_injective EndianNat::to_nat_eq_to_nat_most EndianNat::exp_properties EndianNat::to_big_properties EndianNat::from_big_properties EndianNat::from_big_to_big EndianNat::to_big_from_big EndianNat::to_big_injective EndianNat::from_big_injective

## f32::clone
- path: vstd/float.rs:95  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification[ <f32 as Clone>::clone ](f: &f32) -> (res: f32)`
- ensures: res == f,

## f64::clone
- path: vstd/float.rs:100  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification[ <f64 as Clone>::clone ](f: &f64) -> (res: f64)`
- ensures: res == f,

## ieee_float_cast
- path: vstd/float.rs:112  (spec fn)
- sig: `pub open spec fn ieee_float_cast<From: Copy + IeeeFloatCast<To>, To>(from: From) -> To`

## float_cast_spec
- path: vstd/float.rs:117  (spec fn)
- sig: `pub uninterp spec fn float_cast_spec<From, To>(from: From, to: To) -> bool`

## float_cast
- path: vstd/float.rs:127  (fn)
- sig: `pub fn float_cast<From: Copy + IeeeFloatCast<To>, To>(from: From) -> (to: To)`
- ensures: float_cast_spec(from, to),

## group_function_axioms
- path: vstd/function.rs  (broadcast group)
- members: axiom_proof_fn_requires axiom_proof_fn_ensures axiom_fn_mut_call_requires axiom_fn_mut_call_ensures

## HashMapWithView::new
- path: vstd/hash_map.rs:43  (fn)
- sig: `pub fn new() -> (result: Self)`
- requires: obeys_key_model::<Key>(), forall|k1: Key, k2: Key| k1@ == k2@ ==> k1 == k2,
- ensures: result@ == Map::<<Key as View>::V, Value>::empty(),
- doc: Creates an empty `HashMapWithView` with a capacity of 0.

## HashMapWithView::with_capacity
- path: vstd/hash_map.rs:59  (fn)
- sig: `pub fn with_capacity(capacity: usize) -> (result: Self)`
- requires: obeys_key_model::<Key>(), forall|k1: Key, k2: Key| k1@ == k2@ ==> k1 == k2,
- ensures: result@ == Map::<<Key as View>::V, Value>::empty(),
- doc: Creates an empty `HashMapWithView` with at least capacity for the specified number of elements.

## HashMapWithView::reserve
- path: vstd/hash_map.rs:73  (fn)
- sig: `pub fn reserve(&mut self, additional: usize)`
- ensures: final(self)@ == old(self)@,
- doc: Reserves capacity for at least `additional` number of elements in the map.

## HashMapWithView::is_empty
- path: vstd/hash_map.rs:82  (fn)
- sig: `pub fn is_empty(&self) -> (result: bool)`
- ensures: result == self@.is_empty(),
- doc: Returns true if the map is empty.

## HashMapWithView::spec_len
- path: vstd/hash_map.rs:90  (spec fn)
- sig: `pub uninterp spec fn spec_len(&self) -> usize`
- doc: Returns the number of elements in the map.

## HashMapWithView::len
- path: vstd/hash_map.rs:95  (fn)
- sig: `pub fn len(&self) -> (result: usize)`
- ensures: result == self@.len(),
- doc: Returns the number of elements in the map.

## HashMapWithView::insert
- path: vstd/hash_map.rs:106  (fn)
- sig: `pub fn insert(&mut self, k: Key, v: Value)`
- ensures: final(self)@ == old(self)@.insert(k@, v),
- doc: Inserts the given key and value in the map.

## HashMapWithView::remove
- path: vstd/hash_map.rs:118  (fn)
- sig: `pub fn remove(&mut self, k: &Key) -> (out: Option<Value>)`
- ensures: match out { Some(v) => old(self)@.contains_key(k@) && v == old(self)@[k@] && final(self)@ == old(self)@.remove(k@), None => !old(self)@.contains_key(k@) && final(self)@ == old(self)@, },
- doc: Removes the given key from the map and returns the value. If the key is not present in the map, returns `None`

## HashMapWithView::contains_key
- path: vstd/hash_map.rs:133  (fn)
- sig: `pub fn contains_key(&self, k: &Key) -> (result: bool)`
- ensures: result == self@.contains_key(k@),
- doc: Returns true if the map contains the given key.

## HashMapWithView::get
- path: vstd/hash_map.rs:144  (fn)
- sig: `pub fn get<'a>(&'a self, k: &Key) -> (result: Option<&'a Value>)`
- ensures: match result { Some(v) => self@.contains_key(k@) && *v == self@[k@], None => !self@.contains_key(k@), },
- doc: Returns a reference to the value corresponding to the given key in the map. If the key is not present in the map, returns `None`.

## HashMapWithView::clear
- path: vstd/hash_map.rs:158  (fn)
- sig: `pub fn clear(&mut self)`
- ensures: final(self)@ == Map::<<Key as View>::V, Value>::empty(),
- doc: Clears all key-value pairs in the map. Retains the allocated memory for reuse.

## HashMapWithView::union_prefer_right
- path: vstd/hash_map.rs:167  (fn)
- sig: `pub fn union_prefer_right(&mut self, other: Self)`
- ensures: final(self)@ == old(self)@.union_prefer_right(other@),
- doc: Returns the union of the two maps. If a key is present in both maps, then the value in the right map (`other`) is retained.

## StringHashMap::new
- path: vstd/hash_map.rs:209  (fn)
- sig: `pub fn new() -> (result: Self)`
- ensures: result@ == Map::<Seq<char>, Value>::empty(),
- doc: Creates an empty `StringHashMap` with a capacity of 0.

## StringHashMap::with_capacity
- path: vstd/hash_map.rs:220  (fn)
- sig: `pub fn with_capacity(capacity: usize) -> (result: Self)`
- ensures: result@ == Map::<Seq<char>, Value>::empty(),
- doc: Creates an empty `StringHashMap` with at least capacity for the specified number of elements.

## StringHashMap::reserve
- path: vstd/hash_map.rs:231  (fn)
- sig: `pub fn reserve(&mut self, additional: usize)`
- ensures: final(self)@ == old(self)@,
- doc: Reserves capacity for at least `additional` number of elements in the map.

## StringHashMap::is_empty
- path: vstd/hash_map.rs:240  (fn)
- sig: `pub fn is_empty(&self) -> (result: bool)`
- ensures: result == self@.is_empty(),
- doc: Returns true if the map is empty.

## StringHashMap::spec_len
- path: vstd/hash_map.rs:248  (spec fn)
- sig: `pub uninterp spec fn spec_len(&self) -> usize`
- doc: Returns the number of elements in the map.

## StringHashMap::len
- path: vstd/hash_map.rs:253  (fn)
- sig: `pub fn len(&self) -> (result: usize)`
- ensures: result == self@.len(),
- doc: Returns the number of elements in the map.

## StringHashMap::insert
- path: vstd/hash_map.rs:264  (fn)
- sig: `pub fn insert(&mut self, k: String, v: Value)`
- ensures: final(self)@ == old(self)@.insert(k@, v),
- doc: Inserts the given key and value in the map.

## StringHashMap::remove
- path: vstd/hash_map.rs:275  (fn)
- sig: `pub fn remove(&mut self, k: &str)`
- ensures: final(self)@ == old(self)@.remove(k@),
- doc: Removes the given key from the map. If the key is not present in the map, the map is unmodified.

## StringHashMap::contains_key
- path: vstd/hash_map.rs:286  (fn)
- sig: `pub fn contains_key(&self, k: &str) -> (result: bool)`
- ensures: result == self@.contains_key(k@),
- doc: Returns true if the map contains the given key.

## StringHashMap::get
- path: vstd/hash_map.rs:297  (fn)
- sig: `pub fn get<'a>(&'a self, k: &str) -> (result: Option<&'a Value>)`
- ensures: match result { Some(v) => self@.contains_key(k@) && *v == self@[k@], None => !self@.contains_key(k@), },
- doc: Returns a reference to the value corresponding to the given key in the map. If the key is not present in the map, returns `None`.

## StringHashMap::clear
- path: vstd/hash_map.rs:311  (fn)
- sig: `pub fn clear(&mut self)`
- ensures: final(self)@ == Map::<Seq<char>, Value>::empty(),
- doc: Clears all key-value pairs in the map. Retains the allocated memory for reuse.

## StringHashMap::union_prefer_right
- path: vstd/hash_map.rs:320  (fn)
- sig: `pub fn union_prefer_right(&mut self, other: Self)`
- ensures: final(self)@ == old(self)@.union_prefer_right(other@),
- doc: Returns the union of the two maps. If a key is present in both maps, then the value in the right map (`other`) is retained.

## group_hash_map_axioms
- path: vstd/hash_map.rs  (broadcast group)
- members: axiom_hash_map_with_view_spec_len axiom_string_hash_map_spec_len

## HashSetWithView::new
- path: vstd/hash_set.rs:44  (fn)
- sig: `pub fn new() -> (result: Self)`
- requires: obeys_key_model::<Key>(), forall|k1: Key, k2: Key| k1@ == k2@ ==> k1 == k2,
- ensures: result@ == Set::<<Key as View>::V>::empty(),
- doc: Creates an empty `HashSetWithView` with capacity 0.

## HashSetWithView::with_capacity
- path: vstd/hash_set.rs:60  (fn)
- sig: `pub fn with_capacity(capacity: usize) -> (result: Self)`
- requires: obeys_key_model::<Key>(), forall|k1: Key, k2: Key| k1@ == k2@ ==> k1 == k2,
- ensures: result@ == Set::<<Key as View>::V>::empty(),
- doc: Creates an empty `HashSetWithView` with at least capacity for the specified number of elements.

## HashSetWithView::reserve
- path: vstd/hash_set.rs:74  (fn)
- sig: `pub fn reserve(&mut self, additional: usize)`
- ensures: final(self)@ == old(self)@,
- doc: Reserves capacity for at least `additional` number of elements in the set.

## HashSetWithView::spec_len
- path: vstd/hash_set.rs:82  (spec fn)
- sig: `pub uninterp spec fn spec_len(&self) -> usize`
- doc: Returns the number of elements in the set.

## HashSetWithView::len
- path: vstd/hash_set.rs:87  (fn)
- sig: `pub fn len(&self) -> (result: usize)`
- ensures: result == self@.len(),
- doc: Returns the number of elements in the set.

## HashSetWithView::is_empty
- path: vstd/hash_set.rs:96  (fn)
- sig: `pub fn is_empty(&self) -> (result: bool)`
- ensures: result == self@.is_empty(),
- doc: Returns true if the set is empty.

## HashSetWithView::insert
- path: vstd/hash_set.rs:107  (fn)
- sig: `pub fn insert(&mut self, k: Key) -> (result: bool)`
- ensures: final(self)@ == old(self)@.insert(k@) && result == !old(self)@.contains(k@),
- doc: Inserts the given value into the set. Returns true if the value was not previously in the set, false otherwise.

## HashSetWithView::remove
- path: vstd/hash_set.rs:118  (fn)
- sig: `pub fn remove(&mut self, k: &Key) -> (result: bool)`
- ensures: final(self)@ == old(self)@.remove(k@) && result == old(self)@.contains(k@),
- doc: Removes the given value from the set. Returns true if the value was previously in the set, false otherwise.

## HashSetWithView::contains
- path: vstd/hash_set.rs:129  (fn)
- sig: `pub fn contains(&self, k: &Key) -> (result: bool)`
- ensures: result == self@.contains(k@),
- doc: Returns true if the set contains the given value.

## HashSetWithView::get
- path: vstd/hash_set.rs:140  (fn)
- sig: `pub fn get<'a>(&'a self, k: &Key) -> (result: Option<&'a Key>)`
- ensures: match result { Some(v) => self@.contains(k@) && v == &k, None => !self@.contains(k@), },
- doc: Returns a reference to the value in the set that is equal to the given value. If the value is not present in the set, returns `None`.

## HashSetWithView::clear
- path: vstd/hash_set.rs:154  (fn)
- sig: `pub fn clear(&mut self)`
- ensures: final(self)@ == Set::<<Key as View>::V>::empty(),
- doc: Clears all values from the set.

## StringHashSet::new
- path: vstd/hash_set.rs:195  (fn)
- sig: `pub fn new() -> (result: Self)`
- ensures: result@ == Set::<Seq<char>>::empty(),
- doc: Creates an empty `StringHashSet` with capacity 0.

## StringHashSet::with_capacity
- path: vstd/hash_set.rs:206  (fn)
- sig: `pub fn with_capacity(capacity: usize) -> (result: Self)`
- ensures: result@ == Set::<Seq<char>>::empty(),
- doc: Creates an empty `StringHashSet` with at least capacity for the specified number of elements.

## StringHashSet::reserve
- path: vstd/hash_set.rs:217  (fn)
- sig: `pub fn reserve(&mut self, additional: usize)`
- ensures: final(self)@ == old(self)@,
- doc: Reserves capacity for at least `additional` number of elements in the set.

## StringHashSet::is_empty
- path: vstd/hash_set.rs:226  (fn)
- sig: `pub fn is_empty(&self) -> (result: bool)`
- ensures: result == self@.is_empty(),
- doc: Returns true if the set is empty.

## StringHashSet::spec_len
- path: vstd/hash_set.rs:234  (spec fn)
- sig: `pub uninterp spec fn spec_len(&self) -> usize`
- doc: Returns the number of elements in the set.

## StringHashSet::len
- path: vstd/hash_set.rs:239  (fn)
- sig: `pub fn len(&self) -> (result: usize)`
- ensures: result == self@.len(),
- doc: Returns the number of elements in the set.

## StringHashSet::insert
- path: vstd/hash_set.rs:250  (fn)
- sig: `pub fn insert(&mut self, k: String) -> (result: bool)`
- ensures: final(self)@ == old(self)@.insert(k@) && result == !old(self)@.contains(k@),
- doc: Inserts the given value into the set. Returns true if the value was not previously in the set, false otherwise.

## StringHashSet::remove
- path: vstd/hash_set.rs:261  (fn)
- sig: `pub fn remove(&mut self, k: &str) -> (result: bool)`
- ensures: final(self)@ == old(self)@.remove(k@) && result == old(self)@.contains(k@),
- doc: Removes the given value from the set. Returns true if the value was previously in the set, false otherwise.

## StringHashSet::contains
- path: vstd/hash_set.rs:272  (fn)
- sig: `pub fn contains(&self, k: &str) -> (result: bool)`
- ensures: result == self@.contains(k@),
- doc: Returns true if the set contains the given value.

## StringHashSet::get
- path: vstd/hash_set.rs:283  (fn)
- sig: `pub fn get<'a>(&'a self, k: &str) -> (result: Option<&'a String>)`
- ensures: match result { Some(v) => self@.contains(k@) && v@ == k@, None => !self@.contains(k@), },
- doc: Returns a reference to the value in the set that is equal to the given value. If the value is not present in the set, returns `None`.

## StringHashSet::clear
- path: vstd/hash_set.rs:297  (fn)
- sig: `pub fn clear(&mut self)`
- ensures: final(self)@ == Set::<Seq<char>>::empty(),
- doc: Clears all values from the set.

## group_hash_set_axioms
- path: vstd/hash_set.rs  (broadcast group)
- members: axiom_hash_set_with_view_spec_len axiom_string_hash_set_spec_len

## IMap::empty
- path: vstd/imap.rs:37  (spec fn)
- sig: `pub closed spec fn empty() -> IMap<K, V>`
- doc: An empty map.

## IMap::total
- path: vstd/imap.rs:43  (spec fn)
- sig: `pub open spec fn total(fv: spec_fn(K) -> V) -> IMap<K, V>`
- doc: Gives a `IMap<K, V>` whose domain contains every key, and maps each key

## IMap::new
- path: vstd/imap.rs:49  (spec fn)
- sig: `pub open spec fn new(fk: spec_fn(K) -> bool, fv: spec_fn(K) -> V) -> IMap<K, V>`
- doc: Gives a `IMap<K, V>` whose domain is given by the boolean predicate on keys `fk`,

## IMap::dom
- path: vstd/imap.rs:54  (spec fn)
- sig: `pub closed spec fn dom(self) -> ISet<K>`
- doc: The domain of the map as a set.

## IMap::index
- path: vstd/imap.rs:60  (spec fn)
- sig: `pub closed spec fn index(self, key: K) -> V recommends self.dom().contains(key),`
- doc: Gets the value that the given key `key` maps to.

## IMap::spec_index
- path: vstd/imap.rs:69  (spec fn)
- sig: `pub open spec fn spec_index(self, key: K) -> V recommends self.dom().contains(key),`
- doc: `[]` operator, synonymous with `index`

## IMap::insert
- path: vstd/imap.rs:80  (spec fn)
- sig: `pub closed spec fn insert(self, key: K, value: V) -> IMap<K, V>`
- doc: Inserts the given (key, value) pair into the map.

## IMap::remove
- path: vstd/imap.rs:94  (spec fn)
- sig: `pub closed spec fn remove(self, key: K) -> IMap<K, V>`
- doc: Removes the given key and its associated value from the map.

## IMap::len
- path: vstd/imap.rs:106  (spec fn)
- sig: `pub open spec fn len(self) -> nat`
- doc: Returns the number of key-value pairs in the map

## lemma_imap_empty
- path: vstd/imap.rs:237  (proof fn)
- sig: `pub broadcast proof fn lemma_imap_empty<K, V>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::imap::group_imap_lemmas`: write `broadcast use vstd::imap::group_imap_lemmas;` and the fact is available.
- ensures: #[trigger] IMap::<K, V>::empty().dom() == ISet::<K>::empty(),
- doc: The domain of the empty map is the empty set

## lemma_imap_insert_domain
- path: vstd/imap.rs:248  (proof fn)
- sig: `pub broadcast proof fn lemma_imap_insert_domain<K, V>(m: IMap<K, V>, key: K, value: V)`
- ensures: #[trigger] m.insert(key, value).dom() == m.dom().insert(key),
- doc: The domain of a map after inserting a key-value pair is equivalent to inserting the key into

## lemma_imap_insert_same
- path: vstd/imap.rs:258  (proof fn)
- sig: `pub broadcast proof fn lemma_imap_insert_same<K, V>(m: IMap<K, V>, key: K, value: V)`
- ensures: #[trigger] m.insert(key, value)[key] == value,
- doc: Inserting `value` at `key` in `m` results in a map that maps `key` to `value`

## lemma_imap_insert_different
- path: vstd/imap.rs:265  (proof fn)
- sig: `pub broadcast proof fn lemma_imap_insert_different<K, V>(m: IMap<K, V>, key1: K, key2: K, value: V)`
- requires: key1 != key2,
- ensures: #[trigger] m.insert(key2, value)[key1] == m[key1],
- doc: Inserting `value` at `key2` does not change the value mapped to by any other keys in `m`

## lemma_imap_remove_domain
- path: vstd/imap.rs:275  (proof fn)
- sig: `pub broadcast proof fn lemma_imap_remove_domain<K, V>(m: IMap<K, V>, key: K)`
- ensures: #[trigger] m.remove(key).dom() == m.dom().remove(key),
- doc: The domain of a map after removing a key-value pair is equivalent to removing the key from

## lemma_imap_remove_different
- path: vstd/imap.rs:286  (proof fn)
- sig: `pub broadcast proof fn lemma_imap_remove_different<K, V>(m: IMap<K, V>, key1: K, key2: K)`
- requires: key1 != key2,
- ensures: #[trigger] m.remove(key2)[key1] == m[key1],
- doc: Removing a key-value pair from a map does not change the value mapped to by

## lemma_imap_ext_equal
- path: vstd/imap.rs:295  (proof fn)
- sig: `pub broadcast proof fn lemma_imap_ext_equal<K, V>(m1: IMap<K, V>, m2: IMap<K, V>)`
- ensures: #[trigger] (m1 =~= m2) <==> { &&& m1.dom() =~= m2.dom() &&& forall|k: K| #![auto] m1.dom().contains(k) ==> m1[k] == m2[k] },
- doc: Two maps are equivalent if their domains are equivalent and every key in their domains map to the same value.

## lemma_imap_ext_equal_deep
- path: vstd/imap.rs:324  (proof fn)
- sig: `pub broadcast proof fn lemma_imap_ext_equal_deep<K, V>(m1: IMap<K, V>, m2: IMap<K, V>)`
- ensures: #[trigger] (m1 =~~= m2) <==> { &&& m1.dom() =~~= m2.dom() &&& forall|k: K| #![auto] m1.dom().contains(k) ==> m1[k] =~~= m2[k] },

## group_imap_lemmas
- path: vstd/imap.rs  (broadcast group)
- members: axiom_imap_index_decreases_finite axiom_imap_index_decreases_infinite lemma_imap_empty lemma_imap_insert_domain lemma_imap_insert_same lemma_imap_insert_different lemma_imap_remove_domain lemma_imap_remove_different lemma_imap_ext_equal lemma_imap_ext_equal_deep

## check_argument_is_map
- path: vstd/imap.rs:372  (spec fn)
- sig: `pub open spec fn check_argument_is_map<K, V>(m: IMap<K, V>) -> IMap<K, V>`

## IMap::is_full
- path: vstd/imap_lib.rs:21  (spec fn)
- sig: `pub open spec fn is_full(self) -> bool`
- doc: Is `true` if called by a "full" map, i.e., a map containing every element of type `A`.

## IMap::is_empty
- path: vstd/imap_lib.rs:27  (spec fn)
- sig: `pub open spec fn is_empty(self) -> (b: bool)`
- doc: Is `true` if called by an "empty" map, i.e., a map containing no elements and has length 0

## IMap::contains_key
- path: vstd/imap_lib.rs:33  (spec fn)
- sig: `pub open spec fn contains_key(self, k: K) -> bool`
- doc: Returns true if the key `k` is in the domain of `self`.

## IMap::contains_value
- path: vstd/imap_lib.rs:38  (spec fn)
- sig: `pub open spec fn contains_value(self, v: V) -> bool`
- doc: Returns true if the value `v` is in the range of `self`.

## IMap::index_opt
- path: vstd/imap_lib.rs:44  (spec fn)
- sig: `pub open spec fn index_opt(self, k: K) -> Option<V>`
- doc: Returns `Some(v)` if the key `k` is in the domain of `self` and maps to `v`,

## IMap::values
- path: vstd/imap_lib.rs:65  (spec fn)
- sig: `pub open spec fn values(self) -> ISet<V>`

## IMap::kv_pairs
- path: vstd/imap_lib.rs:82  (spec fn)
- sig: `pub open spec fn kv_pairs(self) -> ISet<(K, V)>`

## IMap::contains_pair
- path: vstd/imap_lib.rs:87  (spec fn)
- sig: `pub open spec fn contains_pair(self, k: K, v: V) -> bool`
- doc: Returns true if the key `k` is in the domain of `self`, and it maps to the value `v`.

## IMap::submap_of
- path: vstd/imap_lib.rs:105  (spec fn)
- sig: `pub open spec fn submap_of(self, m2: Self) -> bool`
- doc: Returns true if `m1` is _contained in_ `m2`, i.e., the domain of `m1` is a subset

## IMap::spec_le
- path: vstd/imap_lib.rs:111  (spec fn)
- sig: `pub open spec fn spec_le(self, m2: Self) -> bool`

## IMap::union_prefer_right
- path: vstd/imap_lib.rs:128  (spec fn)
- sig: `pub open spec fn union_prefer_right(self, m2: Self) -> Self`
- doc: Gives the union of two maps, defined as:

## IMap::remove_keys
- path: vstd/imap_lib.rs:151  (spec fn)
- sig: `pub open spec fn remove_keys(self, keys: ISet<K>) -> Self`
- doc: Removes the given keys and their associated values from the map.

## IMap::restrict
- path: vstd/imap_lib.rs:166  (spec fn)
- sig: `pub open spec fn restrict(self, keys: ISet<K>) -> Self`
- doc: Complement to `remove_keys`. Restricts the map to (key, value) pairs

## IMap::is_equal_on_key
- path: vstd/imap_lib.rs:171  (spec fn)
- sig: `pub open spec fn is_equal_on_key(self, m2: Self, key: K) -> bool`
- doc: Returns `true` if and only if the given key maps to the same value or does not exist in self and m2.

## IMap::agrees
- path: vstd/imap_lib.rs:177  (spec fn)
- sig: `pub open spec fn agrees(self, m2: Self) -> bool`
- doc: Returns `true` if the two given maps agree on all keys that their domains share

## IMap::map_entries
- path: vstd/imap_lib.rs:182  (spec fn)
- sig: `pub open spec fn map_entries<W>(self, f: spec_fn(K, V) -> W) -> IMap<K, W>`
- doc: Map a function `f` over all (k, v) pairs in `self`.

## IMap::map_values
- path: vstd/imap_lib.rs:187  (spec fn)
- sig: `pub open spec fn map_values<W>(self, f: spec_fn(V) -> W) -> IMap<K, W>`
- doc: Map a function `f` over the values in `self`.

## IMap::is_injective
- path: vstd/imap_lib.rs:192  (spec fn)
- sig: `pub open spec fn is_injective(self) -> bool`
- doc: Returns `true` if and only if a map is injective

## IMap::invert
- path: vstd/imap_lib.rs:200  (spec fn)
- sig: `pub open spec fn invert(self) -> IMap<V, K>`
- doc: Swaps map keys and values. Values are not required to be unique; no

## IMap::lemma_remove_key_len
- path: vstd/imap_lib.rs:210  (proof fn)
- sig: `pub proof fn lemma_remove_key_len(self, key: K)`
- requires: self.dom().contains(key), self.dom().finite(),
- ensures: self.dom().len() == 1 + self.remove(key).dom().len(),
- doc: Removing a key from a map that previously contained that key decreases

## IMap::lemma_remove_equivalency
- path: vstd/imap_lib.rs:221  (proof fn)
- sig: `pub proof fn lemma_remove_equivalency(self, key: K)`
- ensures: self.remove(key).dom() == self.dom().remove(key),
- doc: The domain of a map after removing a key is equivalent to removing the key from

## IMap::lemma_remove_keys_len
- path: vstd/imap_lib.rs:229  (proof fn)
- sig: `pub proof fn lemma_remove_keys_len(self, keys: ISet<K>)`
- requires: forall|k: K| #[trigger] keys.contains(k) ==> self.contains_key(k), keys.finite(), self.dom().finite(),
- ensures: self.remove_keys(keys).dom().len() == self.dom().len() - keys.len(),
- doc: Removing a set of n keys from a map that previously contained all n keys

## IMap::lemma_invert_is_injective
- path: vstd/imap_lib.rs:251  (proof fn)
- sig: `pub proof fn lemma_invert_is_injective(self)`
- ensures: self.invert().is_injective(),
- doc: The function `invert` results in an injective map

## IMap::filter_keys
- path: vstd/imap_lib.rs:278  (spec fn)
- sig: `pub open spec fn filter_keys(self, p: spec_fn(K) -> bool) -> Self`
- doc: Keeps only those key-value pairs whose key satisfies `p`.

## IMap::get
- path: vstd/imap_lib.rs:297  (spec fn)
- sig: `pub open spec fn get(self, k: K) -> Option<V>`
- doc: Returns the value associated with key `k` in the map if it exists,

## IMap::lemma_submap_eq_iff
- path: vstd/imap_lib.rs:342  (proof fn)
- sig: `pub proof fn lemma_submap_eq_iff(self, m: Self)`
- ensures: (self == m) <==> (self.submap_of(m) && m.submap_of(self)),
- doc: Two maps are equal if and only if they are submaps of each other.

## IMap::lemma_imap_remove_keys_insert
- path: vstd/imap_lib.rs:372  (proof fn)
- sig: `pub broadcast proof fn lemma_imap_remove_keys_insert(self, r: ISet<K>, k: K, v: V)`
- ensures: #[trigger] self.insert(k, v).remove_keys(r) == if r.contains(k) { self.remove_keys(r) } else { self.remove_keys(r).insert(k, v) },
- doc: When removing a set of keys from a map after inserting (k,v),

## IMap::lemma_filter_keys_insert
- path: vstd/imap_lib.rs:405  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_keys_insert(self, p: spec_fn(K) -> bool, k: K, v: V)`
- ensures: #[trigger] self.insert(k, v).filter_keys(p) == (if p(k) { self.filter_keys(p).insert(k, v) } else { self.filter_keys(p) }),
- doc: Filtering keys after inserting `(k, v)` leaves the result unchanged when `p(k)` is false,

## IMap::lemma_insert_contains_value
- path: vstd/imap_lib.rs:433  (proof fn)
- sig: `pub broadcast proof fn lemma_insert_contains_value(self, k: K, v: V)`
- ensures: #[trigger] self.insert(k, v).contains_value(v),
- doc: Inserting a value in a map means it contains the value that was inserted.

## IMap::lemma_insert_invariant_contains
- path: vstd/imap_lib.rs:451  (proof fn)
- sig: `pub broadcast proof fn lemma_insert_invariant_contains(self, old_v: V, k: K, v: V)`
- requires: self.contains_key(k) ==> self[k] != old_v, old_v != v,
- ensures: #[trigger] self.insert(k, v).contains_value(old_v) == self.contains_value(old_v),
- doc: Inserting a value in a map where that key is already present ensures

## IMap::lemma_injective_values_len
- path: vstd/imap_lib.rs:464  (proof fn)
- sig: `pub proof fn lemma_injective_values_len(self)`
- requires: self.dom().finite(), self.is_injective(),
- ensures: self.values().finite(), self.values().len() == self.dom().len(),

## IMap::lemma_values_len
- path: vstd/imap_lib.rs:486  (proof fn)
- sig: `pub proof fn lemma_values_len(self)`
- requires: self.dom().finite(),
- ensures: self.values().finite(), self.values().len() <= self.dom().len(),

## IMap::prefixed_entries
- path: vstd/imap_lib.rs:523  (spec fn)
- sig: `pub open spec fn prefixed_entries(self, prefix: Seq<K>) -> Self`
- doc: Returns a sub-map of all entries whose key begins with `prefix`,

## IMap::lemma_prefixed_entries_get
- path: vstd/imap_lib.rs:541  (proof fn)
- sig: `pub broadcast proof fn lemma_prefixed_entries_get(self, prefix: Seq<K>, k: Seq<K>)`
- requires: self.prefixed_entries(prefix).contains_key(k),
- ensures: self.prefixed_entries(prefix)[k] == #[trigger] self[prefix + k],
- doc: For every key `k` kept by `prefixed_entries(prefix)`,

## IMap::lemma_prefixed_entries_contains
- path: vstd/imap_lib.rs:569  (proof fn)
- sig: `pub broadcast proof fn lemma_prefixed_entries_contains(self, prefix: Seq<K>, k: Seq<K>)`
- ensures: #[trigger] self.prefixed_entries(prefix).contains_key(k) <==> self.contains_key( prefix + k, ),
- doc: A key `k` is in `prefixed_entries(prefix)` exactly when the original map

## IMap::lemma_prefixed_entries_insert
- path: vstd/imap_lib.rs:596  (proof fn)
- sig: `pub broadcast proof fn lemma_prefixed_entries_insert(self, prefix: Seq<K>, k: Seq<K>, v: V)`
- ensures: #[trigger] self.insert(prefix + k, v).prefixed_entries(prefix) == self.prefixed_entries( prefix, ).insert(k, v),
- doc: Inserting `(prefix + k, v)` before taking `prefixed_entries(prefix)`

## IMap::lemma_prefixed_entries_union
- path: vstd/imap_lib.rs:631  (proof fn)
- sig: `pub broadcast proof fn lemma_prefixed_entries_union(self, m: Self, prefix: Seq<K>)`
- ensures: #[trigger] self.union_prefer_right(m).prefixed_entries(prefix) == self.prefixed_entries( prefix, ).union_prefer_right(m.prefixed_entries(prefix)),
- doc: Taking the entries that share `prefix` commutes with `union_prefer_right`:

## IMap::is_monotonic
- path: vstd/imap_lib.rs:653  (spec fn)
- sig: `pub open spec fn is_monotonic(self) -> bool`
- doc: Returns `true` if a map is monotonic -- that is, if the mapping between ordered sets

## IMap::is_monotonic_from
- path: vstd/imap_lib.rs:661  (spec fn)
- sig: `pub open spec fn is_monotonic_from(self, start: int) -> bool`
- doc: Returns `true` if and only if a map is monotonic, only considering keys greater than

## lemma_union_insert_left
- path: vstd/imap_lib.rs:669  (proof fn)
- sig: `pub broadcast proof fn lemma_union_insert_left<K, V>(m1: IMap<K, V>, m2: IMap<K, V>, k: K, v: V)`
- requires: !m2.contains_key(k),
- ensures: #[trigger] m1.insert(k, v).union_prefer_right(m2) == m1.union_prefer_right(m2).insert(k, v),

## lemma_union_insert_right
- path: vstd/imap_lib.rs:678  (proof fn)
- sig: `pub broadcast proof fn lemma_union_insert_right<K, V>(m1: IMap<K, V>, m2: IMap<K, V>, k: K, v: V)`
- ensures: #[trigger] m1.union_prefer_right(m2.insert(k, v)) == m1.union_prefer_right(m2).insert(k, v),

## lemma_union_remove_left
- path: vstd/imap_lib.rs:685  (proof fn)
- sig: `pub broadcast proof fn lemma_union_remove_left<K, V>(m1: IMap<K, V>, m2: IMap<K, V>, k: K)`
- requires: m1.contains_key(k), !m2.contains_key(k),
- ensures: #[trigger] m1.union_prefer_right(m2).remove(k) == m1.remove(k).union_prefer_right(m2),

## lemma_union_remove_right
- path: vstd/imap_lib.rs:695  (proof fn)
- sig: `pub broadcast proof fn lemma_union_remove_right<K, V>(m1: IMap<K, V>, m2: IMap<K, V>, k: K)`
- requires: !m1.contains_key(k), m2.contains_key(k),
- ensures: #[trigger] m1.union_prefer_right(m2).remove(k) == m1.union_prefer_right(m2.remove(k)),

## lemma_union_dom
- path: vstd/imap_lib.rs:705  (proof fn)
- sig: `pub broadcast proof fn lemma_union_dom<K, V>(m1: IMap<K, V>, m2: IMap<K, V>)`
- ensures: #[trigger] m1.union_prefer_right(m2).dom() == m1.dom().union(m2.dom()),

## lemma_disjoint_union_size
- path: vstd/imap_lib.rs:713  (proof fn)
- sig: `pub broadcast proof fn lemma_disjoint_union_size<K, V>(m1: IMap<K, V>, m2: IMap<K, V>)`
- requires: m1.dom().disjoint(m2.dom()), m1.dom().finite(), m2.dom().finite(),
- ensures: #[trigger] m1.union_prefer_right(m2).dom().len() == m1.dom().len() + m2.dom().len(),
- doc: The size of the union of two disjoint maps is equal to the sum of the sizes of the individual maps

## group_imap_union
- path: vstd/imap_lib.rs  (broadcast group)
- members: lemma_union_dom lemma_union_remove_left lemma_union_remove_right lemma_union_insert_left lemma_union_insert_right lemma_disjoint_union_size

## lemma_submap_of_trans
- path: vstd/imap_lib.rs:739  (proof fn)
- sig: `pub broadcast proof fn lemma_submap_of_trans<K, V>(m1: IMap<K, V>, m2: IMap<K, V>, m3: IMap<K, V>)`
- requires: #[trigger] m1.submap_of(m2), #[trigger] m2.submap_of(m3),
- ensures: m1.submap_of(m3),
- doc: submap_of (<=) is transitive.

## lemma_imap_new_domain
- path: vstd/imap_lib.rs:754  (proof fn)
- sig: `pub broadcast proof fn lemma_imap_new_domain<K, V>(fk: spec_fn(K) -> bool, fv: spec_fn(K) -> V)`
- ensures: #[trigger] IMap::<K, V>::new(fk, fv).dom() == ISet::<K>::new(|k: K| fk(k)),
- doc: The domain of a map constructed with `IMap::new(fk, fv)` is equivalent to the set constructed with `ISet::new(fk)`.

## lemma_imap_new_values
- path: vstd/imap_lib.rs:765  (proof fn)
- sig: `pub broadcast proof fn lemma_imap_new_values<K, V>(fk: spec_fn(K) -> bool, fv: spec_fn(K) -> V)`
- ensures: #[trigger] IMap::<K, V>::new(fk, fv).values() == ISet::<V>::new( |v: V| (exists|k: K| #[trigger] fk(k) && #[trigger] fv(k) == v), ),
- doc: The set of values of a map constructed with `IMap::new(fk, fv)` is equivalent to

## group_imap_properties
- path: vstd/imap_lib.rs  (broadcast group)
- members: lemma_imap_new_domain lemma_imap_new_values

## group_imap_extra
- path: vstd/imap_lib.rs  (broadcast group)
- members: IMap::lemma_imap_remove_keys_insert IMap::lemma_filter_keys_insert IMap::lemma_insert_contains_value IMap::lemma_insert_invariant_contains IMap::lemma_prefixed_entries_get IMap::lemma_prefixed_entries_contains IMap::lemma_prefixed_entries_insert IMap::lemma_prefixed_entries_union

## lemma_values_finite
- path: vstd/imap_lib.rs:797  (proof fn)
- sig: `pub proof fn lemma_values_finite<K, V>(m: IMap<K, V>)`
- requires: m.dom().finite(),
- ensures: m.values().finite(),

## constant
- path: vstd/invariant.rs:182  (spec fn)
- sig: `pub uninterp spec fn constant(&self) -> K`
- doc: `.

## namespace
- path: vstd/invariant.rs:186  (spec fn)
- sig: `pub uninterp spec fn namespace(&self) -> int`
- doc: Namespace the invariant was declared in.

## inv
- path: vstd/invariant.rs:197  (spec fn)
- sig: `pub open spec fn inv(&self, v: V) -> bool`

## create_open_invariant_credit
- path: vstd/invariant.rs:320  (fn)
- sig: `pub fn create_open_invariant_credit() -> Tracked<OpenInvariantCredit>`

## spend_open_invariant_credit
- path: vstd/invariant.rs:337  (fn)
- sig: `pub fn spend_open_invariant_credit( #[allow(unused_variables)] credit: Tracked<OpenInvariantCredit>, )`

## open_atomic_invariant_begin
- path: vstd/invariant.rs:372  (fn)
- sig: `pub fn open_atomic_invariant_begin<'a, K, V, Pred: InvariantPredicate<K, V>>( _inv: &'a AtomicInvariant<K, V, Pred>,`

## open_local_invariant_begin
- path: vstd/invariant.rs:382  (fn)
- sig: `pub fn open_local_invariant_begin<'a, K, V, Pred: InvariantPredicate<K, V>>( _inv: &'a LocalInvariant<K, V, Pred>,`

## open_invariant_end
- path: vstd/invariant.rs:392  (fn)
- sig: `pub fn open_invariant_end<V>(_guard: InvariantBlockGuard, _v: V)`

## ISet::empty
- path: vstd/iset.rs:54  (spec fn)
- sig: `pub closed spec fn empty() -> ISet<A>`
- doc: The "empty" set.

## ISet::new
- path: vstd/iset.rs:66  (spec fn)
- sig: `pub closed spec fn new(f: spec_fn(A) -> bool) -> ISet<A>`
- doc: ISet whose membership is determined by the given boolean predicate.

## ISet::full
- path: vstd/iset.rs:72  (spec fn)
- sig: `pub open spec fn full() -> ISet<A>`
- doc: The "full" set, i.e., set containing every element of type `A`.

## ISet::contains
- path: vstd/iset.rs:78  (spec fn)
- sig: `pub closed spec fn contains(self, a: A) -> bool`
- doc: Predicate indicating if the set contains the given element.

## ISet::spec_has
- path: vstd/iset.rs:84  (spec fn)
- sig: `pub open spec fn spec_has(self, a: A) -> bool`
- doc: Predicate indicating if the set contains the given element: supports `self has a` syntax.

## ISet::subset_of
- path: vstd/iset.rs:90  (spec fn)
- sig: `pub open spec fn subset_of(self, s2: ISet<A>) -> bool`
- doc: Returns `true` if the first argument is a subset of the second.

## ISet::spec_le
- path: vstd/iset.rs:95  (spec fn)
- sig: `pub open spec fn spec_le(self, s2: ISet<A>) -> bool`

## ISet::insert
- path: vstd/iset.rs:102  (spec fn)
- sig: `pub closed spec fn insert(self, a: A) -> ISet<A>`
- doc: Returns a new set with the given element inserted.

## ISet::remove
- path: vstd/iset.rs:116  (spec fn)
- sig: `pub closed spec fn remove(self, a: A) -> ISet<A>`
- doc: Returns a new set with the given element removed.

## ISet::union
- path: vstd/iset.rs:128  (spec fn)
- sig: `pub closed spec fn union(self, s2: ISet<A>) -> ISet<A>`
- doc: Union of two sets.

## ISet::spec_add
- path: vstd/iset.rs:134  (spec fn)
- sig: `pub open spec fn spec_add(self, s2: ISet<A>) -> ISet<A>`
- doc: `+` operator, synonymous with `union`

## ISet::intersect
- path: vstd/iset.rs:139  (spec fn)
- sig: `pub closed spec fn intersect(self, s2: ISet<A>) -> ISet<A>`
- doc: Intersection of two sets.

## ISet::spec_mul
- path: vstd/iset.rs:145  (spec fn)
- sig: `pub open spec fn spec_mul(self, s2: ISet<A>) -> ISet<A>`
- doc: `*` operator, synonymous with `intersect`

## ISet::difference
- path: vstd/iset.rs:150  (spec fn)
- sig: `pub closed spec fn difference(self, s2: ISet<A>) -> ISet<A>`
- doc: ISet difference, i.e., the set of all elements in the first one but not in the second.

## ISet::spec_sub
- path: vstd/iset.rs:156  (spec fn)
- sig: `pub open spec fn spec_sub(self, s2: ISet<A>) -> ISet<A>`
- doc: `-` operator, synonymous with `difference`

## ISet::complement
- path: vstd/iset.rs:161  (spec fn)
- sig: `pub closed spec fn complement(self) -> ISet<A>`
- doc: ISet complement (within the space of all possible elements in `A`).

## ISet::filter
- path: vstd/iset.rs:166  (spec fn)
- sig: `pub open spec fn filter(self, f: spec_fn(A) -> bool) -> ISet<A>`
- doc: ISet of all elements in the given set which satisfy the predicate `f`.

## ISet::finite
- path: vstd/iset.rs:171  (spec fn)
- sig: `pub closed spec fn finite(self) -> bool`
- doc: Returns `true` if the set is finite.

## ISet::to_set
- path: vstd/iset.rs:180  (spec fn)
- sig: `pub open spec fn to_set(self) -> Option<Set<A>> recommends self.finite(),`

## ISet::len
- path: vstd/iset.rs:188  (spec fn)
- sig: `pub closed spec fn len(self) -> nat`
- doc: Cardinality of the set. (Only meaningful if a set is finite.)

## ISet::choose
- path: vstd/iset.rs:198  (spec fn)
- sig: `pub open spec fn choose(self) -> A`
- doc: Chooses an arbitrary element of the set.

## ISet::mk_map
- path: vstd/iset.rs:204  (spec fn)
- sig: `pub uninterp spec fn mk_map<V>(self, f: spec_fn(A) -> V) -> IMap<A, V>`
- doc: Creates a [`Map`] whose domain is the given set.

## ISet::disjoint
- path: vstd/iset.rs:208  (spec fn)
- sig: `pub open spec fn disjoint(self, s2: Self) -> bool`
- doc: Returns `true` if the sets are disjoint, i.e., if their interesection is

## ISet::congruent
- path: vstd/iset.rs:214  (spec fn)
- sig: `pub open spec fn congruent(self, s2: Set<A>) -> bool`
- doc: Returns `true` if this set is congruent to (contains the same elements as)

## is_fun_commutative
- path: vstd/iset.rs:274  (spec fn)
- sig: `pub open spec fn is_fun_commutative<A, B>(f: spec_fn(B, A) -> B) -> bool`

## ISet::fold
- path: vstd/iset.rs:461  (spec fn)
- sig: `pub closed spec fn fold<B>(self, z: B, f: spec_fn(B, A) -> B) -> B recommends self.finite(), is_fun_commutative(f),`
- doc: Folds the set, applying `f` to perform the fold. The next element for the fold is chosen by

## lemma_finite_set_induct
- path: vstd/iset.rs:546  (proof fn)
- sig: `pub proof fn lemma_finite_set_induct<A>(s: ISet<A>, pred: spec_fn(ISet<A>) -> bool)`
- requires: s.finite(), pred(ISet::empty()), forall|s, a| pred(s) && s.finite() && !s.contains(a) ==> #[trigger] pred(s.insert(a)),
- ensures: pred(s),

## lemma_fold_insert
- path: vstd/iset.rs:613  (proof fn)
- sig: `pub broadcast proof fn lemma_fold_insert<A, B>(s: ISet<A>, z: B, f: spec_fn(B, A) -> B, a: A)`
- requires: s.finite(), !s.contains(a), is_fun_commutative(f),
- ensures: #[trigger] s.insert(a).fold(z, f) == f(s.fold(z, f), a),

## lemma_fold_empty
- path: vstd/iset.rs:627  (proof fn)
- sig: `pub broadcast proof fn lemma_fold_empty<A, B>(z: B, f: spec_fn(B, A) -> B)`
- ensures: #[trigger] ISet::empty().fold(z, f) == z,

## lemma_iset_empty
- path: vstd/iset.rs:640  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_empty<A>(a: A)`
- ensures: !(#[trigger] ISet::empty().contains(a)),
- doc: The empty set contains no elements

## lemma_iset_new
- path: vstd/iset.rs:647  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_new<A>(f: spec_fn(A) -> bool, a: A)`
- ensures: #[trigger] ISet::new(f).contains(a) == f(a),
- doc: A call to `ISet::new` with the predicate `f` contains `a` if and only if `f(a)` is true.

## lemma_iset_insert_same
- path: vstd/iset.rs:654  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_insert_same<A>(s: ISet<A>, a: A)`
- ensures: #[trigger] s.insert(a).contains(a),
- doc: The result of inserting element `a` into set `s` must contains `a`.

## lemma_iset_insert_different
- path: vstd/iset.rs:662  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_insert_different<A>(s: ISet<A>, a1: A, a2: A)`
- requires: a1 != a2,
- ensures: #[trigger] s.insert(a2).contains(a1) == s.contains(a1),
- doc: If `a1` does not equal `a2`, then the result of inserting element `a2` into set `s`

## lemma_iset_remove_same
- path: vstd/iset.rs:671  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_remove_same<A>(s: ISet<A>, a: A)`
- ensures: !(#[trigger] s.remove(a).contains(a)),
- doc: The result of removing element `a` from set `s` must not contain `a`.

## lemma_iset_remove_insert
- path: vstd/iset.rs:679  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_remove_insert<A>(s: ISet<A>, a: A)`
- requires: s.contains(a),
- ensures: (#[trigger] s.remove(a)).insert(a) == s,
- doc: Removing an element `a` from a set `s` and then inserting `a` back into the set`

## lemma_iset_remove_different
- path: vstd/iset.rs:709  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_remove_different<A>(s: ISet<A>, a1: A, a2: A)`
- requires: a1 != a2,
- ensures: #[trigger] s.remove(a2).contains(a1) == s.contains(a1),
- doc: If `a1` does not equal `a2`, then the result of removing element `a2` from set `s`

## lemma_iset_union
- path: vstd/iset.rs:719  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_union<A>(s1: ISet<A>, s2: ISet<A>, a: A)`
- ensures: #[trigger] s1.union(s2).contains(a) == (s1.contains(a) || s2.contains(a)),
- doc: The union of sets `s1` and `s2` contains element `a` if and only if

## lemma_iset_intersect
- path: vstd/iset.rs:727  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_intersect<A>(s1: ISet<A>, s2: ISet<A>, a: A)`
- ensures: #[trigger] s1.intersect(s2).contains(a) == (s1.contains(a) && s2.contains(a)),
- doc: The intersection of sets `s1` and `s2` contains element `a` if and only if

## lemma_iset_difference
- path: vstd/iset.rs:735  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_difference<A>(s1: ISet<A>, s2: ISet<A>, a: A)`
- ensures: #[trigger] s1.difference(s2).contains(a) == (s1.contains(a) && !s2.contains(a)),
- doc: The set difference between `s1` and `s2` contains element `a` if and only if

## lemma_iset_complement
- path: vstd/iset.rs:742  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_complement<A>(s: ISet<A>, a: A)`
- ensures: #[trigger] s.complement().contains(a) == !s.contains(a),
- doc: The complement of set `s` contains element `a` if and only if `s` does not contain `a`.

## lemma_iset_ext_equal
- path: vstd/iset.rs:749  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_ext_equal<A>(s1: ISet<A>, s2: ISet<A>)`
- ensures: #[trigger] (s1 =~= s2) <==> (forall|a: A| s1.contains(a) == s2.contains(a)),
- doc: ISets `s1` and `s2` are equal if and only if they contain all of the same elements.

## lemma_iset_ext_equal_deep
- path: vstd/iset.rs:767  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_ext_equal_deep<A>(s1: ISet<A>, s2: ISet<A>)`
- ensures: #[trigger] (s1 =~~= s2) <==> s1 =~= s2,

## lemma_iset_empty_finite
- path: vstd/iset.rs:787  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_empty_finite<A>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::iset::group_iset_lemmas`: write `broadcast use vstd::iset::group_iset_lemmas;` and the fact is available.
- ensures: #[trigger] ISet::<A>::empty().finite(),
- doc: The empty set is finite.

## lemma_iset_insert_finite
- path: vstd/iset.rs:797  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_insert_finite<A>(s: ISet<A>, a: A)`
- requires: s.finite(),
- ensures: #[trigger] s.insert(a).finite(),
- doc: The result of inserting an element `a` into a finite set `s` is also finite.

## lemma_iset_remove_finite
- path: vstd/iset.rs:834  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_remove_finite<A>(s: ISet<A>, a: A)`
- requires: s.finite(),
- ensures: #[trigger] s.remove(a).finite(),
- doc: The result of removing an element `a` from a finite set `s` is also finite.

## lemma_iset_union_finite
- path: vstd/iset.rs:862  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_union_finite<A>(s1: ISet<A>, s2: ISet<A>)`
- requires: s1.finite(), s2.finite(),
- ensures: #[trigger] s1.union(s2).finite(),
- doc: The union of two finite sets is finite.

## lemma_iset_intersect_finite
- path: vstd/iset.rs:887  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_intersect_finite<A>(s1: ISet<A>, s2: ISet<A>)`
- requires: s1.finite() || s2.finite(),
- ensures: #[trigger] s1.intersect(s2).finite(),
- doc: The intersection of two finite sets is finite.

## lemma_iset_difference_finite
- path: vstd/iset.rs:899  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_difference_finite<A>(s1: ISet<A>, s2: ISet<A>)`
- requires: s1.finite(),
- ensures: #[trigger] s1.difference(s2).finite(),
- doc: The set difference between two finite sets is finite.

## lemma_iset_choose_infinite
- path: vstd/iset.rs:911  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_choose_infinite<A>(s: ISet<A>)`
- requires: !s.finite(),
- ensures: #[trigger] s.contains(s.choose()),
- doc: An infinite set `s` contains the element `s.choose()`.

## lemma_iset_empty_len
- path: vstd/iset.rs:926  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_empty_len<A>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::iset::group_iset_lemmas`: write `broadcast use vstd::iset::group_iset_lemmas;` and the fact is available.
- ensures: #[trigger] ISet::<A>::empty().len() == 0,
- doc: The empty set has length 0.

## lemma_iset_insert_len
- path: vstd/iset.rs:935  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_insert_len<A>(s: ISet<A>, a: A)`
- requires: s.finite(),
- ensures: #[trigger] s.insert(a).len() == s.len() + (if s.contains(a) { 0int } else { 1 }),
- doc: The result of inserting an element `a` into a finite set `s` has length

## lemma_iset_remove_len
- path: vstd/iset.rs:954  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_remove_len<A>(s: ISet<A>, a: A)`
- requires: s.finite(),
- ensures: s.len() == #[trigger] s.remove(a).len() + (if s.contains(a) { 1int } else { 0 }),
- doc: The result of removing an element `a` from a finite set `s` has length

## lemma_iset_contains_len
- path: vstd/iset.rs:974  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_contains_len<A>(s: ISet<A>, a: A)`
- requires: s.finite(), #[trigger] s.contains(a),
- ensures: #[trigger] s.len() != 0,
- doc: If a finite set `s` contains any element, it has length greater than 0.

## lemma_iset_choose_len
- path: vstd/iset.rs:989  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_choose_len<A>(s: ISet<A>)`
- requires: s.finite(), #[trigger] s.len() != 0,
- ensures: #[trigger] s.contains(s.choose()),
- doc: A finite set `s` contains the element `s.choose()` if it has length greater than 0.

## lemma_iset_finite_if_subset_of_seq
- path: vstd/iset.rs:1006  (proof fn)
- sig: `pub proof fn lemma_iset_finite_if_subset_of_seq<A>(i: ISet<A>, s: Seq<A>)`
- requires: forall|a| i.contains(a) ==> s.contains(a),
- ensures: i.finite(),

## group_iset_lemmas
- path: vstd/iset.rs  (broadcast group)
- members: lemma_iset_empty lemma_iset_new lemma_iset_insert_same lemma_iset_insert_different lemma_iset_remove_same lemma_iset_remove_insert lemma_iset_remove_different lemma_iset_union lemma_iset_intersect lemma_iset_difference lemma_iset_complement lemma_iset_ext_equal lemma_iset_ext_equal_deep lemma_iset_mk_map_domain lemma_iset_mk_map_index lemma_iset_empty_finite lemma_iset_insert_finite lemma_iset_remove_finite lemma_iset_union_finite lemma_iset_intersect_finite lemma_iset_difference_finite lemma_iset_choose_infinite lemma_iset_empty_len lemma_iset_insert_len lemma_iset_remove_len lemma_iset_contains_len lemma_iset_choose_len

## ISet::is_full
- path: vstd/iset_lib.rs:21  (spec fn)
- sig: `pub open spec fn is_full(self) -> bool`
- doc: Is `true` if called by a "full" set, i.e., a set containing every element of type `A`.

## ISet::is_empty
- path: vstd/iset_lib.rs:26  (spec fn)
- sig: `pub open spec fn is_empty(self) -> (b: bool)`
- doc: Is `true` if called by an "empty" set, i.e., a set containing no elements and has length 0

## ISet::map
- path: vstd/iset_lib.rs:31  (spec fn)
- sig: `pub open spec fn map<B>(self, f: spec_fn(A) -> B) -> ISet<B>`
- doc: Returns the set contains an element `f(x)` for every element `x` in `self`.

## ISet::map_by
- path: vstd/iset_lib.rs:47  (spec fn)
- sig: `pub open spec fn map_by<B>(self, fwd: spec_fn(A) -> B, rev: spec_fn(B) -> A) -> ISet<B> recommends forall|a: A| self.contains(a) ==> rev(fwd(a)) == a,`
- doc: `ISet::map_by` is like `ISet::map`, but `map` only takes a forward function `fwd: spec_fn(A) -> B`,

## ISet::map_flatten_by
- path: vstd/iset_lib.rs:59  (spec fn)
- sig: `pub open spec fn map_flatten_by<B>( self, fwd: spec_fn(A) -> ISet<B>, rev: spec_fn(B) -> A, ) -> ISet<B> recommends forall|a: A, b: B| #[trigger] self.contains(a) && fwd(a).contains(b) ==> #[trigger] rev(b) == a,`
- doc: Similar to `ISet::map_by`, but the forward function returns `ISet<B>` rather than `B`,

## ISet::to_seq
- path: vstd/iset_lib.rs:94  (spec fn)
- sig: `pub open spec fn to_seq(self) -> Seq<A> recommends self.finite(),`
- doc: Converts a set into a sequence with an arbitrary ordering.

## ISet::to_sorted_seq
- path: vstd/iset_lib.rs:109  (spec fn)
- sig: `pub open spec fn to_sorted_seq(self, leq: spec_fn(A, A) -> bool) -> Seq<A>`
- doc: Converts a set into a sequence sorted by the given ordering function `leq`

## ISet::is_singleton
- path: vstd/iset_lib.rs:114  (spec fn)
- sig: `pub open spec fn is_singleton(self) -> bool`
- doc: A singleton set has at least one element and any two elements are equal.

## ISet::injective_on
- path: vstd/iset_lib.rs:122  (spec fn)
- sig: `pub open spec fn injective_on<B>(self, r: spec_fn(A) -> B) -> bool`
- doc: Indicates if the function given by `r` is injective on this set,

## ISet::has_least
- path: vstd/iset_lib.rs:130  (spec fn)
- sig: `pub open spec fn has_least(self, leq: spec_fn(A, A) -> bool, min: A) -> bool`
- doc: An element in an ordered set is called a least element (or a minimum), if it is less than

## ISet::has_minimum
- path: vstd/iset_lib.rs:135  (spec fn)
- sig: `pub open spec fn has_minimum(self, leq: spec_fn(A, A) -> bool, min: A) -> bool`
- doc: An element in an ordered set is called a minimal element, if no other element is less than it.

## ISet::has_greatest
- path: vstd/iset_lib.rs:142  (spec fn)
- sig: `pub open spec fn has_greatest(self, leq: spec_fn(A, A) -> bool, max: A) -> bool`
- doc: An element in an ordered set is called a greatest element (or a maximum), if it is greater than

## ISet::has_maximum
- path: vstd/iset_lib.rs:147  (spec fn)
- sig: `pub open spec fn has_maximum(self, leq: spec_fn(A, A) -> bool, max: A) -> bool`
- doc: An element in an ordered set is called a maximal element, if no other element is greater than it.

## ISet::lemma_injective_on_subset
- path: vstd/iset_lib.rs:153  (proof fn)
- sig: `pub proof fn lemma_injective_on_subset<B>(self, r: spec_fn(A) -> B, other: Self)`
- requires: other <= self, self.injective_on(r),
- ensures: other.injective_on(r),
- doc: If a function is injective on the set `self`, then it is also injective on any subset `other` of `self`.

## ISet::find_unique_minimal
- path: vstd/iset_lib.rs:172  (spec fn)
- sig: `pub closed spec fn find_unique_minimal(self, r: spec_fn(A, A) -> bool) -> A recommends total_ordering(r), self.len() > 0, self.finite(),`
- doc: Any totally-ordered set contains a unique minimal (equivalently, least) element.

## ISet::find_unique_maximal
- path: vstd/iset_lib.rs:260  (spec fn)
- sig: `pub closed spec fn find_unique_maximal(self, r: spec_fn(A, A) -> bool) -> A recommends total_ordering(r), self.len() > 0,`
- doc: Any totally-ordered set contains a unique maximal (equivalently, greatest) element.

## ISet::to_multiset
- path: vstd/iset_lib.rs:347  (spec fn)
- sig: `pub open spec fn to_multiset(self) -> Multiset<A>`
- doc: Converts a set into a multiset where each element from the set has

## ISet::lemma_len0_is_empty
- path: vstd/iset_lib.rs:361  (proof fn)
- sig: `pub proof fn lemma_len0_is_empty(self)`
- requires: self.finite(), self.len() == 0,
- ensures: self == ISet::<A>::empty(),
- doc: A finite set with length 0 is equivalent to the empty set.

## ISet::lemma_singleton_size
- path: vstd/iset_lib.rs:376  (proof fn)
- sig: `pub proof fn lemma_singleton_size(self)`
- requires: self.is_singleton(),
- ensures: self.len() == 1,
- doc: A singleton set has length 1.

## ISet::lemma_is_singleton
- path: vstd/iset_lib.rs:388  (proof fn)
- sig: `pub proof fn lemma_is_singleton(s: ISet<A>)`
- requires: s.finite(),
- ensures: s.is_singleton() == (s.len() == 1),
- doc: A set has exactly one element, if and only if, it has at least one element and any two elements are equal.

## ISet::lemma_len_filter
- path: vstd/iset_lib.rs:409  (proof fn)
- sig: `pub proof fn lemma_len_filter(self, f: spec_fn(A) -> bool)`
- requires: self.finite(),
- ensures: self.filter(f).finite(), self.filter(f).len() <= self.len(),
- doc: The result of filtering a finite set is finite and has size less than or equal to the original set.

## ISet::lemma_greatest_implies_maximal
- path: vstd/iset_lib.rs:421  (proof fn)
- sig: `pub proof fn lemma_greatest_implies_maximal(self, r: spec_fn(A, A) -> bool, max: A)`
- requires: pre_ordering(r),
- ensures: self.has_greatest(r, max) ==> self.has_maximum(r, max),
- doc: In a pre-ordered set, a greatest element is necessarily maximal.

## ISet::lemma_least_implies_minimal
- path: vstd/iset_lib.rs:430  (proof fn)
- sig: `pub proof fn lemma_least_implies_minimal(self, r: spec_fn(A, A) -> bool, min: A)`
- requires: pre_ordering(r),
- ensures: self.has_least(r, min) ==> self.has_minimum(r, min),
- doc: In a pre-ordered set, a least element is necessarily minimal.

## ISet::lemma_maximal_equivalent_greatest
- path: vstd/iset_lib.rs:439  (proof fn)
- sig: `pub proof fn lemma_maximal_equivalent_greatest(self, r: spec_fn(A, A) -> bool, max: A)`
- requires: total_ordering(r),
- ensures: self.has_greatest(r, max) <==> self.has_maximum(r, max),
- doc: In a totally-ordered set, an element is maximal if and only if it is a greatest element.

## ISet::lemma_minimal_equivalent_least
- path: vstd/iset_lib.rs:450  (proof fn)
- sig: `pub proof fn lemma_minimal_equivalent_least(self, r: spec_fn(A, A) -> bool, min: A)`
- requires: total_ordering(r),
- ensures: self.has_least(r, min) <==> self.has_minimum(r, min),
- doc: In a totally-ordered set, an element is maximal if and only if it is a greatest element.

## ISet::lemma_least_is_unique
- path: vstd/iset_lib.rs:461  (proof fn)
- sig: `pub proof fn lemma_least_is_unique(self, r: spec_fn(A, A) -> bool)`
- requires: partial_ordering(r),
- ensures: forall|min: A, min_prime: A| self.has_least(r, min) && self.has_least(r, min_prime) ==> min == min_prime,
- doc: In a partially-ordered set, there exists at most one least element.

## ISet::lemma_greatest_is_unique
- path: vstd/iset_lib.rs:476  (proof fn)
- sig: `pub proof fn lemma_greatest_is_unique(self, r: spec_fn(A, A) -> bool)`
- requires: partial_ordering(r),
- ensures: forall|max: A, max_prime: A| self.has_greatest(r, max) && self.has_greatest(r, max_prime) ==> max == max_prime,
- doc: In a partially-ordered set, there exists at most one greatest element.

## ISet::lemma_minimal_is_unique
- path: vstd/iset_lib.rs:492  (proof fn)
- sig: `pub proof fn lemma_minimal_is_unique(self, r: spec_fn(A, A) -> bool)`
- requires: total_ordering(r),
- ensures: forall|min: A, min_prime: A| self.has_minimum(r, min) && self.has_minimum(r, min_prime) ==> min == min_prime,
- doc: In a totally-ordered set, there exists at most one minimal element.

## ISet::lemma_maximal_is_unique
- path: vstd/iset_lib.rs:508  (proof fn)
- sig: `pub proof fn lemma_maximal_is_unique(self, r: spec_fn(A, A) -> bool)`
- requires: self.finite(), total_ordering(r),
- ensures: forall|max: A, max_prime: A| self.has_maximum(r, max) && self.has_maximum(r, max_prime) ==> max == max_prime,
- doc: In a totally-ordered set, there exists at most one maximal element.

## ISet::lemma_iset_insert_diff_decreases
- path: vstd/iset_lib.rs:527  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_insert_diff_decreases(self, s: ISet<A>, elt: A)`
- requires: self.contains(elt), !s.contains(elt), self.finite(),
- ensures: #[trigger] self.difference(s.insert(elt)).len() < self.difference(s).len(),
- doc: ISet difference with an additional element inserted decreases the size of

## ISet::lemma_subset_not_in_lt
- path: vstd/iset_lib.rs:539  (proof fn)
- sig: `pub proof fn lemma_subset_not_in_lt(self: ISet<A>, s2: ISet<A>, elt: A)`
- requires: self.subset_of(s2), s2.finite(), !self.contains(elt), s2.contains(elt),
- ensures: self.len() < s2.len(),
- doc: If there is an element not present in a subset, its length is stricly smaller.

## ISet::lemma_iset_map_insert_commute
- path: vstd/iset_lib.rs:555  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_map_insert_commute<B>(self, elt: A, f: spec_fn(A) -> B)`
- ensures: #[trigger] self.insert(elt).map(f) =~= self.map(f).insert(f(elt)),
- doc: Inserting an element and mapping a function over a set commute

## ISet::lemma_map_union_commute
- path: vstd/iset_lib.rs:572  (proof fn)
- sig: `pub proof fn lemma_map_union_commute<B>(self, t: ISet<A>, f: spec_fn(A) -> B)`
- ensures: (self.union(t)).map(f) =~= self.map(f).union(t.map(f)),
- doc: `map` and `union` commute

## ISet::all
- path: vstd/iset_lib.rs:594  (spec fn)
- sig: `pub open spec fn all(&self, pred: spec_fn(A) -> bool) -> bool`
- doc: Utility function for more concise universal quantification over sets

## ISet::any
- path: vstd/iset_lib.rs:599  (spec fn)
- sig: `pub open spec fn any(&self, pred: spec_fn(A) -> bool) -> bool`
- doc: Utility function for more concise existential quantification over sets

## ISet::lemma_any_map_preserved_pred
- path: vstd/iset_lib.rs:604  (proof fn)
- sig: `pub broadcast proof fn lemma_any_map_preserved_pred<B>( self, p: spec_fn(A) -> bool, q: spec_fn(B) -> bool, f: spec_fn(A) -> B, )`
- requires: #[trigger] self.any(p), forall|x: A| #[trigger] p(x) ==> q(f(x)),
- ensures: #[trigger] self.map(f).any(q),
- doc: `any` is preserved between predicates `p` and `q` if `p` implies `q`.

## ISet::filter_map
- path: vstd/iset_lib.rs:621  (spec fn)
- sig: `pub open spec fn filter_map<B>(self, f: spec_fn(A) -> Option<B>) -> ISet<B>`
- doc: Collecting all elements `b` where `f` returns `Some(b)`

## ISet::lemma_filter_map_insert
- path: vstd/iset_lib.rs:632  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_map_insert<B>( s: ISet<A>, f: spec_fn(A) -> Option<B>, elem: A, )`
- ensures: #[trigger] s.insert(elem).filter_map(f) == (match f(elem) { Some(res) => s.filter_map(f).insert(res), None => s.filter_map(f), }),
- doc: Inserting commutes with `filter_map`

## ISet::lemma_filter_map_union
- path: vstd/iset_lib.rs:677  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_map_union<B>(self, f: spec_fn(A) -> Option<B>, t: ISet<A>)`
- ensures: #[trigger] self.union(t).filter_map(f) == self.filter_map(f).union(t.filter_map(f)),
- doc: `filter_map` and `union` commute.

## ISet::lemma_map_finite
- path: vstd/iset_lib.rs:718  (proof fn)
- sig: `pub proof fn lemma_map_finite<B>(self, f: spec_fn(A) -> B)`
- requires: self.finite(),
- ensures: self.map(f).finite(),
- doc: `map` preserves finiteness

## ISet::lemma_map_by_finite
- path: vstd/iset_lib.rs:744  (proof fn)
- sig: `pub broadcast proof fn lemma_map_by_finite<B>(self, fwd: spec_fn(A) -> B, rev: spec_fn(B) -> A)`
- requires: self.finite(),
- ensures: #[trigger] self.map_by(fwd, rev).finite(),
- doc: `map_by` preserves finiteness.

## ISet::lemma_map_flatten_by_finite
- path: vstd/iset_lib.rs:757  (proof fn)
- sig: `pub broadcast proof fn lemma_map_flatten_by_finite<B>( self, fwd: spec_fn(A) -> ISet<B>, rev: spec_fn(B) -> A, )`
- requires: self.finite(), forall|a: A| self.contains(a) ==> fwd(a).finite(),
- ensures: #[trigger] self.map_flatten_by(fwd, rev).finite(),
- doc: `map_flatten_by` preserves finiteness.

## ISet::lemma_iset_all_subset
- path: vstd/iset_lib.rs:783  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_all_subset(self, s2: ISet<A>, p: spec_fn(A) -> bool)`
- requires: #[trigger] self.subset_of(s2), s2.all(p),
- ensures: #[trigger] self.all(p),
- doc: If `self` is a subset of `s2`, and all elements of `s2`

## ISet::lemma_filter_map_finite
- path: vstd/iset_lib.rs:795  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_map_finite<B>(self, f: spec_fn(A) -> Option<B>)`
- requires: self.finite(),
- ensures: #[trigger] self.filter_map(f).finite(),
- doc: `filter_map` preserves finiteness.

## ISet::lemma_to_seq_to_set_id
- path: vstd/iset_lib.rs:816  (proof fn)
- sig: `pub broadcast proof fn lemma_to_seq_to_set_id(self)`
- requires: self.finite(),
- ensures: #[trigger] self.to_seq().to_set().to_iset() =~= self,
- doc: Conversion to a sequence and back to a set is the identity function.

## ISet::flatten
- path: vstd/iset_lib.rs:843  (spec fn)
- sig: `pub open spec fn flatten(self) -> ISet<A>`
- doc: This function creates a set from all the elements of all the elements

## ISet::flatten_insert_union_commute
- path: vstd/iset_lib.rs:852  (proof fn)
- sig: `pub broadcast proof fn flatten_insert_union_commute(self, other: ISet<A>)`
- ensures: self.flatten().union(other) =~= #[trigger] self.insert(other).flatten(),
- doc: Flattening then unioning with another set is equivalent to

## ISet::lemma_flatten_finite
- path: vstd/iset_lib.rs:874  (proof fn)
- sig: `pub proof fn lemma_flatten_finite(self)`
- requires: self.finite(), forall|s: ISet<A>| self.contains(s) ==> #[trigger] s.finite(),
- ensures: self.flatten().finite(),
- doc: If `self` is finite and all its elements are finite, then `self.flatten()`

## lemma_isets_eq_iff_injective_map_eq
- path: vstd/iset_lib.rs:896  (proof fn)
- sig: `pub proof fn lemma_isets_eq_iff_injective_map_eq<T, S>(s1: ISet<T>, s2: ISet<T>, f: spec_fn(T) -> S)`
- requires: super::relations::injective(f),
- ensures: (s1 == s2) <==> (s1.map(f) == s2.map(f)),
- doc: Two sets are equal iff mapping `f` results in equal sets, if `f` is injective.

## lemma_isets_eq_iff_injective_map_on_eq
- path: vstd/iset_lib.rs:918  (proof fn)
- sig: `pub proof fn lemma_isets_eq_iff_injective_map_on_eq<T, S>( s1: ISet<T>, s2: ISet<T>, f: spec_fn(T) -> S, )`
- requires: (s1 + s2).injective_on(f),
- ensures: (s1 == s2) <==> (s1.map(f) == s2.map(f)),
- doc: Two sets are equal iff applying an injective (in the union of the sets) function `f` to each set produces equal sets.

## lemma_iset_insert_finite_iff
- path: vstd/iset_lib.rs:944  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_insert_finite_iff<A>(s: ISet<A>, a: A)`
- ensures: #[trigger] s.insert(a).finite() <==> s.finite(),
- doc: The result of inserting an element `a` into a set `s` is finite iff `s` is finite.

## lemma_iset_remove_finite_iff
- path: vstd/iset_lib.rs:959  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_remove_finite_iff<A>(s: ISet<A>, a: A)`
- ensures: #[trigger] s.remove(a).finite() <==> s.finite(),
- doc: The result of removing an element `a` into a set `s` is finite iff `s` is finite.

## lemma_iset_union_finite_iff
- path: vstd/iset_lib.rs:973  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_union_finite_iff<A>(s1: ISet<A>, s2: ISet<A>)`
- ensures: #[trigger] s1.union(s2).finite() <==> s1.finite() && s2.finite(),
- doc: The union of two sets is finite iff both sets are finite.

## lemma_iset_union_finite_implies_sets_finite
- path: vstd/iset_lib.rs:984  (proof fn)
- sig: `pub proof fn lemma_iset_union_finite_implies_sets_finite<A>(s1: ISet<A>, s2: ISet<A>)`
- requires: s1.union(s2).finite(),
- ensures: s1.finite(), s2.finite(),
- doc: If the union of two `ISet`s is finite, then each of those `ISet`s

## lemma_len_union
- path: vstd/iset_lib.rs:1014  (proof fn)
- sig: `pub proof fn lemma_len_union<A>(s1: ISet<A>, s2: ISet<A>)`
- requires: s1.finite(), s2.finite(),
- ensures: s1.union(s2).len() <= s1.len() + s2.len(),
- doc: The size of a union of two sets is less than or equal to the size of

## lemma_len_union_ind
- path: vstd/iset_lib.rs:1037  (proof fn)
- sig: `pub proof fn lemma_len_union_ind<A>(s1: ISet<A>, s2: ISet<A>)`
- requires: s1.finite(), s2.finite(),
- ensures: s1.union(s2).len() >= s1.len(), s1.union(s2).len() >= s2.len(),
- doc: The size of a union of two sets is greater than or equal to the size of

## lemma_len_intersect
- path: vstd/iset_lib.rs:1062  (proof fn)
- sig: `pub proof fn lemma_len_intersect<A>(s1: ISet<A>, s2: ISet<A>)`
- requires: s1.finite(),
- ensures: s1.intersect(s2).len() <= s1.len(),
- doc: The size of the intersection of finite set `s1` and set `s2` is less than or equal to the size of `s1`.

## lemma_len_subset
- path: vstd/iset_lib.rs:1080  (proof fn)
- sig: `pub proof fn lemma_len_subset<A>(s1: ISet<A>, s2: ISet<A>)`
- requires: s2.finite(), s1.subset_of(s2),
- ensures: s1.len() <= s2.len(), s1.finite(),
- doc: If `s1` is a subset of finite set `s2`, then the size of `s1` is less than or equal to

## lemma_iset_subset_finite
- path: vstd/iset_lib.rs:1093  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_subset_finite<A>(s: ISet<A>, sub: ISet<A>)`
- requires: s.finite(), sub.subset_of(s),
- ensures: #![trigger sub.subset_of(s)] sub.finite(),
- doc: A subset of a finite set `s` is finite.

## lemma_len_difference
- path: vstd/iset_lib.rs:1106  (proof fn)
- sig: `pub proof fn lemma_len_difference<A>(s1: ISet<A>, s2: ISet<A>)`
- requires: s1.finite(),
- ensures: s1.difference(s2).len() <= s1.len(),
- doc: The size of the difference of finite set `s1` and set `s2` is less than or equal to the size of `s1`.

## set_int_range
- path: vstd/iset_lib.rs:1123  (spec fn)
- sig: `pub open spec fn set_int_range(lo: int, hi: int) -> ISet<int>`
- doc: Creates a finite set of integers in the range [lo, hi).

## lemma_int_range
- path: vstd/iset_lib.rs:1129  (proof fn)
- sig: `pub proof fn lemma_int_range(lo: int, hi: int)`
- requires: lo <= hi,
- ensures: set_int_range(lo, hi).finite(), set_int_range(lo, hi).len() == hi - lo,
- doc: If a set solely contains integers in the range [a, b), then its size is

## lemma_subset_equality
- path: vstd/iset_lib.rs:1146  (proof fn)
- sig: `pub proof fn lemma_subset_equality<A>(x: ISet<A>, y: ISet<A>)`
- requires: x.subset_of(y), x.finite(), y.finite(), x.len() == y.len(),
- ensures: x =~= y,
- doc: If x is a subset of y and the size of x is equal to the size of y, x is equal to y.

## lemma_map_size
- path: vstd/iset_lib.rs:1167  (proof fn)
- sig: `pub proof fn lemma_map_size<A, B>(x: ISet<A>, y: ISet<B>, f: spec_fn(A) -> B)`
- requires: x.finite(), x.injective_on(f), x.map(f) == y,
- ensures: y.finite(), x.len() == y.len(),
- doc: If an injective function is applied to each element of a set to construct

## lemma_map_size_bound
- path: vstd/iset_lib.rs:1193  (proof fn)
- sig: `pub proof fn lemma_map_size_bound<A, B>(x: ISet<A>, y: ISet<B>, f: spec_fn(A) -> B)`
- requires: x.finite(), x.map(f) == y,
- ensures: y.finite(), y.len() <= x.len(),
- doc: If any function is applied to each element of a set to construct

## lemma_iset_union_again1
- path: vstd/iset_lib.rs:1230  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_union_again1<A>(a: ISet<A>, b: ISet<A>)`
- ensures: #[trigger] a.union(b).union(b) =~= a.union(b),
- doc: Taking the union of sets `a` and `b` and then taking the union of the result with `b`

## lemma_iset_union_again2
- path: vstd/iset_lib.rs:1239  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_union_again2<A>(a: ISet<A>, b: ISet<A>)`
- ensures: #[trigger] a.union(b).union(a) =~= a.union(b),
- doc: Taking the union of sets `a` and `b` and then taking the union of the result with `a`

## lemma_iset_intersect_again1
- path: vstd/iset_lib.rs:1248  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_intersect_again1<A>(a: ISet<A>, b: ISet<A>)`
- ensures: #![trigger (a.intersect(b)).intersect(b)] (a.intersect(b)).intersect(b) =~= a.intersect(b),
- doc: Taking the intersection of sets `a` and `b` and then taking the intersection of the result with `b`

## lemma_iset_intersect_again2
- path: vstd/iset_lib.rs:1258  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_intersect_again2<A>(a: ISet<A>, b: ISet<A>)`
- ensures: #![trigger (a.intersect(b)).intersect(a)] (a.intersect(b)).intersect(a) =~= a.intersect(b),
- doc: Taking the intersection of sets `a` and `b` and then taking the intersection of the result with `a`

## lemma_iset_difference2
- path: vstd/iset_lib.rs:1267  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_difference2<A>(s1: ISet<A>, s2: ISet<A>, a: A)`
- ensures: #![trigger s1.difference(s2).contains(a)] s2.contains(a) ==> !s1.difference(s2).contains(a),
- doc: If set `s2` contains element `a`, then the set difference of `s1` and `s2` does not contain `a`.

## lemma_iset_disjoint
- path: vstd/iset_lib.rs:1277  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_disjoint<A>(a: ISet<A>, b: ISet<A>)`
- ensures: #![trigger (a + b).difference(a)]  //TODO: this might be too free a.disjoint(b) ==> ((a + b).difference(a) =~= b && (a + b).difference(b) =~= a),
- doc: If sets `a` and `b` are disjoint, meaning they have no elements in common, then the set difference

## lemma_iset_empty_equivalency_len
- path: vstd/iset_lib.rs:1291  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_empty_equivalency_len<A>(s: ISet<A>)`
- requires: s.finite(),
- ensures: #![trigger s.len()] (s.len() == 0 <==> s == ISet::<A>::empty()) && (s.len() != 0 ==> exists|x: A| s.contains(x)),
- doc: ISet `s` has length 0 if and only if it is equal to the empty set. If `s` has length greater than 0,

## lemma_iset_disjoint_lens
- path: vstd/iset_lib.rs:1319  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_disjoint_lens<A>(a: ISet<A>, b: ISet<A>)`
- requires: a.finite(), b.finite(),
- ensures: a.disjoint(b) ==> #[trigger] (a + b).len() == a.len() + b.len(),
- doc: If sets `a` and `b` are disjoint, meaning they share no elements in common, then the length

## lemma_iset_disjoint_iff_empty_intersection
- path: vstd/iset_lib.rs:1340  (proof fn)
- sig: `pub proof fn lemma_iset_disjoint_iff_empty_intersection<T>(a: ISet<T>, b: ISet<T>)`
- ensures: a.disjoint(b) <==> a.intersect(b).is_empty(),
- doc: Two sets are disjoint iff their intersection is empty

## lemma_iset_intersect_union_lens
- path: vstd/iset_lib.rs:1366  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_intersect_union_lens<A>(a: ISet<A>, b: ISet<A>)`
- requires: a.finite(), b.finite(),
- ensures: #[trigger] (a + b).len() + #[trigger] a.intersect(b).len() == a.len() + b.len(),
- doc: The length of the union between two sets added to the length of the intersection between the

## lemma_iset_difference_len
- path: vstd/iset_lib.rs:1398  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_difference_len<A>(a: ISet<A>, b: ISet<A>)`
- requires: a.finite(), b.finite(),
- ensures: (#[trigger] a.difference(b).len() + b.difference(a).len() + a.intersect(b).len() == (a + b).len()) && (a.difference(b).len() == a.len() - a.intersect(b).len()),
- doc: The length of the set difference `A \ B` added to the length of the set difference `B \ A` added to

## group_iset_properties
- path: vstd/iset_lib.rs  (broadcast group)
- members: lemma_iset_union_again1 lemma_iset_union_again2 lemma_iset_intersect_again1 lemma_iset_intersect_again2 lemma_iset_difference2 lemma_iset_disjoint lemma_iset_disjoint_lens lemma_iset_intersect_union_lens lemma_iset_difference_len // REVIEW: exclude from broadcast group if trigger is too free //         also note that some proofs in seq_lib requires this lemma lemma_iset_empty_equivalency_len

## lemma_iset_is_empty_len0
- path: vstd/iset_lib.rs:1457  (proof fn)
- sig: `pub broadcast proof fn lemma_iset_is_empty_len0<A>(s: ISet<A>)`
- ensures: #[trigger] s.is_empty() <==> (s.finite() && s.len() == 0),

## check_argument_is_set
- path: vstd/iset_lib.rs:1465  (spec fn)
- sig: `pub open spec fn check_argument_is_set<A>(s: ISet<A>) -> ISet<A>`

## group_iset_lib_default
- path: vstd/iset_lib.rs  (broadcast group)
- members: axiom_iset_is_empty lemma_iset_is_empty_len0 lemma_iset_subset_finite ISet::lemma_map_by_finite ISet::lemma_map_flatten_by_finite

## obeys_partial_cmp_spec_properties
- path: vstd/laws_cmp.rs:12  (spec fn)
- sig: `pub open spec fn obeys_partial_cmp_spec_properties<T: PartialOrd>() -> bool`

## obeys_cmp_partial_ord
- path: vstd/laws_cmp.rs:32  (spec fn)
- sig: `pub open spec fn obeys_cmp_partial_ord<T: PartialOrd>() -> bool`

## obeys_cmp_ord
- path: vstd/laws_cmp.rs:39  (spec fn)
- sig: `pub open spec fn obeys_cmp_ord<T: Ord>() -> bool`

## obeys_cmp
- path: vstd/laws_cmp.rs:47  (spec fn)
- sig: `pub open spec fn obeys_cmp<T: Ord>() -> bool`

## obeys_cmp_spec
- path: vstd/laws_cmp.rs:56  (spec fn)
- sig: `pub open spec fn obeys_cmp_spec<T: Ord>() -> bool`

## lemma_obeys_cmp_spec
- path: vstd/laws_cmp.rs:66  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_cmp_spec()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- ensures: #[trigger] obeys_cmp::<$n>(),

## lemma_obeys_cmp_spec
- path: vstd/laws_cmp.rs:112  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_cmp_spec<$($T,)+>() where $($T: Ord + PartialEq,)+`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: $(obeys_cmp::<$T>(),)+
- ensures: #[trigger] obeys_cmp::<($($T,)+)>(),

## lemma_obeys_cmp_spec
- path: vstd/laws_cmp.rs:172  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_cmp_spec<$U, $($T,)+>() where $U: Ord + PartialEq, $($T: Ord + PartialEq,)+`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: obeys_cmp::<$U>(), $(obeys_cmp::<$T>(),)+
- ensures: #[trigger] obeys_cmp::<($U, $($T,)+)>(),

## lemma_ref_obeys_cmp_spec
- path: vstd/laws_cmp.rs:215  (proof fn)
- sig: `pub broadcast proof fn lemma_ref_obeys_cmp_spec<T: Ord>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::laws_cmp::group_laws_cmp`: write `broadcast use vstd::laws_cmp::group_laws_cmp;` and the fact is available.
- requires: obeys_cmp::<T>(),
- ensures: #[trigger] obeys_cmp::<&T>(),

## lemma_option_obeys_cmp_spec
- path: vstd/laws_cmp.rs:236  (proof fn)
- sig: `pub broadcast proof fn lemma_option_obeys_cmp_spec<T: Ord>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::laws_cmp::group_laws_cmp`: write `broadcast use vstd::laws_cmp::group_laws_cmp;` and the fact is available.
- requires: obeys_cmp::<T>(),
- ensures: #[trigger] obeys_cmp::<Option<T>>(),

## group_laws_cmp
- path: vstd/laws_cmp.rs  (broadcast group)
- members: u8_laws::lemma_obeys_cmp_spec i8_laws::lemma_obeys_cmp_spec u16_laws::lemma_obeys_cmp_spec i16_laws::lemma_obeys_cmp_spec u32_laws::lemma_obeys_cmp_spec i32_laws::lemma_obeys_cmp_spec u64_laws::lemma_obeys_cmp_spec i64_laws::lemma_obeys_cmp_spec u128_laws::lemma_obeys_cmp_spec i128_laws::lemma_obeys_cmp_spec usize_laws::lemma_obeys_cmp_spec isize_laws::lemma_obeys_cmp_spec lemma_ref_obeys_cmp_spec lemma_option_obeys_cmp_spec tuple_1_laws::lemma_obeys_cmp_spec tuple_2_laws::lemma_obeys_cmp_spec tuple_3_laws::lemma_obeys_cmp_spec tuple_4_laws::lemma_obeys_cmp_spec tuple_5_laws::lemma_obeys_cmp_spec tuple_6_laws::lemma_obeys_cmp_spec tuple_7_laws::lemma_obeys_cmp_spec tuple_8_laws::lemma_obeys_cmp_spec tuple_9_laws::lemma_obeys_cmp_spec tuple_10_laws::lemma_obeys_cmp_spec tuple_11_laws::lemma_obeys_cmp_spec tuple_12_laws::lemma_obeys_cmp_spec

## obeys_eq_spec_properties
- path: vstd/laws_eq.rs:11  (spec fn)
- sig: `pub open spec fn obeys_eq_spec_properties<T: PartialEq>() -> bool`

## obeys_eq
- path: vstd/laws_eq.rs:17  (spec fn)
- sig: `pub open spec fn obeys_eq<T: PartialEq>() -> bool`

## obeys_eq_spec
- path: vstd/laws_eq.rs:24  (spec fn)
- sig: `pub open spec fn obeys_eq_spec<T: PartialEq>() -> bool`

## obeys_concrete_eq
- path: vstd/laws_eq.rs:29  (spec fn)
- sig: `pub open spec fn obeys_concrete_eq<T: PartialEq>() -> bool`

## obeys_view_eq
- path: vstd/laws_eq.rs:35  (spec fn)
- sig: `pub open spec fn obeys_view_eq<T: PartialEq + View>() -> bool`

## obeys_deep_eq
- path: vstd/laws_eq.rs:41  (spec fn)
- sig: `pub open spec fn obeys_deep_eq<T: PartialEq + DeepView>() -> bool`

## axiom_structural_obeys_concrete_eq
- path: vstd/laws_eq.rs:46  (proof fn)
- sig: `pub broadcast proof fn axiom_structural_obeys_concrete_eq<T: PartialEq + Structural>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::laws_eq::group_laws_eq`: write `broadcast use vstd::laws_eq::group_laws_eq;` and the fact is available.
- requires: T::obeys_eq_spec(), forall|x: T, y: T| x.eq_spec(&y) <==> x == y,
- ensures: #[trigger] obeys_concrete_eq::<T>(),

## lemma_obeys_eq_spec
- path: vstd/laws_eq.rs:62  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_eq_spec()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- ensures: #[trigger] obeys_eq::<$n>(),

## lemma_obeys_concrete_eq
- path: vstd/laws_eq.rs:69  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_concrete_eq()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- ensures: #[trigger] obeys_concrete_eq::<$n>(),

## lemma_obeys_view_eq
- path: vstd/laws_eq.rs:76  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_view_eq()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- ensures: #[trigger] obeys_view_eq::<$n>(),

## lemma_obeys_deep_eq
- path: vstd/laws_eq.rs:83  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_deep_eq()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- ensures: #[trigger] obeys_deep_eq::<$n>(),

## group_laws_eq
- path: vstd/laws_eq.rs  (broadcast group)
- members: lemma_obeys_eq_spec lemma_obeys_concrete_eq lemma_obeys_view_eq lemma_obeys_deep_eq

## lemma_obeys_eq_spec
- path: vstd/laws_eq.rs:133  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_eq_spec<$($T,)+>() where $($T: PartialEq,)+`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: $(obeys_eq::<$T>(),)+
- ensures: #[trigger] obeys_eq::<($($T,)+)>(),

## lemma_obeys_concrete_eq
- path: vstd/laws_eq.rs:144  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_concrete_eq<$($T,)+>() where $($T: PartialEq,)+`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: $(obeys_concrete_eq::<$T>(),)+
- ensures: #[trigger] obeys_concrete_eq::<($($T,)+)>(),

## lemma_obeys_view_eq
- path: vstd/laws_eq.rs:155  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_view_eq<$($T,)+>() where $($T: PartialEq + View,)+`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: $(obeys_view_eq::<$T>(),)+
- ensures: #[trigger] obeys_view_eq::<($($T,)+)>(),

## lemma_obeys_deep_eq
- path: vstd/laws_eq.rs:166  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_deep_eq<$($T,)+>() where $($T: PartialEq + DeepView,)+`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: $(obeys_deep_eq::<$T>(),)+
- ensures: #[trigger] obeys_deep_eq::<($($T,)+)>(),

## group_laws_eq
- path: vstd/laws_eq.rs  (broadcast group)
- members: lemma_obeys_eq_spec lemma_obeys_concrete_eq lemma_obeys_view_eq lemma_obeys_deep_eq

## lemma_obeys_eq_spec
- path: vstd/laws_eq.rs:209  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_eq_spec<$U, $($T,)+>() where $U: PartialEq, $($T: PartialEq,)+`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: obeys_eq::<$U>(), $(obeys_eq::<$T>(),)+
- ensures: #[trigger] obeys_eq::<($U, $($T,)+)>(),

## lemma_obeys_concrete_eq
- path: vstd/laws_eq.rs:225  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_concrete_eq<$U, $($T,)+>() where $U: PartialEq, $($T: PartialEq,)+`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: obeys_concrete_eq::<$U>(), $(obeys_concrete_eq::<$T>(),)+
- ensures: #[trigger] obeys_concrete_eq::<($U, $($T,)+)>(),

## lemma_obeys_view_eq
- path: vstd/laws_eq.rs:238  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_view_eq<$U, $($T,)+>() where $U: PartialEq + View, $($T: PartialEq + View,)+`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: obeys_view_eq::<$U>(), $(obeys_view_eq::<$T>(),)+
- ensures: #[trigger] obeys_view_eq::<($U, $($T,)+)>(),

## lemma_obeys_deep_eq
- path: vstd/laws_eq.rs:253  (proof fn)
- sig: `pub broadcast proof fn lemma_obeys_deep_eq<$U, $($T,)+>() where $U: PartialEq + DeepView, $($T: PartialEq + DeepView,)+`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: obeys_deep_eq::<$U>(), $(obeys_deep_eq::<$T>(),)+
- ensures: #[trigger] obeys_deep_eq::<($U, $($T,)+)>(),

## group_laws_eq
- path: vstd/laws_eq.rs  (broadcast group)
- members: lemma_obeys_eq_spec lemma_obeys_concrete_eq lemma_obeys_view_eq lemma_obeys_deep_eq

## lemma_ref_obeys_eq_spec
- path: vstd/laws_eq.rs:301  (proof fn)
- sig: `pub broadcast proof fn lemma_ref_obeys_eq_spec<T: PartialEq>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::laws_eq::group_laws_eq`: write `broadcast use vstd::laws_eq::group_laws_eq;` and the fact is available.
- requires: obeys_eq::<T>(),
- ensures: #[trigger] obeys_eq::<&T>(),

## lemma_ref_obeys_concrete_eq
- path: vstd/laws_eq.rs:310  (proof fn)
- sig: `pub broadcast proof fn lemma_ref_obeys_concrete_eq<T: PartialEq>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::laws_eq::group_laws_eq`: write `broadcast use vstd::laws_eq::group_laws_eq;` and the fact is available.
- requires: obeys_concrete_eq::<T>(),
- ensures: #[trigger] obeys_concrete_eq::<&T>(),

## lemma_ref_obeys_view_eq
- path: vstd/laws_eq.rs:319  (proof fn)
- sig: `pub broadcast proof fn lemma_ref_obeys_view_eq<T: PartialEq + View>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::laws_eq::group_laws_eq`: write `broadcast use vstd::laws_eq::group_laws_eq;` and the fact is available.
- requires: obeys_view_eq::<T>(),
- ensures: #[trigger] obeys_view_eq::<&T>(),

## lemma_ref_obeys_deep_eq
- path: vstd/laws_eq.rs:328  (proof fn)
- sig: `pub broadcast proof fn lemma_ref_obeys_deep_eq<T: PartialEq + DeepView>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::laws_eq::group_laws_eq`: write `broadcast use vstd::laws_eq::group_laws_eq;` and the fact is available.
- requires: obeys_deep_eq::<T>(),
- ensures: #[trigger] obeys_deep_eq::<&T>(),

## lemma_option_obeys_eq_spec
- path: vstd/laws_eq.rs:339  (proof fn)
- sig: `pub broadcast proof fn lemma_option_obeys_eq_spec<T: PartialEq>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::laws_eq::group_laws_eq`: write `broadcast use vstd::laws_eq::group_laws_eq;` and the fact is available.
- requires: obeys_eq::<T>(),
- ensures: #[trigger] obeys_eq::<Option<T>>(),

## lemma_option_obeys_concrete_eq
- path: vstd/laws_eq.rs:348  (proof fn)
- sig: `pub broadcast proof fn lemma_option_obeys_concrete_eq<T: PartialEq>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::laws_eq::group_laws_eq`: write `broadcast use vstd::laws_eq::group_laws_eq;` and the fact is available.
- requires: obeys_concrete_eq::<T>(),
- ensures: #[trigger] obeys_concrete_eq::<Option<T>>(),

## lemma_option_obeys_view_eq
- path: vstd/laws_eq.rs:357  (proof fn)
- sig: `pub broadcast proof fn lemma_option_obeys_view_eq<T: PartialEq + View>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::laws_eq::group_laws_eq`: write `broadcast use vstd::laws_eq::group_laws_eq;` and the fact is available.
- requires: obeys_concrete_eq::<T>(),
- ensures: #[trigger] obeys_view_eq::<Option<T>>(),

## lemma_option_obeys_deep_eq
- path: vstd/laws_eq.rs:367  (proof fn)
- sig: `pub broadcast proof fn lemma_option_obeys_deep_eq<T: PartialEq + DeepView>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::laws_eq::group_laws_eq`: write `broadcast use vstd::laws_eq::group_laws_eq;` and the fact is available.
- requires: obeys_deep_eq::<T>(),
- ensures: #[trigger] obeys_deep_eq::<Option<T>>(),

## group_laws_eq
- path: vstd/laws_eq.rs  (broadcast group)
- members: axiom_structural_obeys_concrete_eq bool_laws::group_laws_eq u8_laws::group_laws_eq i8_laws::group_laws_eq u16_laws::group_laws_eq i16_laws::group_laws_eq u32_laws::group_laws_eq i32_laws::group_laws_eq u64_laws::group_laws_eq i64_laws::group_laws_eq u128_laws::group_laws_eq i128_laws::group_laws_eq usize_laws::group_laws_eq isize_laws::group_laws_eq tuple_1_laws::group_laws_eq tuple_2_laws::group_laws_eq tuple_3_laws::group_laws_eq tuple_4_laws::group_laws_eq tuple_5_laws::group_laws_eq tuple_6_laws::group_laws_eq tuple_7_laws::group_laws_eq tuple_8_laws::group_laws_eq tuple_9_laws::group_laws_eq tuple_10_laws::group_laws_eq tuple_11_laws::group_laws_eq tuple_12_laws::group_laws_eq lemma_ref_obeys_eq_spec lemma_ref_obeys_concrete_eq lemma_ref_obeys_view_eq lemma_ref_obeys_deep_eq lemma_option_obeys_eq_spec lemma_option_obeys_concrete_eq lemma_option_obeys_view_eq lemma_option_obeys_deep_eq

## valid_layout
- path: vstd/layout.rs:13  (spec fn)
- sig: `pub open spec fn valid_layout(size: usize, align: usize) -> bool`
- doc: Matches the conditions here: <https://doc.rust-lang.org/stable/std/alloc/struct.Layout.html>

## is_sized
- path: vstd/layout.rs:18  (spec fn)
- sig: `pub uninterp spec fn is_sized<V: ?Sized>() -> bool`

## size_of
- path: vstd/layout.rs:20  (spec fn)
- sig: `pub uninterp spec fn size_of<V>() -> nat`

## align_of
- path: vstd/layout.rs:22  (spec fn)
- sig: `pub uninterp spec fn align_of<V>() -> nat`

## spec_size_of_val
- path: vstd/layout.rs:26  (spec fn)
- sig: `pub uninterp spec fn spec_size_of_val<V: ?Sized>(val: &V) -> nat`
- doc: Spec for `size_of_val`: <https://doc.rust-lang.org/std/mem/fn.size_of_val.html>.

## spec_align_of_val
- path: vstd/layout.rs:29  (spec fn)
- sig: `pub uninterp spec fn spec_align_of_val<V: ?Sized>(val: &V) -> nat`
- doc: Spec for `align_of_val`: <https://doc.rust-lang.org/std/mem/fn.align_of_val.html>.

## size_of_as_usize
- path: vstd/layout.rs:45  (spec fn)
- sig: `pub open spec fn size_of_as_usize<V>() -> usize recommends size_of::<V>() as usize as int == size_of::<V>(),`

## align_of_as_usize
- path: vstd/layout.rs:53  (spec fn)
- sig: `pub open spec fn align_of_as_usize<V>() -> usize recommends align_of::<V>() as usize as int == align_of::<V>(),`

## size_of_val_as_usize
- path: vstd/layout.rs:61  (spec fn)
- sig: `pub open spec fn size_of_val_as_usize<V: ?Sized>(val: &V) -> usize recommends spec_size_of_val::<V>(val) as usize as int == spec_size_of_val::<V>(val),`

## align_of_val_as_usize
- path: vstd/layout.rs:69  (spec fn)
- sig: `pub open spec fn align_of_val_as_usize<V: ?Sized>(val: &V) -> usize recommends spec_align_of_val::<V>(val) as usize as int == spec_align_of_val::<V>(val),`

## core::mem::size_of
- path: vstd/layout.rs:77  (exec spec, assume_specification)
- sig: `pub assume_specification<V>[ core::mem::size_of::<V> ]() -> (u: usize)`
- ensures: u as nat == size_of::<V>(),

## core::mem::align_of
- path: vstd/layout.rs:85  (exec spec, assume_specification)
- sig: `pub assume_specification<V>[ core::mem::align_of::<V> ]() -> (u: usize)`
- ensures: u as nat == align_of::<V>(),

## core::mem::size_of_val
- path: vstd/layout.rs:93  (exec spec, assume_specification)
- sig: `pub assume_specification<V: ?Sized>[ core::mem::size_of_val::<V> ](val: &V) -> (u: usize)`
- ensures: u as nat == spec_size_of_val::<V>(val),

## core::mem::align_of_val
- path: vstd/layout.rs:101  (exec spec, assume_specification)
- sig: `pub assume_specification<V: ?Sized>[ core::mem::align_of_val::<V> ](val: &V) -> (u: usize)`
- ensures: u as nat == spec_align_of_val::<V>(val),

## align_nonzero
- path: vstd/layout.rs:255  (proof fn)
- sig: `pub broadcast proof fn align_nonzero<T>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::layout::group_align_properties`: write `broadcast use vstd::layout::group_align_properties;` and the fact is available.
- ensures: #![trigger align_of::<T>()] align_of::<T>() > 0,
- doc: The alignment is at least 1

## align_of_u8
- path: vstd/layout.rs:268  (proof fn)
- sig: `pub broadcast proof fn align_of_u8()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- ensures: #![trigger align_of::<u8>()] align_of::<u8>() == 1,
- doc: The alignment of `u8` is 1, per [type layout rules](https://doc.rust-lang.org/reference/type-layout.html).

## group_align_properties
- path: vstd/layout.rs  (broadcast group)
- members: align_properties align_nonzero

## group_layout_axioms
- path: vstd/layout.rs  (broadcast group)
- members: layout_of_primitives layout_of_unit_tuple layout_of_references_and_pointers layout_of_references_and_pointers_for_sized_types layout_of_references_and_pointers_for_unsized_types layout_of_slices layout_of_str layout_of_maybe_uninit group_align_properties

## Map::dom
- path: vstd/map.rs:56  (spec fn)
- sig: `pub uninterp spec fn dom(self) -> Set<K>`
- doc: The domain of the map as a set.

## Map::index
- path: vstd/map.rs:60  (spec fn)
- sig: `pub uninterp spec fn index(self, key: K) -> V recommends self.dom().contains(key),`
- doc: Gets the value that the given key `key` maps to.

## Map::new
- path: vstd/map.rs:67  (spec fn)
- sig: `pub uninterp spec fn new(s: Set<K>, fv: spec_fn(K) -> V) -> Map<K, V>`
- doc: Gives a `Map<K, V>` whose domain is given, mapping each key to

## Map::empty
- path: vstd/map.rs:79  (spec fn)
- sig: `pub closed spec fn empty() -> Map<K, V>`
- doc: An empty map.

## Map::spec_index
- path: vstd/map.rs:85  (spec fn)
- sig: `pub open spec fn spec_index(self, key: K) -> V recommends self.dom().contains(key),`
- doc: `[]` operator, synonymous with `index`

## Map::insert
- path: vstd/map.rs:96  (spec fn)
- sig: `pub closed spec fn insert(self, key: K, value: V) -> Map<K, V>`
- doc: Inserts the given (key, value) pair into the map.

## Map::remove
- path: vstd/map.rs:103  (spec fn)
- sig: `pub closed spec fn remove(self, key: K) -> Map<K, V>`
- doc: Removes the given key and its associated value from the map.

## Map::len
- path: vstd/map.rs:108  (spec fn)
- sig: `pub open spec fn len(self) -> nat`
- doc: Returns the number of key-value pairs in the map

## Map::to_imap
- path: vstd/map.rs:113  (spec fn)
- sig: `pub open spec fn to_imap(self) -> IMap<K, V>`
- doc: Converts this `Map` into an equivalent `IMap`

## Map::congruent
- path: vstd/map.rs:118  (spec fn)
- sig: `pub open spec fn congruent(self, m2: IMap<K, V>) -> bool`
- doc: Indicates if this `Map` is equivalent to the given `IMap`.

## lemma_map_new_domain
- path: vstd/map.rs:232  (proof fn)
- sig: `pub broadcast proof fn lemma_map_new_domain<K, V>(s: Set<K>, fv: spec_fn(K) -> V)`
- ensures: #![trigger Map::new(s, fv)] Map::new(s, fv).dom() == s,
- doc: Since `Map::new` is uninterpret, this broadcast lemma is needed to establish

## lemma_map_new_index
- path: vstd/map.rs:242  (proof fn)
- sig: `pub broadcast proof fn lemma_map_new_index<K, V>(s: Set<K>, fv: spec_fn(K) -> V, k: K)`
- requires: s.contains(k),
- ensures: #![trigger Map::new(s, fv)[k]] Map::new(s, fv)[k] == fv(k)
- doc: Since `Map::new` is closed, this broadcast lemma is needed to establish

## lemma_map_empty
- path: vstd/map.rs:253  (proof fn)
- sig: `pub broadcast proof fn lemma_map_empty<K, V>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::map::group_map_lemmas`: write `broadcast use vstd::map::group_map_lemmas;` and the fact is available.
- ensures: #[trigger] Map::<K, V>::empty().dom() == Set::<K>::empty(),
- doc: The domain of the empty map is the empty set

## lemma_map_insert_domain
- path: vstd/map.rs:262  (proof fn)
- sig: `pub broadcast proof fn lemma_map_insert_domain<K, V>(m: Map<K, V>, key: K, value: V)`
- ensures: #[trigger] m.insert(key, value).dom() == m.dom().insert(key),
- doc: The domain of a map after inserting a key-value pair is equivalent to inserting the key into

## lemma_map_insert_same
- path: vstd/map.rs:270  (proof fn)
- sig: `pub broadcast proof fn lemma_map_insert_same<K, V>(m: Map<K, V>, key: K, value: V)`
- ensures: #[trigger] m.insert(key, value)[key] == value,
- doc: Inserting `value` at `key` in `m` results in a map that maps `key` to `value`

## lemma_map_remove_domain
- path: vstd/map.rs:289  (proof fn)
- sig: `pub broadcast proof fn lemma_map_remove_domain<K, V>(m: Map<K, V>, key: K)`
- ensures: #[trigger] m.remove(key).dom() == m.dom().remove(key),
- doc: The domain of a map after removing a key-value pair is equivalent to removing the key from

## axiom_map_ext_equal_deep
- path: vstd/map.rs:319  (proof fn)
- sig: `pub broadcast proof fn axiom_map_ext_equal_deep<K, V>(m1: Map<K, V>, m2: Map<K, V>)`
- ensures: #[trigger] (m1 =~~= m2) <==> { &&& m1.dom() =~~= m2.dom() &&& forall|k: K| #![auto] m1.dom().contains(k) ==> m1[k] =~~= m2[k] },
- doc: Two maps are deeply equivalent if their domains are equivalent and

## group_map_lemmas
- path: vstd/map.rs  (broadcast group)
- members: axiom_map_index_decreases lemma_map_new_domain lemma_map_new_index lemma_map_empty lemma_map_insert_domain lemma_map_insert_same axiom_map_insert_different lemma_map_remove_domain axiom_map_remove_different axiom_map_ext_equal axiom_map_ext_equal_deep

## check_argument_is_map
- path: vstd/map.rs:368  (spec fn)
- sig: `pub open spec fn check_argument_is_map<K, V>(m: Map<K, V>) -> Map<K, V>`

## Map::is_full
- path: vstd/map_lib.rs:25  (spec fn)
- sig: `pub open spec fn is_full(self) -> bool`
- doc: Is `true` if called by a "full" map, i.e., a map containing every element of type `A`.

## Map::is_empty
- path: vstd/map_lib.rs:31  (spec fn)
- sig: `pub open spec fn is_empty(self) -> (b: bool)`
- doc: Is `true` if called by an "empty" map, i.e., a map containing no elements and has length 0

## Map::contains_key
- path: vstd/map_lib.rs:37  (spec fn)
- sig: `pub open spec fn contains_key(self, k: K) -> bool`
- doc: Returns true if the key `k` is in the domain of `self`.

## Map::contains_value
- path: vstd/map_lib.rs:42  (spec fn)
- sig: `pub open spec fn contains_value(self, v: V) -> bool`
- doc: Returns true if the value `v` is in the range of `self`.

## Map::index_opt
- path: vstd/map_lib.rs:48  (spec fn)
- sig: `pub open spec fn index_opt(self, k: K) -> Option<V>`
- doc: Returns `Some(v)` if the key `k` is in the domain of `self` and maps to `v`,

## Map::values
- path: vstd/map_lib.rs:69  (spec fn)
- sig: `pub open spec fn values(self) -> Set<V>`

## Map::kv_pairs
- path: vstd/map_lib.rs:86  (spec fn)
- sig: `pub open spec fn kv_pairs(self) -> Set<(K, V)>`

## Map::contains_pair
- path: vstd/map_lib.rs:91  (spec fn)
- sig: `pub open spec fn contains_pair(self, k: K, v: V) -> bool`
- doc: Returns true if the key `k` is in the domain of `self`, and it maps to the value `v`.

## Map::submap_of
- path: vstd/map_lib.rs:109  (spec fn)
- sig: `pub open spec fn submap_of(self, m2: Self) -> bool`
- doc: Returns true if `m1` is _contained in_ `m2`, i.e., the domain of `m1` is a subset

## Map::spec_le
- path: vstd/map_lib.rs:115  (spec fn)
- sig: `pub open spec fn spec_le(self, m2: Self) -> bool`

## Map::union_prefer_right
- path: vstd/map_lib.rs:132  (spec fn)
- sig: `pub open spec fn union_prefer_right(self, m2: Self) -> Self`
- doc: Gives the union of two maps, defined as:

## Map::remove_keys
- path: vstd/map_lib.rs:155  (spec fn)
- sig: `pub open spec fn remove_keys(self, keys: Set<K>) -> Self`
- doc: Removes the given keys and their associated values from the map.

## Map::restrict
- path: vstd/map_lib.rs:170  (spec fn)
- sig: `pub open spec fn restrict(self, keys: Set<K>) -> Self`
- doc: Complement to `remove_keys`. Restricts the map to (key, value) pairs

## Map::is_equal_on_key
- path: vstd/map_lib.rs:175  (spec fn)
- sig: `pub open spec fn is_equal_on_key(self, m2: Self, key: K) -> bool`
- doc: Returns `true` if and only if the given key maps to the same value or does not exist in self and m2.

## Map::agrees
- path: vstd/map_lib.rs:181  (spec fn)
- sig: `pub open spec fn agrees(self, m2: Self) -> bool`
- doc: Returns `true` if the two given maps agree on all keys that their domains share

## Map::map_entries
- path: vstd/map_lib.rs:186  (spec fn)
- sig: `pub open spec fn map_entries<W>(self, f: spec_fn(K, V) -> W) -> Map<K, W>`
- doc: Map a function `f` over all (k, v) pairs in `self`.

## Map::map_values
- path: vstd/map_lib.rs:191  (spec fn)
- sig: `pub open spec fn map_values<W>(self, f: spec_fn(V) -> W) -> Map<K, W>`
- doc: Map a function `f` over the values in `self`.

## Map::is_injective
- path: vstd/map_lib.rs:196  (spec fn)
- sig: `pub open spec fn is_injective(self) -> bool`
- doc: Returns `true` if and only if a map is injective

## Map::invert
- path: vstd/map_lib.rs:204  (spec fn)
- sig: `pub open spec fn invert(self) -> Map<V, K>`
- doc: Swaps map keys and values. Values are not required to be unique; no

## Map::lemma_remove_key_len
- path: vstd/map_lib.rs:211  (proof fn)
- sig: `pub proof fn lemma_remove_key_len(self, key: K)`
- requires: self.dom().contains(key),
- ensures: self.dom().len() == 1 + self.remove(key).dom().len(),
- doc: Removing a key from a map that previously contained that key decreases

## Map::lemma_remove_equivalency
- path: vstd/map_lib.rs:221  (proof fn)
- sig: `pub proof fn lemma_remove_equivalency(self, key: K)`
- ensures: self.remove(key).dom() == self.dom().remove(key),
- doc: The domain of a map after removing a key is equivalent to removing the key from

## Map::lemma_remove_keys_len
- path: vstd/map_lib.rs:229  (proof fn)
- sig: `pub proof fn lemma_remove_keys_len(self, keys: Set<K>)`
- requires: forall|k: K| #[trigger] keys.contains(k) ==> self.contains_key(k),
- ensures: self.remove_keys(keys).dom().len() == self.dom().len() - keys.len(),
- doc: Removing a set of n keys from a map that previously contained all n keys

## Map::lemma_invert_is_injective
- path: vstd/map_lib.rs:249  (proof fn)
- sig: `pub proof fn lemma_invert_is_injective(self)`
- ensures: self.invert().is_injective(),
- doc: The function `invert` results in an injective map

## Map::filter_keys
- path: vstd/map_lib.rs:278  (spec fn)
- sig: `pub open spec fn filter_keys(self, p: spec_fn(K) -> bool) -> Self`
- doc: Keeps only those key-value pairs whose key satisfies `p`.

## Map::get
- path: vstd/map_lib.rs:297  (spec fn)
- sig: `pub open spec fn get(self, k: K) -> Option<V>`
- doc: Returns the value associated with key `k` in the map if it exists,

## Map::lemma_submap_eq_iff
- path: vstd/map_lib.rs:342  (proof fn)
- sig: `pub proof fn lemma_submap_eq_iff(self, m: Self)`
- ensures: (self == m) <==> (self.submap_of(m) && m.submap_of(self)),
- doc: Two maps are equal if and only if they are submaps of each other.

## Map::lemma_map_remove_keys_insert
- path: vstd/map_lib.rs:372  (proof fn)
- sig: `pub broadcast proof fn lemma_map_remove_keys_insert(self, r: Set<K>, k: K, v: V)`
- ensures: #[trigger] self.insert(k, v).remove_keys(r) == if r.contains(k) { self.remove_keys(r) } else { self.remove_keys(r).insert(k, v) },
- doc: When removing a set of keys from a map after inserting (k,v),

## Map::lemma_filter_keys_insert
- path: vstd/map_lib.rs:405  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_keys_insert(self, p: spec_fn(K) -> bool, k: K, v: V)`
- ensures: #[trigger] self.insert(k, v).filter_keys(p) == (if p(k) { self.filter_keys(p).insert(k, v) } else { self.filter_keys(p) }),
- doc: Filtering keys after inserting `(k, v)` leaves the result unchanged when `p(k)` is false,

## Map::lemma_insert_contains_value
- path: vstd/map_lib.rs:433  (proof fn)
- sig: `pub broadcast proof fn lemma_insert_contains_value(self, k: K, v: V)`
- ensures: #[trigger] self.insert(k, v).contains_value(v),
- doc: Inserting a value in a map means it contains the value that was inserted.

## Map::lemma_insert_invariant_contains
- path: vstd/map_lib.rs:451  (proof fn)
- sig: `pub broadcast proof fn lemma_insert_invariant_contains(self, old_v: V, k: K, v: V)`
- requires: self.contains_key(k) ==> self[k] != old_v, old_v != v,
- ensures: #[trigger] self.insert(k, v).contains_value(old_v) == self.contains_value(old_v),
- doc: Inserting a value in a map where that key is already present ensures

## Map::lemma_injective_values_len
- path: vstd/map_lib.rs:464  (proof fn)
- sig: `pub proof fn lemma_injective_values_len(self)`
- requires: self.is_injective(),
- ensures: self.values().len() == self.dom().len(),

## Map::lemma_values_len
- path: vstd/map_lib.rs:484  (proof fn)
- sig: `pub proof fn lemma_values_len(self)`
- ensures: self.values().len() <= self.dom().len(),

## Map::prefixed_entries
- path: vstd/map_lib.rs:518  (spec fn)
- sig: `pub open spec fn prefixed_entries(self, prefix: Seq<K>) -> Self`
- doc: Returns a sub-map of all entries whose key begins with `prefix`,

## Map::lemma_prefixed_entries_get
- path: vstd/map_lib.rs:591  (proof fn)
- sig: `pub broadcast proof fn lemma_prefixed_entries_get(self, prefix: Seq<K>, k: Seq<K>)`
- requires: self.prefixed_entries(prefix).contains_key(k),
- ensures: self.prefixed_entries(prefix)[k] == #[trigger] self[prefix + k],
- doc: For every key `k` kept by `prefixed_entries(prefix)`,

## Map::lemma_prefixed_entries_contains
- path: vstd/map_lib.rs:620  (proof fn)
- sig: `pub broadcast proof fn lemma_prefixed_entries_contains(self, prefix: Seq<K>, k: Seq<K>)`
- ensures: #[trigger] self.prefixed_entries(prefix).contains_key(k) <==> self.contains_key( prefix + k, ),
- doc: A key `k` is in `prefixed_entries(prefix)` exactly when the original map

## Map::lemma_prefixed_entries_insert
- path: vstd/map_lib.rs:649  (proof fn)
- sig: `pub broadcast proof fn lemma_prefixed_entries_insert(self, prefix: Seq<K>, k: Seq<K>, v: V)`
- ensures: #[trigger] self.insert(prefix + k, v).prefixed_entries(prefix) == self.prefixed_entries( prefix, ).insert(k, v),
- doc: Inserting `(prefix + k, v)` before taking `prefixed_entries(prefix)`

## Map::lemma_prefixed_entries_union
- path: vstd/map_lib.rs:684  (proof fn)
- sig: `pub broadcast proof fn lemma_prefixed_entries_union(self, m: Self, prefix: Seq<K>)`
- ensures: #[trigger] self.union_prefer_right(m).prefixed_entries(prefix) == self.prefixed_entries( prefix, ).union_prefer_right(m.prefixed_entries(prefix)),
- doc: Taking the entries that share `prefix` commutes with `union_prefer_right`:

## Map::is_monotonic
- path: vstd/map_lib.rs:706  (spec fn)
- sig: `pub open spec fn is_monotonic(self) -> bool`
- doc: Returns `true` if a map is monotonic -- that is, if the mapping between ordered sets

## Map::is_monotonic_from
- path: vstd/map_lib.rs:714  (spec fn)
- sig: `pub open spec fn is_monotonic_from(self, start: int) -> bool`
- doc: Returns `true` if and only if a map is monotonic, only considering keys greater than

## lemma_union_insert_left
- path: vstd/map_lib.rs:722  (proof fn)
- sig: `pub broadcast proof fn lemma_union_insert_left<K, V>(m1: Map<K, V>, m2: Map<K, V>, k: K, v: V)`
- requires: !m2.contains_key(k),
- ensures: #[trigger] m1.insert(k, v).union_prefer_right(m2) == m1.union_prefer_right(m2).insert(k, v),

## lemma_union_insert_right
- path: vstd/map_lib.rs:731  (proof fn)
- sig: `pub broadcast proof fn lemma_union_insert_right<K, V>(m1: Map<K, V>, m2: Map<K, V>, k: K, v: V)`
- ensures: #[trigger] m1.union_prefer_right(m2.insert(k, v)) == m1.union_prefer_right(m2).insert(k, v),

## lemma_union_remove_left
- path: vstd/map_lib.rs:738  (proof fn)
- sig: `pub broadcast proof fn lemma_union_remove_left<K, V>(m1: Map<K, V>, m2: Map<K, V>, k: K)`
- requires: m1.contains_key(k), !m2.contains_key(k),
- ensures: #[trigger] m1.union_prefer_right(m2).remove(k) == m1.remove(k).union_prefer_right(m2),

## lemma_union_remove_right
- path: vstd/map_lib.rs:748  (proof fn)
- sig: `pub broadcast proof fn lemma_union_remove_right<K, V>(m1: Map<K, V>, m2: Map<K, V>, k: K)`
- requires: !m1.contains_key(k), m2.contains_key(k),
- ensures: #[trigger] m1.union_prefer_right(m2).remove(k) == m1.union_prefer_right(m2.remove(k)),

## lemma_union_dom
- path: vstd/map_lib.rs:758  (proof fn)
- sig: `pub broadcast proof fn lemma_union_dom<K, V>(m1: Map<K, V>, m2: Map<K, V>)`
- ensures: #[trigger] m1.union_prefer_right(m2).dom() == m1.dom().union(m2.dom()),

## lemma_disjoint_union_size
- path: vstd/map_lib.rs:766  (proof fn)
- sig: `pub broadcast proof fn lemma_disjoint_union_size<K, V>(m1: Map<K, V>, m2: Map<K, V>)`
- requires: m1.dom().disjoint(m2.dom()),
- ensures: #[trigger] m1.union_prefer_right(m2).dom().len() == m1.dom().len() + m2.dom().len(),
- doc: The size of the union of two disjoint maps is equal to the sum of the sizes of the individual maps

## group_map_union
- path: vstd/map_lib.rs  (broadcast group)
- members: lemma_union_dom lemma_union_remove_left lemma_union_remove_right lemma_union_insert_left lemma_union_insert_right lemma_disjoint_union_size

## lemma_submap_of_trans
- path: vstd/map_lib.rs:790  (proof fn)
- sig: `pub broadcast proof fn lemma_submap_of_trans<K, V>(m1: Map<K, V>, m2: Map<K, V>, m3: Map<K, V>)`
- requires: #[trigger] m1.submap_of(m2), #[trigger] m2.submap_of(m3),
- ensures: m1.submap_of(m3),
- doc: submap_of (<=) is transitive.

## lemma_map_new_domain
- path: vstd/map_lib.rs:805  (proof fn)
- sig: `pub broadcast proof fn lemma_map_new_domain<K, V>(s: Set<K>, fv: spec_fn(K) -> V)`
- ensures: #[trigger] Map::<K, V>::new(s, fv).dom() == s,
- doc: The domain of a map constructed with `Map::new(fk, fv)` is equivalent to the set constructed with `Set::new(fk)`.

## lemma_map_new_values
- path: vstd/map_lib.rs:815  (proof fn)
- sig: `pub broadcast proof fn lemma_map_new_values<K, V>(s: Set<K>, fv: spec_fn(K) -> V)`
- ensures: #[trigger] Map::<K, V>::new(s, fv).values() == s.map(fv),
- doc: The set of values of a map constructed with `Map::new(fk, fv)` is equivalent to

## group_map_properties
- path: vstd/map_lib.rs  (broadcast group)
- members: lemma_map_new_domain lemma_map_new_values

## group_map_extra
- path: vstd/map_lib.rs  (broadcast group)
- members: Map::lemma_map_remove_keys_insert Map::lemma_filter_keys_insert Map::lemma_insert_contains_value Map::lemma_insert_invariant_contains Map::lemma_prefixed_entries_get Map::lemma_prefixed_entries_contains Map::lemma_prefixed_entries_insert Map::lemma_prefixed_entries_union

## min
- path: vstd/math.rs:7  (spec fn)
- sig: `pub open spec fn min(x: int, y: int) -> int`
- doc: This function computes the minimum of two given integers.

## max
- path: vstd/math.rs:16  (spec fn)
- sig: `pub open spec fn max(x: int, y: int) -> int`
- doc: This function computes the maximum of two given integers.

## max3
- path: vstd/math.rs:25  (spec fn)
- sig: `pub open spec fn max3(x: int, y: int, z: int) -> int`
- doc: This function computes the maximum of three given integers.

## clip
- path: vstd/math.rs:35  (spec fn)
- sig: `pub open spec fn clip(x: int) -> nat`
- doc: This function converts the given integer `x` to a natural number

## abs
- path: vstd/math.rs:44  (spec fn)
- sig: `pub open spec fn abs(x: int) -> nat`
- doc: This function computes the absolute value of a given integer.

## add
- path: vstd/math.rs:56  (spec fn)
- sig: `pub open spec fn add(x: int, y: int) -> int`
- doc: This function adds two integers together. It's sometimes

## sub
- path: vstd/math.rs:64  (spec fn)
- sig: `pub open spec fn sub(x: int, y: int) -> int`
- doc: This function subtracts two integers. It's sometimes useful as

## div
- path: vstd/math.rs:72  (spec fn)
- sig: `pub open spec fn div(x: int, y: int) -> int`
- doc: This function divides two integers. It's sometimes useful as a

## Multiset::count
- path: vstd/multiset.rs:61  (spec fn)
- sig: `pub uninterp spec fn count(self, value: V) -> nat`
- doc: Returns the _count_, or _multiplicity_ of a single value within the multiset.

## Multiset::len
- path: vstd/multiset.rs:64  (spec fn)
- sig: `pub uninterp spec fn len(self) -> nat`
- doc: The total size of the multiset, i.e., the sum of all multiplicities over all values.

## Multiset::empty
- path: vstd/multiset.rs:67  (spec fn)
- sig: `pub uninterp spec fn empty() -> Self`
- doc: An empty multiset.

## Multiset::from_map
- path: vstd/multiset.rs:71  (spec fn)
- sig: `pub uninterp spec fn from_map(m: Map<V, nat>) -> Self`
- doc: Creates a multiset whose elements are given by the domain of the map `m` and whose

## Multiset::from_set
- path: vstd/multiset.rs:73  (spec fn)
- sig: `pub open spec fn from_set(m: Set<V>) -> Self`

## Multiset::singleton
- path: vstd/multiset.rs:78  (spec fn)
- sig: `pub uninterp spec fn singleton(v: V) -> Self`
- doc: A singleton multiset, i.e., a multiset with a single element of multiplicity 1.

## Multiset::add
- path: vstd/multiset.rs:82  (spec fn)
- sig: `pub uninterp spec fn add(self, m2: Self) -> Self`
- doc: Takes the union of two multisets. For a given element, its multiplicity in

## Multiset::sub
- path: vstd/multiset.rs:91  (spec fn)
- sig: `pub uninterp spec fn sub(self, m2: Self) -> Self`
- doc: Takes the difference of two multisets.

## Multiset::insert
- path: vstd/multiset.rs:96  (spec fn)
- sig: `pub open spec fn insert(self, v: V) -> Self`
- doc: Inserts one instance the value `v` into the multiset.

## Multiset::remove
- path: vstd/multiset.rs:103  (spec fn)
- sig: `pub open spec fn remove(self, v: V) -> Self`
- doc: Removes one instance of the value `v` from the multiset.

## Multiset::update
- path: vstd/multiset.rs:108  (spec fn)
- sig: `pub open spec fn update(self, v: V, mult: nat) -> Self`
- doc: Updates the multiplicity of the value `v` in the multiset to `mult`.

## Multiset::subset_of
- path: vstd/multiset.rs:124  (spec fn)
- sig: `pub open spec fn subset_of(self, m2: Self) -> bool`
- doc: Returns `true` is the left argument is contained in the right argument,

## Multiset::spec_le
- path: vstd/multiset.rs:129  (spec fn)
- sig: `pub open spec fn spec_le(self, m2: Self) -> bool`

## Multiset::filter
- path: vstd/multiset.rs:134  (spec fn)
- sig: `pub uninterp spec fn filter(self, f: impl Fn(V) -> bool) -> Self`

## Multiset::choose
- path: vstd/multiset.rs:142  (spec fn)
- sig: `pub open spec fn choose(self) -> V`
- doc: Chooses an arbitrary value of the multiset.

## Multiset::contains
- path: vstd/multiset.rs:147  (spec fn)
- sig: `pub open spec fn contains(self, v: V) -> bool`
- doc: Predicate indicating if the multiset contains the given value.

## Multiset::spec_has
- path: vstd/multiset.rs:153  (spec fn)
- sig: `pub open spec fn spec_has(self, v: V) -> bool`
- doc: Predicate indicating if the set contains the given element: supports `self has a` syntax.

## Multiset::intersection_with
- path: vstd/multiset.rs:160  (spec fn)
- sig: `pub open spec fn intersection_with(self, other: Self) -> Self`
- doc: Returns a multiset containing the lower count of a given element

## Multiset::difference_with
- path: vstd/multiset.rs:170  (spec fn)
- sig: `pub open spec fn difference_with(self, other: Self) -> Self`
- doc: Returns a multiset containing the difference between the count of a

## Multiset::is_disjoint_from
- path: vstd/multiset.rs:178  (spec fn)
- sig: `pub open spec fn is_disjoint_from(self, other: Self) -> bool`
- doc: Returns true if there exist no elements that have a count greater

## Multiset::dom
- path: vstd/multiset.rs:190  (spec fn)
- sig: `pub closed spec fn dom(self) -> Set<V>`
- doc: Returns the set of all elements that have a count greater than 0

## Multiset::dom_ensures
- path: vstd/multiset.rs:196  (proof fn)
- sig: `pub broadcast proof fn dom_ensures(self)`
- ensures: #![trigger(self.dom())] forall|v: V| #[trigger] self.dom().contains(v) <==> self.count(v) > 0,

## lemma_multiset_empty_len
- path: vstd/multiset.rs:220  (proof fn)
- sig: `pub broadcast proof fn lemma_multiset_empty_len<V>(m: Multiset<V>)`
- ensures: #[trigger] m.len() == 0 <==> m =~= Multiset::empty(), #[trigger] m.len() > 0 ==> exists|v: V| 0 < m.count(v),
- doc: A multiset is equivalent to the empty multiset if and only if it has length 0.

## lemma_from_map_dom
- path: vstd/multiset.rs:251  (proof fn)
- sig: `pub broadcast proof fn lemma_from_map_dom<V>(mymap: Map<V, nat>)`
- requires: forall|k| #[trigger] mymap.contains_key(k) ==> mymap[k] > 0,
- ensures: #[trigger] Multiset::from_map(mymap).dom() == mymap.dom(),

## group_multiset_axioms
- path: vstd/multiset.rs  (broadcast group)
- members: axiom_multiset_empty axiom_multiset_contained axiom_multiset_new_not_contained lemma_from_map_dom axiom_multiset_singleton axiom_multiset_singleton_different axiom_multiset_add axiom_multiset_sub axiom_multiset_ext_equal axiom_multiset_ext_equal_deep axiom_len_empty axiom_len_singleton axiom_len_add axiom_len_sub axiom_count_le_len axiom_filter_count axiom_choose_count

## lemma_update_same
- path: vstd/multiset.rs:413  (proof fn)
- sig: `pub broadcast proof fn lemma_update_same<V>(m: Multiset<V>, v: V, mult: nat)`
- ensures: #[trigger] m.update(v, mult).count(v) == mult,
- doc: The multiset resulting from updating a value `v` in a multiset `m` to multiplicity `mult` will

## lemma_update_different
- path: vstd/multiset.rs:442  (proof fn)
- sig: `pub broadcast proof fn lemma_update_different<V>(m: Multiset<V>, v1: V, mult: nat, v2: V)`
- requires: v1 != v2,
- ensures: #[trigger] m.update(v1, mult).count(v2) == m.count(v2),
- doc: The multiset resulting from updating a value `v1` in a multiset `m` to multiplicity `mult` will

## lemma_insert_containment
- path: vstd/multiset.rs:483  (proof fn)
- sig: `pub broadcast proof fn lemma_insert_containment<V>(m: Multiset<V>, x: V, y: V)`
- ensures: 0 < #[trigger] m.insert(x).count(y) <==> x == y || 0 < m.count(y),
- doc: If you insert element x into multiset m, then element y maps

## lemma_insert_increases_count_by_1
- path: vstd/multiset.rs:493  (proof fn)
- sig: `pub broadcast proof fn lemma_insert_increases_count_by_1<V>(m: Multiset<V>, x: V)`
- ensures: #[trigger] m.insert(x).count(x) == m.count(x) + 1,
- doc: Inserting an element `x` into multiset `m` will increase the count of `x` in `m` by 1.

## lemma_insert_non_decreasing
- path: vstd/multiset.rs:505  (proof fn)
- sig: `pub broadcast proof fn lemma_insert_non_decreasing<V>(m: Multiset<V>, x: V, y: V)`
- ensures: 0 < m.count(y) ==> 0 < #[trigger] m.insert(x).count(y),
- doc: If multiset `m` maps element `y` to a multiplicity greater than 0, then inserting any element `x`

## lemma_insert_other_elements_unchanged
- path: vstd/multiset.rs:515  (proof fn)
- sig: `pub broadcast proof fn lemma_insert_other_elements_unchanged<V>(m: Multiset<V>, x: V, y: V)`
- ensures: x != y ==> m.count(y) == #[trigger] m.insert(x).count(y),
- doc: Inserting an element `x` into a multiset `m` will not change the count of any other element `y` in `m`.

## lemma_insert_len
- path: vstd/multiset.rs:525  (proof fn)
- sig: `pub broadcast proof fn lemma_insert_len<V>(m: Multiset<V>, x: V)`
- ensures: #[trigger] m.insert(x).len() == m.len() + 1,
- doc: Inserting an element `x` into a multiset `m` will increase the length of `m` by 1.

## lemma_intersection_count
- path: vstd/multiset.rs:537  (proof fn)
- sig: `pub broadcast proof fn lemma_intersection_count<V>(a: Multiset<V>, b: Multiset<V>, x: V)`
- ensures: #[trigger] a.intersection_with(b).count(x) == min(a.count(x) as int, b.count(x) as int),
- doc: The multiplicity of an element `x` in the intersection of multisets `a` and `b` will be the minimum

## lemma_left_pseudo_idempotence
- path: vstd/multiset.rs:570  (proof fn)
- sig: `pub broadcast proof fn lemma_left_pseudo_idempotence<V>(a: Multiset<V>, b: Multiset<V>)`
- ensures: #[trigger] a.intersection_with(b).intersection_with(b) =~= a.intersection_with(b),
- doc: Taking the intersection of multisets `a` and `b` and then taking the resulting multiset's intersection

## lemma_right_pseudo_idempotence
- path: vstd/multiset.rs:596  (proof fn)
- sig: `pub broadcast proof fn lemma_right_pseudo_idempotence<V>(a: Multiset<V>, b: Multiset<V>)`
- ensures: #[trigger] a.intersection_with(a.intersection_with(b)) =~= a.intersection_with(b),
- doc: Taking the intersection of multiset `a` with the result of taking the intersection of `a` and `b`

## lemma_difference_count
- path: vstd/multiset.rs:623  (proof fn)
- sig: `pub broadcast proof fn lemma_difference_count<V>(a: Multiset<V>, b: Multiset<V>, x: V)`
- ensures: #[trigger] a.difference_with(b).count(x) == clip(a.count(x) - b.count(x)),
- doc: The multiplicity of an element `x` in the difference of multisets `a` and `b` will be

## lemma_difference_bottoms_out
- path: vstd/multiset.rs:657  (proof fn)
- sig: `pub broadcast proof fn lemma_difference_bottoms_out<V>(a: Multiset<V>, b: Multiset<V>, x: V)`
- ensures: #![trigger a.count(x), b.count(x), a.difference_with(b)] a.count(x) <= b.count(x) ==> a.difference_with(b).count(x) == 0,
- doc: If the multiplicity of element `x` is less in multiset `a` than in multiset `b`, then the multiplicity

## group_multiset_properties
- path: vstd/multiset.rs  (broadcast group)
- members: lemma_update_same lemma_update_different lemma_multiset_empty_len lemma_insert_containment lemma_insert_increases_count_by_1 lemma_insert_non_decreasing lemma_insert_other_elements_unchanged lemma_insert_len lemma_intersection_count lemma_left_pseudo_idempotence lemma_right_pseudo_idempotence lemma_difference_count lemma_difference_bottoms_out Multiset::dom_ensures

## Multiset::is_empty
- path: vstd/multiset_lib.rs:12  (spec fn)
- sig: `pub open spec fn is_empty(self) -> (b: bool)`
- doc: Is `true` if called by an "empty" multiset, i.e., a set containing no elements and has length 0

## Multiset::is_singleton
- path: vstd/multiset_lib.rs:17  (spec fn)
- sig: `pub open spec fn is_singleton(self) -> bool`
- doc: A singleton multiset has at least one element with multiplicity 1 and any two elements are equal.

## Multiset::lemma_is_singleton_contains_elem_equal_singleton
- path: vstd/multiset_lib.rs:24  (proof fn)
- sig: `pub proof fn lemma_is_singleton_contains_elem_equal_singleton(self, x: A)`
- requires: self.is_singleton(), self.contains(x),
- ensures: self =~= Multiset::singleton(x),
- doc: A singleton multiset that contains an alement is equivalent to the singleton multiset with that element.

## Multiset::lemma_singleton_size
- path: vstd/multiset_lib.rs:39  (proof fn)
- sig: `pub proof fn lemma_singleton_size(self)`
- requires: self.is_singleton(),
- ensures: self.len() == 1,
- doc: A singleton multiset has length 1.

## Multiset::lemma_is_singleton
- path: vstd/multiset_lib.rs:49  (proof fn)
- sig: `pub proof fn lemma_is_singleton(s: Multiset<A>)`
- ensures: s.is_singleton() <==> (s.len() == 1),
- doc: A multiset has exactly one element, if and only if, it has at least one element with multiplicity 1 and any two elements are equal.

## trigger
- path: vstd/pervasive.rs:37  (spec fn)
- sig: `pub open spec fn trigger<A>(a: A) -> bool`

## spec_affirm
- path: vstd/pervasive.rs:171  (spec fn)
- sig: `pub closed spec fn spec_affirm(b: bool) -> bool recommends b,`
- doc: A tool to check one's reasoning while writing complex spec functions.

## arbitrary
- path: vstd/pervasive.rs:181  (spec fn)
- sig: `pub uninterp spec fn arbitrary<A>() -> A`
- doc: In spec, all types are inhabited

## unreached
- path: vstd/pervasive.rs:190  (fn)
- sig: `pub fn unreached<A>() -> A`
- requires: false,

## print_u64
- path: vstd/pervasive.rs:199  (fn)
- sig: `pub fn print_u64(i: u64)`

## runtime_assert
- path: vstd/pervasive.rs:204  (fn)
- sig: `pub fn runtime_assert(b: bool)`
- requires: b,

## strictly_cloned
- path: vstd/pervasive.rs:416  (spec fn)
- sig: `pub open spec fn strictly_cloned<T: Clone>(a: T, b: T) -> bool`
- doc: Predicate indicating `b` could be the result of calling `a.clone()`

## cloned
- path: vstd/pervasive.rs:426  (spec fn)
- sig: `pub open spec fn cloned<T: Clone>(a: T, b: T) -> bool`
- doc: Predicate indicating `b` is "a clone" of `a`; i.e., `b` could be the result of

## allow_panic
- path: vstd/pervasive.rs:437  (spec fn)
- sig: `pub open spec fn allow_panic() -> bool`
- doc: The default behavior of the vstd library enforces writing panic-free code.

## __call_panic
- path: vstd/pervasive.rs:443  (fn)
- sig: `pub fn __call_panic(out: &[&str]) -> !`
- requires: allow_panic(),

## __new_argument
- path: vstd/pervasive.rs:454  (fn)
- sig: `pub fn __new_argument<T: core::fmt::Debug>(v: &T) -> alloc::string::String`

## Prophecy::view
- path: vstd/proph.rs:174  (spec fn)
- sig: `pub uninterp spec fn view(self) -> T`
- doc: The prophecized value.

## Prophecy::new
- path: vstd/proph.rs:179  (fn)
- sig: `pub exec fn new() -> (proph_var: Self)`
- doc: Allocate a new prophecy variable.

## Prophecy::resolve
- path: vstd/proph.rs:187  (fn)
- sig: `pub exec fn resolve(self, v: &T)`
- ensures: self@ == v,
- doc: Resolve the prophecy variable to a concrete value.

## ProphecyGhost::value
- path: vstd/proph.rs:216  (spec fn)
- sig: `pub uninterp spec fn value(&self) -> T`

## ProphecySeq::seq
- path: vstd/proph.rs:269  (spec fn)
- sig: `pub closed spec fn seq(&self) -> Seq<T>`

## Provenance::null
- path: vstd/raw_ptr.rs:67  (spec fn)
- sig: `pub uninterp spec fn null() -> Self`
- doc: The provenance of the null ptr (or really, "no provenance")

## *mut T::eq
- path: vstd/raw_ptr.rs:198  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification<T: core::marker::PointeeSized>[ <*mut T as PartialEq<*mut T>>::eq ]( x: &*mut T, y: &*mut T, ) -> (res: bool)`
- ensures: res <==> (x@.addr == y@.addr) && (x@.metadata == y@.metadata),
- doc: Compares the address and metadata of two pointers.

## *const T::eq
- path: vstd/raw_ptr.rs:221  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification<T: core::marker::PointeeSized>[ <*const T as PartialEq<*const T>>::eq ]( x: &*const T, y: &*const T, ) -> (res: bool)`
- ensures: res <==> (x@.addr == y@.addr) && (x@.metadata == y@.metadata),
- doc: Compares the address and metadata of two pointers.

## PointsTo::ptr
- path: vstd/raw_ptr.rs:238  (spec fn)
- sig: `pub open spec fn ptr(&self) -> *mut T`
- doc: The pointer that this permission is associated with.

## PointsTo::opt_value
- path: vstd/raw_ptr.rs:244  (spec fn)
- sig: `pub open spec fn opt_value(&self) -> MemContents<T>`
- doc: The (possibly uninitialized) memory that this permission gives access to.

## PointsTo::is_init
- path: vstd/raw_ptr.rs:250  (spec fn)
- sig: `pub open spec fn is_init(&self) -> bool`
- doc: Returns `true` if the permission's associated memory is initialized.

## PointsTo::is_uninit
- path: vstd/raw_ptr.rs:256  (spec fn)
- sig: `pub open spec fn is_uninit(&self) -> bool`
- doc: Returns `true` if the permission's associated memory is uninitialized.

## PointsTo::value
- path: vstd/raw_ptr.rs:264  (spec fn)
- sig: `pub open spec fn value(&self) -> T recommends self.is_init(),`
- doc: If the permission's associated memory is initialized,

## MemContents::is_init
- path: vstd/raw_ptr.rs:319  (spec fn)
- sig: `pub open spec fn is_init(&self) -> bool`
- doc: Returns `true` if it is a [`MemContents::Init`] value.

## MemContents::is_uninit
- path: vstd/raw_ptr.rs:325  (spec fn)
- sig: `pub open spec fn is_uninit(&self) -> bool`
- doc: Returns `true` if it is a [`MemContents::Uninit`] value.

## MemContents::value
- path: vstd/raw_ptr.rs:332  (spec fn)
- sig: `pub open spec fn value(&self) -> T recommends self is Init,`
- doc: If it is a [`MemContents::Init`] value, returns the value.

## ptr_mut_from_data
- path: vstd/raw_ptr.rs:344  (spec fn)
- sig: `pub uninterp spec fn ptr_mut_from_data<T: core::marker::PointeeSized>(data: PtrData<T>) -> *mut T`
- doc: Constructs a pointer from its underlying model.

## ptr_from_data
- path: vstd/raw_ptr.rs:350  (spec fn)
- sig: `pub open spec fn ptr_from_data<T: core::marker::PointeeSized>(data: PtrData<T>) -> *const T`
- doc: Constructs a pointer from its underlying model.

## view_reverse_for_eq
- path: vstd/raw_ptr.rs:363  (spec fn)
- sig: `pub uninterp spec fn view_reverse_for_eq<T: ?Sized>(data: PtrData<T>) -> *mut T`

## view_reverse_for_eq_sized
- path: vstd/raw_ptr.rs:376  (spec fn)
- sig: `pub closed spec fn view_reverse_for_eq_sized<T>(addr: usize, provenance: Provenance) -> *mut T`

## ptrs_mut_eq_sized
- path: vstd/raw_ptr.rs:380  (proof fn)
- sig: `pub broadcast proof fn ptrs_mut_eq_sized<T>(a: *mut T)`
- ensures: view_reverse_for_eq_sized::<T>((#[trigger] a@).addr, a@.provenance) == a,

## ptr_null
- path: vstd/raw_ptr.rs:393  (spec fn)
- sig: `pub open spec fn ptr_null< T: ::core::marker::PointeeSized + core::ptr::Pointee<Metadata = ()>,`
- doc: ///////////////////////////////////

## ptr_null_mut
- path: vstd/raw_ptr.rs:414  (spec fn)
- sig: `pub open spec fn ptr_null_mut< T: core::marker::PointeeSized + core::ptr::Pointee<Metadata = ()>,`
- doc: Constructs a mutable null pointer.

## spec_cast_ptr_to_thin_ptr
- path: vstd/raw_ptr.rs:436  (spec fn)
- sig: `pub open spec fn spec_cast_ptr_to_thin_ptr<T: ?Sized, U: Sized>(ptr: *mut T) -> *mut U`
- doc: Cast a pointer to a thin pointer. Address and provenance are preserved; metadata is now thin.

## cast_ptr_to_thin_ptr
- path: vstd/raw_ptr.rs:446  (fn)
- sig: `pub fn cast_ptr_to_thin_ptr<T: ?Sized, U: Sized>(ptr: *mut T) -> (result: *mut U)`
- ensures: result == spec_cast_ptr_to_thin_ptr::<T, U>(ptr),
- doc: Cast a pointer to a thin pointer. Address and provenance are preserved; metadata is now thin.

## spec_cast_array_ptr_to_slice_ptr
- path: vstd/raw_ptr.rs:457  (spec fn)
- sig: `pub open spec fn spec_cast_array_ptr_to_slice_ptr<T, const N: usize>(ptr: *mut [T; N]) -> *mut [T]`
- doc: Cast a pointer to an array of length `N` to a slice pointer.

## cast_array_ptr_to_slice_ptr
- path: vstd/raw_ptr.rs:468  (fn)
- sig: `pub fn cast_array_ptr_to_slice_ptr<T, const N: usize>(ptr: *mut [T; N]) -> (result: *mut [T])`
- ensures: result == spec_cast_array_ptr_to_slice_ptr(ptr),
- doc: Cast a pointer to an array of length `N` to a slice pointer.

## spec_cast_slice_ptr_to_slice_ptr
- path: vstd/raw_ptr.rs:479  (spec fn)
- sig: `pub open spec fn spec_cast_slice_ptr_to_slice_ptr<T, U>(ptr: *mut [T]) -> *mut [U]`
- doc: Cast a slice pointer to another slice pointer.

## cast_slice_ptr_to_slice_ptr
- path: vstd/raw_ptr.rs:492  (fn)
- sig: `pub fn cast_slice_ptr_to_slice_ptr<T, U>(ptr: *mut [T]) -> (result: *mut [U])`
- ensures: result == spec_cast_slice_ptr_to_slice_ptr::<T, U>(ptr),
- doc: Cast a slice pointer to another slice pointer.

## spec_cast_slice_ptr_to_str_ptr
- path: vstd/raw_ptr.rs:503  (spec fn)
- sig: `pub open spec fn spec_cast_slice_ptr_to_str_ptr<T>(ptr: *mut [T]) -> *mut str`
- doc: Cast a slice pointer to a `str` pointer.

## cast_slice_ptr_to_str_ptr
- path: vstd/raw_ptr.rs:516  (fn)
- sig: `pub fn cast_slice_ptr_to_str_ptr<T>(ptr: *mut [T]) -> (result: *mut str)`
- ensures: result == spec_cast_slice_ptr_to_str_ptr::<T>(ptr),
- doc: Cast a slice pointer to a `str` pointer.

## spec_cast_str_ptr_to_slice_ptr
- path: vstd/raw_ptr.rs:527  (spec fn)
- sig: `pub open spec fn spec_cast_str_ptr_to_slice_ptr<T>(ptr: *mut str) -> *mut [T]`
- doc: Cast a `str` pointer to a slice pointer.

## cast_str_ptr_to_slice_ptr
- path: vstd/raw_ptr.rs:540  (fn)
- sig: `pub fn cast_str_ptr_to_slice_ptr<T>(ptr: *mut str) -> (result: *mut [T])`
- ensures: result == spec_cast_str_ptr_to_slice_ptr::<T>(ptr),
- doc: Cast a `str` pointer to a slice pointer.

## spec_cast_ptr_to_usize
- path: vstd/raw_ptr.rs:550  (spec fn)
- sig: `pub open spec fn spec_cast_ptr_to_usize<T: Sized>(ptr: *mut T) -> usize`
- doc: Cast a pointer to a `usize` by extracting just the address.

## cast_ptr_to_usize
- path: vstd/raw_ptr.rs:560  (fn)
- sig: `pub fn cast_ptr_to_usize<T: Sized>(ptr: *mut T) -> (result: usize)`
- ensures: result == spec_cast_ptr_to_usize(ptr),
- doc: Cast the address of a pointer to a `usize`.

## ptr_mut_write
- path: vstd/raw_ptr.rs:579  (fn)
- sig: `pub fn ptr_mut_write<T>(ptr: *mut T, Tracked(perm): Tracked<&mut PointsTo<T>>, v: T)`
- requires: old(perm).ptr() == ptr,
- ensures: final(perm).ptr() == ptr, final(perm).opt_value() == MemContents::Init(v),
- doc: Calls [`core::ptr::write`] to write the value `v` to the memory location pointed to by `ptr`,

## ptr_mut_read
- path: vstd/raw_ptr.rs:602  (fn)
- sig: `pub fn ptr_mut_read<T>(ptr: *const T, Tracked(perm): Tracked<&mut PointsTo<T>>) -> (v: T)`
- requires: old(perm).ptr() == ptr, old(perm).is_init(),
- ensures: final(perm).ptr() == ptr, final(perm).is_uninit(), v == old(perm).value(),
- doc: Calls [`core::ptr::read`] to read from the memory pointed to by `ptr`,

## ptr_ref
- path: vstd/raw_ptr.rs:620  (fn)
- sig: `pub fn ptr_ref<T>(ptr: *const T, Tracked(perm): Tracked<&PointsTo<T>>) -> (v: &T)`
- requires: perm.ptr() == ptr, perm.is_init(),
- ensures: v == perm.value(),
- doc: Equivalent to `&*ptr`, passing in a permission `perm` to ensure safety.

## ptr_mut_ref
- path: vstd/raw_ptr.rs:636  (fn)
- sig: `pub fn ptr_mut_ref<T>(ptr: *mut T, Tracked(perm): Tracked<&mut PointsTo<T>>) -> (v: &mut T)`
- requires: old(perm).ptr() == ptr, old(perm).is_init(),
- ensures: final(perm).ptr() == ptr, final(perm).is_init(), old(perm).value() == *v, final(perm).value() == *final(v),
- doc: Equivalent to `&mut *X`, passing in a permission `perm` to ensure safety.

## spec_addr
- path: vstd/raw_ptr.rs:660  (spec fn)
- sig: `pub open spec fn spec_addr<T: ::core::marker::PointeeSized>(p: *$mu T) -> usize { p@.addr }  #[verifier::when_used_as_spec(spec_addr)] #[cfg(verus_keep_ghost)] pub assume_specification<T: ::core::marker::PointeeSized>[<*$mu T>::addr](p: *$mu T) -> (addr: usize)`
- ensures: addr == spec_addr(p) q == spec_with_addr(p, addr) s == self,

## spec_with_addr
- path: vstd/raw_ptr.rs:669  (spec fn)
- sig: `pub open spec fn spec_with_addr<T: ::core::marker::PointeeSized>(p: *$mu T, addr: usize) -> *$mu T`

## group_raw_ptr_axioms
- path: vstd/raw_ptr.rs  (broadcast group)
- members: axiom_ptr_mut_from_data ptrs_mut_eq ptrs_mut_eq_sized

## IsExposed::view
- path: vstd/raw_ptr.rs:715  (spec fn)
- sig: `pub open spec fn view(self) -> Provenance`
- doc: The view of `IsExposed` is simply its provenance.

## IsExposed::provenance
- path: vstd/raw_ptr.rs:720  (spec fn)
- sig: `pub uninterp spec fn provenance(self) -> Provenance`
- doc: Provenance we are exposing.

## expose_provenance
- path: vstd/raw_ptr.rs:731  (fn)
- sig: `pub fn expose_provenance<T: Sized>(m: *mut T) -> (provenance: Tracked<IsExposed>)`
- ensures: provenance@@ == m@.provenance,
- doc: Perform a provenance expose operation.

## with_exposed_provenance
- path: vstd/raw_ptr.rs:744  (fn)
- sig: `pub fn with_exposed_provenance<T: Sized>( addr: usize, Tracked(provenance): Tracked<IsExposed>, ) -> (p: *mut T)`
- ensures: p == ptr_mut_from_data::<T>( PtrData::<T> { addr: addr, provenance: provenance@, metadata: () }, ),
- doc: Construct a pointer with the given provenance from a _usize_ address.

## PointsToRaw::provenance
- path: vstd/raw_ptr.rs:774  (spec fn)
- sig: `pub uninterp spec fn provenance(self) -> Provenance`
- doc: Provenance of the `PointsToRaw` permission;

## PointsToRaw::dom
- path: vstd/raw_ptr.rs:778  (spec fn)
- sig: `pub uninterp spec fn dom(self) -> Set<int>`
- doc: Memory addresses (domain) that the `PointsToRaw` permission gives access to.

## PointsToRaw::is_range
- path: vstd/raw_ptr.rs:781  (spec fn)
- sig: `pub open spec fn is_range(self, start: int, len: int) -> bool`
- doc: Returns `true` if the domain of this permission is exactly the range `[start, start + len)`.

## PointsToRaw::contains_range
- path: vstd/raw_ptr.rs:786  (spec fn)
- sig: `pub open spec fn contains_range(self, start: int, len: int) -> bool`
- doc: Returns `true` if the domain of this permission contains the range `[start, start + len)`.

## Dealloc::view
- path: vstd/raw_ptr.rs:876  (spec fn)
- sig: `pub uninterp spec fn view(self) -> DeallocData`

## Dealloc::addr
- path: vstd/raw_ptr.rs:880  (spec fn)
- sig: `pub open spec fn addr(self) -> usize`
- doc: Start address of the allocation you are allowed to deallocate.

## Dealloc::size
- path: vstd/raw_ptr.rs:886  (spec fn)
- sig: `pub open spec fn size(self) -> nat`
- doc: Size of the allocation you are allowed to deallocate.

## Dealloc::align
- path: vstd/raw_ptr.rs:892  (spec fn)
- sig: `pub open spec fn align(self) -> nat`
- doc: Alignment of the allocation you are allowed to deallocate.

## Dealloc::provenance
- path: vstd/raw_ptr.rs:898  (spec fn)
- sig: `pub open spec fn provenance(self) -> Provenance`
- doc: Provenance of the allocation you are allowed to deallocate.

## allocate
- path: vstd/raw_ptr.rs:908  (fn)
- sig: `pub fn allocate(size: usize, align: usize) -> (pt: ( *mut u8, Tracked<PointsToRaw>, Tracked<Dealloc>, ))`
- requires: valid_layout(size, align), size != 0,
- ensures: pt.1@.is_range(pt.0.addr() as int, size as int), pt.0.addr() + size <= usize::MAX + 1, pt.2@@ == (DeallocData { addr: pt.0.addr(), size: size as nat,
- doc: Allocate with the global allocator.

## deallocate
- path: vstd/raw_ptr.rs:948  (fn)
- sig: `pub fn deallocate( p: *mut u8, size: usize, align: usize, Tracked(pt): Tracked<PointsToRaw>, Tracked(dealloc): Tracked<Dealloc>, )`
- requires: dealloc.addr() == p.addr(), dealloc.size() == size, dealloc.align() == align, dealloc.provenance() == pt.provenance(), pt.is_range(dealloc.addr() as int, dealloc.size() as int),
- doc: Deallocate with the global allocator.

## SharedReference::value
- path: vstd/raw_ptr.rs:995  (spec fn)
- sig: `pub uninterp spec fn value(self) -> T`

## SharedReference::ptr
- path: vstd/raw_ptr.rs:997  (spec fn)
- sig: `pub uninterp spec fn ptr(self) -> *const T`

## ptr_ref2
- path: vstd/raw_ptr.rs:1038  (fn)
- sig: `pub fn ptr_ref2<'a, T>(ptr: *const T, Tracked(perm): Tracked<&PointsTo<T>>) -> (v: SharedReference< 'a, T, >)`
- requires: perm.ptr() == ptr, perm.is_init(),
- ensures: v.value() == perm.value(), v.ptr().addr() == ptr.addr(), v.ptr()@.metadata == ptr@.metadata,
- doc: Like [`ptr_ref`] but returns a `SharedReference` so it keeps track of the relationship

## injective
- path: vstd/relations.rs:11  (spec fn)
- sig: `pub open spec fn injective<X, Y>(r: spec_fn(X) -> Y) -> bool`

## commutative
- path: vstd/relations.rs:15  (spec fn)
- sig: `pub open spec fn commutative<T, U>(r: spec_fn(T, T) -> U) -> bool`

## associative
- path: vstd/relations.rs:19  (spec fn)
- sig: `pub open spec fn associative<T>(r: spec_fn(T, T) -> T) -> bool`

## reflexive
- path: vstd/relations.rs:23  (spec fn)
- sig: `pub open spec fn reflexive<T>(r: spec_fn(T, T) -> bool) -> bool`

## irreflexive
- path: vstd/relations.rs:27  (spec fn)
- sig: `pub open spec fn irreflexive<T>(r: spec_fn(T, T) -> bool) -> bool`

## antisymmetric
- path: vstd/relations.rs:31  (spec fn)
- sig: `pub open spec fn antisymmetric<T>(r: spec_fn(T, T) -> bool) -> bool`

## asymmetric
- path: vstd/relations.rs:35  (spec fn)
- sig: `pub open spec fn asymmetric<T>(r: spec_fn(T, T) -> bool) -> bool`

## symmetric
- path: vstd/relations.rs:39  (spec fn)
- sig: `pub open spec fn symmetric<T>(r: spec_fn(T, T) -> bool) -> bool`

## connected
- path: vstd/relations.rs:43  (spec fn)
- sig: `pub open spec fn connected<T>(r: spec_fn(T, T) -> bool) -> bool`

## strongly_connected
- path: vstd/relations.rs:47  (spec fn)
- sig: `pub open spec fn strongly_connected<T>(r: spec_fn(T, T) -> bool) -> bool`

## transitive
- path: vstd/relations.rs:51  (spec fn)
- sig: `pub open spec fn transitive<T>(r: spec_fn(T, T) -> bool) -> bool`

## total_ordering
- path: vstd/relations.rs:55  (spec fn)
- sig: `pub open spec fn total_ordering<T>(r: spec_fn(T, T) -> bool) -> bool`

## strict_total_ordering
- path: vstd/relations.rs:62  (spec fn)
- sig: `pub open spec fn strict_total_ordering<T>(r: spec_fn(T, T) -> bool) -> bool`

## pre_ordering
- path: vstd/relations.rs:69  (spec fn)
- sig: `pub open spec fn pre_ordering<T>(r: spec_fn(T, T) -> bool) -> bool`

## partial_ordering
- path: vstd/relations.rs:74  (spec fn)
- sig: `pub open spec fn partial_ordering<T>(r: spec_fn(T, T) -> bool) -> bool`

## equivalence_relation
- path: vstd/relations.rs:80  (spec fn)
- sig: `pub open spec fn equivalence_relation<T>(r: spec_fn(T, T) -> bool) -> bool`

## sorted_by
- path: vstd/relations.rs:88  (spec fn)
- sig: `pub open spec fn sorted_by<T>(a: Seq<T>, less_than: spec_fn(T, T) -> bool) -> bool`
- doc: This function returns true if the input sequence a is sorted, using the input function

## lemma_new_first_element_still_sorted_by
- path: vstd/relations.rs:92  (proof fn)
- sig: `pub proof fn lemma_new_first_element_still_sorted_by<T>( x: T, s: Seq<T>, less_than: spec_fn(T, T) -> bool, )`
- requires: sorted_by(s, less_than), s.len() == 0 || less_than(x, s[0]), total_ordering(less_than),
- ensures: sorted_by(seq![x].add(s), less_than),

## Resource::value
- path: vstd/resource/algebra.rs:71  (spec fn)
- sig: `pub closed spec fn value(self) -> RA`
- doc: The underlying value of the resource

## Resource::loc
- path: vstd/resource/algebra.rs:76  (spec fn)
- sig: `pub closed spec fn loc(self) -> Loc`
- doc: The location of the resource

## AgreementRA::view
- path: vstd/resource/combinators/agree.rs:44  (spec fn)
- sig: `pub open spec fn view(self) -> T`

## lemma_agree
- path: vstd/resource/combinators/agree.rs:49  (proof fn)
- sig: `pub proof fn lemma_agree<T>( tracked a: &Resource<AgreementRA<T>>, tracked b: &Resource<AgreementRA<T>>, )`
- requires: a.loc() == b.loc(),
- ensures: a.value()@ == b.value()@,

## FractionRA::new
- path: vstd/resource/combinators/frac.rs:20  (spec fn)
- sig: `pub open spec fn new(f: real) -> Self recommends 0real < f <= 1real,`

## FractionRA::frac
- path: vstd/resource/combinators/frac.rs:27  (spec fn)
- sig: `pub open spec fn frac(self) -> real recommends self is Frac,`

## lemma_whole_fraction_has_no_frame
- path: vstd/resource/combinators/frac.rs:69  (proof fn)
- sig: `pub proof fn lemma_whole_fraction_has_no_frame(a: FractionRA)`
- requires: a == FractionRA::Frac(1 as real),
- ensures: forall|b: FractionRA| #![trigger FractionRA::op(a, b).valid()] !FractionRA::op(a, b).valid(),

## FracGhost::id
- path: vstd/resource/combinators/frac.rs:146  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`

## FracGhost::view
- path: vstd/resource/combinators/frac.rs:150  (spec fn)
- sig: `pub closed spec fn view(self) -> T`

## FracGhost::frac
- path: vstd/resource/combinators/frac.rs:155  (spec fn)
- sig: `pub closed spec fn frac(self) -> real`
- doc: The fractional quantity of this permission

## FracGhost::valid
- path: vstd/resource/combinators/frac.rs:159  (spec fn)
- sig: `pub open spec fn valid(self, id: Loc, frac: real) -> bool`

## lemma_incl_opt
- path: vstd/resource/combinators/option.rs:67  (proof fn)
- sig: `pub proof fn lemma_incl_opt<RA: ResourceAlgebra>(a: RA, b: RA)`
- requires: incl::<RA>(a, b),
- ensures: incl::<Option<RA>>(Some(a), Some(b)),

## lemma_incl_opt_rev
- path: vstd/resource/combinators/option.rs:77  (proof fn)
- sig: `pub proof fn lemma_incl_opt_rev<RA: ResourceAlgebra>(a: RA, b: RA)`
- requires: incl::<Option<RA>>(Some(a), Some(b)),
- ensures: incl::<RA>(a, b) || a == b,

## lemma_set_op_opt
- path: vstd/resource/combinators/option.rs:89  (proof fn)
- sig: `pub proof fn lemma_set_op_opt<RA: ResourceAlgebra>(s: ISet<RA>, t: RA)`
- ensures: set_op(s, t).map(|b| Some(b)) == set_op(s.map(|x| Some(x)), Some(t)),

## Frac::id
- path: vstd/resource/impls/frac_opt.rs:90  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`

## Frac::resource
- path: vstd/resource/impls/frac_opt.rs:94  (spec fn)
- sig: `pub closed spec fn resource(self) -> T`

## Frac::frac
- path: vstd/resource/impls/frac_opt.rs:98  (spec fn)
- sig: `pub closed spec fn frac(self) -> real`

## Frac::valid
- path: vstd/resource/impls/frac_opt.rs:102  (spec fn)
- sig: `pub open spec fn valid(self, id: Loc, frac: real) -> bool`

## Empty::id
- path: vstd/resource/impls/frac_opt.rs:301  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`

## GhostVar::id
- path: vstd/resource/impls/ghost_var.rs:20  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`

## GhostVar::view
- path: vstd/resource/impls/ghost_var.rs:24  (spec fn)
- sig: `pub closed spec fn view(self) -> T`

## GhostVarAuth::id
- path: vstd/resource/impls/ghost_var.rs:65  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`

## GhostVarAuth::view
- path: vstd/resource/impls/ghost_var.rs:69  (spec fn)
- sig: `pub closed spec fn view(self) -> T`

## GhostIMapAuth::id
- path: vstd/resource/impls/imap.rs:368  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Resource location

## GhostIMapAuth::view
- path: vstd/resource/impls/imap.rs:373  (spec fn)
- sig: `pub closed spec fn view(self) -> IMap<K, V>`
- doc: Logically underlying [`IMap`]

## GhostIMapAuth::dom
- path: vstd/resource/impls/imap.rs:378  (spec fn)
- sig: `pub open spec fn dom(self) -> ISet<K>`
- doc: Domain of the [`GhostIMapAuth`]

## GhostIMapAuth::spec_index
- path: vstd/resource/impls/imap.rs:383  (spec fn)
- sig: `pub open spec fn spec_index(self, key: K) -> V recommends self.dom().contains(key),`
- doc: Indexing operation `auth[key]`

## GhostISubmap::is_points_to
- path: vstd/resource/impls/imap.rs:621  (spec fn)
- sig: `pub open spec fn is_points_to(self) -> bool`
- doc: Checks whether the [`GhostISubmap`] refers to a single key (and thus can be converted to a

## GhostISubmap::id
- path: vstd/resource/impls/imap.rs:628  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Resource location

## GhostISubmap::view
- path: vstd/resource/impls/imap.rs:633  (spec fn)
- sig: `pub closed spec fn view(self) -> IMap<K, V>`
- doc: Logically underlying [`IMap`]

## GhostISubmap::dom
- path: vstd/resource/impls/imap.rs:638  (spec fn)
- sig: `pub open spec fn dom(self) -> ISet<K>`
- doc: Domain of the [`GhostISubmap`]

## GhostISubmap::spec_index
- path: vstd/resource/impls/imap.rs:643  (spec fn)
- sig: `pub open spec fn spec_index(self, key: K) -> V recommends self.dom().contains(key),`
- doc: Indexing operation `submap[key]`

## GhostPersistentISubmap::is_points_to
- path: vstd/resource/impls/imap.rs:1018  (spec fn)
- sig: `pub open spec fn is_points_to(self) -> bool`
- doc: Checks whether the [`GhostPersistentISubmap`] refers to a single key (and thus can be converted to a

## GhostPersistentISubmap::id
- path: vstd/resource/impls/imap.rs:1025  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Resource location

## GhostPersistentISubmap::view
- path: vstd/resource/impls/imap.rs:1030  (spec fn)
- sig: `pub closed spec fn view(self) -> IMap<K, V>`
- doc: Logically underlying [`IMap`]

## GhostPersistentISubmap::dom
- path: vstd/resource/impls/imap.rs:1035  (spec fn)
- sig: `pub open spec fn dom(self) -> ISet<K>`
- doc: Domain of the [`GhostPersistentISubmap`]

## GhostPersistentISubmap::spec_index
- path: vstd/resource/impls/imap.rs:1040  (spec fn)
- sig: `pub open spec fn spec_index(self, key: K) -> V recommends self.dom().contains(key),`
- doc: Indexing operation `submap[key]`

## GhostIPointsTo::id
- path: vstd/resource/impls/imap.rs:1296  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Location of the underlying resource

## GhostIPointsTo::view
- path: vstd/resource/impls/imap.rs:1301  (spec fn)
- sig: `pub open spec fn view(self) -> (K, V)`
- doc: Key-Value pair underlying the points to relationship

## GhostIPointsTo::key
- path: vstd/resource/impls/imap.rs:1306  (spec fn)
- sig: `pub closed spec fn key(self) -> K`
- doc: Key of the points to

## GhostIPointsTo::value
- path: vstd/resource/impls/imap.rs:1311  (spec fn)
- sig: `pub closed spec fn value(self) -> V`
- doc: Pointed-to value

## GhostIPointsTo::lemma_view
- path: vstd/resource/impls/imap.rs:1491  (proof fn)
- sig: `pub proof fn lemma_view(self)`
- ensures: self@ == (self.key(), self.value()),
- doc: Can be used to learn what the key-value pair of [`GhostIPointsTo`] is

## GhostPersistentIPointsTo::id
- path: vstd/resource/impls/imap.rs:1515  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Location of the underlying resource

## GhostPersistentIPointsTo::view
- path: vstd/resource/impls/imap.rs:1520  (spec fn)
- sig: `pub open spec fn view(self) -> (K, V)`
- doc: Key-Value pair underlying the points to relationship

## GhostPersistentIPointsTo::key
- path: vstd/resource/impls/imap.rs:1525  (spec fn)
- sig: `pub closed spec fn key(self) -> K`
- doc: Key of the points to

## GhostPersistentIPointsTo::value
- path: vstd/resource/impls/imap.rs:1530  (spec fn)
- sig: `pub closed spec fn value(self) -> V`
- doc: Pointed-to value

## GhostPersistentIPointsTo::lemma_view
- path: vstd/resource/impls/imap.rs:1703  (proof fn)
- sig: `pub proof fn lemma_view(self)`
- ensures: self@ == (self.key(), self.value()),
- doc: Can be used to learn what the key-value pair of [`GhostPersistentIPointsTo`] is

## GhostISetAuth::id
- path: vstd/resource/impls/iset.rs:131  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Resource location

## GhostISetAuth::view
- path: vstd/resource/impls/iset.rs:136  (spec fn)
- sig: `pub closed spec fn view(self) -> ISet<T>`
- doc: Logically underlying [`ISet`]

## GhostISubset::is_singleton
- path: vstd/resource/impls/iset.rs:290  (spec fn)
- sig: `pub open spec fn is_singleton(self) -> bool`
- doc: Checks whether the [`GhostISubset`] refers to a single value (and thus can be converted to a

## GhostISubset::id
- path: vstd/resource/impls/iset.rs:297  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Resource location

## GhostISubset::view
- path: vstd/resource/impls/iset.rs:302  (spec fn)
- sig: `pub closed spec fn view(self) -> ISet<T>`
- doc: Logically underlying [`ISet`]

## GhostPersistentISubset::is_singleton
- path: vstd/resource/impls/iset.rs:498  (spec fn)
- sig: `pub open spec fn is_singleton(self) -> bool`
- doc: Checks whether the [`GhostPersistentISubset`] refers to a single key (and thus can be converted to a

## GhostPersistentISubset::id
- path: vstd/resource/impls/iset.rs:505  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Resource location

## GhostPersistentISubset::view
- path: vstd/resource/impls/iset.rs:510  (spec fn)
- sig: `pub closed spec fn view(self) -> ISet<T>`
- doc: Logically underlying [`ISet`]

## GhostISingleton::id
- path: vstd/resource/impls/iset.rs:664  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Location of the underlying resource

## GhostISingleton::view
- path: vstd/resource/impls/iset.rs:669  (spec fn)
- sig: `pub closed spec fn view(self) -> T`
- doc: Value owned by the singleton

## GhostPersistentISingleton::id
- path: vstd/resource/impls/iset.rs:791  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Location of the underlying resource

## GhostPersistentISingleton::view
- path: vstd/resource/impls/iset.rs:796  (spec fn)
- sig: `pub closed spec fn view(self) -> T`
- doc: Value known by the singleton

## GhostMapAuth::id
- path: vstd/resource/impls/map.rs:365  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Resource location

## GhostMapAuth::view
- path: vstd/resource/impls/map.rs:370  (spec fn)
- sig: `pub closed spec fn view(self) -> Map<K, V>`
- doc: Logically underlying [`Map`]

## GhostMapAuth::dom
- path: vstd/resource/impls/map.rs:375  (spec fn)
- sig: `pub open spec fn dom(self) -> Set<K>`
- doc: Domain of the [`GhostMapAuth`]

## GhostMapAuth::spec_index
- path: vstd/resource/impls/map.rs:380  (spec fn)
- sig: `pub open spec fn spec_index(self, key: K) -> V recommends self.dom().contains(key),`
- doc: Indexing operation `auth[key]`

## GhostSubmap::is_points_to
- path: vstd/resource/impls/map.rs:622  (spec fn)
- sig: `pub open spec fn is_points_to(self) -> bool`
- doc: Checks whether the [`GhostSubmap`] refers to a single key (and thus can be converted to a

## GhostSubmap::id
- path: vstd/resource/impls/map.rs:628  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Resource location

## GhostSubmap::view
- path: vstd/resource/impls/map.rs:633  (spec fn)
- sig: `pub closed spec fn view(self) -> Map<K, V>`
- doc: Logically underlying [`Map`]

## GhostSubmap::dom
- path: vstd/resource/impls/map.rs:638  (spec fn)
- sig: `pub open spec fn dom(self) -> Set<K>`
- doc: Domain of the [`GhostSubmap`]

## GhostSubmap::spec_index
- path: vstd/resource/impls/map.rs:643  (spec fn)
- sig: `pub open spec fn spec_index(self, key: K) -> V recommends self.dom().contains(key),`
- doc: Indexing operation `submap[key]`

## GhostPersistentSubmap::is_points_to
- path: vstd/resource/impls/map.rs:1012  (spec fn)
- sig: `pub open spec fn is_points_to(self) -> bool`
- doc: Checks whether the [`GhostPersistentSubmap`] refers to a single key (and thus can be converted to a

## GhostPersistentSubmap::id
- path: vstd/resource/impls/map.rs:1018  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Resource location

## GhostPersistentSubmap::view
- path: vstd/resource/impls/map.rs:1023  (spec fn)
- sig: `pub closed spec fn view(self) -> Map<K, V>`
- doc: Logically underlying [`Map`]

## GhostPersistentSubmap::dom
- path: vstd/resource/impls/map.rs:1028  (spec fn)
- sig: `pub open spec fn dom(self) -> Set<K>`
- doc: Domain of the [`GhostPersistentSubmap`]

## GhostPersistentSubmap::spec_index
- path: vstd/resource/impls/map.rs:1033  (spec fn)
- sig: `pub open spec fn spec_index(self, key: K) -> V recommends self.dom().contains(key),`
- doc: Indexing operation `submap[key]`

## GhostPointsTo::id
- path: vstd/resource/impls/map.rs:1286  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Location of the underlying resource

## GhostPointsTo::view
- path: vstd/resource/impls/map.rs:1291  (spec fn)
- sig: `pub open spec fn view(self) -> (K, V)`
- doc: Key-Value pair underlying the points to relationship

## GhostPointsTo::key
- path: vstd/resource/impls/map.rs:1296  (spec fn)
- sig: `pub closed spec fn key(self) -> K`
- doc: Key of the points to

## GhostPointsTo::value
- path: vstd/resource/impls/map.rs:1301  (spec fn)
- sig: `pub closed spec fn value(self) -> V`
- doc: Pointed-to value

## GhostPointsTo::lemma_view
- path: vstd/resource/impls/map.rs:1478  (proof fn)
- sig: `pub proof fn lemma_view(self)`
- ensures: self@ == (self.key(), self.value()),
- doc: Can be used to learn what the key-value pair of [`GhostPointsTo`] is

## GhostPersistentPointsTo::id
- path: vstd/resource/impls/map.rs:1502  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Location of the underlying resource

## GhostPersistentPointsTo::view
- path: vstd/resource/impls/map.rs:1507  (spec fn)
- sig: `pub open spec fn view(self) -> (K, V)`
- doc: Key-Value pair underlying the points to relationship

## GhostPersistentPointsTo::key
- path: vstd/resource/impls/map.rs:1512  (spec fn)
- sig: `pub closed spec fn key(self) -> K`
- doc: Key of the points to

## GhostPersistentPointsTo::value
- path: vstd/resource/impls/map.rs:1517  (spec fn)
- sig: `pub closed spec fn value(self) -> V`
- doc: Pointed-to value

## GhostPersistentPointsTo::lemma_view
- path: vstd/resource/impls/map.rs:1687  (proof fn)
- sig: `pub proof fn lemma_view(self)`
- ensures: self@ == (self.key(), self.value()),
- doc: Can be used to learn what the key-value pair of [`GhostPersistentPointsTo`] is

## seq_to_map
- path: vstd/resource/impls/seq.rs:10  (spec fn)
- sig: `pub open spec fn seq_to_map<V>(s: Seq<V>, off: int) -> IMap<int, V>`

## GhostSeqAuth::id
- path: vstd/resource/impls/seq.rs:83  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`

## GhostSeqAuth::view
- path: vstd/resource/impls/seq.rs:87  (spec fn)
- sig: `pub closed spec fn view(self) -> Seq<V>`

## GhostSeqAuth::len
- path: vstd/resource/impls/seq.rs:91  (spec fn)
- sig: `pub open spec fn len(self) -> nat`

## GhostSeqAuth::spec_index
- path: vstd/resource/impls/seq.rs:95  (spec fn)
- sig: `pub open spec fn spec_index(self, idx: int) -> V recommends 0 <= idx < self.len(),`

## GhostSeqAuth::off
- path: vstd/resource/impls/seq.rs:102  (spec fn)
- sig: `pub closed spec fn off(self) -> nat`

## GhostSeqAuth::subrange_abs
- path: vstd/resource/impls/seq.rs:106  (spec fn)
- sig: `pub open spec fn subrange_abs(self, start_inclusive: int, end_exclusive: int) -> Seq<V> recommends self.off() <= start_inclusive <= end_exclusive <= self.off() + self@.len(),`

## GhostSubseq::view
- path: vstd/resource/impls/seq.rs:181  (spec fn)
- sig: `pub closed spec fn view(self) -> Seq<V>`

## GhostSubseq::len
- path: vstd/resource/impls/seq.rs:185  (spec fn)
- sig: `pub open spec fn len(self) -> nat`

## GhostSubseq::spec_index
- path: vstd/resource/impls/seq.rs:189  (spec fn)
- sig: `pub open spec fn spec_index(self, idx: int) -> V recommends 0 <= idx < self.len(),`

## GhostSubseq::subrange_abs
- path: vstd/resource/impls/seq.rs:196  (spec fn)
- sig: `pub open spec fn subrange_abs(self, start_inclusive: int, end_exclusive: int) -> Seq<V> recommends self.off() <= start_inclusive <= end_exclusive <= self.off() + self@.len(),`

## GhostSubseq::off
- path: vstd/resource/impls/seq.rs:203  (spec fn)
- sig: `pub closed spec fn off(self) -> nat`

## GhostSubseq::id
- path: vstd/resource/impls/seq.rs:207  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`

## GhostSetAuth::id
- path: vstd/resource/impls/set.rs:131  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Resource location

## GhostSetAuth::view
- path: vstd/resource/impls/set.rs:136  (spec fn)
- sig: `pub closed spec fn view(self) -> Set<T>`
- doc: Logically underlying [`Set`]

## GhostSubset::is_singleton
- path: vstd/resource/impls/set.rs:290  (spec fn)
- sig: `pub open spec fn is_singleton(self) -> bool`
- doc: Checks whether the [`GhostSubset`] refers to a single value (and thus can be converted to a

## GhostSubset::id
- path: vstd/resource/impls/set.rs:296  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Resource location

## GhostSubset::view
- path: vstd/resource/impls/set.rs:301  (spec fn)
- sig: `pub closed spec fn view(self) -> Set<T>`
- doc: Logically underlying [`Set`]

## GhostPersistentSubset::is_singleton
- path: vstd/resource/impls/set.rs:497  (spec fn)
- sig: `pub open spec fn is_singleton(self) -> bool`
- doc: Checks whether the [`GhostPersistentSubset`] refers to a single key (and thus can be converted to a

## GhostPersistentSubset::id
- path: vstd/resource/impls/set.rs:503  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Resource location

## GhostPersistentSubset::view
- path: vstd/resource/impls/set.rs:508  (spec fn)
- sig: `pub closed spec fn view(self) -> Set<T>`
- doc: Logically underlying [`Set`]

## GhostSingleton::id
- path: vstd/resource/impls/set.rs:662  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Location of the underlying resource

## GhostSingleton::view
- path: vstd/resource/impls/set.rs:667  (spec fn)
- sig: `pub closed spec fn view(self) -> T`
- doc: Value owned by the singleton

## GhostPersistentSingleton::id
- path: vstd/resource/impls/set.rs:787  (spec fn)
- sig: `pub closed spec fn id(self) -> Loc`
- doc: Location of the underlying resource

## GhostPersistentSingleton::view
- path: vstd/resource/impls/set.rs:792  (spec fn)
- sig: `pub closed spec fn view(self) -> T`
- doc: Value known by the singleton

## combine_values
- path: vstd/resource/lib.rs:15  (spec fn)
- sig: `pub open spec fn combine_values<P: PCM>(values: Seq<P>) -> P`
- doc: Combines a list of values into one value using P::op().

## lemma_pcm_properties
- path: vstd/resource/lib.rs:31  (proof fn)
- sig: `pub proof fn lemma_pcm_properties<P: PCM>()`
- ensures: forall|a: P, b: P| (#[trigger] P::op(a, b)).valid() ==> a.valid(), forall|a: P, b: P| (#[trigger] P::op(a, b)) == P::op(b, a), forall|a: P| (#[trigger] P::op(a, P::unit())) == a, P::valid(P::unit()),
- doc: Provides four quantified facts about a partially commutative

## lemma_pcm_associative
- path: vstd/resource/lib.rs:57  (proof fn)
- sig: `pub proof fn lemma_pcm_associative<P: PCM>()`
- ensures: forall|a: P, b: P, c: P| (#[trigger] P::op(a, P::op(b, c))) == P::op(P::op(a, b), c),
- doc: Provides a quantified associativity fact about a partially commutative

## Resource::value
- path: vstd/resource/pcm.rs:85  (spec fn)
- sig: `pub uninterp spec fn value(self) -> P`
- doc: The underlying value of the resource

## Resource::loc
- path: vstd/resource/pcm.rs:88  (spec fn)
- sig: `pub uninterp spec fn loc(self) -> Loc`
- doc: The location of the resource

## incl
- path: vstd/resource/relations.rs:9  (spec fn)
- sig: `pub open spec fn incl<RA: ResourceAlgebra>(a: RA, b: RA) -> bool`
- doc: The preorder relation.

## conjunct_shared
- path: vstd/resource/relations.rs:13  (spec fn)
- sig: `pub open spec fn conjunct_shared<RA: ResourceAlgebra>(a: RA, b: RA, c: RA) -> bool`

## frame_preserving_update
- path: vstd/resource/relations.rs:19  (spec fn)
- sig: `pub open spec fn frame_preserving_update<P: PCM>(a: P, b: P) -> bool`
- doc: A frame preserving update is an update of a value from `a --> b` such that every value `c`

## frame_preserving_update_nondeterministic
- path: vstd/resource/relations.rs:24  (spec fn)
- sig: `pub open spec fn frame_preserving_update_nondeterministic<P: PCM>(a: P, bs: ISet<P>) -> bool`
- doc: A nondeterministic version of a [`frame_preserving_update`].

## frame_preserving_update_opt
- path: vstd/resource/relations.rs:34  (spec fn)
- sig: `pub open spec fn frame_preserving_update_opt<RA: ResourceAlgebra>(a: RA, b: RA) -> bool`
- doc: A frame preserving update with support for resource algebras.

## frame_preserving_update_nondeterministic_opt
- path: vstd/resource/relations.rs:41  (spec fn)
- sig: `pub open spec fn frame_preserving_update_nondeterministic_opt<RA: ResourceAlgebra>( a: RA, bs: ISet<RA>,`
- doc: A nondeterministic version of a [`frame_preserving_update_opt`].

## set_op
- path: vstd/resource/relations.rs:52  (spec fn)
- sig: `pub open spec fn set_op<RA: ResourceAlgebra>(s: ISet<RA>, t: RA) -> ISet<RA>`
- doc: The set of values such that can be created by composing an element of `s` with `t`.

## lemma_incl_transitive
- path: vstd/resource/relations.rs:56  (proof fn)
- sig: `pub proof fn lemma_incl_transitive<RA: ResourceAlgebra>(a: RA, b: RA, c: RA)`
- requires: incl(a, b), incl(b, c),
- ensures: incl(a, c),

## lemma_frame_preserving_opt
- path: vstd/resource/relations.rs:70  (proof fn)
- sig: `pub proof fn lemma_frame_preserving_opt<RA: ResourceAlgebra>(a: RA, b: RA)`
- requires: frame_preserving_update_opt::<RA>(a, b),
- ensures: frame_preserving_update::<Option<RA>>(Some(a), Some(b)),

## lemma_frame_preserving_update_nondeterministic_opt
- path: vstd/resource/relations.rs:78  (proof fn)
- sig: `pub proof fn lemma_frame_preserving_update_nondeterministic_opt<RA: ResourceAlgebra>( a: RA, bs: ISet<RA>, )`
- requires: frame_preserving_update_nondeterministic_opt::<RA>(a, bs),
- ensures: frame_preserving_update_nondeterministic::<Option<RA>>(Some(a), bs.map(|b| Some(b))),

## incl
- path: vstd/resource/storage_protocol.rs:64  (spec fn)
- sig: `pub open spec fn incl<K, V, P: Protocol<K, V>>(a: P, b: P) -> bool`

## guards
- path: vstd/resource/storage_protocol.rs:68  (spec fn)
- sig: `pub open spec fn guards<K, V, P: Protocol<K, V>>(p: P, b: IMap<K, V>) -> bool`

## exchanges
- path: vstd/resource/storage_protocol.rs:72  (spec fn)
- sig: `pub open spec fn exchanges<K, V, P: Protocol<K, V>>( p1: P, b1: IMap<K, V>, p2: P, b2: IMap<K, V>,`

## exchanges_nondeterministic
- path: vstd/resource/storage_protocol.rs:87  (spec fn)
- sig: `pub open spec fn exchanges_nondeterministic<K, V, P: Protocol<K, V>>( p1: P, s1: IMap<K, V>, new_values: ISet<(P, IMap<K, V>)>,`

## deposits
- path: vstd/resource/storage_protocol.rs:105  (spec fn)
- sig: `pub open spec fn deposits<K, V, P: Protocol<K, V>>(p1: P, b1: IMap<K, V>, p2: P) -> bool`

## withdraws
- path: vstd/resource/storage_protocol.rs:114  (spec fn)
- sig: `pub open spec fn withdraws<K, V, P: Protocol<K, V>>(p1: P, p2: P, b2: IMap<K, V>) -> bool`

## updates
- path: vstd/resource/storage_protocol.rs:123  (spec fn)
- sig: `pub open spec fn updates<K, V, P: Protocol<K, V>>(p1: P, p2: P) -> bool`

## set_op
- path: vstd/resource/storage_protocol.rs:129  (spec fn)
- sig: `pub open spec fn set_op<K, V, P: Protocol<K, V>>(s: ISet<(P, IMap<K, V>)>, t: P) -> ISet< (P, IMap<K, V>),`

## StorageResource::value
- path: vstd/resource/storage_protocol.rs:136  (spec fn)
- sig: `pub uninterp spec fn value(self) -> P`

## StorageResource::loc
- path: vstd/resource/storage_protocol.rs:138  (spec fn)
- sig: `pub uninterp spec fn loc(self) -> Loc`

## exc_bit_matches
- path: vstd/rwlock.rs:173  (fn)
- sig: `pub fn exc_bit_matches(&self) -> bool`

## count_matches
- path: vstd/rwlock.rs:180  (fn)
- sig: `pub fn count_matches(&self) -> bool`

## reader_agrees_storage
- path: vstd/rwlock.rs:186  (fn)
- sig: `pub fn reader_agrees_storage(&self) -> bool`

## writer_agrees_storage
- path: vstd/rwlock.rs:192  (fn)
- sig: `pub fn writer_agrees_storage(&self) -> bool`

## writer_agrees_storage_rev
- path: vstd/rwlock.rs:197  (fn)
- sig: `pub fn writer_agrees_storage_rev(&self) -> bool`

## sto_user_inv
- path: vstd/rwlock.rs:202  (fn)
- sig: `pub fn sto_user_inv(&self) -> bool`

## WriteHandle::rwlock
- path: vstd/rwlock.rs:399  (spec fn)
- sig: `pub closed spec fn rwlock(self) -> RwLock<V, Pred>`

## WriteHandle::release_write
- path: vstd/rwlock.rs:403  (fn)
- sig: `pub fn release_write(self, new_val: V)`
- requires: self.rwlock().inv(new_val),

## ReadHandle::view
- path: vstd/rwlock.rs:432  (spec fn)
- sig: `pub closed spec fn view(self) -> V`

## ReadHandle::rwlock
- path: vstd/rwlock.rs:436  (spec fn)
- sig: `pub closed spec fn rwlock(self) -> RwLock<V, Pred>`

## ReadHandle::borrow
- path: vstd/rwlock.rs:441  (fn)
- sig: `pub fn borrow<'b>(&'b self) -> (val: &'b V)`
- ensures: val == self.view(),
- doc: Obtain a shared reference to the object contained in the lock.

## ReadHandle::lemma_readers_match
- path: vstd/rwlock.rs:455  (proof fn)
- sig: `pub proof fn lemma_readers_match( tracked read_handle1: &ReadHandle<V, Pred>, tracked read_handle2: &ReadHandle<V, Pred>, )`
- requires: read_handle1.rwlock() == read_handle2.rwlock(),
- ensures: (equal(read_handle1.view(), read_handle2.view())),

## ReadHandle::release_read
- path: vstd/rwlock.rs:474  (fn)
- sig: `pub fn release_read(self)`

## RwLock::pred
- path: vstd/rwlock.rs:492  (spec fn)
- sig: `pub closed spec fn pred(&self) -> Pred`
- doc: Predicate configured for this lock instance.

## RwLock::inv
- path: vstd/rwlock.rs:498  (spec fn)
- sig: `pub open spec fn inv(&self, val: V) -> bool`
- doc: Indicates if the value `v` can be stored in the lock. Per the definition,

## RwLock::new
- path: vstd/rwlock.rs:502  (fn)
- sig: `pub fn new(val: V, Ghost(pred): Ghost<Pred>) -> (s: Self)`
- requires: pred.inv(val),
- ensures: s.pred() == pred,

## RwLock::acquire_write
- path: vstd/rwlock.rs:530  (fn)
- sig: `pub fn acquire_write(&self) -> (ret: (V, WriteHandle<'_, V, Pred>))`
- ensures: ({ let val = ret.0; let write_handle = ret.1; &&& write_handle.rwlock() == *self &&& self.inv(val)
- doc: Acquires an exclusive write-lock. To release it, use [`WriteHandle::release_write`].

## RwLock::acquire_read
- path: vstd/rwlock.rs:620  (fn)
- sig: `pub fn acquire_read(&self) -> (read_handle: ReadHandle<'_, V, Pred>)`
- ensures: read_handle.rwlock() == *self, self.inv(read_handle.view()),
- doc: Acquires a shared read-lock. To release it, use [`ReadHandle::release_read`].

## RwLock::into_inner
- path: vstd/rwlock.rs:702  (fn)
- sig: `pub fn into_inner(self) -> (v: V)`
- ensures: self.inv(v),
- doc: Destroys the lock and returns the inner object.

## Seq::empty
- path: vstd/seq.rs:934  (spec fn)
- sig: `pub closed spec fn empty() -> Seq<A>`
- doc: An empty sequence (i.e., a sequence of length 0).

## Seq::new
- path: vstd/seq.rs:940  (spec fn)
- sig: `pub closed spec fn new(len: nat, f: spec_fn(int) -> A) -> Seq<A>`
- doc: Construct a sequence `s` of length `len` where entry `s[i]` is given by `f(i)`.

## Seq::len
- path: vstd/seq.rs:952  (spec fn)
- sig: `pub closed spec fn len(self) -> nat`
- doc: The length of a sequence.

## Seq::index
- path: vstd/seq.rs:961  (spec fn)
- sig: `pub closed spec fn index(self, i: int) -> A recommends 0 <= i < self.len(),`
- doc: Gets the value at the given index `i`.

## Seq::spec_index
- path: vstd/seq.rs:970  (spec fn)
- sig: `pub open spec fn spec_index(self, i: int) -> A recommends 0 <= i < self.len(),`
- doc: `[]` operator, synonymous with `index`

## Seq::push
- path: vstd/seq.rs:990  (spec fn)
- sig: `pub closed spec fn push(self, a: A) -> Seq<A>`
- doc: Appends the value `a` to the end of the sequence.

## Seq::update
- path: vstd/seq.rs:1007  (spec fn)
- sig: `pub closed spec fn update(self, i: int, a: A) -> Seq<A> recommends 0 <= i < self.len(),`
- doc: Updates the sequence at the given index, replacing the element with the given

## Seq::subrange
- path: vstd/seq.rs:1028  (spec fn)
- sig: `pub closed spec fn subrange(self, start_inclusive: int, end_exclusive: int) -> Seq<A> recommends 0 <= start_inclusive <= end_exclusive <= self.len(),`
- doc: Returns a sequence for the given subrange.

## Seq::take
- path: vstd/seq.rs:1037  (spec fn)
- sig: `pub open spec fn take(self, n: int) -> Seq<A>`
- doc: Returns a sequence containing only the first n elements of the original sequence

## Seq::skip
- path: vstd/seq.rs:1043  (spec fn)
- sig: `pub open spec fn skip(self, n: int) -> Seq<A>`
- doc: Returns a sequence without the first n elements of the original sequence

## Seq::add
- path: vstd/seq.rs:1058  (spec fn)
- sig: `pub closed spec fn add(self, rhs: Seq<A>) -> Seq<A>`
- doc: Concatenates the sequences.

## Seq::spec_add
- path: vstd/seq.rs:1064  (spec fn)
- sig: `pub open spec fn spec_add(self, rhs: Seq<A>) -> Seq<A>`
- doc: `+` operator, synonymous with `add`

## Seq::last
- path: vstd/seq.rs:1070  (spec fn)
- sig: `pub open spec fn last(self) -> A recommends 0 < self.len(),`
- doc: Returns the last element of the sequence.

## Seq::first
- path: vstd/seq.rs:1079  (spec fn)
- sig: `pub open spec fn first(self) -> A recommends 0 < self.len(),`
- doc: Returns the first element of the sequence.

## axiom_seq_index_decreases
- path: vstd/seq.rs:1216  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_index_decreases<A>(s: Seq<A>, i: int)`
- requires: 0 <= i < s.len(),
- ensures: #[trigger] (decreases_to!(s => s[i])),

## lemma_seq_index_decreases
- path: vstd/seq.rs:1225  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_index_decreases<A>(s: Seq<A>, i: int)`
- requires: 0 <= i < s.len(),
- ensures: #[trigger] (decreases_to!(s => s[i])),

## axiom_seq_subrange_decreases
- path: vstd/seq.rs:1246  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_subrange_decreases<A>(s: Seq<A>, i: int, j: int)`
- requires: 0 <= i <= j <= s.len(), s.subrange(i, j).len() < s.len(),
- ensures: #[trigger] (decreases_to!(s => s.subrange(i, j))),

## lemma_seq_subrange_decreases
- path: vstd/seq.rs:1256  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_subrange_decreases<A>(s: Seq<A>, i: int, j: int)`
- requires: 0 <= i <= j <= s.len(), s.subrange(i, j).len() < s.len(),
- ensures: #[trigger] (decreases_to!(s => s.subrange(i, j))),

## axiom_seq_empty
- path: vstd/seq.rs:1274  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_empty<A>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- ensures: #[trigger] Seq::<A>::empty().len() == 0,

## lemma_seq_empty
- path: vstd/seq.rs:1282  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_empty<A>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::seq::group_seq_axioms`, `vstd::seq::group_seq_lemmas`: write `broadcast use vstd::seq::group_seq_axioms;` and the fact is available.
- ensures: #[trigger] Seq::<A>::empty().len() == 0,

## axiom_seq_new_len
- path: vstd/seq.rs:1300  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_new_len<A>(len: nat, f: spec_fn(int) -> A)`
- ensures: #[trigger] Seq::new(len, f).len() == len,

## lemma_seq_new_len
- path: vstd/seq.rs:1307  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_new_len<A>(len: nat, f: spec_fn(int) -> A)`
- ensures: #[trigger] Seq::new(len, f).len() == len,

## axiom_seq_new_index
- path: vstd/seq.rs:1331  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_new_index<A>(len: nat, f: spec_fn(int) -> A, i: int)`
- requires: 0 <= i < len,
- ensures: #[trigger] Seq::new(len, f)[i] == f(i),

## lemma_seq_new_index
- path: vstd/seq.rs:1340  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_new_index<A>(len: nat, f: spec_fn(int) -> A, i: int)`
- requires: 0 <= i < len,
- ensures: #[trigger] Seq::new(len, f)[i] == f(i),

## axiom_seq_push_len
- path: vstd/seq.rs:1369  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_push_len<A>(s: Seq<A>, a: A)`
- ensures: #[trigger] s.push(a).len() == s.len() + 1,

## lemma_seq_push_len
- path: vstd/seq.rs:1376  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_push_len<A>(s: Seq<A>, a: A)`
- ensures: #[trigger] s.push(a).len() == s.len() + 1,

## axiom_seq_push_index_same
- path: vstd/seq.rs:1384  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_push_index_same<A>(s: Seq<A>, a: A, i: int)`
- requires: i == s.len(),
- ensures: #[trigger] s.push(a)[i] == a,

## lemma_seq_push_index_same
- path: vstd/seq.rs:1393  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_push_index_same<A>(s: Seq<A>, a: A, i: int)`
- requires: i == s.len(),
- ensures: #[trigger] s.push(a)[i] == a,

## axiom_seq_push_index_different
- path: vstd/seq.rs:1403  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_push_index_different<A>(s: Seq<A>, a: A, i: int)`
- requires: i < s.len(),
- ensures: #[trigger] s.push(a)[i] == s[i],

## lemma_seq_push_index_different
- path: vstd/seq.rs:1412  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_push_index_different<A>(s: Seq<A>, a: A, i: int)`
- requires: i < s.len(),
- ensures: #[trigger] s.push(a)[i] == s[i],

## lemma_seq_push_index_different_alt
- path: vstd/seq.rs:1422  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_push_index_different_alt<A>(s: Seq<A>, a: A, i: int)`
- requires: i < s.len(),
- ensures: (#[trigger] s.push(a))[i] == #[trigger] s[i],

## axiom_seq_update_len
- path: vstd/seq.rs:1433  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_update_len<A>(s: Seq<A>, i: int, a: A)`
- ensures: #[trigger] s.update(i, a).len() == s.len(),

## lemma_seq_update_len
- path: vstd/seq.rs:1440  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_update_len<A>(s: Seq<A>, i: int, a: A)`
- ensures: #[trigger] s.update(i, a).len() == s.len(),

## axiom_seq_update_same
- path: vstd/seq.rs:1449  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_update_same<A>(s: Seq<A>, i: int, a: A)`
- requires: 0 <= i < s.len(),
- ensures: #[trigger] s.update(i, a)[i] == a,

## lemma_seq_update_same
- path: vstd/seq.rs:1458  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_update_same<A>(s: Seq<A>, i: int, a: A)`
- requires: 0 <= i < s.len(),
- ensures: #[trigger] s.update(i, a)[i] == a,

## lemma_seq_update_same_alt
- path: vstd/seq.rs:1468  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_update_same_alt<A>(s: Seq<A>, i: int, a: A)`
- requires: 0 <= i < s.len(),
- ensures: #![trigger s.update(i, a), s[i]] s.update(i, a)[i] == a,

## axiom_seq_update_different
- path: vstd/seq.rs:1480  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_update_different<A>(s: Seq<A>, i1: int, i2: int, a: A)`
- requires: i1 != i2,
- ensures: #[trigger] s.update(i2, a)[i1] == s[i1],

## lemma_seq_update_different
- path: vstd/seq.rs:1489  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_update_different<A>(s: Seq<A>, i1: int, i2: int, a: A)`
- requires: i1 != i2,
- ensures: #[trigger] s.update(i2, a)[i1] == s[i1],

## lemma_seq_update_different_alt
- path: vstd/seq.rs:1499  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_update_different_alt<A>(s: Seq<A>, i1: int, i2: int, a: A)`
- requires: i1 != i2,
- ensures: (#[trigger] s.update(i2, a))[i1] == #[trigger] s[i1],

## axiom_seq_ext_equal
- path: vstd/seq.rs:1510  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_ext_equal<A>(s1: Seq<A>, s2: Seq<A>)`
- ensures: #[trigger] (s1 =~= s2) <==> { &&& s1.len() == s2.len() &&& forall|i: int| 0 <= i < s1.len() ==> s1[i] == s2[i] },

## lemma_seq_ext_equal
- path: vstd/seq.rs:1520  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_ext_equal<A>(s1: Seq<A>, s2: Seq<A>)`
- ensures: #[trigger] (s1 =~= s2) <==> { &&& s1.len() == s2.len() &&& forall|i: int| 0 <= i < s1.len() ==> s1[i] == s2[i] },

## axiom_seq_ext_equal_deep
- path: vstd/seq.rs:1572  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_ext_equal_deep<A>(s1: Seq<A>, s2: Seq<A>)`
- ensures: #[trigger] (s1 =~~= s2) <==> { &&& s1.len() == s2.len() &&& forall|i: int| 0 <= i < s1.len() ==> s1[i] =~~= s2[i] },

## lemma_seq_ext_equal_deep
- path: vstd/seq.rs:1582  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_ext_equal_deep<A>(s1: Seq<A>, s2: Seq<A>)`
- ensures: #[trigger] (s1 =~~= s2) <==> { &&& s1.len() == s2.len() &&& forall|i: int| 0 <= i < s1.len() ==> s1[i] =~~= s2[i] },

## axiom_seq_subrange_len
- path: vstd/seq.rs:1633  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_subrange_len<A>(s: Seq<A>, j: int, k: int)`
- requires: 0 <= j <= k <= s.len(),
- ensures: #[trigger] s.subrange(j, k).len() == k - j,

## lemma_seq_subrange_len
- path: vstd/seq.rs:1642  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_subrange_len<A>(s: Seq<A>, j: int, k: int)`
- requires: 0 <= j <= k <= s.len(),
- ensures: #[trigger] s.subrange(j, k).len() == k - j,

## lemma_seq_subrange_composition
- path: vstd/seq.rs:1651  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_subrange_composition<A>( s: Seq<A>, i1: int, j1: int, i2: int, j2: int, )`
- requires: 0 <= i1 <= j1 <= s.len(), 0 <= i2 <= j2 <= j1 - i1,
- ensures: #[trigger] s.subrange(i1, j1).subrange(i2, j2) == s.subrange(i1 + i2, i1 + j2),

## axiom_seq_subrange_index
- path: vstd/seq.rs:1668  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_subrange_index<A>(s: Seq<A>, j: int, k: int, i: int)`
- requires: 0 <= j <= k <= s.len(), 0 <= i < k - j,
- ensures: #[trigger] s.subrange(j, k)[i] == s[i + j],

## lemma_seq_subrange_index
- path: vstd/seq.rs:1678  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_subrange_index<A>(s: Seq<A>, j: int, k: int, i: int)`
- requires: 0 <= j <= k <= s.len(), 0 <= i < k - j,
- ensures: #[trigger] s.subrange(j, k)[i] == s[i + j],

## lemma_seq_subrange_index_alt
- path: vstd/seq.rs:1689  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_subrange_index_alt<A>(s: Seq<A>, j: int, k: int, i: int)`
- requires: 0 <= j <= k <= s.len(), 0 <= i - j < k - j,
- ensures: (#[trigger] s.subrange(j, k))[i - j] == #[trigger] s[i],

## lemma_seq_two_subranges_index
- path: vstd/seq.rs:1701  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_two_subranges_index<A>(s: Seq<A>, j: int, k1: int, k2: int, i: int)`
- requires: 0 <= j <= k1 <= s.len(), 0 <= j <= k2 <= s.len(), 0 <= i < k1 - j, 0 <= i < k2 - j,
- ensures: #[trigger] s.subrange(j, k1)[i] == (#[trigger] s.subrange(j, k2))[i],

## axiom_seq_add_len
- path: vstd/seq.rs:1715  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_add_len<A>(s1: Seq<A>, s2: Seq<A>)`
- ensures: #[trigger] s1.add(s2).len() == s1.len() + s2.len(),

## lemma_seq_add_len
- path: vstd/seq.rs:1722  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_add_len<A>(s1: Seq<A>, s2: Seq<A>)`
- ensures: #[trigger] s1.add(s2).len() == s1.len() + s2.len(),

## axiom_seq_add_index1
- path: vstd/seq.rs:1730  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_add_index1<A>(s1: Seq<A>, s2: Seq<A>, i: int)`
- requires: i < s1.len(),
- ensures: #[trigger] s1.add(s2)[i] == s1[i],

## lemma_seq_add_index1
- path: vstd/seq.rs:1739  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_add_index1<A>(s1: Seq<A>, s2: Seq<A>, i: int)`
- requires: i < s1.len(),
- ensures: #[trigger] s1.add(s2)[i] == s1[i],

## axiom_seq_add_index2
- path: vstd/seq.rs:1749  (proof fn)
- sig: `pub broadcast proof fn axiom_seq_add_index2<A>(s1: Seq<A>, s2: Seq<A>, i: int)`
- requires: s1.len() <= i < s1.len() + s2.len(),
- ensures: #[trigger] s1.add(s2)[i] == s2[i - s1.len()],

## lemma_seq_add_index2
- path: vstd/seq.rs:1758  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_add_index2<A>(s1: Seq<A>, s2: Seq<A>, i: int)`
- requires: s1.len() <= i < s1.len() + s2.len(),
- ensures: #[trigger] s1.add(s2)[i] == s2[i - s1.len()],

## lemma_seq_add_index1_alt
- path: vstd/seq.rs:1768  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_add_index1_alt<A>(s1: Seq<A>, s2: Seq<A>, i: int)`
- requires: 0 <= i < s1.len(),
- ensures: (#[trigger] s1.add(s2))[i] == #[trigger] s1[i],

## lemma_seq_add_index2_alt
- path: vstd/seq.rs:1779  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_add_index2_alt<A>(s1: Seq<A>, s2: Seq<A>, i: int)`
- requires: 0 <= i < s2.len(),
- ensures: (#[trigger] s1.add(s2))[i + s1.len()] == #[trigger] s2[i],

## group_seq_axioms
- path: vstd/seq.rs  (broadcast group)
- members: lemma_seq_index_decreases lemma_seq_subrange_decreases lemma_seq_empty lemma_seq_new_len lemma_seq_new_index lemma_seq_push_len lemma_seq_push_index_same lemma_seq_push_index_different lemma_seq_update_len lemma_seq_update_same lemma_seq_update_different lemma_seq_ext_equal lemma_seq_ext_equal_deep lemma_seq_subrange_len lemma_seq_subrange_index lemma_seq_two_subranges_index lemma_seq_add_len lemma_seq_add_index1 lemma_seq_add_index2

## group_seq_lemmas
- path: vstd/seq.rs  (broadcast group)
- members: lemma_seq_index_decreases lemma_seq_subrange_decreases lemma_seq_empty lemma_seq_new_len lemma_seq_new_index lemma_seq_push_len lemma_seq_push_index_same lemma_seq_push_index_different lemma_seq_update_len lemma_seq_update_same lemma_seq_update_different lemma_seq_ext_equal lemma_seq_ext_equal_deep lemma_seq_subrange_len lemma_seq_subrange_index lemma_seq_two_subranges_index lemma_seq_add_len lemma_seq_add_index1 lemma_seq_add_index2

## group_seq_lemmas_expensive
- path: vstd/seq.rs  (broadcast group)
- members: lemma_seq_push_index_different_alt lemma_seq_update_same_alt lemma_seq_update_different_alt lemma_seq_subrange_index_alt lemma_seq_add_index1_alt lemma_seq_add_index2_alt

## Seq::map
- path: vstd/seq_lib.rs:24  (spec fn)
- sig: `pub open spec fn map<B>(self, f: spec_fn(int, A) -> B) -> Seq<B>`
- doc: Applies the function `f` to each element of the sequence, and returns

## Seq::map_values
- path: vstd/seq_lib.rs:30  (spec fn)
- sig: `pub open spec fn map_values<B>(self, f: spec_fn(A) -> B) -> Seq<B>`
- doc: Applies the function `f` to each element of the sequence, and returns

## Seq::flat_map
- path: vstd/seq_lib.rs:47  (spec fn)
- sig: `pub open spec fn flat_map<B>(self, f: spec_fn(A) -> Seq<B>) -> Seq<B>`
- doc: Applies the function `f` to each element of the sequence,

## Seq::as_ref
- path: vstd/seq_lib.rs:52  (spec fn)
- sig: `pub open spec fn as_ref(&self) -> Seq<&A>`
- doc: Add a reference (&) to each element of the sequence

## Seq::is_prefix_of
- path: vstd/seq_lib.rs:67  (spec fn)
- sig: `pub open spec fn is_prefix_of(self, other: Self) -> bool`
- doc: Is true if the calling sequence is a prefix of the given sequence 'other'.

## Seq::is_suffix_of
- path: vstd/seq_lib.rs:82  (spec fn)
- sig: `pub open spec fn is_suffix_of(self, other: Self) -> bool`
- doc: Is true if the calling sequence is a suffix of the given sequence 'other'.

## Seq::sort_by
- path: vstd/seq_lib.rs:96  (spec fn)
- sig: `pub closed spec fn sort_by(self, leq: spec_fn(A, A) -> bool) -> Seq<A> recommends total_ordering(leq),`
- doc: Sorts the sequence according to the given leq function

## Seq::all
- path: vstd/seq_lib.rs:123  (spec fn)
- sig: `pub open spec fn all(self, pred: spec_fn(A) -> bool) -> bool`
- doc: Tests if all elements in the sequence satisfy the predicate.

## Seq::any
- path: vstd/seq_lib.rs:137  (spec fn)
- sig: `pub open spec fn any(self, pred: spec_fn(A) -> bool) -> bool`
- doc: Tests if any element in the sequence satisfies the predicate.

## Seq::exactly_one
- path: vstd/seq_lib.rs:150  (spec fn)
- sig: `pub open spec fn exactly_one(self, pred: spec_fn(A) -> bool) -> bool`
- doc: Checks that exactly one element in the sequence satisfies the given predicate.

## Seq::lemma_sort_by_ensures
- path: vstd/seq_lib.rs:154  (proof fn)
- sig: `pub proof fn lemma_sort_by_ensures(self, leq: spec_fn(A, A) -> bool)`
- requires: total_ordering(leq),
- ensures: self.to_multiset() =~= self.sort_by(leq).to_multiset(), sorted_by(self.sort_by(leq), leq), forall|x: A| !self.contains(x) ==> !(#[trigger] self.sort_by(leq).contains(x)),

## Seq::filter
- path: vstd/seq_lib.rs:200  (spec fn)
- sig: `pub open spec fn filter(self, pred: spec_fn(A) -> bool) -> Self`
- doc: Returns the sequence containing only the elements of the original sequence

## Seq::lemma_filter_len
- path: vstd/seq_lib.rs:215  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_len(self, pred: spec_fn(A) -> bool)`
- ensures: // the filtered list can't grow #[trigger] self.filter(pred).len() <= self.len(),

## Seq::lemma_filter_pred
- path: vstd/seq_lib.rs:229  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_pred(self, pred: spec_fn(A) -> bool, i: int)`
- requires: 0 <= i < self.filter(pred).len(),
- ensures: pred(#[trigger] self.filter(pred)[i]),

## Seq::lemma_filter_contains
- path: vstd/seq_lib.rs:240  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_contains(self, pred: spec_fn(A) -> bool, i: int)`
- requires: 0 <= i < self.len() && pred(self[i]),
- ensures: #[trigger] self.filter(pred).contains(self[i]),

## Seq::filter_distributes_over_add
- path: vstd/seq_lib.rs:295  (proof fn)
- sig: `pub broadcast proof fn filter_distributes_over_add(a: Self, b: Self, pred: spec_fn(A) -> bool)`
- ensures: #[trigger] (a + b).filter(pred) == a.filter(pred) + b.filter(pred),

## Seq::add_empty_left
- path: vstd/seq_lib.rs:317  (proof fn)
- sig: `pub broadcast proof fn add_empty_left(a: Self, b: Self)`
- requires: a.len() == 0,
- ensures: #[trigger] (a + b) == b,

## Seq::add_empty_right
- path: vstd/seq_lib.rs:326  (proof fn)
- sig: `pub broadcast proof fn add_empty_right(a: Self, b: Self)`
- requires: b.len() == 0,
- ensures: #[trigger] (a + b) == a,

## Seq::push_distributes_over_add
- path: vstd/seq_lib.rs:335  (proof fn)
- sig: `pub broadcast proof fn push_distributes_over_add(a: Self, b: Self, elt: A)`
- ensures: #[trigger] (a + b).push(elt) == a + b.push(elt),

## Seq::max_via
- path: vstd/seq_lib.rs:343  (spec fn)
- sig: `pub open spec fn max_via(self, leq: spec_fn(A, A) -> bool) -> A recommends self.len() > 0,`
- doc: Returns the maximum value in a non-empty sequence, given sorting function leq

## Seq::min_via
- path: vstd/seq_lib.rs:360  (spec fn)
- sig: `pub open spec fn min_via(self, leq: spec_fn(A, A) -> bool) -> A recommends self.len() > 0,`
- doc: Returns the minimum value in a non-empty sequence, given sorting function leq

## Seq::contains
- path: vstd/seq_lib.rs:379  (spec fn)
- sig: `pub open spec fn contains(self, needle: A) -> bool`

## Seq::index_of
- path: vstd/seq_lib.rs:385  (spec fn)
- sig: `pub open spec fn index_of(self, needle: A) -> int`
- doc: Returns an index where `needle` appears in the sequence.

## Seq::index_of_first
- path: vstd/seq_lib.rs:391  (spec fn)
- sig: `pub closed spec fn index_of_first(self, needle: A) -> (result: Option<int>)`
- doc: For an element that occurs at least once in a sequence, if its first occurence

## Seq::index_of_last
- path: vstd/seq_lib.rs:441  (spec fn)
- sig: `pub closed spec fn index_of_last(self, needle: A) -> Option<int>`
- doc: For an element that occurs at least once in a sequence, if its last occurence

## Seq::drop_last
- path: vstd/seq_lib.rs:493  (spec fn)
- sig: `pub open spec fn drop_last(self) -> Seq<A> recommends self.len() >= 1,`
- doc: Drops the last element of a sequence and returns a sequence whose length is

## Seq::drop_first
- path: vstd/seq_lib.rs:511  (spec fn)
- sig: `pub open spec fn drop_first(self) -> Seq<A> recommends self.len() >= 1,`

## Seq::no_duplicates
- path: vstd/seq_lib.rs:519  (spec fn)
- sig: `pub open spec fn no_duplicates(self) -> bool`
- doc: returns `true` if the sequence has no duplicate elements

## Seq::disjoint
- path: vstd/seq_lib.rs:524  (spec fn)
- sig: `pub open spec fn disjoint(self, other: Self) -> bool`
- doc: Returns `true` if two sequences are disjoint

## Seq::to_set
- path: vstd/seq_lib.rs:529  (spec fn)
- sig: `pub closed spec fn to_set(self) -> Set<A>`
- doc: Converts a sequence into a set

## Seq::to_set_ensures
- path: vstd/seq_lib.rs:533  (proof fn)
- sig: `pub broadcast proof fn to_set_ensures(self)`
- ensures: #![trigger(self.to_set())] // to_set works for all indices forall|i| 0 <= i < self.len() ==> #[trigger] self.to_set().contains(self[i]), // to_set finds everything .contains finds

## Seq::to_iset
- path: vstd/seq_lib.rs:566  (spec fn)
- sig: `pub open spec fn to_iset(self) -> ISet<A>`

## Seq::to_multiset
- path: vstd/seq_lib.rs:571  (spec fn)
- sig: `pub closed spec fn to_multiset(self) -> Multiset<A>`
- doc: Converts a sequence into a multiset

## Seq::to_multiset_ensures
- path: vstd/seq_lib.rs:584  (proof fn)
- sig: `pub broadcast proof fn to_multiset_ensures(self)`
- ensures: forall|a: A| #[trigger] (self.push(a).to_multiset()) =~= self.to_multiset().insert(a),  // to_multiset_build forall|i: int| 0 <= i < self.len() ==> #[trigger] (self.remove(i).to_multiset()) =~= self.to_multiset().remove(self[i]),  // to_multiset_remove self.len() == #[trigger] self.to_multiset().len(),  // to_multiset_len
- doc: Proof of function to_multiset() correctness

## Seq::insert
- path: vstd/seq_lib.rs:600  (spec fn)
- sig: `pub open spec fn insert(self, i: int, a: A) -> Seq<A> recommends 0 <= i <= self.len(),`
- doc: Insert item a at index i, shifting remaining elements (if any) to the right

## Seq::remove
- path: vstd/seq_lib.rs:620  (spec fn)
- sig: `pub open spec fn remove(self, i: int) -> Seq<A> recommends 0 <= i < self.len(),`
- doc: Remove item at index i, shifting remaining elements to the left

## Seq::remove_value
- path: vstd/seq_lib.rs:641  (spec fn)
- sig: `pub open spec fn remove_value(self, val: A) -> Seq<A>`
- doc: If a given element occurs at least once in a sequence, the sequence without

## Seq::reverse
- path: vstd/seq_lib.rs:650  (spec fn)
- sig: `pub open spec fn reverse(self) -> Seq<A>`
- doc: Returns the sequence that is in reverse order to a given sequence.

## Seq::zip_with
- path: vstd/seq_lib.rs:662  (spec fn)
- sig: `pub open spec fn zip_with<B>(self, other: Seq<B>) -> Seq<(A, B)> recommends self.len() == other.len(),`
- doc: Zips two sequences of equal length into one sequence that consists of pairs.

## Seq::fold_left
- path: vstd/seq_lib.rs:682  (spec fn)
- sig: `pub open spec fn fold_left<B>(self, b: B, f: spec_fn(B, A) -> B) -> (res: B)`
- doc: Folds the sequence to the left, applying `f` to perform the fold.

## Seq::fold_left_alt
- path: vstd/seq_lib.rs:695  (spec fn)
- sig: `pub open spec fn fold_left_alt<B>(self, b: B, f: spec_fn(B, A) -> B) -> (res: B)`
- doc: Equivalent to [`Self::fold_left`] but defined by breaking off the leftmost element when

## Seq::lemma_fold_left_split
- path: vstd/seq_lib.rs:706  (proof fn)
- sig: `pub broadcast proof fn lemma_fold_left_split<B>(self, b: B, f: spec_fn(B, A) -> B, k: int)`
- requires: 0 <= k <= self.len(),
- ensures: self.subrange(k, self.len() as int).fold_left( (#[trigger] self.subrange(0, k).fold_left(b, f)), f, ) == self.fold_left(b, f),
- doc: A lemma that proves how [`Self::fold_left`] distributes over splitting a sequence.

## Seq::lemma_fold_left_alt
- path: vstd/seq_lib.rs:769  (proof fn)
- sig: `pub proof fn lemma_fold_left_alt<B>(self, b: B, f: spec_fn(B, A) -> B)`
- ensures: self.fold_left(b, f) == self.fold_left_alt(b, f),
- doc: [`Self::fold_left`] and [`Self::fold_left_alt`] are equivalent.

## Seq::lemma_reverse_fold_left
- path: vstd/seq_lib.rs:790  (proof fn)
- sig: `pub proof fn lemma_reverse_fold_left<B>(self, v: B, f: spec_fn(B, A) -> B)`
- ensures: self.reverse().fold_left(v, f) == self.fold_right(|a: A, b: B| f(b, a), v),
- doc: [`Self::fold_left`] on the reversed sequence is equivalent to

## Seq::fold_right
- path: vstd/seq_lib.rs:806  (spec fn)
- sig: `pub open spec fn fold_right<B>(self, f: spec_fn(A, B) -> B, b: B) -> (res: B)`
- doc: Folds the sequence to the right, applying `f` to perform the fold.

## Seq::fold_right_alt
- path: vstd/seq_lib.rs:819  (spec fn)
- sig: `pub open spec fn fold_right_alt<B>(self, f: spec_fn(A, B) -> B, b: B) -> (res: B)`
- doc: Equivalent to [`Self::fold_right`] but defined by breaking off the leftmost element when

## Seq::lemma_fold_right_split
- path: vstd/seq_lib.rs:830  (proof fn)
- sig: `pub broadcast proof fn lemma_fold_right_split<B>(self, f: spec_fn(A, B) -> B, b: B, k: int)`
- requires: 0 <= k <= self.len(),
- ensures: self.subrange(0, k).fold_right( f, (#[trigger] self.subrange(k, self.len() as int).fold_right(f, b)), ) == self.fold_right(f, b),
- doc: A lemma that proves how [`Self::fold_right`] distributes over splitting a sequence.

## Seq::lemma_fold_right_commute_one
- path: vstd/seq_lib.rs:863  (proof fn)
- sig: `pub proof fn lemma_fold_right_commute_one<B>(self, a: A, f: spec_fn(A, B) -> B, v: B)`
- requires: commutative_foldr(f),
- ensures: self.fold_right(f, f(a, v)) == f(a, self.fold_right(f, v)),

## Seq::lemma_fold_right_alt
- path: vstd/seq_lib.rs:876  (proof fn)
- sig: `pub proof fn lemma_fold_right_alt<B>(self, f: spec_fn(A, B) -> B, b: B)`
- ensures: self.fold_right(f, b) == self.fold_right_alt(f, b),
- doc: [`Self::fold_right`] and [`Self::fold_right_alt`] are equivalent.

## Seq::lemma_reverse_fold_right
- path: vstd/seq_lib.rs:893  (proof fn)
- sig: `pub proof fn lemma_reverse_fold_right<B>(self, v: B, f: spec_fn(A, B) -> B)`
- ensures: self.reverse().fold_right(f, v) == self.fold_left(v, |b: B, a: A| f(a, b)),
- doc: [`Self::fold_right`] on the reversed sequence is equivalent to

## Seq::lemma_multiset_has_no_duplicates
- path: vstd/seq_lib.rs:923  (proof fn)
- sig: `pub proof fn lemma_multiset_has_no_duplicates(self)`
- requires: self.no_duplicates(),
- ensures: forall|x: A| self.to_multiset().contains(x) ==> self.to_multiset().count(x) == 1,
- doc: Given a sequence with no duplicates, each element occurs only

## Seq::lemma_multiset_has_no_duplicates_conv
- path: vstd/seq_lib.rs:945  (proof fn)
- sig: `pub proof fn lemma_multiset_has_no_duplicates_conv(self)`
- requires: forall|x: A| self.to_multiset().contains(x) ==> self.to_multiset().count(x) == 1,
- ensures: self.no_duplicates(),
- doc: If, in a sequence's conversion to a multiset, each element occurs only once,

## Seq::lemma_reverse_to_multiset
- path: vstd/seq_lib.rs:980  (proof fn)
- sig: `pub proof fn lemma_reverse_to_multiset(self)`
- ensures: self.reverse().to_multiset() =~= self.to_multiset(),
- doc: Conversion of a sequence to multiset is equivalent to conversion of its reversion to multiset

## Seq::lemma_add_last_back
- path: vstd/seq_lib.rs:1004  (proof fn)
- sig: `pub proof fn lemma_add_last_back(self)`
- requires: 0 < self.len(),
- ensures: #[trigger] self.drop_last().push(self.last()) =~= self,
- doc: The concatenation of two subsequences derived from a non-empty sequence,

## Seq::lemma_indexing_implies_membership
- path: vstd/seq_lib.rs:1016  (proof fn)
- sig: `pub proof fn lemma_indexing_implies_membership(self, f: spec_fn(A) -> bool)`
- requires: forall|i: int| 0 <= i < self.len() ==> #[trigger] f(#[trigger] self[i]),
- ensures: forall|x: A| #[trigger] self.contains(x) ==> #[trigger] f(x),
- doc: If a predicate is true at every index of a sequence,

## Seq::lemma_membership_implies_indexing
- path: vstd/seq_lib.rs:1029  (proof fn)
- sig: `pub proof fn lemma_membership_implies_indexing(self, f: spec_fn(A) -> bool)`
- requires: forall|x: A| #[trigger] self.contains(x) ==> #[trigger] f(x),
- ensures: forall|i: int| 0 <= i < self.len() ==> #[trigger] f(self[i]),
- doc: If a predicate is true for every member of a sequence as a collection,

## Seq::lemma_split_at
- path: vstd/seq_lib.rs:1043  (proof fn)
- sig: `pub proof fn lemma_split_at(self, pos: int)`
- requires: 0 <= pos <= self.len(),
- ensures: self.subrange(0, pos) + self.subrange(pos, self.len() as int) =~= self,
- doc: A sequence that is sliced at the pos-th element, concatenated

## Seq::lemma_element_from_slice
- path: vstd/seq_lib.rs:1052  (proof fn)
- sig: `pub proof fn lemma_element_from_slice(self, new: Seq<A>, a: int, b: int, pos: int)`
- requires: 0 <= a <= b <= self.len(), new == self.subrange(a, b), a <= pos < b,
- ensures: pos - a < new.len(), new[pos - a] == self[pos],
- doc: Any element in a slice is included in the original sequence.

## Seq::lemma_slice_of_slice
- path: vstd/seq_lib.rs:1065  (proof fn)
- sig: `pub proof fn lemma_slice_of_slice(self, s1: int, e1: int, s2: int, e2: int)`
- requires: 0 <= s1 <= e1 <= self.len(), 0 <= s2 <= e2 <= e1 - s1,
- ensures: self.subrange(s1, e1).subrange(s2, e2) =~= self.subrange(s1 + s2, s1 + e2),
- doc: A slice (from s2..e2) of a slice (from s1..e1) of a sequence is equal to just a

## Seq::lemma_cardinality_of_set
- path: vstd/seq_lib.rs:1101  (proof fn)
- sig: `pub proof fn lemma_cardinality_of_set(self)`
- ensures: self.to_set().len() <= self.len(),
- doc: The cardinality of a set of elements is always less than or

## Seq::lemma_cardinality_of_empty_set_is_0
- path: vstd/seq_lib.rs:1116  (proof fn)
- sig: `pub proof fn lemma_cardinality_of_empty_set_is_0(self)`
- ensures: self.to_set().len() == 0 <==> self.len() == 0,
- doc: A sequence is of length 0 if and only if its conversion to

## Seq::lemma_no_dup_set_cardinality
- path: vstd/seq_lib.rs:1135  (proof fn)
- sig: `pub proof fn lemma_no_dup_set_cardinality(self)`
- requires: self.to_set().len() == self.len(),
- ensures: self.no_duplicates(),
- doc: A sequence with cardinality equal to its set has no duplicates.

## Seq::lemma_to_set_map_commutes
- path: vstd/seq_lib.rs:1167  (proof fn)
- sig: `pub broadcast proof fn lemma_to_set_map_commutes<B>(self, f: spec_fn(A) -> B)`
- ensures: #[trigger] self.to_set().map(f) =~= self.map_values(f).to_set(),
- doc: Mapping a function over a sequence and converting to a set is the same

## Seq::lemma_to_iset_map_commutes
- path: vstd/seq_lib.rs:1191  (proof fn)
- sig: `pub broadcast proof fn lemma_to_iset_map_commutes<B>(self, f: spec_fn(A) -> B)`
- ensures: #[trigger] self.to_iset().map(f) =~= self.map_values(f).to_iset(),
- doc: Mapping a function over a sequence and converting to an ISet is the same

## Seq::lemma_to_set_insert_commutes
- path: vstd/seq_lib.rs:1217  (proof fn)
- sig: `pub broadcast proof fn lemma_to_set_insert_commutes(sq: Seq<A>, elt: A)`
- ensures: #[trigger] (sq + seq![elt]).to_set() =~= sq.to_set().insert(elt),
- doc: Appending an element to a sequence and converting to a Set is equal

## Seq::lemma_to_iset_insert_commutes
- path: vstd/seq_lib.rs:1232  (proof fn)
- sig: `pub broadcast proof fn lemma_to_iset_insert_commutes(sq: Seq<A>, elt: A)`
- ensures: #[trigger] (sq + seq![elt]).to_iset() =~= sq.to_iset().insert(elt),
- doc: Appending an element to a sequence and converting to an ISet is equal

## Seq::update_subrange_with
- path: vstd/seq_lib.rs:1248  (spec fn)
- sig: `pub open spec fn update_subrange_with(self, off: int, vs: Self) -> Self recommends 0 <= off, off + vs.len() <= self.len(),`
- doc: Update a subrange of a sequence starting at `off` to values `vs`.

## Seq::lemma_seq_skip_skip
- path: vstd/seq_lib.rs:1275  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_skip_skip(self, i: int)`
- ensures: 0 <= i < self.len() ==> (self.skip(i)).skip(1) =~= #[trigger] self.skip(i + 1),
- doc: Skipping `i` elements and then 1 more is equivalent to skipping `i + 1` elements.

## Seq::lemma_contains_to_index
- path: vstd/seq_lib.rs:1295  (proof fn)
- sig: `pub proof fn lemma_contains_to_index(self, elem: A) -> (idx: int)`
- requires: self.contains(elem),
- ensures: 0 <= idx < self.len() && self[idx] == elem,
- doc: If an element is contained in a sequence, then there exists an index where that element appears.

## Seq::lemma_all_from_head_tail
- path: vstd/seq_lib.rs:1327  (proof fn)
- sig: `pub proof fn lemma_all_from_head_tail(self, pred: spec_fn(A) -> bool)`
- requires: self.len() > 0, pred(self[0]) && self.skip(1).all(|x| pred(x)),
- ensures: self.all(|x| pred(x)),
- doc: If a predicate holds for the first element and for all elements in the tail,

## Seq::lemma_any_tail
- path: vstd/seq_lib.rs:1354  (proof fn)
- sig: `pub proof fn lemma_any_tail(self, pred: spec_fn(A) -> bool)`
- requires: self.any(|x| pred(x)),
- ensures: !pred(self[0]) ==> self.skip(1).any(|x| pred(x)),
- doc: If a predicate holds for any element in the sequence and does not hold for the first element,

## Seq::remove_duplicates
- path: vstd/seq_lib.rs:1381  (spec fn)
- sig: `pub open spec fn remove_duplicates(self, seen: Seq<A>) -> Seq<A>`
- doc: Removes duplicate elements from a sequence, maintaining the order of first appearance.

## Seq::lemma_remove_duplicates_properties
- path: vstd/seq_lib.rs:1410  (proof fn)
- sig: `pub broadcast proof fn lemma_remove_duplicates_properties(self, seen: Seq<A>)`
- ensures: forall|x| (self + seen).contains(x) <==> #[trigger] self.remove_duplicates(seen).contains(x), #[trigger] self.remove_duplicates(seen).len() <= self.len() + seen.len(),
- doc: Properties of remove_duplicates:

## Seq::lemma_remove_duplicates_append_index
- path: vstd/seq_lib.rs:1444  (proof fn)
- sig: `pub proof fn lemma_remove_duplicates_append_index(self, i: int, seen: Seq<A>)`
- requires: 0 <= i < self.len(),
- ensures: self.remove_duplicates(seen) == self.skip(i).remove_duplicates( self.take(i).remove_duplicates(seen), ),
- doc: Shows that removing duplicates from a sequence is equivalent to:

## Seq::lemma_remove_duplicates_append
- path: vstd/seq_lib.rs:1514  (proof fn)
- sig: `pub proof fn lemma_remove_duplicates_append(self, x: A, seen: Seq<A>)`
- ensures: (self + seen).contains(x) ==> (self + seq![x]).remove_duplicates(seen) == self.remove_duplicates(seen), !(self + seen).contains(x) ==> (self + seq![x]).remove_duplicates(seen) == self.remove_duplicates(seen) + seq![x],
- doc: When appending an element `x` to a sequence:

## Seq::lemma_all_neg_filter_empty
- path: vstd/seq_lib.rs:1554  (proof fn)
- sig: `pub proof fn lemma_all_neg_filter_empty(self, pred: spec_fn(A) -> bool)`
- requires: self.all(|x: A| !pred(x)),
- ensures: self.filter(pred).len() == 0,
- doc: If all elements in a sequence fail the predicate,

## Seq::filter_map
- path: vstd/seq_lib.rs:1581  (spec fn)
- sig: `pub open spec fn filter_map<B>(self, f: spec_fn(A) -> Option<B>) -> Seq<B>`
- doc: Applies an Option-returning function to each element, keeping only successful (Some) results

## Seq::lemma_filter_contains_rev
- path: vstd/seq_lib.rs:1601  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_contains_rev(self, p: spec_fn(A) -> bool, elem: A)`
- requires: #[trigger] self.filter(p).contains(elem),
- ensures: self.contains(elem),
- doc: If an element exists in the filtered sequence,

## Seq::lemma_filter_map_contains
- path: vstd/seq_lib.rs:1624  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_map_contains<B>(self, f: spec_fn(A) -> Option<B>, elt: B)`
- requires: #[trigger] self.filter_map(f).contains(elt),
- ensures: exists|t: A| #[trigger] self.contains(t) && f(t) == Some(elt),
- doc: If an element exists in filter_map's output,

## Seq::lemma_take_succ
- path: vstd/seq_lib.rs:1655  (proof fn)
- sig: `pub proof fn lemma_take_succ(xs: Seq<A>, k: int)`
- requires: 0 <= k < xs.len(),
- ensures: xs.take(k + 1) =~= xs.take(k) + seq![xs[k]],
- doc: Taking k+1 elements is the same as taking k elements plus the kth element

## Seq::lemma_filter_map_singleton
- path: vstd/seq_lib.rs:1668  (proof fn)
- sig: `pub proof fn lemma_filter_map_singleton<B>(a: A, f: spec_fn(A) -> Option<B>)`
- ensures: seq![a].filter_map(f) =~= match f(a) { Option::Some(b) => seq![b], Option::None => Seq::empty(), },
- doc: filter_map on a single element sequence

## Seq::lemma_filter_map_take_succ
- path: vstd/seq_lib.rs:1689  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_map_take_succ<B>(self, f: spec_fn(A) -> Option<B>, i: int)`
- requires: 0 <= i < self.len(),
- ensures: #[trigger] self.take(i + 1).filter_map(f) =~= self.take(i).filter_map(f) + (match f( self[i], ) { Option::Some(s) => seq![s], Option::None => Seq::empty(),
- doc: filter_map of take(i+1) equals

## Seq::filter_alt
- path: vstd/seq_lib.rs:1711  (spec fn)
- sig: `pub open spec fn filter_alt(self, p: spec_fn(A) -> bool) -> Seq<A>`
- doc: An alternative implementation of filter that processes the sequence recursively from

## Seq::lemma_filter_prepend
- path: vstd/seq_lib.rs:1739  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_prepend(self, x: A, p: spec_fn(A) -> bool)`
- ensures: #[trigger] (seq![x] + self).filter(p) == (if p(x) { seq![x] } else { Seq::empty() }) + self.filter(p),
- doc: When filtering (x + sequence), if x satisfies the predicate, x is prepended to

## Seq::lemma_filter_eq_filter_alt
- path: vstd/seq_lib.rs:1780  (proof fn)
- sig: `pub proof fn lemma_filter_eq_filter_alt(self, p: spec_fn(A) -> bool)`
- ensures: self.filter(p) =~= self.filter_alt(p),
- doc: The filter() and filter_alt() methods produce equivalent results for any sequence

## Seq::lemma_filter_monotone
- path: vstd/seq_lib.rs:1812  (proof fn)
- sig: `pub proof fn lemma_filter_monotone(self, ys: Seq<A>, p: spec_fn(A) -> bool)`
- requires: self.is_prefix_of(ys),
- ensures: self.filter(p).is_prefix_of(ys.filter(p)),
- doc: Filtering preserves the prefix relationship between sequences.

## Seq::lemma_filter_take_len
- path: vstd/seq_lib.rs:1843  (proof fn)
- sig: `pub proof fn lemma_filter_take_len(self, p: spec_fn(A) -> bool, i: int)`
- requires: 0 <= i <= self.len(),
- ensures: self.filter(p).len() >= self.take(i).filter(p).len(),
- doc: The length of filter(take(i)) is never greater than the length of filter(entire_sequence).

## Seq::lemma_filter_len_push
- path: vstd/seq_lib.rs:1868  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_len_push(self, p: spec_fn(A) -> bool, elem: A)`
- ensures: #[trigger] self.push(elem).filter(p).len() == self.filter(p).len() + (if p(elem) { 1int } else { 0int }),
- doc: Filtering a prefix of a sequence produces the same number or fewer elements

## Seq::lemma_index_contains
- path: vstd/seq_lib.rs:1883  (proof fn)
- sig: `pub broadcast proof fn lemma_index_contains(self, i: int)`
- requires: 0 <= i < self.len(),
- ensures: self.contains(#[trigger] self[i]),
- doc: If an index i is valid for a sequence (0 ≤ i < len), then the element at that index

## Seq::lemma_take_succ_push
- path: vstd/seq_lib.rs:1893  (proof fn)
- sig: `pub broadcast proof fn lemma_take_succ_push(self, i: int)`
- requires: 0 <= i < self.len(),
- ensures: #[trigger] self.take(i + 1) =~= self.take(i).push(self[i]),
- doc: Taking i+1 elements from a sequence is equivalent to taking i elements

## Seq::lemma_take_len
- path: vstd/seq_lib.rs:1904  (proof fn)
- sig: `pub broadcast proof fn lemma_take_len(self)`
- ensures: #[trigger] self.take(self.len() as int) == self,
- doc: Taking the full length of a sequence returns the sequence itself.

## Seq::lemma_take_any_succ
- path: vstd/seq_lib.rs:1924  (proof fn)
- sig: `pub broadcast proof fn lemma_take_any_succ(self, p: spec_fn(A) -> bool, i: int)`
- requires: 0 <= i < self.len(),
- ensures: #[trigger] self.take(i + 1).any(p) <==> self.take(i).any(p) || p(self[i]),
- doc: Taking i+1 elements and checking if any element satisfies predicate p is equivalent to:

## Seq::lemma_no_duplicates_injective
- path: vstd/seq_lib.rs:1957  (proof fn)
- sig: `pub proof fn lemma_no_duplicates_injective<B>(self, f: spec_fn(A) -> B)`
- requires: injective(f),
- ensures: self.no_duplicates() <==> self.map_values(f).no_duplicates(),
- doc: A sequence has no duplicates iff mapping an injective function over it

## Seq::lemma_push_map_commute
- path: vstd/seq_lib.rs:1987  (proof fn)
- sig: `pub broadcast proof fn lemma_push_map_commute<B>(self, f: spec_fn(A) -> B, x: A)`
- ensures: self.map_values(f).push(f(x)) =~= #[trigger] self.push(x).map_values(f),
- doc: Pushing an element and then mapping a function over a sequence is equivalent to

## Seq::lemma_push_to_set_commute
- path: vstd/seq_lib.rs:2006  (proof fn)
- sig: `pub broadcast proof fn lemma_push_to_set_commute(self, elem: A)`
- ensures: #[trigger] self.push(elem).to_set() =~= self.to_set().insert(elem),
- doc: Converting a sequence to a set after pushing an element is equivalent to

## Seq::lemma_filter_push
- path: vstd/seq_lib.rs:2032  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_push(self, elem: A, pred: spec_fn(A) -> bool)`
- ensures: #[trigger] self.push(elem).filter(pred) == if pred(elem) { self.filter(pred).push(elem) } else { self.filter(pred) },
- doc: Filtering a sequence after pushing an element is equivalent to:

## Seq::lemma_zip_with_contains_index
- path: vstd/seq_lib.rs:2058  (proof fn)
- sig: `pub proof fn lemma_zip_with_contains_index<B>(self, b: Seq<B>, i: int)`
- requires: 0 <= i < self.len(), self.len() == b.len(),
- ensures: self.zip_with(b).contains((self[i], b[i])),
- doc: If two sequences have the same length and `i` is a valid index,

## Seq::lemma_zip_with_uncurry_all
- path: vstd/seq_lib.rs:2084  (proof fn)
- sig: `pub proof fn lemma_zip_with_uncurry_all<B>(self, b: Seq<B>, f: spec_fn(A, B) -> bool)`
- requires: self.len() == b.len(),
- ensures: self.zip_with(b).all(|p: (A, B)| f(p.0, p.1)) <==> forall|i: int| 0 <= i < self.len() ==> f(self[i], b[i]),
- doc: Proves equivalence between checking a predicate over zipped sequences and checking

## Seq::lemma_flat_map_push
- path: vstd/seq_lib.rs:2118  (proof fn)
- sig: `pub proof fn lemma_flat_map_push<B>(self, f: spec_fn(A) -> Seq<B>, elem: A)`
- ensures: self.push(elem).flat_map(f) =~= self.flat_map(f) + f(elem),
- doc: flat_mapping after pushing an element is the same as

## Seq::lemma_flat_map_take_append
- path: vstd/seq_lib.rs:2143  (proof fn)
- sig: `pub broadcast proof fn lemma_flat_map_take_append<B>(self, f: spec_fn(A) -> Seq<B>, i: int)`
- requires: 0 <= i < self.len(),
- ensures: #[trigger] self.take(i + 1).flat_map(f) =~= self.take(i).flat_map(f) + f(self[i]),
- doc: flat_mapping a sequence up to index i+1 is equivalent to

## Seq::lemma_flat_map_singleton
- path: vstd/seq_lib.rs:2158  (proof fn)
- sig: `pub broadcast proof fn lemma_flat_map_singleton<B>(self, f: spec_fn(A) -> Seq<B>)`
- requires: #[trigger] self.len() == 1,
- ensures: #[trigger] self.flat_map(f) == f(self[0]),
- doc: flat_mapping a sequence with a single element

## Seq::lemma_map_take_succ
- path: vstd/seq_lib.rs:2182  (proof fn)
- sig: `pub broadcast proof fn lemma_map_take_succ<B>(self, f: spec_fn(A) -> B, i: int)`
- requires: 0 <= i < self.len(),
- ensures: #[trigger] self.take(i + 1).map_values(f) =~= self.take(i).map_values(f).push( f(self[i]), ),
- doc: Mapping a sequence's first i+1 elements equals

## Seq::lemma_prefix_index_eq
- path: vstd/seq_lib.rs:2207  (proof fn)
- sig: `pub broadcast proof fn lemma_prefix_index_eq(self, prefix: Seq<A>)`
- requires: #[trigger] prefix.is_prefix_of(self),
- ensures: forall|i: int| 0 <= i < prefix.len() ==> prefix[i] == self[i],
- doc: If a sequence is a prefix of another sequence,

## Seq::lemma_prefix_concat
- path: vstd/seq_lib.rs:2228  (proof fn)
- sig: `pub broadcast proof fn lemma_prefix_concat(self, prefix1: Seq<A>, prefix2: Seq<A>)`
- requires: #[trigger] (prefix1 + prefix2).is_prefix_of(self),
- ensures: prefix1.is_prefix_of(self),
- doc: If a concatenated sequence (prefix1 + prefix2) is a prefix of another sequence,

## Seq::lemma_prefix_chain_contains
- path: vstd/seq_lib.rs:2258  (proof fn)
- sig: `pub broadcast proof fn lemma_prefix_chain_contains(self, prefix1: Seq<A>, prefix2: Seq<A>, t: A)`
- requires: #[trigger] (prefix1 + seq![t]).is_prefix_of(self), #[trigger] prefix1.is_prefix_of(prefix2), prefix2.is_prefix_of(self), prefix1 != prefix2, !prefix1.contains(t),
- ensures: prefix2.contains(t),
- doc: If `prefix1 + [t]` is a prefix of a sequence,

## Seq::lemma_prefix_append_unique
- path: vstd/seq_lib.rs:2277  (proof fn)
- sig: `pub broadcast proof fn lemma_prefix_append_unique(self, prefix1: Seq<A>, prefix2: Seq<A>, t: A)`
- requires: #[trigger] (prefix1 + seq![t]).is_prefix_of(self), #[trigger] (prefix2 + seq![t]).is_prefix_of(self), !prefix1.contains(t), !prefix2.contains(t),
- ensures: prefix1 == prefix2,
- doc: If `prefix1 + [t]` and `prefix2 + [t]` are both prefixes of a sequence,

## Seq::lemma_all_push
- path: vstd/seq_lib.rs:2309  (proof fn)
- sig: `pub broadcast proof fn lemma_all_push(self, p: spec_fn(A) -> bool, elem: A)`
- requires: self.all(p), p(elem),
- ensures: #[trigger] self.push(elem).all(p),
- doc: If a predicate `p` is true for all elements in a sequence,

## Seq::lemma_concat_injective
- path: vstd/seq_lib.rs:2325  (proof fn)
- sig: `pub proof fn lemma_concat_injective(self, s1: Seq<A>, s2: Seq<A>)`
- ensures: (self + s1 == self + s2) <==> (s1 == s2),
- doc: Two sequences are equal when concatenated with the same prefix

## group_seq_extra
- path: vstd/seq_lib.rs  (broadcast group)
- members: Seq::<_>::lemma_seq_skip_skip Seq::<_>::lemma_remove_duplicates_properties Seq::<_>::lemma_filter_contains_rev Seq::<_>::lemma_filter_map_take_succ Seq::<_>::lemma_filter_prepend Seq::<_>::lemma_filter_len_push Seq::<_>::lemma_take_len Seq::<_>::lemma_take_any_succ Seq::<_>::lemma_push_map_commute Seq::<_>::lemma_push_to_set_commute Seq::<_>::lemma_filter_push Seq::<_>::lemma_flat_map_take_append Seq::<_>::lemma_flat_map_singleton Seq::<_>::lemma_map_take_succ Seq::<_>::lemma_prefix_index_eq Seq::<_>::lemma_prefix_concat Seq::<_>::lemma_prefix_chain_contains Seq::<_>::lemma_prefix_append_unique Seq::<_>::lemma_all_push

## Seq::unref
- path: vstd/seq_lib.rs:2359  (spec fn)
- sig: `pub open spec fn unref(self) -> Seq<A>`
- doc: Dereference each element of the sequence

## Seq::unref
- path: vstd/seq_lib.rs:2366  (spec fn)
- sig: `pub open spec fn unref(self) -> Seq<(A, B)>`
- doc: Dereference each element of each tuple in the sequence

## lemma_filter_view_commute
- path: vstd/seq_lib.rs:2387  (proof fn)
- sig: `pub proof fn lemma_filter_view_commute<S: View>( s: Seq<S>, p: spec_fn(S) -> bool, sp: spec_fn(S::V) -> bool, )`
- requires: forall|s: S| p(s) <==> sp(s.view()),
- ensures: s.filter(p).map_values(|x: S| x.view()) == s.map_values(|x: S| x.view()).filter(sp),
- doc: Filtering a sequence and then viewing its elements produces the same result as

## lemma_exactly_one_view
- path: vstd/seq_lib.rs:2427  (proof fn)
- sig: `pub proof fn lemma_exactly_one_view<S: View>( s: Seq<S>, p: spec_fn(S) -> bool, sp: spec_fn(S::V) -> bool, )`
- requires: forall|s: S| p(s) <==> sp(s.view()), injective(|x: S| x.view()),
- ensures: s.exactly_one(p) <==> s.map_values(|x: S| x.view()).exactly_one(sp),
- doc: A sequence has exactly one element satisfying a predicate iff

## Seq::unzip
- path: vstd/seq_lib.rs:2443  (spec fn)
- sig: `pub closed spec fn unzip(self) -> (Seq<A>, Seq<B>)`
- doc: Unzips a sequence that contains pairs into two separate sequences.

## Seq::lemma_zip_of_unzip
- path: vstd/seq_lib.rs:2465  (proof fn)
- sig: `pub proof fn lemma_zip_of_unzip(self)`
- ensures: self.unzip().0.zip_with(self.unzip().1) =~= self,
- doc: Unzipping a sequence of sequences and then zipping the resulting two sequences

## Seq::flatten
- path: vstd/seq_lib.rs:2486  (spec fn)
- sig: `pub open spec fn flatten(self) -> Seq<A>`
- doc: Flattens a sequence of sequences into a single sequence by concatenating

## Seq::flatten_alt
- path: vstd/seq_lib.rs:2500  (spec fn)
- sig: `pub open spec fn flatten_alt(self) -> Seq<A>`
- doc: Flattens a sequence of sequences into a single sequence by concatenating

## Seq::lemma_flatten_one_element
- path: vstd/seq_lib.rs:2512  (proof fn)
- sig: `pub proof fn lemma_flatten_one_element(self)`
- ensures: self.len() == 1 ==> self.flatten() == self.first(),
- doc: Flattening a sequence of a sequence x, where x has length 1,

## Seq::lemma_flatten_length_ge_single_element_length
- path: vstd/seq_lib.rs:2525  (proof fn)
- sig: `pub proof fn lemma_flatten_length_ge_single_element_length(self, i: int)`
- requires: 0 <= i < self.len(),
- ensures: self.flatten_alt().len() >= self[i].len(),
- doc: The length of a flattened sequence of sequences x is greater than or

## Seq::lemma_flatten_length_le_mul
- path: vstd/seq_lib.rs:2545  (proof fn)
- sig: `pub proof fn lemma_flatten_length_le_mul(self, j: int)`
- requires: forall|i: int| 0 <= i < self.len() ==> (#[trigger] self[i]).len() <= j,
- ensures: self.flatten_alt().len() <= self.len() * j,
- doc: The length of a flattened sequence of sequences x is less than or equal

## Seq::lemma_flatten_and_flatten_alt_are_equivalent
- path: vstd/seq_lib.rs:2563  (proof fn)
- sig: `pub proof fn lemma_flatten_and_flatten_alt_are_equivalent(self)`
- ensures: self.flatten() =~= self.flatten_alt(),
- doc: Flattening sequences of sequences in order (starting from the beginning)

## Seq::lemma_flatten_push
- path: vstd/seq_lib.rs:2587  (proof fn)
- sig: `pub broadcast proof fn lemma_flatten_push(self, elem: Seq<A>)`
- ensures: #[trigger] self.push(elem).flatten() =~= self.flatten() + elem,
- doc: Flattening a sequence of sequences after pushing a new sequence is equivalent to

## Seq::lemma_flatten_singleton
- path: vstd/seq_lib.rs:2610  (proof fn)
- sig: `pub broadcast proof fn lemma_flatten_singleton(self)`
- requires: #[trigger] self.len() == 1,
- ensures: #[trigger] self.flatten() == self[0],
- doc: Flattening a sequence containing a single sequence yields that inner sequence.

## group_seq_flatten
- path: vstd/seq_lib.rs  (broadcast group)
- members: Seq::<_>::lemma_flatten_push Seq::<_>::lemma_flatten_singleton

## Seq::max
- path: vstd/seq_lib.rs:2630  (spec fn)
- sig: `pub open spec fn max(self) -> int recommends 0 < self.len(),`
- doc: Returns the maximum integer value in a non-empty sequence of integers.

## Seq::min
- path: vstd/seq_lib.rs:2671  (spec fn)
- sig: `pub open spec fn min(self) -> int recommends 0 < self.len(),`
- doc: Returns the minimum integer value in a non-empty sequence of integers.

## Seq::sort
- path: vstd/seq_lib.rs:2713  (spec fn)
- sig: `pub closed spec fn sort(self) -> Self`

## Seq::lemma_sort_ensures
- path: vstd/seq_lib.rs:2717  (proof fn)
- sig: `pub proof fn lemma_sort_ensures(self)`
- ensures: self.to_multiset() =~= self.sort().to_multiset(), sorted_by(self.sort(), |x: int, y: int| x <= y),

## Seq::lemma_subrange_max
- path: vstd/seq_lib.rs:2727  (proof fn)
- sig: `pub proof fn lemma_subrange_max(self, from: int, to: int)`
- requires: 0 <= from < to <= self.len(),
- ensures: self.subrange(from, to).max() <= self.max(),
- doc: The maximum element in a non-empty sequence is greater than or equal to

## Seq::lemma_subrange_min
- path: vstd/seq_lib.rs:2739  (proof fn)
- sig: `pub proof fn lemma_subrange_min(self, from: int, to: int)`
- requires: 0 <= from < to <= self.len(),
- ensures: self.subrange(from, to).min() >= self.min(),
- doc: The minimum element in a non-empty sequence is less than or equal to

## lemma_max_of_concat
- path: vstd/seq_lib.rs:2846  (proof fn)
- sig: `pub proof fn lemma_max_of_concat(x: Seq<int>, y: Seq<int>)`
- requires: 0 < x.len() && 0 < y.len(),
- ensures: x.max() <= (x + y).max(), y.max() <= (x + y).max(), forall|elt: int| (x + y).contains(elt) ==> elt <= (x + y).max(),
- doc: The maximum of the concatenation of two non-empty sequences is greater than or

## lemma_min_of_concat
- path: vstd/seq_lib.rs:2877  (proof fn)
- sig: `pub proof fn lemma_min_of_concat(x: Seq<int>, y: Seq<int>)`
- requires: 0 < x.len() && 0 < y.len(),
- ensures: (x + y).min() <= x.min(), (x + y).min() <= y.min(), forall|elt: int| (x + y).contains(elt) ==> (x + y).min() <= elt,
- doc: The minimum of the concatenation of two non-empty sequences is less than or

## to_multiset_build
- path: vstd/seq_lib.rs:2910  (proof fn)
- sig: `pub broadcast proof fn to_multiset_build<A>(s: Seq<A>, a: A)`
- ensures: #![trigger s.push(a).to_multiset()] s.push(a).to_multiset() =~= s.to_multiset().insert(a),
- doc: push(a) o to_multiset = to_multiset o insert(a)

## to_multiset_remove
- path: vstd/seq_lib.rs:2931  (proof fn)
- sig: `pub broadcast proof fn to_multiset_remove<A>(s: Seq<A>, i: int)`
- requires: 0 <= i < s.len(),
- ensures: #![trigger s.remove(i).to_multiset()] s.remove(i).to_multiset() == s.to_multiset().remove(s[i]),

## to_multiset_insert
- path: vstd/seq_lib.rs:2950  (proof fn)
- sig: `pub broadcast proof fn to_multiset_insert<A>(s: Seq<A>, i: int, a: A)`
- requires: 0 <= i <= s.len(),
- ensures: #![trigger s.insert(i, a).to_multiset()] s.insert(i, a).to_multiset() == s.to_multiset().insert(a),

## to_multiset_len
- path: vstd/seq_lib.rs:2974  (proof fn)
- sig: `pub broadcast proof fn to_multiset_len<A>(s: Seq<A>)`
- ensures: s.len() == #[trigger] s.to_multiset().len(),
- doc: to_multiset() preserves length

## to_multiset_contains
- path: vstd/seq_lib.rs:2992  (proof fn)
- sig: `pub broadcast proof fn to_multiset_contains<A>(s: Seq<A>, a: A)`
- ensures: #![trigger s.to_multiset().count(a)] s.contains(a) <==> s.to_multiset().count(a) > 0,
- doc: to_multiset() contains only the elements of the sequence

## to_multiset_update
- path: vstd/seq_lib.rs:3028  (proof fn)
- sig: `pub broadcast proof fn to_multiset_update<A>(s: Seq<A>, i: int, a: A)`
- requires: 0 <= i < s.len(),
- ensures: #[trigger] s.update(i, a).to_multiset() == s.to_multiset().insert(a).remove(s[i]),

## lemma_update_is_remove_insert
- path: vstd/seq_lib.rs:3050  (proof fn)
- sig: `pub broadcast proof fn lemma_update_is_remove_insert<A>(s: Seq<A>, i: int, a: A)`
- requires: 0 <= i < s.len(),
- ensures: #[trigger] s.update(i, a) =~= s.remove(i).insert(i, a),
- doc: Lemma showing that update is equivalent to a remove followed by an insertae

## lemma_append_last
- path: vstd/seq_lib.rs:3061  (proof fn)
- sig: `pub proof fn lemma_append_last<A>(s1: Seq<A>, s2: Seq<A>)`
- requires: 0 < s2.len(),
- ensures: (s1 + s2).last() == s2.last(),
- doc: The last element of two concatenated sequences, the second one being non-empty, will be the

## lemma_concat_associative
- path: vstd/seq_lib.rs:3070  (proof fn)
- sig: `pub proof fn lemma_concat_associative<A>(s1: Seq<A>, s2: Seq<A>, s3: Seq<A>)`
- ensures: s1.add(s2.add(s3)) =~= s1.add(s2).add(s3),
- doc: The concatenation of sequences is associative

## lemma_no_dup_in_concat
- path: vstd/seq_lib.rs:3142  (proof fn)
- sig: `pub proof fn lemma_no_dup_in_concat<A>(a: Seq<A>, b: Seq<A>)`
- requires: a.no_duplicates(), b.no_duplicates(), forall|i: int, j: int| 0 <= i < a.len() && 0 <= j < b.len() ==> a[i] != b[j],
- ensures: #[trigger] (a + b).no_duplicates(),
- doc: If sequences a and b don't have duplicates, and there are no

## lemma_flatten_concat
- path: vstd/seq_lib.rs:3155  (proof fn)
- sig: `pub proof fn lemma_flatten_concat<A>(x: Seq<Seq<A>>, y: Seq<Seq<A>>)`
- ensures: (x + y).flatten() =~= x.flatten() + y.flatten(),
- doc: Flattening sequences of sequences is distributive over concatenation. That is, concatenating

## lemma_flatten_alt_concat
- path: vstd/seq_lib.rs:3175  (proof fn)
- sig: `pub proof fn lemma_flatten_alt_concat<A>(x: Seq<Seq<A>>, y: Seq<Seq<A>>)`
- ensures: (x + y).flatten_alt() =~= x.flatten_alt() + y.flatten_alt(),
- doc: Flattening sequences of sequences in reverse order is distributive over concatentation.

## lemma_seq_union_to_multiset_commutative
- path: vstd/seq_lib.rs:3193  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_union_to_multiset_commutative<A>(a: Seq<A>, b: Seq<A>)`
- ensures: #[trigger] (a + b).to_multiset() =~= (b + a).to_multiset(),
- doc: The multiset of a concatenated sequence `a + b` is equivalent to the multiset of the

## lemma_multiset_commutative
- path: vstd/seq_lib.rs:3205  (proof fn)
- sig: `pub broadcast proof fn lemma_multiset_commutative<A>(a: Seq<A>, b: Seq<A>)`
- ensures: #[trigger] (a + b).to_multiset() =~= a.to_multiset().add(b.to_multiset()),
- doc: The multiset of a concatenated sequence `a + b` is equivalent to the multiset of just

## lemma_sorted_unique
- path: vstd/seq_lib.rs:3221  (proof fn)
- sig: `pub proof fn lemma_sorted_unique<A>(x: Seq<A>, y: Seq<A>, leq: spec_fn(A, A) -> bool)`
- requires: sorted_by(x, leq), sorted_by(y, leq), total_ordering(leq), x.to_multiset() == y.to_multiset(),
- ensures: x =~= y,
- doc: Any two sequences that are sorted by a total order and that have the same elements are equal.

## lemma_seq_contains
- path: vstd/seq_lib.rs:3252  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_contains<A>(s: Seq<A>, x: A)`
- ensures: #[trigger] s.contains(x) <==> exists|i: int| 0 <= i < s.len() && #[trigger] s[i] == x,

## lemma_seq_empty_contains_nothing
- path: vstd/seq_lib.rs:3260  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_empty_contains_nothing<A>(x: A)`
- ensures: !(#[trigger] Seq::<A>::empty().contains(x)),
- doc: The empty sequence contains nothing

## lemma_seq_empty_equality
- path: vstd/seq_lib.rs:3269  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_empty_equality<A>(s: Seq<A>)`
- ensures: #[trigger] s.len() == 0 ==> s =~= Seq::<A>::empty(),
- doc: A sequence with length 0 is equivalent to the empty sequence

## lemma_seq_concat_contains_all_elements
- path: vstd/seq_lib.rs:3278  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_concat_contains_all_elements<A>(x: Seq<A>, y: Seq<A>, elt: A)`
- ensures: #[trigger] (x + y).contains(elt) <==> x.contains(elt) || y.contains(elt),
- doc: The concatenation of two sequences contains only the elements

## lemma_seq_contains_after_push
- path: vstd/seq_lib.rs:3303  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_contains_after_push<A>(s: Seq<A>, v: A, x: A)`
- ensures: #[trigger] s.push(v).contains(x) <==> v == x || s.contains(x),
- doc: After pushing an element onto a sequence, the sequence contains that element

## lemma_seq_subrange_elements
- path: vstd/seq_lib.rs:3317  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_subrange_elements<A>(s: Seq<A>, start: int, stop: int, x: A)`
- requires: 0 <= start <= stop <= s.len(),
- ensures: #[trigger] s.subrange(start, stop).contains(x) <==> (exists|i: int| 0 <= start <= i < stop <= s.len() && #[trigger] s[i] == x),
- doc: The subrange of a sequence contains only the elements within the indices `start` and `stop`

## commutative_foldr
- path: vstd/seq_lib.rs:3336  (spec fn)
- sig: `pub open spec fn commutative_foldr<A, B>(f: spec_fn(A, B) -> B) -> bool`

## commutative_foldl
- path: vstd/seq_lib.rs:3341  (spec fn)
- sig: `pub open spec fn commutative_foldl<A, B>(f: spec_fn(B, A) -> B) -> bool`

## lemma_fold_right_permutation
- path: vstd/seq_lib.rs:3347  (proof fn)
- sig: `pub proof fn lemma_fold_right_permutation<A, B>(l1: Seq<A>, l2: Seq<A>, f: spec_fn(A, B) -> B, v: B)`
- requires: commutative_foldr(f), l1.to_multiset() == l2.to_multiset(),
- ensures: l1.fold_right(f, v) == l2.fold_right(f, v),

## lemma_fold_left_permutation
- path: vstd/seq_lib.rs:3386  (proof fn)
- sig: `pub proof fn lemma_fold_left_permutation<A, B>(l1: Seq<A>, l2: Seq<A>, f: spec_fn(B, A) -> B, v: B)`
- requires: commutative_foldl(f), l1.to_multiset() == l2.to_multiset(),
- ensures: l1.fold_left(v, f) == l2.fold_left(v, f),

## lemma_seq_take_len
- path: vstd/seq_lib.rs:3415  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_take_len<A>(s: Seq<A>, n: int)`
- ensures: 0 <= n <= s.len() ==> #[trigger] s.take(n).len() == n,
- doc: Taking the first `n` elements of a sequence results in a sequence of length `n`,

## lemma_seq_take_contains
- path: vstd/seq_lib.rs:3424  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_take_contains<A>(s: Seq<A>, n: int, x: A)`
- requires: 0 <= n <= s.len(),
- ensures: #[trigger] s.take(n).contains(x) <==> (exists|i: int| 0 <= i < n <= s.len() && #[trigger] s[i] == x),
- doc: The resulting sequence after taking the first `n` elements from sequence `s` contains

## lemma_seq_take_index
- path: vstd/seq_lib.rs:3443  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_take_index<A>(s: Seq<A>, n: int, j: int)`
- ensures: 0 <= j < n <= s.len() ==> #[trigger] s.take(n)[j] == s[j],
- doc: If `j` is a valid index less than `n`, then the `j`th element of the sequence `s`

## lemma_seq_skip_len
- path: vstd/seq_lib.rs:3470  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_skip_len<A>(s: Seq<A>, n: int)`
- ensures: 0 <= n <= s.len() ==> #[trigger] s.skip(n).len() == s.len() - n,
- doc: Skipping the first `n` elements of a sequence gives a sequence of length `n` less than

## lemma_seq_skip_contains
- path: vstd/seq_lib.rs:3479  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_skip_contains<A>(s: Seq<A>, n: int, x: A)`
- requires: 0 <= n <= s.len(),
- ensures: #[trigger] s.skip(n).contains(x) <==> (exists|i: int| 0 <= n <= i < s.len() && #[trigger] s[i] == x),
- doc: The resulting sequence after skipping the first `n` elements from sequence `s` contains

## lemma_seq_skip_index
- path: vstd/seq_lib.rs:3496  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_skip_index<A>(s: Seq<A>, n: int, j: int)`
- ensures: 0 <= n && 0 <= j < (s.len() - n) ==> #[trigger] s.skip(n)[j] == s[j + n],
- doc: If `j` is a valid index less than `s.len() - n`, then the `j`th element of the sequence

## lemma_seq_skip_index2
- path: vstd/seq_lib.rs:3506  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_skip_index2<A>(s: Seq<A>, n: int, k: int)`
- ensures: 0 <= n <= k < s.len() ==> (#[trigger] s.skip(n))[k - n] == #[trigger] s[k],
- doc: If `k` is a valid index between `n` (inclusive) and the length of sequence `s` (exclusive),

## lemma_seq_append_take_skip
- path: vstd/seq_lib.rs:3516  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_append_take_skip<A>(a: Seq<A>, b: Seq<A>, n: int)`
- ensures: #![trigger (a + b).take(n)] #![trigger (a + b).skip(n)] n == a.len() ==> ((a + b).take(n) =~= a && (a + b).skip(n) =~= b),
- doc: If `n` is the length of sequence `a`, then taking the first `n` elements of the concatenation

## lemma_seq_take_update_commut1
- path: vstd/seq_lib.rs:3530  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_take_update_commut1<A>(s: Seq<A>, i: int, v: A, n: int)`
- ensures: #![trigger s.update(i, v).take(n)] 0 <= i < n <= s.len() ==> #[trigger] s.update(i, v).take(n) =~= s.take(n).update(i, v),
- doc: If `i` is in the first `n` indices of sequence `s`, updating sequence `s` at index `i` with

## lemma_seq_take_update_commut2
- path: vstd/seq_lib.rs:3541  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_take_update_commut2<A>(s: Seq<A>, i: int, v: A, n: int)`
- ensures: 0 <= n <= i < s.len() ==> #[trigger] s.update(i, v).take(n) =~= s.take(n),
- doc: If `i` is a valid index after the first `n` indices of sequence `s`, updating sequence `s` at

## lemma_seq_skip_update_commut1
- path: vstd/seq_lib.rs:3551  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_skip_update_commut1<A>(s: Seq<A>, i: int, v: A, n: int)`
- ensures: 0 <= n <= i < s.len() ==> #[trigger] s.update(i, v).skip(n) =~= s.skip(n).update(i - n, v),
- doc: If `i` is a valid index after the first `n` indices of sequence `s`, updating sequence `s` at

## lemma_seq_skip_update_commut2
- path: vstd/seq_lib.rs:3561  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_skip_update_commut2<A>(s: Seq<A>, i: int, v: A, n: int)`
- ensures: 0 <= i < n <= s.len() ==> #[trigger] s.update(i, v).skip(n) =~= s.skip(n),
- doc: If `i` is a valid index in the first `n` indices of sequence `s`, updating sequence `s` at

## lemma_seq_skip_build_commut
- path: vstd/seq_lib.rs:3570  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_skip_build_commut<A>(s: Seq<A>, v: A, n: int)`
- ensures: #![trigger s.push(v).skip(n)] 0 <= n <= s.len() ==> s.push(v).skip(n) =~= s.skip(n).push(v),
- doc: Pushing element `v` onto the end of sequence `s` and then skipping the first `n` elements is

## lemma_seq_skip_nothing
- path: vstd/seq_lib.rs:3579  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_skip_nothing<A>(s: Seq<A>, n: int)`
- ensures: n == 0 ==> #[trigger] s.skip(n) =~= s,
- doc: `s.skip(0)` is equivalent to `s`.

## lemma_seq_take_nothing
- path: vstd/seq_lib.rs:3587  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_take_nothing<A>(s: Seq<A>, n: int)`
- ensures: n == 0 ==> #[trigger] s.take(n) =~= Seq::<A>::empty(),
- doc: `s.take(0)` is equivalent to the empty sequence.

## lemma_seq_skip_of_skip
- path: vstd/seq_lib.rs:3597  (proof fn)
- sig: `pub broadcast proof fn lemma_seq_skip_of_skip<A>(s: Seq<A>, m: int, n: int)`
- ensures: (0 <= m && 0 <= n && m + n <= s.len()) ==> #[trigger] s.skip(m).skip(n) =~= s.skip(m + n),
- doc: If `m + n` is less than or equal to the length of sequence `s`, then skipping the first `m` elements

## check_argument_is_seq
- path: vstd/seq_lib.rs:3605  (spec fn)
- sig: `pub open spec fn check_argument_is_seq<A>(s: Seq<A>) -> Seq<A>`

## group_filter_ensures
- path: vstd/seq_lib.rs  (broadcast group)
- members: Seq::lemma_filter_len Seq::lemma_filter_pred Seq::lemma_filter_contains

## group_seq_lib_default
- path: vstd/seq_lib.rs  (broadcast group)
- members: Seq::to_set_ensures group_filter_ensures Seq::add_empty_left Seq::add_empty_right Seq::push_distributes_over_add Seq::filter_distributes_over_add Seq::lemma_fold_right_split Seq::lemma_fold_left_split

## group_to_multiset_ensures
- path: vstd/seq_lib.rs  (broadcast group)
- members: to_multiset_build to_multiset_remove to_multiset_len to_multiset_contains to_multiset_insert to_multiset_update

## group_seq_properties
- path: vstd/seq_lib.rs  (broadcast group)
- members: lemma_seq_contains lemma_seq_empty_contains_nothing lemma_seq_empty_equality lemma_seq_concat_contains_all_elements lemma_seq_contains_after_push lemma_seq_subrange_elements lemma_seq_take_len lemma_seq_take_contains lemma_seq_take_index lemma_seq_skip_len lemma_seq_skip_contains lemma_seq_skip_index lemma_seq_skip_index2 lemma_seq_append_take_skip lemma_seq_take_update_commut1 lemma_seq_take_update_commut2 lemma_seq_skip_update_commut1 lemma_seq_skip_update_commut2 lemma_seq_skip_build_commut lemma_seq_skip_nothing lemma_seq_take_nothing // Removed the following from group due to bad verification performance // for `lemma_merge_sorted_with_ensures` // lemma_seq_skip_of_skip group_to_multiset_ensures

## Set::to_iset
- path: vstd/set.rs:53  (spec fn)
- sig: `pub uninterp spec fn to_iset(self) -> ISet<A>`
- doc: Generates an `ISet` with the same elements

## Set::empty
- path: vstd/set.rs:98  (spec fn)
- sig: `pub closed spec fn empty() -> Set<A>`
- doc: The "empty" set.

## Set::new_from_iset
- path: vstd/set.rs:113  (spec fn)
- sig: `pub closed spec fn new_from_iset(s: ISet<A>) -> Option<Set<A>>`
- doc: Set whose membership is determined by the given `ISet`,

## Set::new
- path: vstd/set.rs:133  (spec fn)
- sig: `pub closed spec fn new(f: spec_fn(A) -> bool) -> Option<Set<A>>`
- doc: Set whose membership is determined by the given boolean predicate,

## Set::new_assuming_finite
- path: vstd/set.rs:147  (spec fn)
- sig: `pub closed spec fn new_assuming_finite(f: spec_fn(A) -> bool) -> Set<A>`
- doc: Set whose membership is determined by the given boolean predicate,

## Set::full
- path: vstd/set.rs:154  (spec fn)
- sig: `pub open spec fn full() -> Option<Set<A>>`
- doc: The "full" set, i.e., set containing every element of type `A`.

## Set::contains
- path: vstd/set.rs:161  (spec fn)
- sig: `pub open spec fn contains(self, a: A) -> bool`
- doc: Predicate indicating if the set contains the given element.

## Set::spec_has
- path: vstd/set.rs:167  (spec fn)
- sig: `pub open spec fn spec_has(self, a: A) -> bool`
- doc: Predicate indicating if the set contains the given element: supports `self has a` syntax.

## Set::subset_of
- path: vstd/set.rs:173  (spec fn)
- sig: `pub open spec fn subset_of(self, s2: Set<A>) -> bool`
- doc: Returns `true` if the first argument is a subset of the second.

## Set::spec_le
- path: vstd/set.rs:178  (spec fn)
- sig: `pub open spec fn spec_le(self, s2: Set<A>) -> bool`

## Set::insert
- path: vstd/set.rs:185  (spec fn)
- sig: `pub closed spec fn insert(self, a: A) -> Set<A>`
- doc: Returns a new set with the given element inserted.

## Set::remove
- path: vstd/set.rs:192  (spec fn)
- sig: `pub closed spec fn remove(self, a: A) -> Set<A>`
- doc: Returns a new set with the given element removed.

## Set::union
- path: vstd/set.rs:197  (spec fn)
- sig: `pub closed spec fn union(self, s2: Set<A>) -> Set<A>`
- doc: Union of two sets.

## Set::spec_add
- path: vstd/set.rs:203  (spec fn)
- sig: `pub open spec fn spec_add(self, s2: Set<A>) -> Set<A>`
- doc: `+` operator, synonymous with `union`

## Set::intersect
- path: vstd/set.rs:208  (spec fn)
- sig: `pub closed spec fn intersect(self, s2: Set<A>) -> Set<A>`
- doc: Intersection of two sets.

## Set::spec_mul
- path: vstd/set.rs:214  (spec fn)
- sig: `pub open spec fn spec_mul(self, s2: Set<A>) -> Set<A>`
- doc: `*` operator, synonymous with `intersect`

## Set::difference
- path: vstd/set.rs:219  (spec fn)
- sig: `pub closed spec fn difference(self, s2: Set<A>) -> Set<A>`
- doc: Set difference, i.e., the set of all elements in the first one but not in the second.

## Set::spec_sub
- path: vstd/set.rs:225  (spec fn)
- sig: `pub open spec fn spec_sub(self, s2: Set<A>) -> Set<A>`
- doc: `-` operator, synonymous with `difference`

## Set::complement
- path: vstd/set.rs:231  (spec fn)
- sig: `pub open spec fn complement(self) -> Option<Set<A>>`
- doc: Set complement (within the space of all possible elements in `A`).

## Set::filter
- path: vstd/set.rs:236  (spec fn)
- sig: `pub closed spec fn filter(self, f: spec_fn(A) -> bool) -> Set<A>`
- doc: Set of all elements in the given set which satisfy the predicate `f`.

## Set::finite
- path: vstd/set.rs:242  (spec fn)
- sig: `pub open spec fn finite(self) -> bool`
- doc: Returns `true` if the set is finite.

## Set::congruent
- path: vstd/set.rs:248  (spec fn)
- sig: `pub open spec fn congruent(self, s2: ISet<A>) -> bool`
- doc: Returns `true` if this set is congruent to (contains the same elements as)

## Set::len
- path: vstd/set.rs:253  (spec fn)
- sig: `pub closed spec fn len(self) -> nat`
- doc: Cardinality of the set.

## Set::choose
- path: vstd/set.rs:263  (spec fn)
- sig: `pub open spec fn choose(self) -> A`
- doc: Chooses an arbitrary element of the set.

## Set::disjoint
- path: vstd/set.rs:269  (spec fn)
- sig: `pub open spec fn disjoint(self, s2: Self) -> bool`
- doc: Returns `true` if the sets are disjoint, i.e., if their interesection is

## axiom_set_ext_equal
- path: vstd/set.rs:276  (proof fn)
- sig: `pub broadcast proof fn axiom_set_ext_equal<A>(s1: Set<A>, s2: Set<A>)`
- ensures: #[trigger] (s1 =~= s2) <==> (forall|a: A| s1.contains(a) == s2.contains(a)),
- doc: Sets `s1` and `s2` are considered equal if and only if they contain all of the same elements.

## axiom_set_ext_equal_deep
- path: vstd/set.rs:285  (proof fn)
- sig: `pub broadcast proof fn axiom_set_ext_equal_deep<A>(s1: Set<A>, s2: Set<A>)`
- ensures: #[trigger] (s1 =~~= s2) <==> s1 =~= s2,
- doc: Sets `s1` and `s2` are considered equal if and only if they contain all of the same elements.

## Set::fold
- path: vstd/set.rs:304  (spec fn)
- sig: `pub open spec fn fold<B>(self, z: B, f: spec_fn(B, A) -> B) -> B recommends super::super::iset::fold::is_fun_commutative(f),`
- doc: Folds the set, applying `f` to perform the fold. The next element for the fold is chosen by

## lemma_set_empty
- path: vstd/set.rs:315  (proof fn)
- sig: `pub broadcast proof fn lemma_set_empty<A>(a: A)`
- ensures: !(#[trigger] Set::empty().contains(a)),
- doc: The empty set contains no elements

## lemma_set_new
- path: vstd/set.rs:325  (proof fn)
- sig: `pub broadcast proof fn lemma_set_new<A>(f: spec_fn(A) -> bool, a: A)`
- requires: Set::<A>::new(f) is Some,
- ensures: #[trigger] Set::<A>::new(f).unwrap().contains(a) == f(a),
- doc: If `Set::<A>::new(f)` produces `Some(s)`, then `s` contains `a`

## lemma_set_new_some
- path: vstd/set.rs:338  (proof fn)
- sig: `pub broadcast proof fn lemma_set_new_some<A>(f: spec_fn(A) -> bool)`
- requires: ISet::<A>::new(f).finite(),
- ensures: #[trigger] Set::<A>::new(f) is Some,
- doc: If `ISet::<A>::new(f)` is finite, then `Set::<A>::new(f)`

## lemma_set_new_assuming_finite
- path: vstd/set.rs:351  (proof fn)
- sig: `pub broadcast proof fn lemma_set_new_assuming_finite<A>(f: spec_fn(A) -> bool, a: A)`
- ensures: #[trigger] Set::<A>::new_assuming_finite(f).contains(a) == f(a),
- doc: Shows that `Set::<A>::new_assuming_finite(f)` contains `a`

## lemma_set_new_from_iset
- path: vstd/set.rs:362  (proof fn)
- sig: `pub broadcast proof fn lemma_set_new_from_iset<A>(s: ISet<A>)`
- requires: s.finite(),
- ensures: #![trigger Set::<A>::new_from_iset(s)] Set::<A>::new_from_iset(s) is Some, Set::<A>::new_from_iset(s).unwrap().to_iset() == s,
- doc: If an iset `s` is finite, then `Set::new_from_iset(s)` has the same

## lemma_set_insert_same
- path: vstd/set.rs:376  (proof fn)
- sig: `pub broadcast proof fn lemma_set_insert_same<A>(s: Set<A>, a: A)`
- ensures: #[trigger] s.insert(a).contains(a),
- doc: The result of inserting element `a` into set `s` must contains `a`.

## lemma_set_insert_different
- path: vstd/set.rs:387  (proof fn)
- sig: `pub broadcast proof fn lemma_set_insert_different<A>(s: Set<A>, a1: A, a2: A)`
- requires: a1 != a2,
- ensures: #[trigger] s.insert(a2).contains(a1) == s.contains(a1),
- doc: If `a1` does not equal `a2`, then the result of inserting element `a2` into set `s`

## lemma_set_remove_same
- path: vstd/set.rs:399  (proof fn)
- sig: `pub broadcast proof fn lemma_set_remove_same<A>(s: Set<A>, a: A)`
- ensures: !(#[trigger] s.remove(a).contains(a)),
- doc: The result of removing element `a` from set `s` must not contain `a`.

## lemma_set_remove_insert
- path: vstd/set.rs:410  (proof fn)
- sig: `pub broadcast proof fn lemma_set_remove_insert<A>(s: Set<A>, a: A)`
- requires: s.contains(a),
- ensures: (#[trigger] s.remove(a)).insert(a) == s,
- doc: Removing an element `a` from a set `s` and then inserting `a` back into the set`

## lemma_set_remove_different
- path: vstd/set.rs:440  (proof fn)
- sig: `pub broadcast proof fn lemma_set_remove_different<A>(s: Set<A>, a1: A, a2: A)`
- requires: a1 != a2,
- ensures: #[trigger] s.remove(a2).contains(a1) == s.contains(a1),
- doc: If `a1` does not equal `a2`, then the result of removing element `a2` from set `s`

## lemma_set_union
- path: vstd/set.rs:454  (proof fn)
- sig: `pub broadcast proof fn lemma_set_union<A>(s1: Set<A>, s2: Set<A>, a: A)`
- ensures: #[trigger] s1.union(s2).contains(a) == (s1.contains(a) || s2.contains(a)),
- doc: The union of sets `s1` and `s2` contains element `a` if and only if

## lemma_set_intersect
- path: vstd/set.rs:466  (proof fn)
- sig: `pub broadcast proof fn lemma_set_intersect<A>(s1: Set<A>, s2: Set<A>, a: A)`
- ensures: #[trigger] s1.intersect(s2).contains(a) == (s1.contains(a) && s2.contains(a)),
- doc: The intersection of sets `s1` and `s2` contains element `a` if and only if

## lemma_set_difference
- path: vstd/set.rs:478  (proof fn)
- sig: `pub broadcast proof fn lemma_set_difference<A>(s1: Set<A>, s2: Set<A>, a: A)`
- ensures: #[trigger] s1.difference(s2).contains(a) == (s1.contains(a) && !s2.contains(a)),
- doc: The set difference between `s1` and `s2` contains element `a` if and only if

## lemma_set_complement
- path: vstd/set.rs:488  (proof fn)
- sig: `pub broadcast proof fn lemma_set_complement<A>(s: Set<A>, a: A)`
- requires: ISet::new(|a| !s.contains(a)).finite(),
- ensures: #[trigger] s.complement().unwrap().contains(a) == !s.contains(a),
- doc: The complement of set `s` contains element `a` if and only if `s` does not contain `a`.

## lemma_set_filter
- path: vstd/set.rs:500  (proof fn)
- sig: `pub broadcast proof fn lemma_set_filter<A>(s: Set<A>, f: spec_fn(A) -> bool, a: A)`
- ensures: #[trigger] s.filter(f).contains(a) == (s.contains(a) && f(a)),
- doc: The filter of set `s` using function `f` contains element `a` if and only if `s` contains `a`

## lemma_set_empty_len
- path: vstd/set.rs:512  (proof fn)
- sig: `pub broadcast proof fn lemma_set_empty_len<A>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::set::group_set_lemmas`: write `broadcast use vstd::set::group_set_lemmas;` and the fact is available.
- ensures: #[trigger] Set::<A>::empty().len() == 0,
- doc: The empty set has length 0.

## lemma_set_insert_len
- path: vstd/set.rs:522  (proof fn)
- sig: `pub broadcast proof fn lemma_set_insert_len<A>(s: Set<A>, a: A)`
- ensures: #[trigger] s.insert(a).len() == s.len() + (if s.contains(a) { 0int } else { 1 }),
- doc: The result of inserting an element `a` into a finite set `s` has length

## lemma_set_remove_len
- path: vstd/set.rs:537  (proof fn)
- sig: `pub broadcast proof fn lemma_set_remove_len<A>(s: Set<A>, a: A)`
- ensures: s.len() == #[trigger] s.remove(a).len() + (if s.contains(a) { 1int } else { 0 }),
- doc: The result of removing an element `a` from a finite set `s` has length

## lemma_set_contains_len
- path: vstd/set.rs:551  (proof fn)
- sig: `pub broadcast proof fn lemma_set_contains_len<A>(s: Set<A>, a: A)`
- requires: #[trigger] s.contains(a),
- ensures: #[trigger] s.len() != 0,
- doc: If a finite set `s` contains any element, it has length greater than 0.

## lemma_set_choose_len
- path: vstd/set.rs:563  (proof fn)
- sig: `pub broadcast proof fn lemma_set_choose_len<A>(s: Set<A>)`
- requires: #[trigger] s.len() != 0,
- ensures: #[trigger] s.contains(s.choose()),
- doc: A finite set `s` contains the element `s.choose()` if it has length greater than 0.

## lemma_to_iset_finite
- path: vstd/set.rs:573  (proof fn)
- sig: `pub broadcast proof fn lemma_to_iset_finite<A>(s: Set<A>)`
- ensures: #[trigger] s.to_iset().finite(),
- doc: Converting a `Set` to an `ISet` produces a finite result.

## lemma_to_iset_len
- path: vstd/set.rs:584  (proof fn)
- sig: `pub broadcast proof fn lemma_to_iset_len<A>(s: Set<A>)`
- ensures: #[trigger] s.to_iset().len() == s.len(),
- doc: Converting a `Set` to an `ISet` produces a result with the same

## group_set_lemmas
- path: vstd/set.rs  (broadcast group)
- members: axiom_set_ext_equal axiom_set_ext_equal_deep lemma_set_empty lemma_set_new lemma_set_new_assuming_finite lemma_set_new_from_iset lemma_set_new_some lemma_set_insert_same lemma_set_insert_different lemma_set_remove_same lemma_set_remove_insert lemma_set_remove_different lemma_set_union lemma_set_intersect lemma_set_difference lemma_set_complement lemma_set_filter lemma_set_empty_len lemma_set_insert_len lemma_set_remove_len lemma_set_contains_len lemma_set_choose_len lemma_set_new lemma_to_iset_finite lemma_to_iset_len

## Set::is_empty
- path: vstd/set_lib.rs:21  (spec fn)
- sig: `pub open spec fn is_empty(self) -> (b: bool)`
- doc: Is `true` if called by an "empty" set, i.e., a set containing no elements and has length 0

## Set::map
- path: vstd/set_lib.rs:26  (spec fn)
- sig: `pub closed spec fn map<B>(self, f: spec_fn(A) -> B) -> Set<B>`
- doc: Returns the set contains an element `f(x)` for every element `x` in `self`.

## Set::lemma_map_contains
- path: vstd/set_lib.rs:32  (proof fn)
- sig: `pub broadcast proof fn lemma_map_contains<B>(self, f: spec_fn(A) -> B, b: B)`
- ensures: #[trigger] self.map(f).contains(b) <==> exists|a: A| self.contains(a) && b == f(a),
- doc: Since `Self::map` is `closed`, this broadcast lemma is needed

## Set::map_by
- path: vstd/set_lib.rs:51  (spec fn)
- sig: `pub closed spec fn map_by<B>(self, fwd: spec_fn(A) -> B, rev: spec_fn(B) -> A) -> Set<B> recommends forall|a: A| self.contains(a) ==> rev(fwd(a)) == a,`
- doc: `Set::map_by` is like `Set::map`, but `map` only takes a forward function `fwd: spec_fn(A) -> B`,

## Set::lemma_map_by_contains
- path: vstd/set_lib.rs:60  (proof fn)
- sig: `pub broadcast proof fn lemma_map_by_contains<B>( self, fwd: spec_fn(A) -> B, rev: spec_fn(B) -> A, b: B, )`
- ensures: #[trigger] self.map_by(fwd, rev).contains(b) <==> self.contains(rev(b)) && b == fwd( rev(b), ),
- doc: Since `Self::map_by` is `closed`, this broadcast lemma is needed

## Set::map_flatten_by
- path: vstd/set_lib.rs:80  (spec fn)
- sig: `pub closed spec fn map_flatten_by<B>( self, fwd: spec_fn(A) -> Set<B>, rev: spec_fn(B) -> A, ) -> Set<B> recommends forall|a: A, b: B| #[trigger] self.contains(a) && fwd(a).contains(b) ==> #[trigger] rev(b) == a,`
- doc: Similar to `Set::map_by`, but the forward function returns `Set<B>` rather than `B`,

## Set::lemma_map_flatten_by_contains
- path: vstd/set_lib.rs:117  (proof fn)
- sig: `pub broadcast proof fn lemma_map_flatten_by_contains<B>( self, fwd: spec_fn(A) -> Set<B>, rev: spec_fn(B) -> A, b: B, )`
- requires: forall|a: A, b: B| #[trigger] self.contains(a) && fwd(a).contains(b) ==> #[trigger] rev(b) == a,
- ensures: #[trigger] self.map_flatten_by(fwd, rev).contains(b) <==> self.contains(rev(b)) && fwd( rev(b), ).contains(b),
- doc: Since `Self::map_flatten_by` is `closed`, this broadcast lemma is needed

## Set::to_seq
- path: vstd/set_lib.rs:163  (spec fn)
- sig: `pub open spec fn to_seq(self) -> Seq<A>`
- doc: Converts a set into a sequence with an arbitrary ordering.

## Set::to_sorted_seq
- path: vstd/set_lib.rs:175  (spec fn)
- sig: `pub open spec fn to_sorted_seq(self, leq: spec_fn(A, A) -> bool) -> Seq<A>`
- doc: Converts a set into a sequence sorted by the given ordering function `leq`

## Set::is_singleton
- path: vstd/set_lib.rs:180  (spec fn)
- sig: `pub open spec fn is_singleton(self) -> bool`
- doc: A singleton set has at least one element and any two elements are equal.

## Set::injective_on
- path: vstd/set_lib.rs:188  (spec fn)
- sig: `pub open spec fn injective_on<B>(self, r: spec_fn(A) -> B) -> bool`
- doc: Indicates if the function given by `r` is injective on this set,

## Set::has_least
- path: vstd/set_lib.rs:194  (spec fn)
- sig: `pub open spec fn has_least(self, leq: spec_fn(A, A) -> bool, min: A) -> bool`
- doc: An element in an ordered set is called a least element (or a minimum), if it is less than

## Set::has_minimum
- path: vstd/set_lib.rs:199  (spec fn)
- sig: `pub open spec fn has_minimum(self, leq: spec_fn(A, A) -> bool, min: A) -> bool`
- doc: An element in an ordered set is called a minimal element, if no other element is less than it.

## Set::has_greatest
- path: vstd/set_lib.rs:205  (spec fn)
- sig: `pub open spec fn has_greatest(self, leq: spec_fn(A, A) -> bool, max: A) -> bool`
- doc: An element in an ordered set is called a greatest element (or a maximum), if it is greater than

## Set::has_maximum
- path: vstd/set_lib.rs:210  (spec fn)
- sig: `pub open spec fn has_maximum(self, leq: spec_fn(A, A) -> bool, max: A) -> bool`
- doc: An element in an ordered set is called a maximal element, if no other element is greater than it.

## Set::lemma_injective_on_subset
- path: vstd/set_lib.rs:215  (proof fn)
- sig: `pub proof fn lemma_injective_on_subset<B>(self, r: spec_fn(A) -> B, other: Self)`
- requires: other <= self, self.injective_on(r),
- ensures: other.injective_on(r),
- doc: If a function is injective on the set `self`, then it is also injective on any subset `other` of `self`.

## Set::find_unique_minimal
- path: vstd/set_lib.rs:227  (spec fn)
- sig: `pub closed spec fn find_unique_minimal(self, r: spec_fn(A, A) -> bool) -> A recommends total_ordering(r), self.len() > 0,`
- doc: Any totally-ordered set contains a unique minimal (equivalently, least) element.

## Set::find_unique_maximal
- path: vstd/set_lib.rs:250  (spec fn)
- sig: `pub closed spec fn find_unique_maximal(self, r: spec_fn(A, A) -> bool) -> A recommends total_ordering(r), self.len() > 0,`
- doc: Any totally-ordered set contains a unique maximal (equivalently, greatest) element.

## Set::to_multiset
- path: vstd/set_lib.rs:272  (spec fn)
- sig: `pub open spec fn to_multiset(self) -> Multiset<A>`
- doc: Converts a set into a multiset where each element from the set has

## Set::lemma_len0_is_empty
- path: vstd/set_lib.rs:285  (proof fn)
- sig: `pub proof fn lemma_len0_is_empty(self)`
- requires: self.len() == 0,
- ensures: self == Set::<A>::empty(),
- doc: A finite set with length 0 is equivalent to the empty set.

## Set::lemma_singleton_size
- path: vstd/set_lib.rs:299  (proof fn)
- sig: `pub proof fn lemma_singleton_size(self)`
- requires: self.is_singleton(),
- ensures: self.len() == 1,
- doc: A singleton set has length 1.

## Set::lemma_is_singleton
- path: vstd/set_lib.rs:311  (proof fn)
- sig: `pub proof fn lemma_is_singleton(s: Set<A>)`
- ensures: s.is_singleton() == (s.len() == 1),
- doc: A set has exactly one element, if and only if, it has at least one element and any two elements are equal.

## Set::lemma_len_filter
- path: vstd/set_lib.rs:330  (proof fn)
- sig: `pub proof fn lemma_len_filter(self, f: spec_fn(A) -> bool)`
- ensures: self.filter(f).len() <= self.len(),
- doc: The result of filtering a finite set is finite and has size less than or equal to the original set.

## Set::lemma_greatest_implies_maximal
- path: vstd/set_lib.rs:345  (proof fn)
- sig: `pub proof fn lemma_greatest_implies_maximal(self, r: spec_fn(A, A) -> bool, max: A)`
- requires: pre_ordering(r),
- ensures: self.has_greatest(r, max) ==> self.has_maximum(r, max),
- doc: In a pre-ordered set, a greatest element is necessarily maximal.

## Set::lemma_least_implies_minimal
- path: vstd/set_lib.rs:354  (proof fn)
- sig: `pub proof fn lemma_least_implies_minimal(self, r: spec_fn(A, A) -> bool, min: A)`
- requires: pre_ordering(r),
- ensures: self.has_least(r, min) ==> self.has_minimum(r, min),
- doc: In a pre-ordered set, a least element is necessarily minimal.

## Set::lemma_maximal_equivalent_greatest
- path: vstd/set_lib.rs:363  (proof fn)
- sig: `pub proof fn lemma_maximal_equivalent_greatest(self, r: spec_fn(A, A) -> bool, max: A)`
- requires: total_ordering(r),
- ensures: self.has_greatest(r, max) <==> self.has_maximum(r, max),
- doc: In a totally-ordered set, an element is maximal if and only if it is a greatest element.

## Set::lemma_minimal_equivalent_least
- path: vstd/set_lib.rs:373  (proof fn)
- sig: `pub proof fn lemma_minimal_equivalent_least(self, r: spec_fn(A, A) -> bool, min: A)`
- requires: total_ordering(r),
- ensures: self.has_least(r, min) <==> self.has_minimum(r, min),
- doc: In a totally-ordered set, an element is maximal if and only if it is a greatest element.

## Set::lemma_least_is_unique
- path: vstd/set_lib.rs:383  (proof fn)
- sig: `pub proof fn lemma_least_is_unique(self, r: spec_fn(A, A) -> bool)`
- requires: partial_ordering(r),
- ensures: forall|min: A, min_prime: A| self.has_least(r, min) && self.has_least(r, min_prime) ==> min == min_prime,
- doc: In a partially-ordered set, there exists at most one least element.

## Set::lemma_greatest_is_unique
- path: vstd/set_lib.rs:394  (proof fn)
- sig: `pub proof fn lemma_greatest_is_unique(self, r: spec_fn(A, A) -> bool)`
- requires: partial_ordering(r),
- ensures: forall|max: A, max_prime: A| self.has_greatest(r, max) && self.has_greatest(r, max_prime) ==> max == max_prime,
- doc: In a partially-ordered set, there exists at most one greatest element.

## Set::lemma_minimal_is_unique
- path: vstd/set_lib.rs:405  (proof fn)
- sig: `pub proof fn lemma_minimal_is_unique(self, r: spec_fn(A, A) -> bool)`
- requires: total_ordering(r),
- ensures: forall|min: A, min_prime: A| self.has_minimum(r, min) && self.has_minimum(r, min_prime) ==> min == min_prime,
- doc: In a totally-ordered set, there exists at most one minimal element.

## Set::lemma_maximal_is_unique
- path: vstd/set_lib.rs:416  (proof fn)
- sig: `pub proof fn lemma_maximal_is_unique(self, r: spec_fn(A, A) -> bool)`
- requires: total_ordering(r),
- ensures: forall|max: A, max_prime: A| self.has_maximum(r, max) && self.has_maximum(r, max_prime) ==> max == max_prime,
- doc: In a totally-ordered set, there exists at most one maximal element.

## Set::lemma_set_insert_diff_decreases
- path: vstd/set_lib.rs:429  (proof fn)
- sig: `pub broadcast proof fn lemma_set_insert_diff_decreases(self, s: Set<A>, elt: A)`
- requires: self.contains(elt), !s.contains(elt),
- ensures: #[trigger] self.difference(s.insert(elt)).len() < self.difference(s).len(),
- doc: Set difference with an additional element inserted decreases the size of

## Set::lemma_subset_not_in_lt
- path: vstd/set_lib.rs:440  (proof fn)
- sig: `pub proof fn lemma_subset_not_in_lt(self: Set<A>, s2: Set<A>, elt: A)`
- requires: self.subset_of(s2), !self.contains(elt), s2.contains(elt),
- ensures: self.len() < s2.len(),
- doc: If there is an element not present in a subset, its length is stricly smaller.

## Set::lemma_set_map_insert_commute
- path: vstd/set_lib.rs:455  (proof fn)
- sig: `pub broadcast proof fn lemma_set_map_insert_commute<B>(self, elt: A, f: spec_fn(A) -> B)`
- ensures: #[trigger] self.insert(elt).map(f) =~= self.map(f).insert(f(elt)),
- doc: Inserting an element and mapping a function over a set commute

## Set::lemma_map_union_commute
- path: vstd/set_lib.rs:474  (proof fn)
- sig: `pub proof fn lemma_map_union_commute<B>(self, t: Set<A>, f: spec_fn(A) -> B)`
- ensures: (self.union(t)).map(f) =~= self.map(f).union(t.map(f)),
- doc: `map` and `union` commute

## Set::all
- path: vstd/set_lib.rs:496  (spec fn)
- sig: `pub open spec fn all(&self, pred: spec_fn(A) -> bool) -> bool`
- doc: Utility function for more concise universal quantification over sets

## Set::any
- path: vstd/set_lib.rs:501  (spec fn)
- sig: `pub open spec fn any(&self, pred: spec_fn(A) -> bool) -> bool`
- doc: Utility function for more concise existential quantification over sets

## Set::lemma_any_map_preserved_pred
- path: vstd/set_lib.rs:506  (proof fn)
- sig: `pub broadcast proof fn lemma_any_map_preserved_pred<B>( self, p: spec_fn(A) -> bool, q: spec_fn(B) -> bool, f: spec_fn(A) -> B, )`
- requires: #[trigger] self.any(p), forall|x: A| #[trigger] p(x) ==> q(f(x)),
- ensures: #[trigger] self.map(f).any(q),
- doc: `any` is preserved between predicates `p` and `q` if `p` implies `q`.

## Set::filter_map
- path: vstd/set_lib.rs:525  (spec fn)
- sig: `pub open spec fn filter_map<B>(self, f: spec_fn(A) -> Option<B>) -> Set<B>`
- doc: Collecting all elements `b` where `f` returns `Some(b)`

## Set::lemma_filter_map_insert
- path: vstd/set_lib.rs:536  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_map_insert<B>( s: Set<A>, f: spec_fn(A) -> Option<B>, elem: A, )`
- ensures: #[trigger] s.insert(elem).filter_map(f) == (match f(elem) { Some(res) => s.filter_map(f).insert(res), None => s.filter_map(f), }),
- doc: Inserting commutes with `filter_map`

## Set::lemma_filter_map_union
- path: vstd/set_lib.rs:583  (proof fn)
- sig: `pub broadcast proof fn lemma_filter_map_union<B>(self, f: spec_fn(A) -> Option<B>, t: Set<A>)`
- ensures: #[trigger] self.union(t).filter_map(f) == self.filter_map(f).union(t.filter_map(f)),
- doc: `filter_map` and `union` commute.

## Set::lemma_set_all_subset
- path: vstd/set_lib.rs:628  (proof fn)
- sig: `pub broadcast proof fn lemma_set_all_subset(self, s2: Set<A>, p: spec_fn(A) -> bool)`
- requires: #[trigger] self.subset_of(s2), s2.all(p),
- ensures: #[trigger] self.all(p),
- doc: If `self` is a subset of `s2`, and all elements of `s2`

## Set::lemma_to_seq_to_set_id
- path: vstd/set_lib.rs:640  (proof fn)
- sig: `pub broadcast proof fn lemma_to_seq_to_set_id(self)`
- ensures: #[trigger] self.to_seq().to_set() =~= self,
- doc: Conversion to a sequence and back to a set is the identity function.

## Set::flatten
- path: vstd/set_lib.rs:663  (spec fn)
- sig: `pub closed spec fn flatten(self) -> Set<A>`
- doc: This function creates a set from all the elements of all the elements

## Set::lemma_flatten_contains
- path: vstd/set_lib.rs:698  (proof fn)
- sig: `pub broadcast proof fn lemma_flatten_contains(self, elem: A)`
- ensures: #[trigger] self.flatten().contains(elem) <==> (exists|elem_s: Set<A>| #[trigger] self.contains(elem_s) && elem_s.contains(elem)),
- doc: Since `Self::flatten` is `closed`, this broadcast lemma is

## Set::flatten_insert_union_commute
- path: vstd/set_lib.rs:708  (proof fn)
- sig: `pub broadcast proof fn flatten_insert_union_commute(self, other: Set<A>)`
- ensures: self.flatten().union(other) =~= #[trigger] self.insert(other).flatten(),
- doc: Flattening then unioning with another set is equivalent to

## range_set_properties
- path: vstd/set_lib.rs:752  (proof fn)
- sig: `pub broadcast proof fn range_set_properties<A: FiniteRange>(lo: A, hi: A)`
- ensures: forall|i: A| #[trigger] A::range_set(lo, hi).contains(i) <==> A::in_range(i, lo, hi), (#[trigger] A::range_set(lo, hi)).len() == A::range_len(lo, hi),
- doc: This public broadcast lemma shows that when `A` has trait

## full_set_properties
- path: vstd/set_lib.rs:770  (proof fn)
- sig: `pub broadcast proof fn full_set_properties<A: FiniteFull>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::set_lib::group_set_lib_default`: write `broadcast use vstd::set_lib::group_set_lib_default;` and the fact is available.
- ensures: #![trigger Set::<A>::full()] Set::<A>::full() is Some,
- doc: This public broadcast lemma shows that when `A` has trait

## Set::range
- path: vstd/set_lib.rs:780  (spec fn)
- sig: `pub open spec fn range(lo: A, hi: A) -> Set<A>`

## Set::range_inclusive
- path: vstd/set_lib.rs:785  (spec fn)
- sig: `pub open spec fn range_inclusive(lo: A, hi: A) -> Set<A>`

## Set::from_finite_type
- path: vstd/set_lib.rs:792  (spec fn)
- sig: `pub open spec fn from_finite_type(f: spec_fn(A) -> bool) -> Set<A>`

## lemma_sets_eq_iff_injective_map_eq
- path: vstd/set_lib.rs:904  (proof fn)
- sig: `pub proof fn lemma_sets_eq_iff_injective_map_eq<T, S>(s1: Set<T>, s2: Set<T>, f: spec_fn(T) -> S)`
- requires: super::relations::injective(f),
- ensures: (s1 == s2) <==> (s1.map(f) == s2.map(f)),
- doc: Two sets are equal iff mapping `f` results in equal sets, if `f` is injective.

## lemma_sets_eq_iff_injective_map_on_eq
- path: vstd/set_lib.rs:927  (proof fn)
- sig: `pub proof fn lemma_sets_eq_iff_injective_map_on_eq<T, S>(s1: Set<T>, s2: Set<T>, f: spec_fn(T) -> S)`
- requires: (s1 + s2).injective_on(f),
- ensures: (s1 == s2) <==> (s1.map(f) == s2.map(f)),
- doc: Two sets are equal iff applying an injective (in the union of the sets) function `f` to each set produces equal sets.

## lemma_len_union
- path: vstd/set_lib.rs:951  (proof fn)
- sig: `pub proof fn lemma_len_union<A>(s1: Set<A>, s2: Set<A>)`
- ensures: s1.union(s2).len() <= s1.len() + s2.len(),
- doc: The size of a union of two sets is less than or equal to the size of

## lemma_len_union_ind
- path: vstd/set_lib.rs:971  (proof fn)
- sig: `pub proof fn lemma_len_union_ind<A>(s1: Set<A>, s2: Set<A>)`
- ensures: s1.union(s2).len() >= s1.len(), s1.union(s2).len() >= s2.len(),
- doc: The size of a union of two sets is greater than or equal to the size of

## lemma_len_intersect
- path: vstd/set_lib.rs:993  (proof fn)
- sig: `pub proof fn lemma_len_intersect<A>(s1: Set<A>, s2: Set<A>)`
- ensures: s1.intersect(s2).len() <= s1.len(),
- doc: The size of the intersection of finite set `s1` and set `s2` is less than or equal to the size of `s1`.

## lemma_len_subset
- path: vstd/set_lib.rs:1009  (proof fn)
- sig: `pub proof fn lemma_len_subset<A>(s1: Set<A>, s2: Set<A>)`
- requires: s1.subset_of(s2),
- ensures: s1.len() <= s2.len(),
- doc: If `s1` is a subset of finite set `s2`, then the size of `s1` is less than or equal to

## lemma_len_difference
- path: vstd/set_lib.rs:1020  (proof fn)
- sig: `pub proof fn lemma_len_difference<A>(s1: Set<A>, s2: Set<A>)`
- ensures: s1.difference(s2).len() <= s1.len(),
- doc: The size of the difference of finite set `s1` and set `s2` is less than or equal to the size of `s1`.

## set_int_range
- path: vstd/set_lib.rs:1035  (spec fn)
- sig: `pub open spec fn set_int_range(lo: int, hi: int) -> Set<int>`
- doc: Creates a finite set of integers in the range [lo, hi).

## lemma_int_range
- path: vstd/set_lib.rs:1041  (proof fn)
- sig: `pub proof fn lemma_int_range(lo: int, hi: int)`
- requires: lo <= hi,
- ensures: forall|j: int| set_int_range(lo, hi).contains(j) <==> lo <= j < hi, set_int_range(lo, hi).len() == hi - lo,
- doc: If a set solely contains integers in the range [a, b), then its size is

## lemma_subset_equality
- path: vstd/set_lib.rs:1054  (proof fn)
- sig: `pub proof fn lemma_subset_equality<A>(x: Set<A>, y: Set<A>)`
- requires: x.subset_of(y), x.len() == y.len(),
- ensures: x =~= y,
- doc: If x is a subset of y and the size of x is equal to the size of y, x is equal to y.

## lemma_map_size
- path: vstd/set_lib.rs:1073  (proof fn)
- sig: `pub proof fn lemma_map_size<A, B>(x: Set<A>, y: Set<B>, f: spec_fn(A) -> B)`
- requires: x.injective_on(f), x.map(f) == y,
- ensures: x.len() == y.len(),
- doc: If an injective function is applied to each element of a set to construct

## lemma_map_size_bound
- path: vstd/set_lib.rs:1098  (proof fn)
- sig: `pub proof fn lemma_map_size_bound<A, B>(x: Set<A>, y: Set<B>, f: spec_fn(A) -> B)`
- requires: x.map(f) == y,
- ensures: y.len() <= x.len(),
- doc: If any function is applied to each element of a set to construct

## lemma_set_union_again1
- path: vstd/set_lib.rs:1134  (proof fn)
- sig: `pub broadcast proof fn lemma_set_union_again1<A>(a: Set<A>, b: Set<A>)`
- ensures: #[trigger] a.union(b).union(b) =~= a.union(b),
- doc: Taking the union of sets `a` and `b` and then taking the union of the result with `b`

## lemma_set_union_again2
- path: vstd/set_lib.rs:1143  (proof fn)
- sig: `pub broadcast proof fn lemma_set_union_again2<A>(a: Set<A>, b: Set<A>)`
- ensures: #[trigger] a.union(b).union(a) =~= a.union(b),
- doc: Taking the union of sets `a` and `b` and then taking the union of the result with `a`

## lemma_set_intersect_again1
- path: vstd/set_lib.rs:1152  (proof fn)
- sig: `pub broadcast proof fn lemma_set_intersect_again1<A>(a: Set<A>, b: Set<A>)`
- ensures: #![trigger (a.intersect(b)).intersect(b)] (a.intersect(b)).intersect(b) =~= a.intersect(b),
- doc: Taking the intersection of sets `a` and `b` and then taking the intersection of the result with `b`

## lemma_set_intersect_again2
- path: vstd/set_lib.rs:1162  (proof fn)
- sig: `pub broadcast proof fn lemma_set_intersect_again2<A>(a: Set<A>, b: Set<A>)`
- ensures: #![trigger (a.intersect(b)).intersect(a)] (a.intersect(b)).intersect(a) =~= a.intersect(b),
- doc: Taking the intersection of sets `a` and `b` and then taking the intersection of the result with `a`

## lemma_set_difference2
- path: vstd/set_lib.rs:1171  (proof fn)
- sig: `pub broadcast proof fn lemma_set_difference2<A>(s1: Set<A>, s2: Set<A>, a: A)`
- ensures: #![trigger s1.difference(s2).contains(a)] s2.contains(a) ==> !s1.difference(s2).contains(a),
- doc: If set `s2` contains element `a`, then the set difference of `s1` and `s2` does not contain `a`.

## lemma_set_disjoint
- path: vstd/set_lib.rs:1181  (proof fn)
- sig: `pub broadcast proof fn lemma_set_disjoint<A>(a: Set<A>, b: Set<A>)`
- ensures: #![trigger (a + b).difference(a)]  //TODO: this might be too free a.disjoint(b) ==> ((a + b).difference(a) =~= b && (a + b).difference(b) =~= a),
- doc: If sets `a` and `b` are disjoint, meaning they have no elements in common, then the set difference

## lemma_set_empty_equivalency_len
- path: vstd/set_lib.rs:1195  (proof fn)
- sig: `pub broadcast proof fn lemma_set_empty_equivalency_len<A>(s: Set<A>)`
- ensures: #![trigger s.len()] (s.len() == 0 <==> s == Set::<A>::empty()) && (s.len() != 0 ==> exists|x: A| s.contains(x)),
- doc: Set `s` has length 0 if and only if it is equal to the empty set. If `s` has length greater than 0,

## lemma_set_disjoint_lens
- path: vstd/set_lib.rs:1220  (proof fn)
- sig: `pub broadcast proof fn lemma_set_disjoint_lens<A>(a: Set<A>, b: Set<A>)`
- ensures: a.disjoint(b) ==> #[trigger] (a + b).len() == a.len() + b.len(),
- doc: If sets `a` and `b` are disjoint, meaning they share no elements in common, then the length

## lemma_set_disjoint_iff_empty_intersection
- path: vstd/set_lib.rs:1238  (proof fn)
- sig: `pub proof fn lemma_set_disjoint_iff_empty_intersection<T>(a: Set<T>, b: Set<T>)`
- ensures: a.disjoint(b) <==> a.intersect(b).is_empty(),
- doc: Two sets are disjoint iff their intersection is empty

## lemma_set_intersect_union_lens
- path: vstd/set_lib.rs:1264  (proof fn)
- sig: `pub broadcast proof fn lemma_set_intersect_union_lens<A>(a: Set<A>, b: Set<A>)`
- ensures: #[trigger] (a + b).len() + #[trigger] a.intersect(b).len() == a.len() + b.len(),
- doc: The length of the union between two sets added to the length of the intersection between the

## lemma_set_difference_len
- path: vstd/set_lib.rs:1293  (proof fn)
- sig: `pub broadcast proof fn lemma_set_difference_len<A>(a: Set<A>, b: Set<A>)`
- ensures: (#[trigger] a.difference(b).len() + b.difference(a).len() + a.intersect(b).len() == (a + b).len()) && (a.difference(b).len() == a.len() - a.intersect(b).len()),
- doc: The length of the set difference `A \ B` added to the length of the set difference `B \ A` added to

## group_set_properties
- path: vstd/set_lib.rs  (broadcast group)
- members: lemma_set_union_again1 lemma_set_union_again2 lemma_set_intersect_again1 lemma_set_intersect_again2 lemma_set_difference2 lemma_set_disjoint lemma_set_disjoint_lens lemma_set_intersect_union_lens lemma_set_difference_len // REVIEW: exclude from broadcast group if trigger is too free //         also note that some proofs in seq_lib requires this lemma lemma_set_empty_equivalency_len

## lemma_set_is_empty
- path: vstd/set_lib.rs:1337  (proof fn)
- sig: `pub broadcast proof fn lemma_set_is_empty<A>(s: Set<A>)`
- requires: !(#[trigger] s.is_empty()),
- ensures: exists|a: A| s.contains(a),

## lemma_set_is_empty_len0
- path: vstd/set_lib.rs:1346  (proof fn)
- sig: `pub broadcast proof fn lemma_set_is_empty_len0<A>(s: Set<A>)`
- ensures: #[trigger] s.is_empty() <==> s.len() == 0,

## check_argument_is_set
- path: vstd/set_lib.rs:1354  (spec fn)
- sig: `pub open spec fn check_argument_is_set<A>(s: Set<A>) -> Set<A>`

## group_set_lib_default
- path: vstd/set_lib.rs  (broadcast group)
- members: lemma_set_is_empty lemma_set_is_empty_len0 Set::lemma_flatten_contains Set::lemma_map_contains Set::lemma_map_by_contains Set::lemma_map_flatten_by_contains range_set_properties full_set_properties

## agreement
- path: vstd/shared.rs:27  (fn)
- sig: `pub fn agreement(&self) -> bool`

## Shared::view
- path: vstd/shared.rs:51  (spec fn)
- sig: `pub closed spec fn view(self) -> T`

## PPtr::spec_addr
- path: vstd/simple_pptr.rs:177  (spec fn)
- sig: `pub open spec fn spec_addr(p: PPtr<V>) -> usize`
- doc: Use `addr()` instead

## PPtr::addr
- path: vstd/simple_pptr.rs:184  (fn)
- sig: `pub fn addr(self) -> (u: usize)`
- ensures: u == self.addr(),
- doc: Cast a pointer to an integer.

## PPtr::from_addr
- path: vstd/simple_pptr.rs:203  (fn)
- sig: `pub fn from_addr(u: usize) -> (s: Self)`
- ensures: u == s.addr(),
- doc: Cast an integer to a pointer.

## PPtr::from_usize
- path: vstd/simple_pptr.rs:212  (fn)
- sig: `pub fn from_usize(u: usize) -> (s: Self)`
- ensures: u == s.addr(),

## PointsTo::pptr
- path: vstd/simple_pptr.rs:222  (spec fn)
- sig: `pub open spec fn pptr(&self) -> PPtr<V>`

## PointsTo::addr
- path: vstd/simple_pptr.rs:226  (spec fn)
- sig: `pub closed spec fn addr(self) -> usize`

## PointsTo::mem_contents
- path: vstd/simple_pptr.rs:246  (spec fn)
- sig: `pub closed spec fn mem_contents(&self) -> MemContents<V>`

## PointsTo::opt_value
- path: vstd/simple_pptr.rs:252  (spec fn)
- sig: `pub open spec fn opt_value(&self) -> MemContents<V>`

## PointsTo::is_init
- path: vstd/simple_pptr.rs:257  (spec fn)
- sig: `pub open spec fn is_init(&self) -> bool`

## PointsTo::is_uninit
- path: vstd/simple_pptr.rs:262  (spec fn)
- sig: `pub open spec fn is_uninit(&self) -> bool`

## PointsTo::value
- path: vstd/simple_pptr.rs:267  (spec fn)
- sig: `pub open spec fn value(&self) -> V recommends self.is_init(),`

## PPtr::empty
- path: vstd/simple_pptr.rs:347  (fn)
- sig: `pub fn empty() -> (pt: (PPtr<V>, Tracked<PointsTo<V>>))`
- ensures: pt.1@.pptr() == pt.0, pt.1@.is_uninit(),
- doc: Allocates heap memory for type `V`, leaving it uninitialized.

## PPtr::new
- path: vstd/simple_pptr.rs:397  (fn)
- sig: `pub fn new(v: V) -> (pt: (PPtr<V>, Tracked<PointsTo<V>>))`
- ensures: pt.1@.pptr() == pt.0, pt.1@.mem_contents() == MemContents::Init(v),
- doc: Allocates heap memory for type `V`, leaving it initialized

## PPtr::free
- path: vstd/simple_pptr.rs:413  (fn)
- sig: `pub fn free(self, Tracked(perm): Tracked<PointsTo<V>>)`
- requires: perm.pptr() == self, perm.is_uninit(),
- doc: Free the memory pointed to be `perm`.

## PPtr::into_inner
- path: vstd/simple_pptr.rs:442  (fn)
- sig: `pub fn into_inner(self, Tracked(perm): Tracked<PointsTo<V>>) -> (v: V)`
- requires: perm.pptr() == self, perm.is_init(),
- ensures: v == perm.value(),
- doc: Free the memory pointed to be `perm` and return the

## PPtr::put
- path: vstd/simple_pptr.rs:462  (fn)
- sig: `pub fn put(self, Tracked(perm): Tracked<&mut PointsTo<V>>, v: V)`
- requires: old(perm).pptr() == self, old(perm).mem_contents() == MemContents::Uninit::<V>,
- ensures: final(perm).pptr() == old(perm).pptr(), final(perm).mem_contents() == MemContents::Init(v),
- doc: Moves `v` into the location pointed to by the pointer `self`.

## PPtr::take
- path: vstd/simple_pptr.rs:487  (fn)
- sig: `pub fn take(self, Tracked(perm): Tracked<&mut PointsTo<V>>) -> (v: V)`
- requires: old(perm).pptr() == self, old(perm).is_init(),
- ensures: final(perm).pptr() == old(perm).pptr(), final(perm).mem_contents() == MemContents::Uninit::<V>, v == old(perm).value(),
- doc: Moves `v` out of the location pointed to by the pointer `self`

## PPtr::replace
- path: vstd/simple_pptr.rs:508  (fn)
- sig: `pub fn replace(self, Tracked(perm): Tracked<&mut PointsTo<V>>, in_v: V) -> (out_v: V)`
- requires: old(perm).pptr() == self, old(perm).is_init(),
- ensures: final(perm).pptr() == old(perm).pptr(), final(perm).mem_contents() == MemContents::Init(in_v), out_v == old(perm).value(),
- doc: Swaps the `in_v: V` passed in as an argument with the value in memory.

## PPtr::borrow
- path: vstd/simple_pptr.rs:530  (fn)
- sig: `pub fn borrow<'a>(self, Tracked(perm): Tracked<&'a PointsTo<V>>) -> (v: &'a V)`
- requires: perm.pptr() == self, perm.is_init(),
- ensures: *v == perm.value(),
- doc: Given a shared borrow of the `PointsTo<V>`, obtain a shared borrow of `V`.

## PPtr::borrow_mut
- path: vstd/simple_pptr.rs:548  (fn)
- sig: `pub fn borrow_mut<'a>(self, Tracked(perm): Tracked<&'a mut PointsTo<V>>) -> (v: &'a mut V)`
- requires: perm.pptr() == self, perm.is_init(),
- ensures: final(perm).pptr() == self, final(perm).is_init(), *v == old(perm).value(), final(perm).value() == *final(v),
- doc: Given a shared borrow of the `PointsTo<V>`, obtain a shared borrow of `V`.

## PPtr::write
- path: vstd/simple_pptr.rs:568  (fn)
- sig: `pub fn write(self, Tracked(perm): Tracked<&mut PointsTo<V>>, in_v: V) where V: Copy`
- requires: old(perm).pptr() == self,
- ensures: final(perm).pptr() == old(perm).pptr(), final(perm).mem_contents() == MemContents::Init(in_v),

## PPtr::read
- path: vstd/simple_pptr.rs:585  (fn)
- sig: `pub fn read(self, Tracked(perm): Tracked<&PointsTo<V>>) -> (out_v: V) where V: Copy`
- requires: perm.pptr() == self, perm.is_init(),
- ensures: out_v == perm.value(),

## slice_index_get
- path: vstd/slice.rs:62  (fn)
- sig: `pub exec fn slice_index_get<T>(slice: &[T], i: usize) -> (out: &T)`
- requires: 0 <= i < slice.view().len(),
- ensures: *out == slice@.index(i as int),

## spec_slice_len
- path: vstd/slice.rs:73  (spec fn)
- sig: `pub uninterp spec fn spec_slice_len<T>(slice: &[T]) -> usize`
- doc: /// Len (with autospec)

## <[T
- path: vstd/slice.rs:83  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ <[T]>::len ](slice: &[T]) -> (len: usize)`

## spec_slice_is_empty
- path: vstd/slice.rs:88  (spec fn)
- sig: `pub open spec fn spec_slice_is_empty<T>(slice: &[T]) -> bool`

## <[T
- path: vstd/slice.rs:93  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ <[T]>::is_empty ](slice: &[T]) -> (b: bool)`
- ensures: b <==> slice@.len() == 0,

## slice_to_vec
- path: vstd/slice.rs:100  (fn)
- sig: `pub exec fn slice_to_vec<T: Copy>(slice: &[T]) -> (out: alloc::vec::Vec<T>)`
- ensures: out@ == slice@,

## slice_subrange
- path: vstd/slice.rs:108  (fn)
- sig: `pub exec fn slice_subrange<T, 'a>(slice: &'a [T], i: usize, j: usize) -> (out: &'a [T])`
- requires: 0 <= i <= j <= slice@.len(),
- ensures: out@ == slice@.subrange(i as int, j as int),

## <[T
- path: vstd/slice.rs:133  (exec spec, assume_specification)
- sig: `pub assume_specification<T, I>[ <[T]>::get::<I> ](slice: &[T], i: I) -> (b: Option< &<I as SliceIndex<[T]>>::Output, >) where I: SliceIndex<[T]>`

## spec_slice_get
- path: vstd/slice.rs:140  (spec fn)
- sig: `pub uninterp spec fn spec_slice_get<T: ?Sized, I: SliceIndex<T>>(val: &T, idx: I) -> Option< &<I as SliceIndex<T>>::Output, >`

## spec_slice_update
- path: vstd/slice.rs:158  (spec fn)
- sig: `pub uninterp spec fn spec_slice_update<T>(slice: &[T], i: int, t: T) -> &[T]`

## spec_slice_index
- path: vstd/slice.rs:168  (spec fn)
- sig: `pub uninterp spec fn spec_slice_index<T>(slice: &[T], i: int) -> T`

## group_slice_axioms
- path: vstd/slice.rs  (broadcast group)
- members: axiom_spec_len axiom_slice_get_usize axiom_slice_ext_equal axiom_spec_slice_update axiom_spec_slice_index axiom_slice_has_resolved

## assert_safety
- path: vstd/state_machine_internal.rs:36  (fn)
- sig: `pub fn assert_safety(b: bool)`

## assert_let_pattern
- path: vstd/state_machine_internal.rs:47  (fn)
- sig: `pub fn assert_let_pattern(b: bool)`

## assert_add_option
- path: vstd/state_machine_internal.rs:60  (fn)
- sig: `pub fn assert_add_option(b: bool)`

## assert_add_set
- path: vstd/state_machine_internal.rs:72  (fn)
- sig: `pub fn assert_add_set(b: bool)`

## assert_add_iset
- path: vstd/state_machine_internal.rs:84  (fn)
- sig: `pub fn assert_add_iset(b: bool)`

## assert_add_bool
- path: vstd/state_machine_internal.rs:96  (fn)
- sig: `pub fn assert_add_bool(b: bool)`

## assert_add_map
- path: vstd/state_machine_internal.rs:108  (fn)
- sig: `pub fn assert_add_map(b: bool)`

## assert_add_imap
- path: vstd/state_machine_internal.rs:120  (fn)
- sig: `pub fn assert_add_imap(b: bool)`

## assert_add_persistent_map
- path: vstd/state_machine_internal.rs:132  (fn)
- sig: `pub fn assert_add_persistent_map(b: bool)`

## assert_add_persistent_imap
- path: vstd/state_machine_internal.rs:144  (fn)
- sig: `pub fn assert_add_persistent_imap(b: bool)`

## assert_add_persistent_option
- path: vstd/state_machine_internal.rs:156  (fn)
- sig: `pub fn assert_add_persistent_option(b: bool)`

## assert_withdraw_option
- path: vstd/state_machine_internal.rs:168  (fn)
- sig: `pub fn assert_withdraw_option(b: bool)`

## assert_deposit_option
- path: vstd/state_machine_internal.rs:175  (fn)
- sig: `pub fn assert_deposit_option(b: bool)`

## assert_guard_option
- path: vstd/state_machine_internal.rs:187  (fn)
- sig: `pub fn assert_guard_option(b: bool)`

## assert_withdraw_map
- path: vstd/state_machine_internal.rs:199  (fn)
- sig: `pub fn assert_withdraw_map(b: bool)`

## assert_withdraw_imap
- path: vstd/state_machine_internal.rs:211  (fn)
- sig: `pub fn assert_withdraw_imap(b: bool)`

## assert_deposit_map
- path: vstd/state_machine_internal.rs:223  (fn)
- sig: `pub fn assert_deposit_map(b: bool)`

## assert_deposit_imap
- path: vstd/state_machine_internal.rs:235  (fn)
- sig: `pub fn assert_deposit_imap(b: bool)`

## assert_guard_map
- path: vstd/state_machine_internal.rs:247  (fn)
- sig: `pub fn assert_guard_map(b: bool)`

## assert_guard_imap
- path: vstd/state_machine_internal.rs:259  (fn)
- sig: `pub fn assert_guard_imap(b: bool)`

## assert_general_add_option
- path: vstd/state_machine_internal.rs:273  (fn)
- sig: `pub fn assert_general_add_option(b: bool)`

## assert_general_add_set
- path: vstd/state_machine_internal.rs:285  (fn)
- sig: `pub fn assert_general_add_set(b: bool)`

## assert_general_add_iset
- path: vstd/state_machine_internal.rs:297  (fn)
- sig: `pub fn assert_general_add_iset(b: bool)`

## assert_general_add_bool
- path: vstd/state_machine_internal.rs:309  (fn)
- sig: `pub fn assert_general_add_bool(b: bool)`

## assert_general_add_map
- path: vstd/state_machine_internal.rs:321  (fn)
- sig: `pub fn assert_general_add_map(b: bool)`

## assert_general_add_imap
- path: vstd/state_machine_internal.rs:333  (fn)
- sig: `pub fn assert_general_add_imap(b: bool)`

## assert_general_add_persistent_map
- path: vstd/state_machine_internal.rs:345  (fn)
- sig: `pub fn assert_general_add_persistent_map(b: bool)`

## assert_general_add_persistent_imap
- path: vstd/state_machine_internal.rs:357  (fn)
- sig: `pub fn assert_general_add_persistent_imap(b: bool)`

## assert_general_add_persistent_option
- path: vstd/state_machine_internal.rs:369  (fn)
- sig: `pub fn assert_general_add_persistent_option(b: bool)`

## assert_general_withdraw_option
- path: vstd/state_machine_internal.rs:381  (fn)
- sig: `pub fn assert_general_withdraw_option(b: bool)`

## assert_general_deposit_option
- path: vstd/state_machine_internal.rs:393  (fn)
- sig: `pub fn assert_general_deposit_option(b: bool)`

## assert_general_guard_option
- path: vstd/state_machine_internal.rs:405  (fn)
- sig: `pub fn assert_general_guard_option(b: bool)`

## assert_general_withdraw_map
- path: vstd/state_machine_internal.rs:417  (fn)
- sig: `pub fn assert_general_withdraw_map(b: bool)`

## assert_general_withdraw_imap
- path: vstd/state_machine_internal.rs:429  (fn)
- sig: `pub fn assert_general_withdraw_imap(b: bool)`

## assert_general_deposit_map
- path: vstd/state_machine_internal.rs:441  (fn)
- sig: `pub fn assert_general_deposit_map(b: bool)`

## assert_general_deposit_imap
- path: vstd/state_machine_internal.rs:453  (fn)
- sig: `pub fn assert_general_deposit_imap(b: bool)`

## assert_general_guard_map
- path: vstd/state_machine_internal.rs:465  (fn)
- sig: `pub fn assert_general_guard_map(b: bool)`

## assert_general_guard_imap
- path: vstd/state_machine_internal.rs:477  (fn)
- sig: `pub fn assert_general_guard_imap(b: bool)`

## nat_max
- path: vstd/state_machine_internal.rs:497  (spec fn)
- sig: `pub open spec fn nat_max(a: nat, b: nat) -> nat`

## Seq::update_at_index
- path: vstd/state_machine_internal.rs:508  (spec fn)
- sig: `pub open spec fn update_at_index(self, i: int, a: A) -> Self recommends 0 <= i < self.len(),`

## Map::update_at_index
- path: vstd/state_machine_internal.rs:520  (spec fn)
- sig: `pub open spec fn update_at_index(self, k: K, v: V) -> Self`

## IMap::update_at_index
- path: vstd/state_machine_internal.rs:529  (spec fn)
- sig: `pub open spec fn update_at_index(self, k: K, v: V) -> Self`

## opt_is_none
- path: vstd/state_machine_internal.rs:536  (spec fn)
- sig: `pub open spec fn opt_is_none<V>(a: Option<V>) -> bool`

## opt_ge
- path: vstd/state_machine_internal.rs:542  (spec fn)
- sig: `pub open spec fn opt_ge<V>(a: Option<V>, b: Option<V>) -> bool`

## opt_add
- path: vstd/state_machine_internal.rs:548  (spec fn)
- sig: `pub open spec fn opt_add<V>(a: Option<V>, b: Option<V>) -> Option<V>`

## opt_agree
- path: vstd/state_machine_internal.rs:558  (spec fn)
- sig: `pub open spec fn opt_agree<V>(a: Option<V>, b: Option<V>) -> bool`

## opt_sub
- path: vstd/state_machine_internal.rs:564  (spec fn)
- sig: `pub open spec fn opt_sub<V>(a: Option<V>, b: Option<V>) -> Option<V>`

## alloc::boxed::box_assume_init_into_vec_unsafe
- path: vstd/std_specs/alloc.rs:15  (exec spec, assume_specification)
- sig: `pub assume_specification<T, const N: usize>[ alloc::boxed::box_assume_init_into_vec_unsafe ]( vals: alloc::boxed::Box<core::mem::MaybeUninit<[T; N]>>, ) -> (result: alloc::vec::Vec<T>)`
- requires: vals.mem_contents() is Init,
- ensures: vals.mem_contents() matches MemContents::Init(array) && result@ == array@,

## alloc::intrinsics::write_box_via_move
- path: vstd/std_specs/alloc.rs:26  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ alloc::intrinsics::write_box_via_move ]( _0: alloc::boxed::Box<core::mem::MaybeUninit<T>>, v: T, ) -> (result: alloc::boxed::Box<core::mem::MaybeUninit<T>>)`
- ensures: result.mem_contents() == MemContents::Init(v),

## alloc::boxed::Box::new_uninit
- path: vstd/std_specs/alloc.rs:36  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ alloc::boxed::Box::<T>::new_uninit ]() -> alloc::boxed::Box< core::mem::MaybeUninit<T>, >`

## u8_trailing_zeros
- path: vstd/std_specs/bits.rs:11  (spec fn)
- sig: `pub closed spec fn u8_trailing_zeros(i: u8) -> u32`
- doc: ////////////////////////

## u8_leading_zeros
- path: vstd/std_specs/bits.rs:25  (spec fn)
- sig: `pub closed spec fn u8_leading_zeros(i: u8) -> u32`
- doc: Equivalent to `i.leading_zeros()`.

## u8_trailing_ones
- path: vstd/std_specs/bits.rs:37  (spec fn)
- sig: `pub open spec fn u8_trailing_ones(i: u8) -> u32`
- doc: Equivalent to `i.trailing_ones()`.

## u8_leading_ones
- path: vstd/std_specs/bits.rs:43  (spec fn)
- sig: `pub open spec fn u8_leading_ones(i: u8) -> u32`
- doc: Equivalent to `i.leading_ones()`.

## u8::trailing_zeros
- path: vstd/std_specs/bits.rs:48  (exec spec, assume_specification)
- sig: `pub assume_specification[ u8::trailing_zeros ](i: u8) -> (r: u32)`
- ensures: r == u8_trailing_zeros(i),

## u8::trailing_ones
- path: vstd/std_specs/bits.rs:54  (exec spec, assume_specification)
- sig: `pub assume_specification[ u8::trailing_ones ](i: u8) -> (r: u32)`
- ensures: r == u8_trailing_ones(i),

## u8::leading_zeros
- path: vstd/std_specs/bits.rs:60  (exec spec, assume_specification)
- sig: `pub assume_specification[ u8::leading_zeros ](i: u8) -> (r: u32)`
- ensures: r == u8_leading_zeros(i),

## u8::leading_ones
- path: vstd/std_specs/bits.rs:66  (exec spec, assume_specification)
- sig: `pub assume_specification[ u8::leading_ones ](i: u8) -> (r: u32)`
- ensures: r == u8_leading_ones(i),

## axiom_u8_trailing_zeros
- path: vstd/std_specs/bits.rs:71  (proof fn)
- sig: `pub broadcast proof fn axiom_u8_trailing_zeros(i: u8)`
- ensures: 0 <= #[trigger] u8_trailing_zeros(i) <= 8, i == 0 <==> u8_trailing_zeros(i) == 8, // i^th bit is 1 0 <= u8_trailing_zeros(i) < 8 ==> (i >> u8_trailing_zeros(i) as u8) & 1u8 == 1u8, // trailing bits are 0

## axiom_u8_trailing_ones
- path: vstd/std_specs/bits.rs:103  (proof fn)
- sig: `pub broadcast proof fn axiom_u8_trailing_ones(i: u8)`
- ensures: 0 <= #[trigger] u8_trailing_ones(i) <= 8, i == 0xffu8 <==> u8_trailing_ones(i) == 8, // i^th bit is 0 0 <= u8_trailing_ones(i) < 8 ==> (i >> u8_trailing_ones(i) as u8) & 1u8 == 0u8, // trailing bits are 1

## axiom_u8_leading_zeros
- path: vstd/std_specs/bits.rs:125  (proof fn)
- sig: `pub broadcast proof fn axiom_u8_leading_zeros(i: u8)`
- ensures: 0 <= #[trigger] u8_leading_zeros(i) <= 8, i == 0 <==> u8_leading_zeros(i) == 8, // i^th bit from the left is 1 0 <= u8_leading_zeros(i) < 8 ==> (i >> sub(7u8, u8_leading_zeros(i) as u8)) & 1u8 != 0u8, // leading bits are 0

## axiom_u8_leading_ones
- path: vstd/std_specs/bits.rs:155  (proof fn)
- sig: `pub broadcast proof fn axiom_u8_leading_ones(i: u8)`
- ensures: 0 <= #[trigger] u8_leading_ones(i) <= 8, i == 0xffu8 <==> u8_leading_ones(i) == 8, // i^th bit from the left is 0 0 <= u8_leading_ones(i) < 8 ==> (i >> sub(7u8, u8_leading_ones(i) as u8)) & 1u8 == 0u8, (!i) >> sub(8, u8_leading_ones(i) as u8) == 0,

## u16_trailing_zeros
- path: vstd/std_specs/bits.rs:181  (spec fn)
- sig: `pub closed spec fn u16_trailing_zeros(i: u16) -> u32`
- doc: ////////////////////////

## u16_leading_zeros
- path: vstd/std_specs/bits.rs:195  (spec fn)
- sig: `pub closed spec fn u16_leading_zeros(i: u16) -> u32`
- doc: Equivalent to `i.leading_zeros()`.

## u16_trailing_ones
- path: vstd/std_specs/bits.rs:207  (spec fn)
- sig: `pub open spec fn u16_trailing_ones(i: u16) -> u32`
- doc: Equivalent to `i.trailing_ones()`.

## u16_leading_ones
- path: vstd/std_specs/bits.rs:213  (spec fn)
- sig: `pub open spec fn u16_leading_ones(i: u16) -> u32`
- doc: Equivalent to `i.leading_ones()`.

## u16::trailing_zeros
- path: vstd/std_specs/bits.rs:218  (exec spec, assume_specification)
- sig: `pub assume_specification[ u16::trailing_zeros ](i: u16) -> (r: u32)`
- ensures: r == u16_trailing_zeros(i),

## u16::trailing_ones
- path: vstd/std_specs/bits.rs:224  (exec spec, assume_specification)
- sig: `pub assume_specification[ u16::trailing_ones ](i: u16) -> (r: u32)`
- ensures: r == u16_trailing_ones(i),

## u16::leading_zeros
- path: vstd/std_specs/bits.rs:230  (exec spec, assume_specification)
- sig: `pub assume_specification[ u16::leading_zeros ](i: u16) -> (r: u32)`
- ensures: r == u16_leading_zeros(i),

## u16::leading_ones
- path: vstd/std_specs/bits.rs:236  (exec spec, assume_specification)
- sig: `pub assume_specification[ u16::leading_ones ](i: u16) -> (r: u32)`
- ensures: r == u16_leading_ones(i),

## axiom_u16_trailing_zeros
- path: vstd/std_specs/bits.rs:241  (proof fn)
- sig: `pub broadcast proof fn axiom_u16_trailing_zeros(i: u16)`
- ensures: 0 <= #[trigger] u16_trailing_zeros(i) <= 16, i == 0 <==> u16_trailing_zeros(i) == 16, // i^th bit is 1 0 <= u16_trailing_zeros(i) < 16 ==> (i >> u16_trailing_zeros(i) as u16) & 1u16 == 1u16, // trailing bits are 0

## axiom_u16_trailing_ones
- path: vstd/std_specs/bits.rs:274  (proof fn)
- sig: `pub broadcast proof fn axiom_u16_trailing_ones(i: u16)`
- ensures: 0 <= #[trigger] u16_trailing_ones(i) <= 16, i == 0xffffu16 <==> u16_trailing_ones(i) == 16, // i^th bit is 0 0 <= u16_trailing_ones(i) < 16 ==> (i >> u16_trailing_ones(i) as u16) & 1u16 == 0u16, // trailing bits are 1

## axiom_u16_leading_zeros
- path: vstd/std_specs/bits.rs:297  (proof fn)
- sig: `pub broadcast proof fn axiom_u16_leading_zeros(i: u16)`
- ensures: 0 <= #[trigger] u16_leading_zeros(i) <= 16, i == 0 <==> u16_leading_zeros(i) == 16, // i^th bit from the left is 1 0 <= u16_leading_zeros(i) < 16 ==> (i >> sub(15u16, u16_leading_zeros(i) as u16)) & 1u16 != 0u16,

## axiom_u16_leading_ones
- path: vstd/std_specs/bits.rs:329  (proof fn)
- sig: `pub broadcast proof fn axiom_u16_leading_ones(i: u16)`
- ensures: 0 <= #[trigger] u16_leading_ones(i) <= 16, i == 0xffffu16 <==> u16_leading_ones(i) == 16, // i^th bit from the left is 0 0 <= u16_leading_ones(i) < 16 ==> (i >> sub(15u16, u16_leading_ones(i) as u16)) & 1u16 == 0u16,

## u32_trailing_zeros
- path: vstd/std_specs/bits.rs:357  (spec fn)
- sig: `pub closed spec fn u32_trailing_zeros(i: u32) -> u32`
- doc: ////////////////////////

## u32_leading_zeros
- path: vstd/std_specs/bits.rs:371  (spec fn)
- sig: `pub closed spec fn u32_leading_zeros(i: u32) -> u32`
- doc: Equivalent to `i.leading_zeros()`.

## u32_trailing_ones
- path: vstd/std_specs/bits.rs:383  (spec fn)
- sig: `pub open spec fn u32_trailing_ones(i: u32) -> u32`
- doc: Equivalent to `i.trailing_ones()`.

## u32_leading_ones
- path: vstd/std_specs/bits.rs:389  (spec fn)
- sig: `pub open spec fn u32_leading_ones(i: u32) -> u32`
- doc: Equivalent to `i.leading_ones()`.

## u32::trailing_zeros
- path: vstd/std_specs/bits.rs:394  (exec spec, assume_specification)
- sig: `pub assume_specification[ u32::trailing_zeros ](i: u32) -> (r: u32)`
- ensures: r == u32_trailing_zeros(i),

## u32::trailing_ones
- path: vstd/std_specs/bits.rs:400  (exec spec, assume_specification)
- sig: `pub assume_specification[ u32::trailing_ones ](i: u32) -> (r: u32)`
- ensures: r == u32_trailing_ones(i),

## u32::leading_zeros
- path: vstd/std_specs/bits.rs:406  (exec spec, assume_specification)
- sig: `pub assume_specification[ u32::leading_zeros ](i: u32) -> (r: u32)`
- ensures: r == u32_leading_zeros(i),

## u32::leading_ones
- path: vstd/std_specs/bits.rs:412  (exec spec, assume_specification)
- sig: `pub assume_specification[ u32::leading_ones ](i: u32) -> (r: u32)`
- ensures: r == u32_leading_ones(i),

## axiom_u32_trailing_zeros
- path: vstd/std_specs/bits.rs:417  (proof fn)
- sig: `pub broadcast proof fn axiom_u32_trailing_zeros(i: u32)`
- ensures: 0 <= #[trigger] u32_trailing_zeros(i) <= 32, i == 0 <==> u32_trailing_zeros(i) == 32, // i^th bit is 1 0 <= u32_trailing_zeros(i) < 32 ==> (i >> u32_trailing_zeros(i) as u32) & 1u32 == 1u32, // trailing bits are 0

## axiom_u32_trailing_ones
- path: vstd/std_specs/bits.rs:450  (proof fn)
- sig: `pub broadcast proof fn axiom_u32_trailing_ones(i: u32)`
- ensures: 0 <= #[trigger] u32_trailing_ones(i) <= 32, i == 0xffff_ffffu32 <==> u32_trailing_ones(i) == 32, // i^th bit is 0 0 <= u32_trailing_ones(i) < 32 ==> (i >> u32_trailing_ones(i) as u32) & 1u32 == 0u32, // trailing bits are 1

## axiom_u32_leading_zeros
- path: vstd/std_specs/bits.rs:473  (proof fn)
- sig: `pub broadcast proof fn axiom_u32_leading_zeros(i: u32)`
- ensures: 0 <= #[trigger] u32_leading_zeros(i) <= 32, i == 0 <==> u32_leading_zeros(i) == 32, // i^th bit from the left is 1 0 <= u32_leading_zeros(i) < 32 ==> (i >> sub(31u32, u32_leading_zeros(i) as u32)) & 1u32 != 0u32,

## axiom_u32_leading_ones
- path: vstd/std_specs/bits.rs:505  (proof fn)
- sig: `pub broadcast proof fn axiom_u32_leading_ones(i: u32)`
- ensures: 0 <= #[trigger] u32_leading_ones(i) <= 32, i == 0xffff_ffffu32 <==> u32_leading_ones(i) == 32, // i^th bit from the left is 0 0 <= u32_leading_ones(i) < 32 ==> (i >> sub(31u32, u32_leading_ones(i) as u32)) & 1u32 == 0u32,

## u64_trailing_zeros
- path: vstd/std_specs/bits.rs:533  (spec fn)
- sig: `pub closed spec fn u64_trailing_zeros(i: u64) -> u32`
- doc: ////////////////////////

## u64_leading_zeros
- path: vstd/std_specs/bits.rs:548  (spec fn)
- sig: `pub open spec fn u64_leading_zeros(i: u64) -> int`
- doc: Equivalent to `i.leading_zeros()`.

## u64_trailing_ones
- path: vstd/std_specs/bits.rs:560  (spec fn)
- sig: `pub open spec fn u64_trailing_ones(i: u64) -> u32`
- doc: Equivalent to `i.trailing_ones()`.

## u64_leading_ones
- path: vstd/std_specs/bits.rs:566  (spec fn)
- sig: `pub open spec fn u64_leading_ones(i: u64) -> u32`
- doc: Equivalent to `i.leading_ones()`.

## u64::trailing_zeros
- path: vstd/std_specs/bits.rs:571  (exec spec, assume_specification)
- sig: `pub assume_specification[ u64::trailing_zeros ](i: u64) -> (r: u32)`
- ensures: r == u64_trailing_zeros(i),

## u64::trailing_ones
- path: vstd/std_specs/bits.rs:577  (exec spec, assume_specification)
- sig: `pub assume_specification[ u64::trailing_ones ](i: u64) -> (r: u32)`
- ensures: r == u64_trailing_ones(i),

## u64::leading_zeros
- path: vstd/std_specs/bits.rs:583  (exec spec, assume_specification)
- sig: `pub assume_specification[ u64::leading_zeros ](i: u64) -> (r: u32)`
- ensures: r as int == u64_leading_zeros(i),

## u64::leading_ones
- path: vstd/std_specs/bits.rs:589  (exec spec, assume_specification)
- sig: `pub assume_specification[ u64::leading_ones ](i: u64) -> (r: u32)`
- ensures: r == u64_leading_ones(i),

## axiom_u64_trailing_zeros
- path: vstd/std_specs/bits.rs:594  (proof fn)
- sig: `pub broadcast proof fn axiom_u64_trailing_zeros(i: u64)`
- ensures: 0 <= #[trigger] u64_trailing_zeros(i) <= 64, i == 0 <==> u64_trailing_zeros(i) == 64, // i^th bit is 1 0 <= u64_trailing_zeros(i) < 64 ==> (i >> u64_trailing_zeros(i) as u64) & 1u64 == 1u64, // trailing bits are 0

## axiom_u64_trailing_ones
- path: vstd/std_specs/bits.rs:627  (proof fn)
- sig: `pub broadcast proof fn axiom_u64_trailing_ones(i: u64)`
- ensures: 0 <= #[trigger] u64_trailing_ones(i) <= 64, i == 0xffff_ffff_ffff_ffffu64 <==> u64_trailing_ones(i) == 64, // i^th bit is 0 0 <= u64_trailing_ones(i) < 64 ==> (i >> u64_trailing_ones(i) as u64) & 1u64 == 0u64, // trailing bits are 1

## axiom_u64_leading_zeros
- path: vstd/std_specs/bits.rs:650  (proof fn)
- sig: `pub broadcast proof fn axiom_u64_leading_zeros(i: u64)`
- ensures: 0 <= #[trigger] u64_leading_zeros(i) <= 64, i == 0 <==> u64_leading_zeros(i) == 64, // i^th bit from the left is 1 0 <= u64_leading_zeros(i) < 64 ==> (i >> sub(63u64, u64_leading_zeros(i) as u64)) & 1u64 != 0u64,

## axiom_u64_leading_ones
- path: vstd/std_specs/bits.rs:683  (proof fn)
- sig: `pub broadcast proof fn axiom_u64_leading_ones(i: u64)`
- ensures: 0 <= #[trigger] u64_leading_ones(i) <= 64, i == 0xffff_ffff_ffff_ffffu64 <==> u64_leading_ones(i) == 64, // i^th bit from the left is 0 0 <= u64_leading_ones(i) < 64 ==> (i >> sub(63u64, u64_leading_ones(i) as u64)) & 1u64 == 0u64,

## group_bits_axioms
- path: vstd/std_specs/bits.rs  (broadcast group)
- members: axiom_u8_trailing_zeros axiom_u8_trailing_ones axiom_u8_leading_zeros axiom_u8_leading_ones axiom_u16_trailing_zeros axiom_u16_trailing_ones axiom_u16_leading_zeros axiom_u16_leading_ones axiom_u32_trailing_zeros axiom_u32_trailing_ones axiom_u32_leading_zeros axiom_u32_leading_ones axiom_u64_trailing_zeros axiom_u64_trailing_ones axiom_u64_leading_zeros axiom_u64_leading_ones

## key_obeys_cmp_spec
- path: vstd/std_specs/btree.rs:36  (spec fn)
- sig: `pub uninterp spec fn key_obeys_cmp_spec<Key: ?Sized>() -> bool`
- doc: Whether the `Key` type obeys the cmp spec, required for [`BTreeMap`]

## increasing_seq
- path: vstd/std_specs/btree.rs:48  (spec fn)
- sig: `pub uninterp spec fn increasing_seq<K>(s: Seq<K>) -> bool`
- doc: Whether a sequence is ordered in increasing order.

## into_iter_keys
- path: vstd/std_specs/btree.rs:69  (spec fn)
- sig: `pub uninterp spec fn into_iter_keys<'a, Key, Value>(i: Keys<'a, Key, Value>) -> Seq<Key>`

## into_iter_values
- path: vstd/std_specs/btree.rs:107  (spec fn)
- sig: `pub uninterp spec fn into_iter_values<'a, Key, Value>(i: Values<'a, Key, Value>) -> Seq<Value>`

## into_iter
- path: vstd/std_specs/btree.rs:145  (spec fn)
- sig: `pub uninterp spec fn into_iter<'a, Key, Value>(i: btree_map::Iter<'a, Key, Value>) -> Seq< (Key, Value), >`

## spec_btree_map_iter
- path: vstd/std_specs/btree.rs:182  (spec fn)
- sig: `pub uninterp spec fn spec_btree_map_iter<'a, Key, Value, A: Allocator + Clone>( m: &'a BTreeMap<Key, Value, A>, ) -> (r: btree_map::Iter<'a, Key, Value>)`

## BTreeMap::iter
- path: vstd/std_specs/btree.rs:204  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, Key, Value, A: Allocator + Clone>[ BTreeMap::<Key, Value, A>::iter ]( m: &'a BTreeMap<Key, Value, A>, ) -> (iter: btree_map::Iter<'a, Key, Value>)`
- ensures: key_obeys_cmp_spec::<Key>() ==> { &&& iter == spec_btree_map_iter(m) &&& iter.remaining().no_duplicates() &&& IteratorSpec::decrease(&iter) is Some &&& IteratorSpec::initial_value_relation(&iter, &iter)

## btree_map_deep_view_impl
- path: vstd/std_specs/btree.rs:270  (spec fn)
- sig: `pub open spec fn btree_map_deep_view_impl<Key: DeepView, Value: DeepView, A: Allocator + Clone>( m: BTreeMap<Key, Value, A>,`
- doc: The actual definition of `BTreeMap::deep_view`.

## lemma_btree_map_deepview_dom
- path: vstd/std_specs/btree.rs:283  (proof fn)
- sig: `pub broadcast proof fn lemma_btree_map_deepview_dom<K: DeepView, V: DeepView>(m: BTreeMap<K, V>)`
- ensures: #[trigger] m.deep_view().dom() == m@.dom().map(|k: K| k.deep_view()),

## lemma_btree_map_deepview_properties
- path: vstd/std_specs/btree.rs:294  (proof fn)
- sig: `pub broadcast proof fn lemma_btree_map_deepview_properties<K: DeepView, V: DeepView>( m: BTreeMap<K, V>, )`
- requires: crate::relations::injective(|k: K| k.deep_view()),
- ensures: #![trigger m.deep_view()] // all elements in m.view() are present in m.deep_view() forall|k: K| #[trigger] m@.contains_key(k) ==> m.deep_view().contains_key(k.deep_view()) && m.deep_view()[k.deep_view()] == m@[k].deep_view(),

## lemma_btree_map_deepview_values
- path: vstd/std_specs/btree.rs:327  (proof fn)
- sig: `pub broadcast proof fn lemma_btree_map_deepview_values<K: DeepView, V: DeepView>(m: BTreeMap<K, V>)`
- requires: crate::relations::injective(|k: K| k.deep_view()),
- ensures: #[trigger] m.deep_view().values() =~= m@.values().map(|v: V| v.deep_view()),

## spec_btree_map_len
- path: vstd/std_specs/btree.rs:364  (spec fn)
- sig: `pub uninterp spec fn spec_btree_map_len<Key, Value, A: Allocator + Clone>( m: &BTreeMap<Key, Value, A>, ) -> usize`

## BTreeMap::len
- path: vstd/std_specs/btree.rs:376  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, Value, A: Allocator + Clone>[ BTreeMap::<Key, Value, A>::len ]( m: &BTreeMap<Key, Value, A>, ) -> (len: usize)`
- ensures: len == spec_btree_map_len(m),

## BTreeMap::is_empty
- path: vstd/std_specs/btree.rs:383  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, Value, A: Allocator + Clone>[ BTreeMap::<Key, Value, A>::is_empty ]( m: &BTreeMap<Key, Value, A>, ) -> (res: bool)`
- ensures: res == m@.is_empty(),

## BTreeMap::new
- path: vstd/std_specs/btree.rs:399  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, Value>[ BTreeMap::<Key, Value>::new ]() -> (m: BTreeMap<Key, Value>)`
- ensures: m@ == Map::<Key, Value>::empty(),

## BTreeMap::default
- path: vstd/std_specs/btree.rs:404  (exec spec, assume_specification)
- trait: core::default::Default
- sig: `pub assume_specification<K, V>[ <BTreeMap<K, V> as core::default::Default>::default ]() -> (m: BTreeMap<K, V>)`
- ensures: m@ == Map::<K, V>::empty(),

## contains_borrowed_key
- path: vstd/std_specs/btree.rs:439  (spec fn)
- sig: `pub uninterp spec fn contains_borrowed_key<Key, Value, Q: ?Sized>( m: Map<Key, Value>, k: &Q, ) -> bool`

## maps_borrowed_key_to_value
- path: vstd/std_specs/btree.rs:483  (spec fn)
- sig: `pub uninterp spec fn maps_borrowed_key_to_value<Key, Value, Q: ?Sized>( m: Map<Key, Value>, k: &Q, v: Value, ) -> bool`

## borrowed_key_removed
- path: vstd/std_specs/btree.rs:535  (spec fn)
- sig: `pub uninterp spec fn borrowed_key_removed<Key, Value, Q: ?Sized>( old_m: Map<Key, Value>, new_m: Map<Key, Value>, k: &Q, ) -> bool`

## BTreeMap::clear
- path: vstd/std_specs/btree.rs:579  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, Value, A: Allocator + Clone>[ BTreeMap::<Key, Value, A>::clear ]( m: &mut BTreeMap<Key, Value, A>, )`
- ensures: final(m)@ == Map::<Key, Value>::empty(),

## spec_keys_iter
- path: vstd/std_specs/btree.rs:592  (spec fn)
- sig: `pub uninterp spec fn spec_keys_iter<'a, Key, Value, A: Allocator + Clone>( m: &'a BTreeMap<Key, Value, A>, ) -> (keys: Keys<'a, Key, Value>)`

## axiom_spec_keys_iter
- path: vstd/std_specs/btree.rs:596  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_keys_iter<'a, Key, Value, A: Allocator + Clone>( m: &'a BTreeMap<Key, Value, A>, )`
- ensures: (#[trigger] spec_keys_iter(m).remaining()).unref().to_set() == m@.dom(), spec_keys_iter(m).remaining().no_duplicates(), spec_keys_iter(m).remaining().len() == m@.dom().len(), increasing_seq(spec_keys_iter(m).remaining()),

## BTreeMap::keys
- path: vstd/std_specs/btree.rs:609  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, Key, Value, A: Allocator + Clone>[ BTreeMap::<Key, Value, A>::keys ]( m: &'a BTreeMap<Key, Value, A>, ) -> (keys: Keys<'a, Key, Value>)`
- ensures: key_obeys_cmp_spec::<Key>() ==> { &&& keys == spec_keys_iter(m) &&& IteratorSpec::decrease(&keys) is Some &&& IteratorSpec::initial_value_relation(&keys, &keys) },

## spec_values_iter
- path: vstd/std_specs/btree.rs:626  (spec fn)
- sig: `pub uninterp spec fn spec_values_iter<'a, Key, Value, A: Allocator + Clone>( m: &'a BTreeMap<Key, Value, A>, ) -> (values: Values<'a, Key, Value>)`

## axiom_spec_values_iter
- path: vstd/std_specs/btree.rs:630  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_values_iter<'a, Key, Value, A: Allocator + Clone>( m: &'a BTreeMap<Key, Value, A>, )`
- ensures: (#[trigger] spec_values_iter(m).remaining()).unref().to_set() == m@.values(), spec_values_iter(m).remaining().len() == m@.dom().len(),

## BTreeMap::values
- path: vstd/std_specs/btree.rs:641  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, Key, Value, A: Allocator + Clone>[ BTreeMap::<Key, Value, A>::values ]( m: &'a BTreeMap<Key, Value, A>, ) -> (values: Values<'a, Key, Value>)`
- ensures: key_obeys_cmp_spec::<Key>() ==> { &&& values == spec_values_iter(m) &&& IteratorSpec::decrease(&values) is Some &&& IteratorSpec::initial_value_relation(&values, &values) &&& exists|key_seq: Seq<Key>|

## into_iter_btree_keys
- path: vstd/std_specs/btree.rs:675  (spec fn)
- sig: `pub uninterp spec fn into_iter_btree_keys<'a, Key>(i: btree_set::Iter::<'a, Key>) -> Seq<Key>`

## spec_btree_set_len
- path: vstd/std_specs/btree.rs:731  (spec fn)
- sig: `pub uninterp spec fn spec_btree_set_len<Key, A: Allocator + Clone>(m: &BTreeSet<Key, A>) -> usize`

## BTreeSet::len
- path: vstd/std_specs/btree.rs:739  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, A: Allocator + Clone>[ BTreeSet::<Key, A>::len ]( m: &BTreeSet<Key, A>, ) -> (len: usize)`
- ensures: len == spec_btree_set_len(m),

## BTreeSet::is_empty
- path: vstd/std_specs/btree.rs:746  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, A: Allocator + Clone>[ BTreeSet::<Key, A>::is_empty ]( m: &BTreeSet<Key, A>, ) -> (res: bool)`
- ensures: res == m@.is_empty(),

## BTreeSet::clone
- path: vstd/std_specs/btree.rs:753  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification<K: Clone, A: Allocator + Clone>[ <BTreeSet::<K, A> as Clone>::clone ]( this: &BTreeSet<K, A>, ) -> (other: BTreeSet<K, A>)`
- ensures: other@ == this@,

## BTreeSet::new
- path: vstd/std_specs/btree.rs:760  (exec spec, assume_specification)
- sig: `pub assume_specification<Key>[ BTreeSet::<Key>::new ]() -> (m: BTreeSet<Key>)`
- ensures: m@ == Set::<Key>::empty(),

## BTreeSet::default
- path: vstd/std_specs/btree.rs:765  (exec spec, assume_specification)
- trait: core::default::Default
- sig: `pub assume_specification<T>[ <BTreeSet<T> as core::default::Default>::default ]() -> (m: BTreeSet< T, >)`
- ensures: m@ == Set::<T>::empty(),

## BTreeSet::insert
- path: vstd/std_specs/btree.rs:772  (exec spec, assume_specification)
- sig: `pub assume_specification<Key: Ord, A: Allocator + Clone>[ BTreeSet::<Key, A>::insert ]( m: &mut BTreeSet<Key, A>, k: Key, ) -> (result: bool)`
- ensures: obeys_cmp::<Key>() ==> { &&& final(m)@ == old(m)@.insert(k) &&& result == !old(m)@.contains(k) },

## set_contains_borrowed_key
- path: vstd/std_specs/btree.rs:797  (spec fn)
- sig: `pub uninterp spec fn set_contains_borrowed_key<Key, Q: ?Sized>(m: Set<Key>, k: &Q) -> bool`

## sets_borrowed_key_to_key
- path: vstd/std_specs/btree.rs:834  (spec fn)
- sig: `pub uninterp spec fn sets_borrowed_key_to_key<Key, Q: ?Sized>(m: Set<Key>, k: &Q, v: &Key) -> bool`

## sets_differ_by_borrowed_key
- path: vstd/std_specs/btree.rs:875  (spec fn)
- sig: `pub uninterp spec fn sets_differ_by_borrowed_key<Key, Q: ?Sized>( old_m: Set<Key>, new_m: Set<Key>, k: &Q, ) -> bool`

## BTreeSet::clear
- path: vstd/std_specs/btree.rs:905  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, A: Allocator + Clone>[ BTreeSet::<Key, A>::clear ]( m: &mut BTreeSet<Key, A>, ) where A: Clone`
- ensures: final(m)@ == Set::<Key>::empty(),

## spec_btree_keys_iter
- path: vstd/std_specs/btree.rs:918  (spec fn)
- sig: `pub uninterp spec fn spec_btree_keys_iter<'a, Key, A: Allocator + Clone>( m: &'a BTreeSet<Key, A>, ) -> (r: btree_set::Iter<'a, Key>)`

## axiom_spec_btree_keys_iter
- path: vstd/std_specs/btree.rs:922  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_btree_keys_iter<'a, Key, A: Allocator + Clone>( m: &'a BTreeSet<Key, A>, )`
- ensures: (#[trigger] spec_btree_keys_iter(m).remaining()).unref().to_set() == m@, spec_btree_keys_iter(m).remaining().no_duplicates(), spec_btree_keys_iter(m).remaining().len() == m@.len(), increasing_seq(spec_btree_keys_iter(m).remaining()),

## BTreeSet::iter
- path: vstd/std_specs/btree.rs:935  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, Key, A: Allocator + Clone>[ BTreeSet::<Key, A>::iter ]( m: &'a BTreeSet<Key, A>, ) -> (r: btree_set::Iter<'a, Key>)`
- ensures: key_obeys_cmp_spec::<Key>() ==> { &&& r == spec_btree_keys_iter(m) &&& IteratorSpec::decrease(&r) is Some &&& IteratorSpec::initial_value_relation(&r, &r) },

## group_btree_axioms
- path: vstd/std_specs/btree.rs  (broadcast group)
- members: axiom_key_obeys_cmp_spec_meaning axiom_increasing_seq_meaning axiom_box_key_removed axiom_contains_deref_key axiom_contains_box axiom_deref_key_removed axiom_maps_deref_key_to_value axiom_maps_box_key_to_value axiom_btree_map_deepview_borrow axiom_spec_btree_map_len axiom_set_box_key_removed axiom_set_contains_deref_key axiom_set_contains_box axiom_set_deref_key_removed axiom_set_deref_key_to_value axiom_set_box_key_to_value axiom_spec_btree_set_len axiom_spec_btree_keys_iter axiom_spec_btree_map_iter axiom_spec_keys_iter axiom_spec_values_iter axiom_btree_map_decreases axiom_btree_set_decreases

## ex_clone_clone_from
- path: vstd/std_specs/clone.rs:20  (fn)
- sig: `pub fn ex_clone_clone_from<T: Clone>(a: &mut T, b: &T)`

## bool::clone
- path: vstd/std_specs/clone.rs:26  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification[ <bool as Clone>::clone ](b: &bool) -> (res: bool)`

## char::clone
- path: vstd/std_specs/clone.rs:31  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification[ <char as Clone>::clone ](c: &char) -> (res: char)`

## &'b T::clone
- path: vstd/std_specs/clone.rs:37  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification<'b, T: core::marker::PointeeSized, 'a>[ <&'b T as Clone>::clone ]( b: &'a &'b T, ) -> (res: &'b T)`
- ensures: res == b,

## <[T;N
- path: vstd/std_specs/clone.rs:44  (exec spec, assume_specification)
- sig: `pub assume_specification<T: Clone, const N: usize>[ <[T; N] as Clone>::clone ](a: &[T; N]) -> (res: [T; N])`
- ensures: forall|i| #![all_triggers] 0 <= i < N ==> cloned::<T>(a@[i], res@[i]), a@ =~= res@ ==> a@ == res@,

## ex_bool_clone_from
- path: vstd/std_specs/clone.rs:53  (fn)
- sig: `pub fn ex_bool_clone_from(dest: &mut bool, source: &bool)`
- ensures: *dest == source,

## Tracked::clone
- path: vstd/std_specs/clone.rs:61  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification<T: Copy>[ <Tracked<T> as Clone>::clone ](b: &Tracked<T>) -> (res: Tracked< T, >)`
- ensures: res == b,

## Ghost::clone
- path: vstd/std_specs/clone.rs:68  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification<T>[ <Ghost<T> as Clone>::clone ](b: &Ghost<T>) -> (res: Ghost<T>)`
- ensures: res == b,

## bool::eq
- path: vstd/std_specs/cmp.rs:250  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification[ <bool as PartialEq<bool>>::eq ](x: &bool, y: &bool) -> bool`

## bool::ne
- path: vstd/std_specs/cmp.rs:252  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification[ <bool as PartialEq<bool>>::ne ](x: &bool, y: &bool) -> bool`

## eq_ensures
- path: vstd/std_specs/cmp.rs:264  (spec fn)
- sig: `pub uninterp spec fn eq_ensures<A>(x: A, y: A, o: bool) -> bool`

## ne_ensures
- path: vstd/std_specs/cmp.rs:266  (spec fn)
- sig: `pub uninterp spec fn ne_ensures<A>(x: A, y: A, o: bool) -> bool`

## partial_cmp_ensures
- path: vstd/std_specs/cmp.rs:268  (spec fn)
- sig: `pub uninterp spec fn partial_cmp_ensures<A>(x: A, y: A, o: Option<Ordering>) -> bool`

## lt_ensures
- path: vstd/std_specs/cmp.rs:270  (spec fn)
- sig: `pub uninterp spec fn lt_ensures<A>(x: A, y: A, o: bool) -> bool`

## le_ensures
- path: vstd/std_specs/cmp.rs:272  (spec fn)
- sig: `pub uninterp spec fn le_ensures<A>(x: A, y: A, o: bool) -> bool`

## gt_ensures
- path: vstd/std_specs/cmp.rs:274  (spec fn)
- sig: `pub uninterp spec fn gt_ensures<A>(x: A, y: A, o: bool) -> bool`

## ge_ensures
- path: vstd/std_specs/cmp.rs:276  (spec fn)
- sig: `pub uninterp spec fn ge_ensures<A>(x: A, y: A, o: bool) -> bool`

## f32::eq
- path: vstd/std_specs/cmp.rs:279  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification[ <f32 as PartialEq<f32>>::eq ](x: &f32, y: &f32) -> (o: bool)`
- ensures: eq_ensures::<f32>(*x, *y, o),

## f32::ne
- path: vstd/std_specs/cmp.rs:285  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification[ <f32 as PartialEq<f32>>::ne ](x: &f32, y: &f32) -> (o: bool)`
- ensures: ne_ensures::<f32>(*x, *y, o),

## f32::partial_cmp
- path: vstd/std_specs/cmp.rs:290  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification[ <f32 as PartialOrd<f32>>::partial_cmp ](x: &f32, y: &f32) -> (o: Option<Ordering>)`
- ensures: partial_cmp_ensures::<f32>(*x, *y, o),

## f32::lt
- path: vstd/std_specs/cmp.rs:295  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification[ <f32 as PartialOrd<f32>>::lt ](x: &f32, y: &f32) -> (o: bool)`
- ensures: lt_ensures::<f32>(*x, *y, o),

## f32::le
- path: vstd/std_specs/cmp.rs:300  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification[ <f32 as PartialOrd<f32>>::le ](x: &f32, y: &f32) -> (o: bool)`
- ensures: le_ensures::<f32>(*x, *y, o),

## f32::gt
- path: vstd/std_specs/cmp.rs:305  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification[ <f32 as PartialOrd<f32>>::gt ](x: &f32, y: &f32) -> (o: bool)`
- ensures: gt_ensures::<f32>(*x, *y, o),

## f32::ge
- path: vstd/std_specs/cmp.rs:310  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification[ <f32 as PartialOrd<f32>>::ge ](x: &f32, y: &f32) -> (o: bool)`
- ensures: ge_ensures::<f32>(*x, *y, o),

## f64::eq
- path: vstd/std_specs/cmp.rs:316  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification[ <f64 as PartialEq<f64>>::eq ](x: &f64, y: &f64) -> (o: bool)`
- ensures: eq_ensures::<f64>(*x, *y, o),

## f64::ne
- path: vstd/std_specs/cmp.rs:322  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification[ <f64 as PartialEq<f64>>::ne ](x: &f64, y: &f64) -> (o: bool)`
- ensures: ne_ensures::<f64>(*x, *y, o),

## f64::partial_cmp
- path: vstd/std_specs/cmp.rs:327  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification[ <f64 as PartialOrd<f64>>::partial_cmp ](x: &f64, y: &f64) -> (o: Option<Ordering>)`
- ensures: partial_cmp_ensures::<f64>(*x, *y, o),

## f64::lt
- path: vstd/std_specs/cmp.rs:332  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification[ <f64 as PartialOrd<f64>>::lt ](x: &f64, y: &f64) -> (o: bool)`
- ensures: lt_ensures::<f64>(*x, *y, o),

## f64::le
- path: vstd/std_specs/cmp.rs:337  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification[ <f64 as PartialOrd<f64>>::le ](x: &f64, y: &f64) -> (o: bool)`
- ensures: le_ensures::<f64>(*x, *y, o),

## f64::gt
- path: vstd/std_specs/cmp.rs:342  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification[ <f64 as PartialOrd<f64>>::gt ](x: &f64, y: &f64) -> (o: bool)`
- ensures: gt_ensures::<f64>(*x, *y, o),

## f64::ge
- path: vstd/std_specs/cmp.rs:347  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification[ <f64 as PartialOrd<f64>>::ge ](x: &f64, y: &f64) -> (o: bool)`
- ensures: ge_ensures::<f64>(*x, *y, o),

## &'a A::eq
- path: vstd/std_specs/cmp.rs:367  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification<'_0, 'a, A: PointeeSized, B: PointeeSized>[ <&'a A as PartialEq<&B>>::eq ]( a: &&'a A, b: &&B, ) -> bool where A: PartialEq<B>,`

## &'a A::ne
- path: vstd/std_specs/cmp.rs:375  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification<'_0, 'a, A: PointeeSized, B: PointeeSized>[ <&'a A as PartialEq<&B>>::ne ]( a: &&'a A, b: &&B, ) -> bool where A: PartialEq<B>,`

## &'a A::partial_cmp
- path: vstd/std_specs/cmp.rs:396  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification<'_0, 'a, A: PointeeSized, B: PointeeSized>[ <&'a A as PartialOrd<&B>>::partial_cmp ]( a: &&'a A, b: &&B, ) -> Option<core::cmp::Ordering> where A: PartialOrd<B>,`

## &'a A::lt
- path: vstd/std_specs/cmp.rs:404  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification<'_0, 'a, A: PointeeSized, B: PointeeSized>[ <&'a A as PartialOrd<&B>>::lt ]( a: &&'a A, b: &&B, ) -> bool where A: PartialOrd<B>,`

## &'a A::le
- path: vstd/std_specs/cmp.rs:412  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification<'_0, 'a, A: PointeeSized, B: PointeeSized>[ <&'a A as PartialOrd<&B>>::le ]( a: &&'a A, b: &&B, ) -> bool where A: PartialOrd<B>,`

## &'a A::gt
- path: vstd/std_specs/cmp.rs:420  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification<'_0, 'a, A: PointeeSized, B: PointeeSized>[ <&'a A as PartialOrd<&B>>::gt ]( a: &&'a A, b: &&B, ) -> bool where A: PartialOrd<B>,`

## &'a A::ge
- path: vstd/std_specs/cmp.rs:428  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification<'_0, 'a, A: PointeeSized, B: PointeeSized>[ <&'a A as PartialOrd<&B>>::ge ]( a: &&'a A, b: &&B, ) -> bool where A: PartialOrd<B>,`

## &'a A::cmp
- path: vstd/std_specs/cmp.rs:446  (exec spec, assume_specification)
- trait: Ord
- sig: `pub assume_specification<'a, A: PointeeSized + Ord>[ <&'a A as Ord>::cmp ]( a: &&'a A, b: &&'a A, ) -> core::cmp::Ordering`

## Result::branch
- path: vstd/std_specs/control_flow.rs:18  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E>[ Result::<T, E>::branch ](result: Result<T, E>) -> (cf: ControlFlow< <Result<T, E> as Try>::Residual, <Result<T, E> as Try>::Output, >)`
- ensures: cf == match result { Ok(v) => ControlFlow::Continue(v), Err(e) => ControlFlow::Break(Err(e)), },

## Option::branch
- path: vstd/std_specs/control_flow.rs:30  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::<T>::branch ](option: Option<T>) -> (cf: ControlFlow< <Option<T> as Try>::Residual, <Option<T> as Try>::Output, >)`
- ensures: cf == match option { Some(v) => ControlFlow::Continue(v), None => ControlFlow::Break(None), },

## Option::from_residual
- path: vstd/std_specs/control_flow.rs:42  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::<T>::from_residual ](option: Option<Infallible>) -> (option2: Option<T>)`
- ensures: option.is_none(), option2.is_none(),

## spec_from
- path: vstd/std_specs/control_flow.rs:50  (spec fn)
- sig: `pub uninterp spec fn spec_from<S, T>(value: T, ret: S) -> bool`

## spec_from_blanket_identity
- path: vstd/std_specs/control_flow.rs:52  (proof fn)
- sig: `pub broadcast proof fn spec_from_blanket_identity<T>(t: T, s: T)`
- ensures: #[trigger] spec_from::<T, T>(t, s) ==> t == s,

## Result::from_residual
- path: vstd/std_specs/control_flow.rs:59  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E, F: From<E>>[ Result::<T, F>::from_residual ]( result: Result<Infallible, E>, ) -> (result2: Result<T, F>)`
- ensures: match (result, result2) { (Err(e), Err(e2)) => spec_from::<F, E>(e, e2), _ => false, },

## group_control_flow_axioms
- path: vstd/std_specs/control_flow.rs  (broadcast group)
- members: spec_from_blanket_identity

## T::into
- path: vstd/std_specs/convert.rs:48  (exec spec, assume_specification)
- trait: Into
- sig: `pub assume_specification<T, U: From<T>>[ <T as Into<U>>::into ](a: T) -> (ret: U)`
- ensures: call_ensures(U::from, (a,), ret),

## T::try_into
- path: vstd/std_specs/convert.rs:101  (exec spec, assume_specification)
- trait: TryInto
- sig: `pub assume_specification<T, U: TryFrom<T>>[ <T as TryInto<U>>::try_into ](a: T) -> (ret: Result< U, U::Error, >)`
- ensures: call_ensures(U::try_from, (a,), ret),

## T::try_from
- path: vstd/std_specs/convert.rs:109  (exec spec, assume_specification)
- trait: TryFrom
- sig: `pub assume_specification<T, U: Into<T>>[ <T as TryFrom<U>>::try_from ](a: U) -> (ret: Result< T, <T as TryFrom<U>>::Error, >)`
- ensures: ret.is_ok(), call_ensures(U::into, (a,), ret.unwrap()),

## core::mem::swap
- path: vstd/std_specs/core.rs:132  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ core::mem::swap::<T> ](a: &mut T, b: &mut T)`
- ensures: *final(a) == *old(b), *final(b) == *old(a),

## core::intrinsics::likely
- path: vstd/std_specs/core.rs:165  (exec spec, assume_specification)
- sig: `pub assume_specification[ core::intrinsics::likely ](b: bool) -> (c: bool)`
- ensures: c == b,

## core::intrinsics::unlikely
- path: vstd/std_specs/core.rs:170  (exec spec, assume_specification)
- sig: `pub assume_specification[ core::intrinsics::unlikely ](b: bool) -> (c: bool)`
- ensures: c == b,

## bool::then
- path: vstd/std_specs/core.rs:175  (exec spec, assume_specification)
- sig: `pub assume_specification<T, F: FnOnce() -> T>[ bool::then ](b: bool, f: F) -> (ret: Option<T>)`
- ensures: if b { ret.is_some() && f.ensures((), ret.unwrap()) } else { ret.is_none() },

## index_set
- path: vstd/std_specs/core.rs:205  (fn)
- sig: `pub fn index_set<T, Idx, E>(container: &mut T, index: Idx, val: E) where T: ?Sized + core::ops::IndexMut<Idx> + core::ops::Index<Idx, Output = E> + IndexSetTrustedSpec< Idx, >,`
- requires: old(container).spec_index_set_requires(index),
- ensures: old(container).spec_index_set_ensures(final(container), index, val),

## Option::default
- path: vstd/std_specs/default.rs:46  (exec spec, assume_specification)
- trait: core::default::Default
- sig: `pub assume_specification<T>[ <Option<T> as core::default::Default>::default ]() -> (r: Option<T>)`
- ensures: r == Option::<T>::None,

## &'a str::default
- path: vstd/std_specs/default.rs:51  (exec spec, assume_specification)
- trait: core::default::Default
- sig: `pub assume_specification<'a>[ <&'a str as core::default::Default>::default ]() -> (r: &'a str)`
- ensures: r == "",

## DefaultHasher::new
- path: vstd/std_specs/hash.rs:72  (exec spec, assume_specification)
- sig: `pub assume_specification[ DefaultHasher::new ]() -> (result: DefaultHasher)`
- ensures: result@ == Seq::<Seq<u8>>::empty(),

## DefaultHasher::write
- path: vstd/std_specs/hash.rs:78  (exec spec, assume_specification)
- sig: `pub assume_specification[ DefaultHasher::write ](state: &mut DefaultHasher, bytes: &[u8])`
- ensures: final(state)@ == old(state)@.push(bytes@),

## DefaultHasher::finish
- path: vstd/std_specs/hash.rs:84  (exec spec, assume_specification)
- sig: `pub assume_specification[ DefaultHasher::finish ](state: &DefaultHasher) -> (result: u64)`
- ensures: result == DefaultHasher::spec_finish(state@),

## obeys_key_model
- path: vstd/std_specs/hash.rs:107  (spec fn)
- sig: `pub uninterp spec fn obeys_key_model<Key: ?Sized>() -> bool`
- doc: Specifies whether a type `Key` conforms to our requirements to be

## axiom_bool_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:113  (proof fn)
- sig: `pub broadcast proof fn axiom_bool_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<bool>(),

## axiom_u8_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:120  (proof fn)
- sig: `pub broadcast proof fn axiom_u8_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<u8>(),

## axiom_u16_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:127  (proof fn)
- sig: `pub broadcast proof fn axiom_u16_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<u16>(),

## axiom_u32_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:134  (proof fn)
- sig: `pub broadcast proof fn axiom_u32_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<u32>(),

## axiom_u64_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:141  (proof fn)
- sig: `pub broadcast proof fn axiom_u64_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<u64>(),

## axiom_u128_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:148  (proof fn)
- sig: `pub broadcast proof fn axiom_u128_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<u128>(),

## axiom_usize_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:155  (proof fn)
- sig: `pub broadcast proof fn axiom_usize_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<usize>(),

## axiom_i8_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:162  (proof fn)
- sig: `pub broadcast proof fn axiom_i8_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<i8>(),

## axiom_i16_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:169  (proof fn)
- sig: `pub broadcast proof fn axiom_i16_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<i16>(),

## axiom_i32_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:176  (proof fn)
- sig: `pub broadcast proof fn axiom_i32_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<i32>(),

## axiom_i64_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:183  (proof fn)
- sig: `pub broadcast proof fn axiom_i64_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<i64>(),

## axiom_i128_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:190  (proof fn)
- sig: `pub broadcast proof fn axiom_i128_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<i128>(),

## axiom_isize_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:197  (proof fn)
- sig: `pub broadcast proof fn axiom_isize_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<isize>(),

## axiom_box_bool_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:204  (proof fn)
- sig: `pub broadcast proof fn axiom_box_bool_obeys_hash_table_key_model()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] obeys_key_model::<Box<bool>>(),

## axiom_box_integer_type_obeys_hash_table_key_model
- path: vstd/std_specs/hash.rs:211  (proof fn)
- sig: `pub broadcast proof fn axiom_box_integer_type_obeys_hash_table_key_model<Key: Integer + ?Sized>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- requires: obeys_key_model::<Key>(),
- ensures: #[trigger] obeys_key_model::<Box<Key>>(),

## builds_valid_hashers
- path: vstd/std_specs/hash.rs:254  (spec fn)
- sig: `pub uninterp spec fn builds_valid_hashers<T: ?Sized>() -> bool`
- doc: Specifies whether a type conforms to our requirements to be a hash builder

## axiom_random_state_builds_valid_hashers
- path: vstd/std_specs/hash.rs:266  (proof fn)
- sig: `pub broadcast proof fn axiom_random_state_builds_valid_hashers()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); it is a member of `vstd::std_specs::hash::group_hash_axioms`: write `broadcast use vstd::std_specs::hash::group_hash_axioms;` and the fact is available.
- ensures: #[trigger] builds_valid_hashers::<RandomState>(),

## into_iter_keys
- path: vstd/std_specs/hash.rs:283  (spec fn)
- sig: `pub uninterp spec fn into_iter_keys<'a, Key, Value>(i: Keys<'a, Key, Value>) -> Seq<Key>`

## into_iter_values
- path: vstd/std_specs/hash.rs:321  (spec fn)
- sig: `pub uninterp spec fn into_iter_values<'a, Key, Value>(i: Values<'a, Key, Value>) -> Seq<Value>`

## into_iter
- path: vstd/std_specs/hash.rs:359  (spec fn)
- sig: `pub uninterp spec fn into_iter<'a, Key, Value>(i: hash_map::Iter<'a, Key, Value>) -> Seq< (Key, Value), >`

## spec_hash_map_iter
- path: vstd/std_specs/hash.rs:396  (spec fn)
- sig: `pub uninterp spec fn spec_hash_map_iter<'a, Key, Value, S, A: Allocator>( m: &'a HashMap<Key, Value, S, A>, ) -> (r: hash_map::Iter<'a, Key, Value>)`

## axiom_spec_hash_map_iter
- path: vstd/std_specs/hash.rs:400  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_hash_map_iter<'a, Key, Value, S>(m: &'a HashMap<Key, Value, S>)`
- ensures: ({ let v = #[trigger] spec_hash_map_iter(m).remaining(); &&& v.len() == m@.dom().len() &&& forall|i: int| #![trigger m@.contains_key(*v[i].0)]

## HashMap::iter
- path: vstd/std_specs/hash.rs:417  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, Key, Value, S, A: Allocator>[ HashMap::<Key, Value, S, A>::iter ]( m: &'a HashMap<Key, Value, S, A>, ) -> (iter: hash_map::Iter<'a, Key, Value>)`
- ensures: obeys_key_model::<Key>() && builds_valid_hashers::<S>() ==> { &&& iter == spec_hash_map_iter(m) &&& iter.remaining().no_duplicates() &&& IteratorSpec::decrease(&iter) is Some &&& IteratorSpec::initial_value_relation(&iter, &iter)

## hash_map_deep_view_impl
- path: vstd/std_specs/hash.rs:473  (spec fn)
- sig: `pub open spec fn hash_map_deep_view_impl< Key: DeepView, Value: DeepView, S, A: core::alloc::Allocator,`
- doc: The actual definition of `HashMap::deep_view`.

## lemma_hashmap_deepview_dom
- path: vstd/std_specs/hash.rs:489  (proof fn)
- sig: `pub broadcast proof fn lemma_hashmap_deepview_dom<K: DeepView, V: DeepView>(m: HashMap<K, V>)`
- ensures: #[trigger] m.deep_view().dom() == m@.dom().map(|k: K| k.deep_view()),

## lemma_hashmap_deepview_properties
- path: vstd/std_specs/hash.rs:500  (proof fn)
- sig: `pub broadcast proof fn lemma_hashmap_deepview_properties<K: DeepView, V: DeepView>(m: HashMap<K, V>)`
- requires: crate::relations::injective(|k: K| k.deep_view()),
- ensures: #![trigger m.deep_view()] // all elements in m.view() are present in m.deep_view() forall|k: K| #[trigger] m@.contains_key(k) ==> m.deep_view().contains_key(k.deep_view()) && m.deep_view()[k.deep_view()] == m@[k].deep_view(),

## lemma_hashmap_deepview_values
- path: vstd/std_specs/hash.rs:544  (proof fn)
- sig: `pub broadcast proof fn lemma_hashmap_deepview_values<K: DeepView, V: DeepView>(m: HashMap<K, V>)`
- requires: crate::relations::injective(|k: K| k.deep_view()),
- ensures: #[trigger] m.deep_view().values() =~= m@.values().map(|v: V| v.deep_view()),

## axiom_hashmap_deepview_borrow
- path: vstd/std_specs/hash.rs:569  (proof fn)
- sig: `pub broadcast proof fn axiom_hashmap_deepview_borrow< K: DeepView + Borrow<Q>, V: DeepView, Q: View<V = <K as DeepView>::V> + Hash + Eq + ?Sized, >(m: HashMap<K, V>, k: &Q)`
- requires: obeys_key_model::<K>(), crate::relations::injective(|k: K| k.deep_view()),
- ensures: #[trigger] contains_borrowed_key(m@, k) <==> m.deep_view().contains_key(k@),
- doc: Borrowing a key works the same way on deep_view as on view,

## spec_hash_map_len
- path: vstd/std_specs/hash.rs:583  (spec fn)
- sig: `pub uninterp spec fn spec_hash_map_len<Key, Value, S, A: Allocator>( m: &HashMap<Key, Value, S, A>, ) -> usize`

## axiom_spec_hash_map_len
- path: vstd/std_specs/hash.rs:587  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_hash_map_len<Key, Value, S, A: Allocator>( m: &HashMap<Key, Value, S, A>, )`
- ensures: obeys_key_model::<Key>() && builds_valid_hashers::<S>() ==> #[trigger] spec_hash_map_len(m) == m@.len(),

## HashMap::len
- path: vstd/std_specs/hash.rs:598  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, Value, S, A: Allocator>[ HashMap::<Key, Value, S, A>::len ]( m: &HashMap<Key, Value, S, A>, ) -> (len: usize)`
- ensures: len == spec_hash_map_len(m),

## HashMap::is_empty
- path: vstd/std_specs/hash.rs:605  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, Value, S, A: Allocator>[ HashMap::<Key, Value, S, A>::is_empty ]( m: &HashMap<Key, Value, S, A>, ) -> (res: bool)`
- ensures: res == m@.is_empty(),

## HashMap::new
- path: vstd/std_specs/hash.rs:625  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, Value>[ HashMap::<Key, Value>::new ]() -> (m: HashMap< Key, Value, RandomState, >)`
- ensures: m@ == Map::<Key, Value>::empty(),

## HashMap::with_capacity
- path: vstd/std_specs/hash.rs:643  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, Value>[ HashMap::<Key, Value>::with_capacity ](capacity: usize) -> (m: HashMap<Key, Value, RandomState>)`
- ensures: m@ == Map::<Key, Value>::empty(),

## contains_borrowed_key
- path: vstd/std_specs/hash.rs:689  (spec fn)
- sig: `pub uninterp spec fn contains_borrowed_key<Key, Value, Q: ?Sized>( m: Map<Key, Value>, k: &Q, ) -> bool`

## axiom_contains_deref_key
- path: vstd/std_specs/hash.rs:694  (proof fn)
- sig: `pub broadcast proof fn axiom_contains_deref_key<Q, Value>(m: Map<Q, Value>, k: &Q)`
- ensures: #[trigger] contains_borrowed_key::<Q, Value, Q>(m, k) <==> m.contains_key(*k),

## axiom_contains_box
- path: vstd/std_specs/hash.rs:701  (proof fn)
- sig: `pub broadcast proof fn axiom_contains_box<Q, Value>(m: Map<Box<Q>, Value>, k: &Q)`
- ensures: #[trigger] contains_borrowed_key::<Box<Q>, Value, Q>(m, k) <==> m.contains_key( Box::new(*k), ),

## maps_borrowed_key_to_value
- path: vstd/std_specs/hash.rs:743  (spec fn)
- sig: `pub uninterp spec fn maps_borrowed_key_to_value<Key, Value, Q: ?Sized>( m: Map<Key, Value>, k: &Q, v: Value, ) -> bool`

## axiom_maps_deref_key_to_value
- path: vstd/std_specs/hash.rs:749  (proof fn)
- sig: `pub broadcast proof fn axiom_maps_deref_key_to_value<Q, Value>(m: Map<Q, Value>, k: &Q, v: Value)`
- ensures: #[trigger] maps_borrowed_key_to_value::<Q, Value, Q>(m, k, v) <==> m.contains_key(*k) && m[*k] == v,

## axiom_maps_box_key_to_value
- path: vstd/std_specs/hash.rs:757  (proof fn)
- sig: `pub broadcast proof fn axiom_maps_box_key_to_value<Q, Value>(m: Map<Box<Q>, Value>, q: &Q, v: Value)`
- ensures: #[trigger] maps_borrowed_key_to_value::<Box<Q>, Value, Q>(m, q, v) <==> { let k = Box::new(*q); &&& m.contains_key(k) &&& m[k] == v },

## borrowed_key_removed
- path: vstd/std_specs/hash.rs:799  (spec fn)
- sig: `pub uninterp spec fn borrowed_key_removed<Key, Value, Q: ?Sized>( old_m: Map<Key, Value>, new_m: Map<Key, Value>, k: &Q, ) -> bool`

## axiom_deref_key_removed
- path: vstd/std_specs/hash.rs:805  (proof fn)
- sig: `pub broadcast proof fn axiom_deref_key_removed<Q, Value>( old_m: Map<Q, Value>, new_m: Map<Q, Value>, k: &Q, )`
- ensures: #[trigger] borrowed_key_removed::<Q, Value, Q>(old_m, new_m, k) <==> new_m == old_m.remove( *k, ),

## axiom_box_key_removed
- path: vstd/std_specs/hash.rs:818  (proof fn)
- sig: `pub broadcast proof fn axiom_box_key_removed<Q, Value>( old_m: Map<Box<Q>, Value>, new_m: Map<Box<Q>, Value>, q: &Q, )`
- ensures: #[trigger] borrowed_key_removed::<Box<Q>, Value, Q>(old_m, new_m, q) <==> new_m == old_m.remove(Box::new(*q)),

## HashMap::clear
- path: vstd/std_specs/hash.rs:848  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, Value, S, A: Allocator>[ HashMap::<Key, Value, S, A>::clear ]( m: &mut HashMap<Key, Value, S, A>, )`
- ensures: final(m)@ == Map::<Key, Value>::empty(),

## spec_keys_iter
- path: vstd/std_specs/hash.rs:861  (spec fn)
- sig: `pub uninterp spec fn spec_keys_iter<'a, Key, Value, S, A: Allocator>( m: &'a HashMap<Key, Value, S, A>, ) -> (keys: Keys<'a, Key, Value>)`

## axiom_spec_keys_iter
- path: vstd/std_specs/hash.rs:865  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_keys_iter<'a, Key, Value, S, A: Allocator>( m: &'a HashMap<Key, Value, S, A>, )`
- ensures: (#[trigger] spec_keys_iter(m).remaining()).unref().to_set() == m@.dom(), spec_keys_iter(m).remaining().no_duplicates(), spec_keys_iter(m).remaining().len() == m@.dom().len(),

## HashMap::keys
- path: vstd/std_specs/hash.rs:877  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, Key, Value, S, A: Allocator>[ HashMap::<Key, Value, S, A>::keys ]( m: &'a HashMap<Key, Value, S, A>, ) -> (keys: Keys<'a, Key, Value>)`
- ensures: obeys_key_model::<Key>() && builds_valid_hashers::<S>() ==> { &&& keys == spec_keys_iter(m) &&& IteratorSpec::decrease(&keys) is Some &&& IteratorSpec::initial_value_relation(&keys, &keys) },

## spec_values_iter
- path: vstd/std_specs/hash.rs:894  (spec fn)
- sig: `pub uninterp spec fn spec_values_iter<'a, Key, Value, S, A: Allocator>( m: &'a HashMap<Key, Value, S, A>, ) -> (values: Values<'a, Key, Value>)`

## axiom_spec_values_iter
- path: vstd/std_specs/hash.rs:898  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_values_iter<'a, Key, Value, S, A: Allocator>( m: &'a HashMap<Key, Value, S, A>, )`
- ensures: (#[trigger] spec_values_iter(m).remaining()).unref().to_set() == m@.values(), spec_values_iter(m).remaining().len() == m@.dom().len(),

## HashMap::values
- path: vstd/std_specs/hash.rs:909  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, Key, Value, S, A: Allocator>[ HashMap::<Key, Value, S, A>::values ]( m: &'a HashMap<Key, Value, S, A>, ) -> (values: Values<'a, Key, Value>)`
- ensures: obeys_key_model::<Key>() && builds_valid_hashers::<S>() ==> { &&& values == spec_values_iter(m) &&& IteratorSpec::decrease(&values) is Some &&& IteratorSpec::initial_value_relation(&values, &values) },

## axiom_hashmap_decreases
- path: vstd/std_specs/hash.rs:920  (proof fn)
- sig: `pub broadcast proof fn axiom_hashmap_decreases<Key, Value, S>(m: HashMap<Key, Value, S>)`
- ensures: #[trigger] (decreases_to!(m => m@)),

## into_iter_hash_keys
- path: vstd/std_specs/hash.rs:936  (spec fn)
- sig: `pub uninterp spec fn into_iter_hash_keys<'a, Key>(i: hash_set::Iter::<'a, Key>) -> Seq<Key>`

## spec_hash_set_len
- path: vstd/std_specs/hash.rs:982  (spec fn)
- sig: `pub uninterp spec fn spec_hash_set_len<Key, S, A: Allocator>(m: &HashSet<Key, S, A>) -> usize`

## axiom_spec_hash_set_len
- path: vstd/std_specs/hash.rs:984  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_hash_set_len<Key, S, A: Allocator>(m: &HashSet<Key, S, A>)`
- ensures: obeys_key_model::<Key>() && builds_valid_hashers::<S>() ==> #[trigger] spec_hash_set_len(m) == m@.len(),

## HashSet::len
- path: vstd/std_specs/hash.rs:993  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, S, A: Allocator>[ HashSet::<Key, S, A>::len ]( m: &HashSet<Key, S, A>, ) -> (len: usize)`
- ensures: len == spec_hash_set_len(m),

## HashSet::is_empty
- path: vstd/std_specs/hash.rs:1000  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, S, A: Allocator>[ HashSet::<Key, S, A>::is_empty ]( m: &HashSet<Key, S, A>, ) -> (res: bool)`
- ensures: res == m@.is_empty(),

## HashSet::new
- path: vstd/std_specs/hash.rs:1007  (exec spec, assume_specification)
- sig: `pub assume_specification<Key>[ HashSet::<Key>::new ]() -> (m: HashSet<Key, RandomState>)`
- ensures: m@ == Set::<Key>::empty(),

## HashSet::with_capacity
- path: vstd/std_specs/hash.rs:1020  (exec spec, assume_specification)
- sig: `pub assume_specification<Key>[ HashSet::<Key>::with_capacity ](capacity: usize) -> (m: HashSet< Key, RandomState, >)`
- ensures: m@ == Set::<Key>::empty(),

## set_contains_borrowed_key
- path: vstd/std_specs/hash.rs:1063  (spec fn)
- sig: `pub uninterp spec fn set_contains_borrowed_key<Key, Q: ?Sized>(m: Set<Key>, k: &Q) -> bool`

## axiom_set_contains_deref_key
- path: vstd/std_specs/hash.rs:1065  (proof fn)
- sig: `pub broadcast proof fn axiom_set_contains_deref_key<Q>(m: Set<Q>, k: &Q)`
- ensures: #[trigger] set_contains_borrowed_key::<Q, Q>(m, k) <==> m.contains(*k),

## axiom_set_contains_box
- path: vstd/std_specs/hash.rs:1072  (proof fn)
- sig: `pub broadcast proof fn axiom_set_contains_box<Q>(m: Set<Box<Q>>, k: &Q)`
- ensures: #[trigger] set_contains_borrowed_key::<Box<Q>, Q>(m, k) <==> m.contains(Box::new(*k)),

## sets_borrowed_key_to_key
- path: vstd/std_specs/hash.rs:1106  (spec fn)
- sig: `pub uninterp spec fn sets_borrowed_key_to_key<Key, Q: ?Sized>(m: Set<Key>, k: &Q, v: &Key) -> bool`

## axiom_set_deref_key_to_value
- path: vstd/std_specs/hash.rs:1108  (proof fn)
- sig: `pub broadcast proof fn axiom_set_deref_key_to_value<Q>(m: Set<Q>, k: &Q, v: &Q)`
- ensures: #[trigger] sets_borrowed_key_to_key::<Q, Q>(m, k, v) <==> m.contains(*k) && k == v,

## axiom_set_box_key_to_value
- path: vstd/std_specs/hash.rs:1115  (proof fn)
- sig: `pub broadcast proof fn axiom_set_box_key_to_value<Q>(m: Set<Box<Q>>, q: &Q, v: &Box<Q>)`
- ensures: #[trigger] sets_borrowed_key_to_key::<Box<Q>, Q>(m, q, v) <==> (m.contains(*v) && Box::new( *q, ) == v),

## sets_differ_by_borrowed_key
- path: vstd/std_specs/hash.rs:1152  (spec fn)
- sig: `pub uninterp spec fn sets_differ_by_borrowed_key<Key, Q: ?Sized>( old_m: Set<Key>, new_m: Set<Key>, k: &Q, ) -> bool`

## axiom_set_deref_key_removed
- path: vstd/std_specs/hash.rs:1158  (proof fn)
- sig: `pub broadcast proof fn axiom_set_deref_key_removed<Q>(old_m: Set<Q>, new_m: Set<Q>, k: &Q)`
- ensures: #[trigger] sets_differ_by_borrowed_key::<Q, Q>(old_m, new_m, k) <==> new_m == old_m.remove( *k, ),

## axiom_set_box_key_removed
- path: vstd/std_specs/hash.rs:1167  (proof fn)
- sig: `pub broadcast proof fn axiom_set_box_key_removed<Q>(old_m: Set<Box<Q>>, new_m: Set<Box<Q>>, q: &Q)`
- ensures: #[trigger] sets_differ_by_borrowed_key::<Box<Q>, Q>(old_m, new_m, q) <==> new_m == old_m.remove(Box::new(*q)),

## HashSet::clear
- path: vstd/std_specs/hash.rs:1188  (exec spec, assume_specification)
- sig: `pub assume_specification<Key, S, A: Allocator>[ HashSet::<Key, S, A>::clear ]( m: &mut HashSet<Key, S, A>, )`
- ensures: final(m)@ == Set::<Key>::empty(),

## spec_hash_keys_iter
- path: vstd/std_specs/hash.rs:1201  (spec fn)
- sig: `pub uninterp spec fn spec_hash_keys_iter<'a, Key, S, A: Allocator>(m: &'a HashSet<Key, S, A>) -> (r: hash_set::Iter<'a, Key>)`

## axiom_spec_hash_keys_iter
- path: vstd/std_specs/hash.rs:1204  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_hash_keys_iter<'a, Key, S, A: Allocator>( m: &'a HashSet<Key, S, A>, )`
- ensures: (#[trigger] spec_hash_keys_iter(m).remaining()).unref().to_set() == m@, spec_hash_keys_iter(m).remaining().no_duplicates(), spec_hash_keys_iter(m).remaining().len() == m@.len(),

## HashSet::iter
- path: vstd/std_specs/hash.rs:1216  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, Key, S, A: Allocator>[ HashSet::<Key, S, A>::iter ]( m: &'a HashSet<Key, S, A>, ) -> (hash_keys: hash_set::Iter<'a, Key>)`
- ensures: obeys_key_model::<Key>() && builds_valid_hashers::<S>() ==> { &&& hash_keys == spec_hash_keys_iter(m) &&& IteratorSpec::decrease(&hash_keys) is Some &&& IteratorSpec::initial_value_relation(&hash_keys, &hash_keys) },

## axiom_hashset_decreases
- path: vstd/std_specs/hash.rs:1227  (proof fn)
- sig: `pub broadcast proof fn axiom_hashset_decreases<Key, S, A: Allocator>(m: HashSet<Key, S, A>)`
- ensures: #[trigger] (decreases_to!(m => m@)),

## axiom_has_resolved_entry
- path: vstd/std_specs/hash.rs:1346  (proof fn)
- sig: `pub broadcast proof fn axiom_has_resolved_entry<K, V, A: Allocator>(entry: Entry<K, V, A>)`
- ensures: #[trigger] has_resolved(entry) ==> entry.final_value() == entry.value(),

## Entry::key
- path: vstd/std_specs/hash.rs:1371  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, 'b, K, V, A: Allocator>[ Entry::key ]( entry: &'b Entry::<'a, K, V, A>, ) -> (key: &'b K)`
- doc: / Entry

## Entry::or_insert
- path: vstd/std_specs/hash.rs:1378  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, K, V, A: Allocator>[ Entry::or_insert ]( entry: Entry::<'a, K, V, A>, default: V, ) -> (value: &'a mut V)`
- ensures: *value == (match entry.value() { Some(v) => v, None => default, }), entry.final_value() == Some(*final(value)),

## Entry::insert_entry
- path: vstd/std_specs/hash.rs:1390  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, K, V, A: Allocator>[ Entry::insert_entry ]( entry: Entry::<'a, K, V, A>, value: V, ) -> (occ_entry: OccupiedEntry<'a, K, V, A>)`
- ensures: occ_entry.key() == entry.key(), occ_entry.value() == value, entry.final_value() == occ_entry.final_value(),

## OccupiedEntry::key
- path: vstd/std_specs/hash.rs:1406  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, 'b, K, V, A: Allocator>[ OccupiedEntry::key ]( entry: &'b OccupiedEntry::<'a, K, V, A>, ) -> (key: &'b K)`

## OccupiedEntry::remove_entry
- path: vstd/std_specs/hash.rs:1415  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, K, V, A: Allocator>[ OccupiedEntry::remove_entry ]( entry: OccupiedEntry::<'a, K, V, A>, ) -> (kv: (K, V))`
- ensures: entry.final_value() == None,

## OccupiedEntry::get
- path: vstd/std_specs/hash.rs:1424  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, 'b, K, V, A: Allocator>[ OccupiedEntry::get ]( entry: &'b OccupiedEntry::<'a, K, V, A>, ) -> (value: &'b V)`
- ensures: *value == entry.value(),

## OccupiedEntry::get_mut
- path: vstd/std_specs/hash.rs:1431  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, 'b, K, V, A: Allocator>[ OccupiedEntry::get_mut ]( entry: &'b mut OccupiedEntry::<'a, K, V, A>, ) -> (value: &'b mut V)`
- ensures: *value == old(entry).value(), final(entry).key() == old(entry).key(), final(entry).value() == *final(value), final(entry).final_value() == old(entry).final_value(),

## OccupiedEntry::into_mut
- path: vstd/std_specs/hash.rs:1441  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, K, V, A: Allocator>[ OccupiedEntry::into_mut ]( entry: OccupiedEntry::<'a, K, V, A>, ) -> (value: &mut V)`
- ensures: *value == entry.value(), entry.final_value() == Some(*final(value)),

## OccupiedEntry::insert
- path: vstd/std_specs/hash.rs:1449  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, K, V, A: Allocator>[ OccupiedEntry::insert ]( entry: &mut OccupiedEntry::<'a, K, V, A>, value: V, ) -> (old_value: V)`
- ensures: old_value == old(entry).value(), final(entry).key() == old(entry).key(), final(entry).value() == value, final(entry).final_value() == old(entry).final_value(),

## OccupiedEntry::remove
- path: vstd/std_specs/hash.rs:1460  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, K, V, A: Allocator>[ OccupiedEntry::remove ]( entry: OccupiedEntry::<'a, K, V, A>, ) -> (value: V)`
- ensures: value == entry.value(), entry.final_value() == None,

## VacantEntry::key
- path: vstd/std_specs/hash.rs:1474  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, 'b, K: 'a, V: 'a, A: Allocator>[ VacantEntry::key ]( entry: &'b VacantEntry::<'a, K, V, A>, ) -> (key: &'b K)`

## VacantEntry::into_key
- path: vstd/std_specs/hash.rs:1483  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, K: 'a, V: 'a, A: Allocator>[ VacantEntry::into_key ]( entry: VacantEntry::<'a, K, V, A>, ) -> (key: K)`
- ensures: key == entry.key(), entry.final_value() == None,

## VacantEntry::insert
- path: vstd/std_specs/hash.rs:1491  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, K: 'a, V: 'a, A: Allocator>[ VacantEntry::insert ]( entry: VacantEntry::<'a, K, V, A>, value: V, ) -> (value_ref: &mut V)`
- ensures: *value_ref == value, entry.final_value() == Some(*final(value_ref)),

## VacantEntry::insert_entry
- path: vstd/std_specs/hash.rs:1500  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, K: 'a, V: 'a, A: Allocator>[ VacantEntry::insert_entry ]( entry: VacantEntry::<'a, K, V, A>, value: V, ) -> (occ_entry: OccupiedEntry::<'a, K, V, A>)`
- ensures: occ_entry.key() == entry.key(), occ_entry.value() == value, entry.final_value() == occ_entry.final_value(),

## group_hash_axioms
- path: vstd/std_specs/hash.rs  (broadcast group)
- members: axiom_box_key_removed axiom_contains_deref_key axiom_contains_box axiom_deref_key_removed axiom_maps_deref_key_to_value axiom_maps_box_key_to_value axiom_hashmap_deepview_borrow axiom_bool_obeys_hash_table_key_model axiom_u8_obeys_hash_table_key_model axiom_u16_obeys_hash_table_key_model axiom_u32_obeys_hash_table_key_model axiom_u64_obeys_hash_table_key_model axiom_u128_obeys_hash_table_key_model axiom_usize_obeys_hash_table_key_model axiom_i8_obeys_hash_table_key_model axiom_i16_obeys_hash_table_key_model axiom_i32_obeys_hash_table_key_model axiom_i64_obeys_hash_table_key_model axiom_i128_obeys_hash_table_key_model axiom_isize_obeys_hash_table_key_model axiom_box_bool_obeys_hash_table_key_model axiom_box_integer_type_obeys_hash_table_key_model axiom_random_state_builds_valid_hashers axiom_spec_hash_map_len axiom_set_box_key_removed axiom_set_contains_deref_key axiom_set_contains_box axiom_set_deref_key_removed axiom_set_deref_key_to_value axiom_set_box_key_to_value axiom_spec_hash_set_len axiom_spec_hash_map_iter axiom_spec_hash_keys_iter axiom_spec_keys_iter axiom_spec_values_iter axiom_hashmap_decreases axiom_hashset_decreases axiom_has_resolved_occupied_entry axiom_has_resolved_vacant_entry axiom_has_resolved_entry

## iter_into_iter_spec
- path: vstd/std_specs/iter.rs:249  (spec fn)
- sig: `pub open spec fn iter_into_iter_spec<I: Iterator>(i: I) -> I`

## I::into_iter
- path: vstd/std_specs/iter.rs:254  (exec spec, assume_specification)
- trait: IntoIterator
- sig: `pub assume_specification<I: Iterator>[ <I as IntoIterator>::into_iter ](i: I) -> (r: I)`
- ensures: r == i,

## into_iter_remaining
- path: vstd/std_specs/iter.rs:262  (spec fn)
- sig: `pub uninterp spec fn into_iter_remaining<A, T>(iter: T) -> Seq<A>`

## rev_iter
- path: vstd/std_specs/iter.rs:294  (spec fn)
- sig: `pub uninterp spec fn rev_iter<I>(r: Rev<I>) -> I`

## into_rev_spec
- path: vstd/std_specs/iter.rs:297  (spec fn)
- sig: `pub uninterp spec fn into_rev_spec<I>(i: I) -> Rev<I>`

## rev_post
- path: vstd/std_specs/iter.rs:304  (spec fn)
- sig: `pub uninterp spec fn rev_post<I>(i: I, r: Rev<I>) -> bool`

## VerusForLoopWrapper::seq
- path: vstd/std_specs/iter.rs:409  (spec fn)
- sig: `pub open spec fn seq(self) -> Seq<I::Item>`

## VerusForLoopWrapper::history
- path: vstd/std_specs/iter.rs:414  (spec fn)
- sig: `pub open spec fn history(self) -> Seq<I::Item>`

## VerusForLoopWrapper::index
- path: vstd/std_specs/iter.rs:418  (spec fn)
- sig: `pub open spec fn index(self) -> int`

## VerusForLoopWrapper::wf_inner
- path: vstd/std_specs/iter.rs:425  (spec fn)
- sig: `pub closed spec fn wf_inner(self) -> bool`
- doc: These properties help maintain the properties in wf,

## VerusForLoopWrapper::wf
- path: vstd/std_specs/iter.rs:433  (spec fn)
- sig: `pub open spec fn wf(self) -> bool`
- doc: These properties are needed for the client code to verify

## VerusForLoopWrapper::new
- path: vstd/std_specs/iter.rs:444  (fn)
- sig: `pub fn new(iter: I, init: Ghost<Option<&'a I>>) -> (s: Self)`
- requires: init@ matches Some(i) ==> iter.initial_value_relation(i),
- ensures: s.index == 0, s.snapshot == iter, s.init == init, s.iter == iter, s.history@ == Seq::<I::Item>::empty(),
- doc: Bundle the real iterator with its ghost state and loop invariants

## VerusForLoopWrapper::next
- path: vstd/std_specs/iter.rs:467  (fn)
- sig: `pub fn next(&mut self) -> (ret: Option<I::Item>)`
- requires: old(self).wf(),
- ensures: final(self).seq() == old(self).seq(), final(self).index() == old(self).index() + if ret is Some { 1int } else { 0 }, final(self).snapshot == old(self).snapshot, final(self).init == old(self).init, final(self).iter.obeys_prophetic_iter_laws() ==> final(self).wf(),
- doc: Advance the underlying (real) iterator and prove

## trigger_peek_implications
- path: vstd/std_specs/iter.rs:504  (spec fn)
- sig: `pub open spec fn trigger_peek_implications<T>(x: T) -> bool { true }  /******************************************************************************** * Definitions for the Step trait ********************************************************************************/ #[verifier::external_trait_specification] #[verifier::external_trait_extension(StepSpec via StepSpecImpl)]`

## group_iter_axioms
- path: vstd/std_specs/iter.rs  (broadcast group)
- members: rev_postcondition

## ManuallyDrop::new
- path: vstd/std_specs/manually_drop.rs:30  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ ManuallyDrop::<T>::new ](value: T) -> (res: ManuallyDrop<T>)`
- ensures: res@ == value,

## ManuallyDrop::into_inner
- path: vstd/std_specs/manually_drop.rs:35  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ ManuallyDrop::<T>::into_inner ](m: ManuallyDrop<T>) -> T`

## ManuallyDrop::clone
- path: vstd/std_specs/manually_drop.rs:40  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification<T: Clone + ?Sized>[ <ManuallyDrop<T> as Clone>::clone ]( m: &ManuallyDrop<T>, ) -> (res: ManuallyDrop<T>)`
- ensures: cloned(m@, res@),

## ManuallyDrop::deref
- path: vstd/std_specs/manually_drop.rs:47  (exec spec, assume_specification)
- trait: Deref
- sig: `pub assume_specification<T: ?Sized>[ <ManuallyDrop<T> as Deref>::deref ]( m: &ManuallyDrop<T>, ) -> (res: &T)`

## group_manually_drop_axioms
- path: vstd/std_specs/manually_drop.rs  (broadcast group)
- members: axiom_manually_drop_has_resolved

## MaybeUninit::new
- path: vstd/std_specs/maybe_uninit.rs:29  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ MaybeUninit::<T>::new ](val: T) -> (res: MaybeUninit<T>)`
- ensures: res.mem_contents() == MemContents::Init(val),

## MaybeUninit::uninit
- path: vstd/std_specs/maybe_uninit.rs:34  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ MaybeUninit::<T>::uninit ]() -> (res: MaybeUninit<T>)`
- ensures: res.mem_contents() == MemContents::Uninit,

## MaybeUninit::assume_init
- path: vstd/std_specs/maybe_uninit.rs:39  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ MaybeUninit::<T>::assume_init ](m: MaybeUninit<T>) -> T`
- requires: m.mem_contents().is_init(),

## MaybeUninit::assume_init_ref
- path: vstd/std_specs/maybe_uninit.rs:45  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ MaybeUninit::<T>::assume_init_ref ](m: &MaybeUninit<T>) -> (ret: &T)`
- requires: m.mem_contents().is_init(),
- ensures: ret == m.mem_contents().value(),

## MaybeUninit::assume_init_mut
- path: vstd/std_specs/maybe_uninit.rs:51  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ MaybeUninit::<T>::assume_init_mut ](m: &mut MaybeUninit<T>) -> (ret: &mut T)`
- requires: m.mem_contents().is_init(),
- ensures: *ret == old(m).mem_contents().value(), final(m).mem_contents().is_init(), final(m).mem_contents().value() == *final(ret),

## nonzero_from_primitive
- path: vstd/std_specs/nonzero.rs:51  (spec fn)
- sig: `pub uninterp spec fn nonzero_from_primitive<T: ZeroablePrimitive>(n: T) -> NonZero<T>`

## NonZero::new
- path: vstd/std_specs/nonzero.rs:70  (exec spec, assume_specification)
- sig: `pub assume_specification<T: ZeroablePrimitive>[ NonZero::<T>::new ](n: T) -> (ret: Option< NonZero<T>, >)`
- ensures: match ret { Some(nz) => nz@ == n && !n.is_zero(), None => n.is_zero(), },

## NonZero::new_unchecked
- path: vstd/std_specs/nonzero.rs:82  (exec spec, assume_specification)
- sig: `pub assume_specification<T: ZeroablePrimitive>[ NonZero::<T>::new_unchecked ](n: T) -> (ret: NonZero<T>)`
- requires: !n.is_zero(),
- ensures: ret@ == n,

## nonzero_spec_get
- path: vstd/std_specs/nonzero.rs:93  (spec fn)
- sig: `pub open spec fn nonzero_spec_get<T: ZeroablePrimitive>(n: NonZero<T>) -> T`

## NonZero::get
- path: vstd/std_specs/nonzero.rs:98  (exec spec, assume_specification)
- sig: `pub assume_specification<T: ZeroablePrimitive>[ NonZero::<T>::get ](n: NonZero<T>) -> T`

## NonZero::clone
- path: vstd/std_specs/nonzero.rs:164  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification<T: ZeroablePrimitive>[ <NonZero<T> as Clone>::clone ]( nz: &NonZero<T>, ) -> NonZero<T>`

## group_nonzero_axioms
- path: vstd/std_specs/nonzero.rs  (broadcast group)
- members: axiom_nonzero_from_primitive_view_eq axiom_view_nonzero_from_primitive_eq axiom_nonzero_is_not_zero

## checked_div
- path: vstd/std_specs/num.rs:166  (spec fn)
- sig: `pub open spec fn checked_div(x: $uN, y: $uN) -> Option<$uN>`

## neg_ensures
- path: vstd/std_specs/ops.rs:454  (spec fn)
- sig: `pub uninterp spec fn neg_ensures<A>(x: A, o: A) -> bool`

## add_ensures
- path: vstd/std_specs/ops.rs:456  (spec fn)
- sig: `pub uninterp spec fn add_ensures<A>(x: A, y: A, o: A) -> bool`

## sub_ensures
- path: vstd/std_specs/ops.rs:458  (spec fn)
- sig: `pub uninterp spec fn sub_ensures<A>(x: A, y: A, o: A) -> bool`

## mul_ensures
- path: vstd/std_specs/ops.rs:460  (spec fn)
- sig: `pub uninterp spec fn mul_ensures<A>(x: A, y: A, o: A) -> bool`

## div_ensures
- path: vstd/std_specs/ops.rs:462  (spec fn)
- sig: `pub uninterp spec fn div_ensures<A>(x: A, y: A, o: A) -> bool`

## f32::neg
- path: vstd/std_specs/ops.rs:464  (exec spec, assume_specification)
- trait: core::ops::Neg
- sig: `pub assume_specification[ <f32 as core::ops::Neg>::neg ](x: f32) -> (o: f32)`
- ensures: neg_ensures::<f32>(x, o),

## f32::add
- path: vstd/std_specs/ops.rs:469  (exec spec, assume_specification)
- trait: core::ops::Add
- sig: `pub assume_specification[ <f32 as core::ops::Add>::add ](x: f32, y: f32) -> (o: f32)`
- ensures: add_ensures::<f32>(x, y, o),

## f32::sub
- path: vstd/std_specs/ops.rs:474  (exec spec, assume_specification)
- trait: core::ops::Sub
- sig: `pub assume_specification[ <f32 as core::ops::Sub>::sub ](x: f32, y: f32) -> (o: f32)`
- ensures: sub_ensures::<f32>(x, y, o),

## f32::mul
- path: vstd/std_specs/ops.rs:479  (exec spec, assume_specification)
- trait: core::ops::Mul
- sig: `pub assume_specification[ <f32 as core::ops::Mul>::mul ](x: f32, y: f32) -> (o: f32)`
- ensures: mul_ensures::<f32>(x, y, o),

## f32::div
- path: vstd/std_specs/ops.rs:484  (exec spec, assume_specification)
- trait: core::ops::Div
- sig: `pub assume_specification[ <f32 as core::ops::Div>::div ](x: f32, y: f32) -> (o: f32)`
- ensures: div_ensures::<f32>(x, y, o),

## f64::neg
- path: vstd/std_specs/ops.rs:489  (exec spec, assume_specification)
- trait: core::ops::Neg
- sig: `pub assume_specification[ <f64 as core::ops::Neg>::neg ](x: f64) -> (o: f64)`
- ensures: neg_ensures::<f64>(x, o),

## f64::add
- path: vstd/std_specs/ops.rs:494  (exec spec, assume_specification)
- trait: core::ops::Add
- sig: `pub assume_specification[ <f64 as core::ops::Add>::add ](x: f64, y: f64) -> (o: f64)`
- ensures: add_ensures::<f64>(x, y, o),

## f64::sub
- path: vstd/std_specs/ops.rs:499  (exec spec, assume_specification)
- trait: core::ops::Sub
- sig: `pub assume_specification[ <f64 as core::ops::Sub>::sub ](x: f64, y: f64) -> (o: f64)`
- ensures: sub_ensures::<f64>(x, y, o),

## f64::mul
- path: vstd/std_specs/ops.rs:504  (exec spec, assume_specification)
- trait: core::ops::Mul
- sig: `pub assume_specification[ <f64 as core::ops::Mul>::mul ](x: f64, y: f64) -> (o: f64)`
- ensures: mul_ensures::<f64>(x, y, o),

## f64::div
- path: vstd/std_specs/ops.rs:509  (exec spec, assume_specification)
- trait: core::ops::Div
- sig: `pub assume_specification[ <f64 as core::ops::Div>::div ](x: f64, y: f64) -> (o: f64)`
- ensures: div_ensures::<f64>(x, y, o),

## is_some
- path: vstd/std_specs/option.rs:118  (spec fn)
- sig: `pub open spec fn is_some<T>(option: &Option<T>) -> bool`

## Option::is_some
- path: vstd/std_specs/option.rs:123  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::<T>::is_some ](option: &Option<T>) -> (b: bool)`
- ensures: b == is_some(option),

## is_none
- path: vstd/std_specs/option.rs:131  (spec fn)
- sig: `pub open spec fn is_none<T>(option: &Option<T>) -> bool`

## Option::is_none
- path: vstd/std_specs/option.rs:136  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::<T>::is_none ](option: &Option<T>) -> (b: bool)`
- ensures: b == is_none(option),

## Option::as_ref
- path: vstd/std_specs/option.rs:143  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::<T>::as_ref ](option: &Option<T>) -> (a: Option<&T>)`
- ensures: a is Some <==> option is Some, a is Some ==> option->0 == a->0,

## spec_unwrap
- path: vstd/std_specs/option.rs:152  (spec fn)
- sig: `pub open spec fn spec_unwrap<T>(option: Option<T>) -> T recommends option is Some,`

## Option::unwrap
- path: vstd/std_specs/option.rs:160  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::<T>::unwrap ](option: Option<T>) -> (t: T)`
- requires: option is Some,
- ensures: t == spec_unwrap(option),

## spec_unwrap_or
- path: vstd/std_specs/option.rs:169  (spec fn)
- sig: `pub open spec fn spec_unwrap_or<T>(option: Option<T>, default: T) -> T`

## Option::unwrap_or
- path: vstd/std_specs/option.rs:177  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::<T>::unwrap_or ](option: Option<T>, default: T) -> (t: T)`
- ensures: t == spec_unwrap_or(option, default),

## spec_expect
- path: vstd/std_specs/option.rs:185  (spec fn)
- sig: `pub open spec fn spec_expect<T>(option: Option<T>, msg: &str) -> T recommends option is Some,`

## Option::expect
- path: vstd/std_specs/option.rs:193  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::<T>::expect ](option: Option<T>, msg: &str) -> (t: T)`
- requires: option is Some,
- ensures: t == spec_expect(option, msg),

## Option::take
- path: vstd/std_specs/option.rs:201  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::<T>::take ](option: &mut Option<T>) -> (t: Option<T>)`
- ensures: t == *old(option), *final(option) is None,

## Option::map
- path: vstd/std_specs/option.rs:209  (exec spec, assume_specification)
- sig: `pub assume_specification<T, U, F: FnOnce(T) -> U>[ Option::<T>::map ](a: Option<T>, f: F) -> (ret: Option<U>)`
- requires: a.is_some() ==> f.requires((a.unwrap(),)),
- ensures: ret.is_some() == a.is_some(), ret.is_some() ==> f.ensures((a.unwrap(),), ret.unwrap()),

## Option::cloned
- path: vstd/std_specs/option.rs:219  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, T: Clone>[ Option::<&'a T>::cloned ](opt: Option<&'a T>) -> (res: Option<T>)`
- ensures: opt.is_none() ==> res.is_none(), opt.is_some() ==> res.is_some() && cloned::<T>(*opt.unwrap(), res.unwrap()),

## Option::and_then
- path: vstd/std_specs/option.rs:227  (exec spec, assume_specification)
- sig: `pub assume_specification<T, U, F: FnOnce(T) -> Option<U>>[ Option::<T>::and_then ]( option: Option<T>, f: F, ) -> (res: Option<U>)`
- requires: option.is_some() ==> f.requires((option.unwrap(),)),
- ensures: option.is_none() ==> res.is_none(), option.is_some() ==> f.ensures((option.unwrap(),), res),

## Option::ok_or_else
- path: vstd/std_specs/option.rs:239  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E, F: FnOnce() -> E>[ Option::<T>::ok_or_else ]( option: Option<T>, err: F, ) -> (res: Result<T, E>)`
- requires: option.is_none() ==> err.requires(()),
- ensures: option.is_some() ==> res == Ok::<T, E>(option.unwrap()), option.is_none() ==> { &&& res.is_err() &&& err.ensures((), res->Err_0) },

## Option::unwrap_or_default
- path: vstd/std_specs/option.rs:254  (exec spec, assume_specification)
- sig: `pub assume_specification<T: core::default::Default>[ Option::<T>::unwrap_or_default ]( option: Option<T>, ) -> (res: T)`
- ensures: option.is_some() ==> res == option.unwrap(), option.is_none() ==> T::default.ensures((), res),

## Option::unwrap_or_else
- path: vstd/std_specs/option.rs:263  (exec spec, assume_specification)
- sig: `pub assume_specification<T, F: FnOnce() -> T>[ Option::<T>::unwrap_or_else ]( option: Option<T>, f: F, ) -> (res: T)`
- requires: option.is_none() ==> f.requires(()),
- ensures: option.is_some() ==> res == option.unwrap(), option.is_none() ==> f.ensures((), res),

## Option::clone
- path: vstd/std_specs/option.rs:275  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification<T: Clone>[ <Option<T> as Clone>::clone ](opt: &Option<T>) -> (res: Option< T, >)`
- ensures: opt.is_none() ==> res.is_none(), opt.is_some() ==> res.is_some() && cloned::<T>(opt.unwrap(), res.unwrap()),

## Option::eq
- path: vstd/std_specs/option.rs:298  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification<T: PartialEq>[ <Option<T> as PartialEq>::eq ]( x: &Option<T>, y: &Option<T>, ) -> bool`

## Option::partial_cmp
- path: vstd/std_specs/option.rs:320  (exec spec, assume_specification)
- trait: PartialOrd
- sig: `pub assume_specification<T: PartialOrd>[ <Option<T> as PartialOrd>::partial_cmp ]( x: &Option<T>, y: &Option<T>, ) -> Option<core::cmp::Ordering>`

## Option::cmp
- path: vstd/std_specs/option.rs:341  (exec spec, assume_specification)
- trait: Ord
- sig: `pub assume_specification<T: Ord>[ <Option<T> as Ord>::cmp ]( x: &Option<T>, y: &Option<T>, ) -> core::cmp::Ordering`

## spec_ok_or
- path: vstd/std_specs/option.rs:349  (spec fn)
- sig: `pub open spec fn spec_ok_or<T, E>(option: Option<T>, err: E) -> Result<T, E>`

## Option::ok_or
- path: vstd/std_specs/option.rs:357  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E>[ Option::ok_or ](option: Option<T>, err: E) -> (res: Result<T, E>)`
- ensures: res == spec_ok_or(option, err),

## Option::as_mut
- path: vstd/std_specs/option.rs:363  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::as_mut ](option: &mut Option<T>) -> (res: Option<&mut T>)`
- ensures: (match *old(option) { None => final(option).is_none() && res.is_none(), Some(r) => final(option).is_some() && res.is_some() && *res.unwrap() == r && *final(res.unwrap()) == final(option).unwrap(), }),

## Option::as_slice
- path: vstd/std_specs/option.rs:372  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::as_slice ](option: &Option<T>) -> (res: &[T])`
- ensures: res@ == (match *option { Some(x) => seq![x], None => seq![], }),

## Option::as_mut_slice
- path: vstd/std_specs/option.rs:381  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::as_mut_slice ](option: &mut Option<T>) -> (res: &mut [T])`
- ensures: res@ == (match *old(option) { Some(x) => seq![x], None => seq![], }), final(res)@.len() == res@.len(),  // TODO this should be broadcast for all `&mut [T]`

## Option::insert
- path: vstd/std_specs/option.rs:395  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::insert ](option: &mut Option<T>, value: T) -> (res: &mut T)`
- ensures: *res == value, *final(option) == Some(*final(res)),

## Option::get_or_insert
- path: vstd/std_specs/option.rs:402  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Option::get_or_insert ](option: &mut Option<T>, value: T) -> (res: &mut T)`
- ensures: *res == (match *old(option) { Some(x) => x, None => value, }), *final(option) == Some(*final(res)),

## spec_range_next
- path: vstd/std_specs/range.rs:68  (spec fn)
- sig: `pub uninterp spec fn spec_range_next<A>(a: Range<A>) -> (Range<A>, Option<A>)`

## Range::contains
- path: vstd/std_specs/range.rs:74  (exec spec, assume_specification)
- sig: `pub assume_specification<Idx: PartialOrd<Idx>, U>[ Range::<Idx>::contains ]( r: &Range<Idx>, i: &U, ) -> (ret: bool) where Idx: PartialOrd<U>, U: ?Sized + PartialOrd<Idx>`
- ensures: <Range::<Idx> as ContainsSpec<Idx, U>>::obeys_contains() ==> ret == r.contains_spec(i),
- doc: Range::contains method is valid and safe to use only when cmp operations are implemented to satisfy

## RangeInclusive::contains
- path: vstd/std_specs/range.rs:82  (exec spec, assume_specification)
- sig: `pub assume_specification<Idx: PartialOrd<Idx>, U>[ RangeInclusive::<Idx>::contains ]( r: &RangeInclusive<Idx>, i: &U, ) -> (ret: bool) where Idx: PartialOrd<U>, U: ?Sized + PartialOrd<Idx>`
- ensures: <RangeInclusive::<Idx> as ContainsSpec<Idx, U>>::obeys_contains() ==> ret == r.contains_spec(i),

## spec_range_inclusive_new
- path: vstd/std_specs/range.rs:98  (spec fn)
- sig: `pub uninterp spec fn spec_range_inclusive_new<Idx>( start: Idx, end: Idx, ) -> core::ops::RangeInclusive<Idx>`

## RangeInclusive::new
- path: vstd/std_specs/range.rs:111  (exec spec, assume_specification)
- sig: `pub assume_specification<Idx>[ RangeInclusive::<Idx>::new ](start: Idx, end: Idx) -> (ret: core::ops::RangeInclusive<Idx>)`
- ensures: ret == spec_range_inclusive_new(start, end),

## Range::next
- path: vstd/std_specs/range.rs:228  (exec spec, assume_specification)
- trait: Iterator
- sig: `pub assume_specification<A: core::iter::Step>[ <Range<A> as Iterator>::next ]( range: &mut Range<A>, ) -> (r: Option<A>)`
- ensures: (*final(range), r) == spec_range_next(*old(range)),

## spec_bound
- path: vstd/std_specs/range.rs:245  (spec fn)
- sig: `pub open spec fn spec_bound<T>(bound: Bound<T>) -> SpecBound<T>`
- doc: Spec model of a [`core::ops::Bound`] value as a [`SpecBound`].

## spec_bound_ref
- path: vstd/std_specs/range.rs:254  (spec fn)
- sig: `pub open spec fn spec_bound_ref<'a, T>(bound: &'a Bound<T>) -> SpecBound<&'a T>`
- doc: Spec model of a borrowed [`core::ops::Bound`] value as a [`SpecBound`].

## Range::start_bound
- path: vstd/std_specs/range.rs:283  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T>[ <Range<T> as RangeBounds<T>>::start_bound ]( range: &'s Range<T>, ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == SpecBound::Included(&range.start),

## Range::end_bound
- path: vstd/std_specs/range.rs:290  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T>[ <Range<T> as RangeBounds<T>>::end_bound ]( range: &'s Range<T>, ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == SpecBound::Excluded(&range.end),

## RangeFull::start_bound
- path: vstd/std_specs/range.rs:297  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T: ?Sized>[ <RangeFull as RangeBounds<T>>::start_bound ]( range: &'s RangeFull, ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == SpecBound::Unbounded,

## RangeFull::end_bound
- path: vstd/std_specs/range.rs:304  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T: ?Sized>[ <RangeFull as RangeBounds<T>>::end_bound ]( range: &'s RangeFull, ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == SpecBound::Unbounded,

## RangeFrom::start_bound
- path: vstd/std_specs/range.rs:311  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T>[ <RangeFrom<T> as RangeBounds<T>>::start_bound ]( range: &'s RangeFrom<T>, ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == SpecBound::Included(&range.start),

## RangeFrom::end_bound
- path: vstd/std_specs/range.rs:318  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T>[ <RangeFrom<T> as RangeBounds<T>>::end_bound ]( range: &'s RangeFrom<T>, ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == SpecBound::Unbounded,

## RangeTo::start_bound
- path: vstd/std_specs/range.rs:325  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T>[ <RangeTo<T> as RangeBounds<T>>::start_bound ]( range: &'s RangeTo<T>, ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == SpecBound::Unbounded,

## RangeTo::end_bound
- path: vstd/std_specs/range.rs:332  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T>[ <RangeTo<T> as RangeBounds<T>>::end_bound ]( range: &'s RangeTo<T>, ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == SpecBound::Excluded(&range.end),

## RangeInclusive::start_bound
- path: vstd/std_specs/range.rs:339  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T>[ <RangeInclusive<T> as RangeBounds<T>>::start_bound ]( range: &'s RangeInclusive<T>, ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == SpecBound::Included(&range@.start),

## RangeInclusive::end_bound
- path: vstd/std_specs/range.rs:346  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T>[ <RangeInclusive<T> as RangeBounds<T>>::end_bound ]( range: &'s RangeInclusive<T>, ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == SpecBound::Included(&range@.end),

## RangeToInclusive::start_bound
- path: vstd/std_specs/range.rs:353  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T>[ <RangeToInclusive<T> as RangeBounds<T>>::start_bound ]( range: &'s RangeToInclusive<T>, ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == SpecBound::Unbounded,

## RangeToInclusive::end_bound
- path: vstd/std_specs/range.rs:360  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T>[ <RangeToInclusive<T> as RangeBounds<T>>::end_bound ]( range: &'s RangeToInclusive<T>, ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == SpecBound::Included(&range.end),

## (Bound, Bound)::start_bound
- path: vstd/std_specs/range.rs:367  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T>[ <(Bound<T>, Bound<T>) as RangeBounds<T>>::start_bound ]( range: &'s (Bound<T>, Bound<T>), ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == spec_bound_ref(&range.0),

## (Bound, Bound)::end_bound
- path: vstd/std_specs/range.rs:374  (exec spec, assume_specification)
- trait: RangeBounds
- sig: `pub assume_specification<'s, T>[ <(Bound<T>, Bound<T>) as RangeBounds<T>>::end_bound ]( range: &'s (Bound<T>, Bound<T>), ) -> (result: Bound<&'s T>)`
- ensures: spec_bound(result) == spec_bound_ref(&range.1),

## slice_range_start
- path: vstd/std_specs/range.rs:542  (spec fn)
- sig: `pub open spec fn slice_range_start<R: RangeBoundsSpec<usize>>(range: &R) -> int`
- doc: Normalized (inclusive) start index of `range`, matching std's

## slice_range_end
- path: vstd/std_specs/range.rs:553  (spec fn)
- sig: `pub open spec fn slice_range_end<R: RangeBoundsSpec<usize>>(range: &R, len: nat) -> int`
- doc: Normalized (exclusive) end index of a range over a sequence of length `len`,

## slice_range_valid
- path: vstd/std_specs/range.rs:563  (spec fn)
- sig: `pub open spec fn slice_range_valid<R: RangeBoundsSpec<usize>>(range: &R, len: nat) -> bool`
- doc: Whether a range normalizes to `start <= end <= len`, i.e. the condition

## group_range_axioms
- path: vstd/std_specs/range.rs  (broadcast group)
- members: axiom_spec_range_next_u8 axiom_spec_range_next_u16 axiom_spec_range_next_u32 axiom_spec_range_next_u64 axiom_spec_range_next_u128 axiom_spec_range_next_usize axiom_spec_range_next_i8 axiom_spec_range_next_i16 axiom_spec_range_next_i32 axiom_spec_range_next_i64 axiom_spec_range_next_i128 axiom_spec_range_next_isize axiom_spec_range_inclusive_new

## is_ok
- path: vstd/std_specs/result.rs:130  (spec fn)
- sig: `pub open spec fn is_ok<T, E>(result: &Result<T, E>) -> bool`

## Result::is_ok
- path: vstd/std_specs/result.rs:135  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E>[ Result::<T, E>::is_ok ](r: &Result<T, E>) -> (b: bool)`
- ensures: b == is_ok(r),

## is_err
- path: vstd/std_specs/result.rs:143  (spec fn)
- sig: `pub open spec fn is_err<T, E>(result: &Result<T, E>) -> bool`

## Result::is_err
- path: vstd/std_specs/result.rs:148  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E>[ Result::<T, E>::is_err ](r: &Result<T, E>) -> (b: bool)`
- ensures: b == is_err(r),

## Result::as_ref
- path: vstd/std_specs/result.rs:155  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E>[ Result::<T, E>::as_ref ](result: &Result<T, E>) -> (r: Result< &T, &E, >)`
- ensures: r is Ok <==> result is Ok, r is Ok ==> result->Ok_0 == r->Ok_0, r is Err <==> result is Err, r is Err ==> result->Err_0 == r->Err_0,

## spec_unwrap
- path: vstd/std_specs/result.rs:169  (spec fn)
- sig: `pub open spec fn spec_unwrap<T, E: core::fmt::Debug>(result: Result<T, E>) -> T recommends result is Ok,`

## Result::unwrap
- path: vstd/std_specs/result.rs:177  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E: core::fmt::Debug>[ Result::<T, E>::unwrap ]( result: Result<T, E>, ) -> (t: T)`
- requires: result is Ok,
- ensures: t == result->Ok_0,

## spec_unwrap_err
- path: vstd/std_specs/result.rs:188  (spec fn)
- sig: `pub open spec fn spec_unwrap_err<T: core::fmt::Debug, E>(result: Result<T, E>) -> E recommends result is Err,`

## Result::unwrap_err
- path: vstd/std_specs/result.rs:196  (exec spec, assume_specification)
- sig: `pub assume_specification<T: core::fmt::Debug, E>[ Result::<T, E>::unwrap_err ]( result: Result<T, E>, ) -> (e: E)`
- requires: result is Err,
- ensures: e == result->Err_0,

## spec_expect
- path: vstd/std_specs/result.rs:207  (spec fn)
- sig: `pub open spec fn spec_expect<T, E: core::fmt::Debug>(result: Result<T, E>, msg: &str) -> T recommends result is Ok,`

## Result::expect
- path: vstd/std_specs/result.rs:215  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E: core::fmt::Debug>[ Result::<T, E>::expect ]( result: Result<T, E>, msg: &str, ) -> (t: T)`
- requires: result is Ok,
- ensures: t == result->Ok_0,

## Result::map
- path: vstd/std_specs/result.rs:226  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E, U, F: FnOnce(T) -> U>[ Result::<T, E>::map ]( result: Result<T, E>, op: F, ) -> (mapped_result: Result<U, E>)`
- requires: result.is_ok() ==> op.requires((result->Ok_0,)),
- ensures: result.is_ok() ==> mapped_result.is_ok() && op.ensures( (result->Ok_0,), mapped_result->Ok_0, ), result.is_err() ==> mapped_result == Result::<U, E>::Err(result->Err_0),

## Result::map_err
- path: vstd/std_specs/result.rs:242  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E, F, O: FnOnce(E) -> F>[Result::<T, E>::map_err](result: Result<T, E>, op: O) -> (mapped_result: Result<T, F>)`
- requires: result.is_err() ==> op.requires((result->Err_0,)),
- ensures: result.is_err() ==> mapped_result.is_err() && op.ensures( (result->Err_0,), mapped_result->Err_0, ), result.is_ok() ==> mapped_result == Result::<T, F>::Ok(result->Ok_0)

## ok
- path: vstd/std_specs/result.rs:254  (spec fn)
- sig: `pub open spec fn ok<T, E>(result: Result<T, E>) -> Option<T>`

## Result::ok
- path: vstd/std_specs/result.rs:262  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E>[ Result::<T, E>::ok ](result: Result<T, E>) -> (opt: Option<T>)`
- ensures: opt == ok(result),

## err
- path: vstd/std_specs/result.rs:270  (spec fn)
- sig: `pub open spec fn err<T, E>(result: Result<T, E>) -> Option<E>`

## Result::err
- path: vstd/std_specs/result.rs:278  (exec spec, assume_specification)
- sig: `pub assume_specification<T, E>[ Result::<T, E>::err ](result: Result<T, E>) -> (opt: Option<E>)`
- ensures: opt == err(result),

## <usizeasSliceIndex<[T
- path: vstd/std_specs/slice.rs:44  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ <usize as SliceIndex<[T]>>::index ](i: usize, slice: &[T]) -> &T`

## <RangeasSliceIndex<[T
- path: vstd/std_specs/slice.rs:56  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ <Range<usize> as SliceIndex<[T]>>::index ](i: Range<usize>, slice: &[T]) -> (r: &[T])`
- ensures: r@ == slice@.subrange(i.start as int, i.end as int),

## T
- path: vstd/std_specs/slice.rs:75  (exec spec, assume_specification)
- sig: `pub assume_specification<T, I: SliceIndex<[T]>> [<[T] as Index<I>>::index] ( slice: &[T], index: I, ) -> (output: &<I as core::slice::SliceIndex<[T]>>::Output)`
- ensures: call_ensures(<I as SliceIndex<[T]>>::index, (index, slice), output),

## <[T;N
- path: vstd/std_specs/slice.rs:83  (exec spec, assume_specification)
- sig: `pub assume_specification<T, I, const N: usize> [<[T; N] as Index<I>>::index] ( array: &[T; N], index: I, ) -> (output: &<[T; N] as core::ops::Index<I>>::Output) where [T]: Index<I>,`
- ensures: call_ensures(<[T] as Index<I>>::index, (array, index), output),

## core::hint::unreachable_unchecked
- path: vstd/std_specs/slice.rs:92  (exec spec, assume_specification)
- sig: `pub assume_specification[ core::hint::unreachable_unchecked ]() -> !`
- requires: false,

## into_iter_elts
- path: vstd/std_specs/slice.rs:106  (spec fn)
- sig: `pub uninterp spec fn into_iter_elts<'a, T: 'a>(i: Iter<'a, T>) -> Seq<T>`

## spec_slice_iter
- path: vstd/std_specs/slice.rs:140  (spec fn)
- sig: `pub uninterp spec fn spec_slice_iter<'a, T>(s: &'a [T]) -> (iter: Iter<'a, T>)`

## axiom_spec_slice_iter
- path: vstd/std_specs/slice.rs:142  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_slice_iter<'a, T>(s: &'a [T])`
- ensures: #[trigger] spec_slice_iter(s).remaining() == s@.as_ref(),

## <[T
- path: vstd/std_specs/slice.rs:150  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, T>[ <[T]>::iter ](s: &'a [T]) -> (iter: Iter<'a, T>)`
- ensures: iter == spec_slice_iter(s), IteratorSpec::decrease(&iter) is Some, IteratorSpec::initial_value_relation(&iter, &iter),

## <&'a[T
- path: vstd/std_specs/slice.rs:158  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, T> [<&'a [T] as core::iter::IntoIterator>::into_iter] (s: &'a [T]) -> (iter: Iter<'a, T>)`
- ensures: iter == spec_slice_iter(s), IteratorSpec::decrease(&iter) is Some, IteratorSpec::initial_value_relation(&iter, &iter),

## <[T
- path: vstd/std_specs/slice.rs:166  (exec spec, assume_specification)
- sig: `pub assume_specification<T> [ <[T]>::first ](slice: &[T]) -> (res: Option<&T>)`
- ensures: slice.len() == 0 ==> res.is_none(), slice.len() != 0 ==> res.is_some() && res.unwrap() == slice[0]

## <[T
- path: vstd/std_specs/slice.rs:172  (exec spec, assume_specification)
- sig: `pub assume_specification<T> [ <[T]>::last ](slice: &[T]) -> (res: Option<&T>)`
- ensures: slice.len() == 0 ==> res.is_none(), slice.len() != 0 ==> res.is_some() && res.unwrap() == slice@.last()

## <[T
- path: vstd/std_specs/slice.rs:179  (exec spec, assume_specification)
- sig: `pub assume_specification<T> [ <[T]>::first_mut ](slice: &mut [T]) -> (res: Option<&mut T>)`
- ensures: old(slice).len() == 0 ==> res.is_none() && final(slice)@ == seq![], old(slice).len() != 0 ==> res.is_some() && *res.unwrap() == old(slice)[0] && final(slice)@ == old(slice)@.update(0, *final(res.unwrap()))

## <[T
- path: vstd/std_specs/slice.rs:187  (exec spec, assume_specification)
- sig: `pub assume_specification<T> [ <[T]>::last_mut ](slice: &mut [T]) -> (res: Option<&mut T>)`
- ensures: old(slice).len() == 0 ==> res.is_none() && final(slice)@ == seq![], old(slice).len() != 0 ==> res.is_some() && *res.unwrap() == old(slice)@.last() && final(slice)@ == old(slice)@.update(old(slice).len() - 1, *final(res.unwrap()))

## <[T
- path: vstd/std_specs/slice.rs:194  (exec spec, assume_specification)
- sig: `pub assume_specification<T> [ <[T]>::split_at ](slice: &[T], mid: usize) -> (ret: (&[T], &[T]))`
- requires: 0 <= mid <= slice.len(),
- ensures: ret.0@ == slice@.subrange(0, mid as int), ret.1@ == slice@.subrange(mid as int, slice@.len() as int),

## <[T
- path: vstd/std_specs/slice.rs:203  (exec spec, assume_specification)
- sig: `pub assume_specification<T> [ <[T]>::split_at_mut ](slice: &mut [T], mid: usize) -> (ret: (&mut [T], &mut [T]))`
- requires: 0 <= mid <= slice.len(),
- ensures: ret.0@ == old(slice)@.subrange(0, mid as int), ret.1@ == old(slice)@.subrange(mid as int, old(slice)@.len() as int), final(slice)@ == final(ret.0)@ + final(ret.1)@,

## <[T
- path: vstd/std_specs/slice.rs:213  (exec spec, assume_specification)
- sig: `pub assume_specification<T: Copy>[ <[T]>::copy_from_slice ](dst: &mut [T], src: &[T])`
- requires: old(dst)@.len() == src@.len(),
- ensures: final(dst)@ == src@,
- doc: Copy the contents of `src` into `dst`, which must have the same length.

## copy_within_result
- path: vstd/std_specs/slice.rs:224  (spec fn)
- sig: `pub open spec fn copy_within_result<T>( old_slice: Seq<T>, src_start: int, src_end: int, dest: int,`
- doc: The sequence resulting from copying `old_slice[src_start..src_end]` to start

## <[T
- path: vstd/std_specs/slice.rs:243  (exec spec, assume_specification)
- sig: `pub assume_specification<T: Copy, R: core::ops::RangeBounds<usize>>[ <[T]>::copy_within::<R> ]( slice: &mut [T], src: R, dest: usize, )`
- requires: slice_range_valid(&src, old(slice)@.len()), (dest as int) + (slice_range_end(&src, old(slice)@.len()) - slice_range_start(&src)) <= old(slice)@.len(),
- ensures: final(slice)@ == copy_within_result( old(slice)@, slice_range_start(&src), slice_range_end(&src, old(slice)@.len()), dest as int,
- doc: Copy the elements in range `src` within the slice to start at index `dest`.

## group_slice_axioms
- path: vstd/std_specs/slice.rs  (broadcast group)
- members: axiom_spec_slice_iter

## <[T
- path: vstd/std_specs/smart_ptrs.rs:12  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ <[T]>::into_vec ](b: Box<[T], A>) -> (v: Vec<T, A>)`
- ensures: v@ == b@,

## Box::new
- path: vstd/std_specs/smart_ptrs.rs:17  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Box::<T>::new ](t: T) -> (v: Box<T>)`
- ensures: *v == t,

## Rc::new
- path: vstd/std_specs/smart_ptrs.rs:29  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Rc::<T>::new ](t: T) -> (v: Rc<T>)`
- ensures: *v == t,

## Arc::new
- path: vstd/std_specs/smart_ptrs.rs:41  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Arc::<T>::new ](t: T) -> (v: Arc<T>)`
- ensures: *v == t,

## Box::clone
- path: vstd/std_specs/smart_ptrs.rs:53  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification<T: Clone, A: Allocator + Clone>[ <Box<T, A> as Clone>::clone ]( b: &Box<T, A>, ) -> (res: Box<T, A>)`
- ensures: cloned::<T>(**b, *res),

## Rc::try_unwrap
- path: vstd/std_specs/smart_ptrs.rs:60  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Rc::<T, A>::try_unwrap ](v: Rc<T, A>) -> (result: Result< T, Rc<T, A>, >)`
- ensures: match result { Ok(t) => t == *v, Err(e) => e == v, },

## Rc::into_inner
- path: vstd/std_specs/smart_ptrs.rs:71  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Rc::<T, A>::into_inner ](v: Rc<T, A>) -> (result: Option< T, >)`
- ensures: result matches Some(t) ==> t == *v,

## vec_index
- path: vstd/std_specs/vec.rs:53  (fn)
- sig: `pub fn vec_index<T, A: Allocator>(vec: &Vec<T, A>, i: usize) -> (element: &T)`
- requires: i < vec.view().len(),
- ensures: *element == vec.view().index(i as int),

## vec_index_mut
- path: vstd/std_specs/vec.rs:67  (fn)
- sig: `pub fn vec_index_mut<T, A: Allocator>(vec: &mut Vec<T, A>, i: usize) -> (element: &mut T)`
- requires: i < vec.view().len(),
- ensures: *element == old(vec)@.index(i as int), final(vec)@ == old(vec)@.update(i as int, *final(element)), *final(element) == final(vec).view().index(i as int),
- doc: This is a specification for the indexing operator `vec[i]` when it expands to the `IndexMut` trait

## spec_vec_len
- path: vstd/std_specs/vec.rs:81  (spec fn)
- sig: `pub uninterp spec fn spec_vec_len<T, A: Allocator>(v: &Vec<T, A>) -> usize`
- doc: /// Len (with autospec)

## axiom_spec_len
- path: vstd/std_specs/vec.rs:85  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_len<T, A: Allocator>(v: &Vec<T, A>)`
- ensures: #[trigger] spec_vec_len(v) == v@.len(),

## Vec::len
- path: vstd/std_specs/vec.rs:93  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::len ](vec: &Vec<T, A>) -> (len: usize)`
- ensures: len == spec_vec_len(vec),

## Vec::new
- path: vstd/std_specs/vec.rs:100  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Vec::<T>::new ]() -> (v: Vec<T>)`
- ensures: v@ == Seq::<T>::empty(),
- doc: /// Other functions

## Vec::default
- path: vstd/std_specs/vec.rs:105  (exec spec, assume_specification)
- trait: core::default::Default
- sig: `pub assume_specification<T>[ <Vec<T> as core::default::Default>::default ]() -> (v: Vec<T>)`
- ensures: v@ == Seq::<T>::empty(),

## Vec::new_in
- path: vstd/std_specs/vec.rs:110  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::new_in ](alloc: A) -> (v: Vec<T, A>)`
- ensures: v@ == Seq::<T>::empty(),

## Vec::with_capacity
- path: vstd/std_specs/vec.rs:115  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ Vec::<T>::with_capacity ](capacity: usize) -> (v: Vec<T>)`
- ensures: v@ == Seq::<T>::empty(),

## Vec::with_capacity_in
- path: vstd/std_specs/vec.rs:120  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::with_capacity_in ](capacity: usize, alloc: A) -> (v: Vec<T, A>)`
- ensures: v@ == Seq::<T>::empty(),

## Vec::reserve
- path: vstd/std_specs/vec.rs:125  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::reserve ]( vec: &mut Vec<T, A>, additional: usize, )`
- ensures: final(vec)@ == old(vec)@,

## Vec::try_reserve
- path: vstd/std_specs/vec.rs:133  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::try_reserve ]( vec: &mut Vec<T, A>, additional: usize, ) -> (result: Result<(), TryReserveError>)`
- ensures: final(vec)@ == old(vec)@,

## Vec::push
- path: vstd/std_specs/vec.rs:141  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::push ](vec: &mut Vec<T, A>, value: T)`
- ensures: final(vec)@ == old(vec)@.push(value),

## Vec::pop
- path: vstd/std_specs/vec.rs:146  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::pop ](vec: &mut Vec<T, A>) -> (value: Option<T>)`
- ensures: old(vec)@.len() > 0 ==> value == Some(old(vec)@[old(vec)@.len() - 1]) && final(vec)@ == old(vec)@.subrange(0, old(vec)@.len() - 1), old(vec)@.len() == 0 ==> value == None::<T> && final(vec)@ == old(vec)@,

## Vec::append
- path: vstd/std_specs/vec.rs:154  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::append ]( vec: &mut Vec<T, A>, other: &mut Vec<T, A>, )`
- ensures: final(vec)@ == old(vec)@ + old(other)@, final(other)@ == Seq::<T>::empty(),

## Vec::extend_from_slice
- path: vstd/std_specs/vec.rs:163  (exec spec, assume_specification)
- sig: `pub assume_specification<T: core::clone::Clone, A: Allocator>[ Vec::<T, A>::extend_from_slice ]( vec: &mut Vec<T, A>, other: &[T], )`
- ensures: final(vec)@.len() == old(vec)@.len() + other@.len(), forall|i: int| #![trigger final(vec)@[i]] 0 <= i < final(vec)@.len() ==> if i < old(vec)@.len() { final(vec)@[i] == old(vec)@[i]

## T
- path: vstd/std_specs/vec.rs:184  (exec spec, assume_specification)
- sig: `pub assume_specification<T, I: SliceIndex<[T]>, A: Allocator>[Vec::<T, A>::index]( vec: &Vec<T, A>, i: I, ) -> (r: &<Vec<T, A> as Index<I>>::Output)`
- ensures: exists|s: &[T]| #[trigger] s@ == vec@ && call_ensures(<I as SliceIndex<[T]>>::index, (i, s), r),

## Vec::swap_remove
- path: vstd/std_specs/vec.rs:192  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::swap_remove ]( vec: &mut Vec<T, A>, i: usize, ) -> (element: T)`
- requires: i < old(vec).len(),
- ensures: element == old(vec)[i as int], final(vec)@ == old(vec)@.update(i as int, old(vec)@.last()).drop_last(),

## Vec::insert
- path: vstd/std_specs/vec.rs:203  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::insert ]( vec: &mut Vec<T, A>, i: usize, element: T, )`
- requires: i <= old(vec).len(),
- ensures: final(vec)@ == old(vec)@.insert(i as int, element),

## ::is_empty
- path: vstd/std_specs/vec.rs:214  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator> [ <Vec<T, A>>::is_empty ]( v: &Vec<T, A>, ) -> (res: bool)`
- ensures: res <==> v@.len() == 0,

## Vec::remove
- path: vstd/std_specs/vec.rs:220  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::remove ]( vec: &mut Vec<T, A>, i: usize, ) -> (element: T)`
- requires: i < old(vec).len(),
- ensures: element == old(vec)[i as int], final(vec)@ == old(vec)@.remove(i as int),

## Vec::clear
- path: vstd/std_specs/vec.rs:231  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::clear ](vec: &mut Vec<T, A>)`
- ensures: final(vec).view() == Seq::<T>::empty(),

## Vec::as_slice
- path: vstd/std_specs/vec.rs:236  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::as_slice ](vec: &Vec<T, A>) -> (slice: &[T])`
- ensures: slice@ == vec@,

## Vec::as_mut_slice
- path: vstd/std_specs/vec.rs:242  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::as_mut_slice ](vec: &mut Vec<T, A>) -> (slice: &mut [T])`
- ensures: slice@ == old(vec)@, final(slice)@ == final(vec)@,

## Vec::deref
- path: vstd/std_specs/vec.rs:248  (exec spec, assume_specification)
- trait: core::ops::Deref
- sig: `pub assume_specification<T, A: Allocator>[ <Vec<T, A> as core::ops::Deref>::deref ]( vec: &Vec<T, A>, ) -> (slice: &[T])`
- ensures: slice@ == vec@,

## Vec::deref_mut
- path: vstd/std_specs/vec.rs:255  (exec spec, assume_specification)
- trait: core::ops::DerefMut
- sig: `pub assume_specification<T, A: Allocator>[ <Vec<T, A> as core::ops::DerefMut>::deref_mut ]( vec: &mut Vec<T, A>, ) -> (slice: &mut [T])`
- ensures: slice@ == old(vec)@, final(slice)@ == final(vec)@,

## Vec::split_off
- path: vstd/std_specs/vec.rs:263  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator + core::clone::Clone>[ Vec::<T, A>::split_off ]( vec: &mut Vec<T, A>, at: usize, ) -> (return_value: Vec<T, A>)`
- requires: at <= old(vec)@.len(),
- ensures: final(vec)@ == old(vec)@.subrange(0, at as int), return_value@ == old(vec)@.subrange(at as int, old(vec)@.len() as int),

## vec_clone_trigger
- path: vstd/std_specs/vec.rs:274  (spec fn)
- sig: `pub open spec fn vec_clone_trigger<T, A: Allocator>(v1: Vec<T, A>, v2: Vec<T, A>) -> bool`

## Vec::clone
- path: vstd/std_specs/vec.rs:278  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification<T: Clone, A: Allocator + Clone>[ <Vec<T, A> as Clone>::clone ]( vec: &Vec<T, A>, ) -> (res: Vec<T, A>)`
- ensures: res.len() == vec.len(), forall|i| #![all_triggers] 0 <= i < vec.len() ==> cloned::<T>(vec[i], res[i]), vec_clone_trigger(*vec, res), vec@ =~= res@ ==> vec@ == res@,

## vec_clone_deep_view_proof
- path: vstd/std_specs/vec.rs:288  (proof fn)
- sig: `pub broadcast proof fn vec_clone_deep_view_proof<T: DeepView, A: Allocator>( v1: Vec<T, A>, v2: Vec<T, A>, )`
- requires: #[trigger] vec_clone_trigger(v1, v2), v1.deep_view() =~= v2.deep_view(),
- ensures: v1.deep_view() == v2.deep_view(),

## Vec::truncate
- path: vstd/std_specs/vec.rs:300  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::truncate ](vec: &mut Vec<T, A>, len: usize)`
- ensures: len <= old(vec).len() ==> final(vec)@ == old(vec)@.subrange(0, len as int), len > old(vec).len() ==> final(vec)@ == old(vec)@,

## Vec::resize
- path: vstd/std_specs/vec.rs:306  (exec spec, assume_specification)
- sig: `pub assume_specification<T: Clone, A: Allocator>[ Vec::<T, A>::resize ]( vec: &mut Vec<T, A>, len: usize, value: T, )`
- ensures: len <= old(vec).len() ==> final(vec)@ == old(vec)@.subrange(0, len as int), len > old(vec).len() ==> { &&& final(vec)@.len() == len &&& final(vec)@.subrange(0, old(vec).len() as int) == old(vec)@ &&& forall|i| #![all_triggers] old(vec).len() <= i < len ==> cloned::<T>(value, final(vec)@[i])

## axiom_vec_index_decreases
- path: vstd/std_specs/vec.rs:320  (proof fn)
- sig: `pub broadcast proof fn axiom_vec_index_decreases<A>(v: Vec<A>, i: int)`
- requires: 0 <= i < v.len(),
- ensures: #[trigger] (decreases_to!(v => v[i])),

## Vec::eq
- path: vstd/std_specs/vec.rs:343  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification<T: PartialEq<U>, U, A1: Allocator, A2: Allocator>[ <Vec<T, A1> as PartialEq<Vec<U, A2>>>::eq ]( x: &Vec<T, A1>, y: &Vec<U, A2>, ) -> bool`

## into_iter_elts
- path: vstd/std_specs/vec.rs:370  (spec fn)
- sig: `pub uninterp spec fn into_iter_elts<T, A: Allocator>(i: IntoIter<T, A>) -> Seq<T>`

## alloc::vec::from_elem
- path: vstd/std_specs/vec.rs:409  (exec spec, assume_specification)
- sig: `pub assume_specification<T: Clone>[ alloc::vec::from_elem ](elem: T, n: usize) -> (v: Vec<T>)`
- ensures: v.len() == n, forall |i| 0 <= i < n ==> cloned(elem, #[trigger] v@[i])

## spec_into_iter
- path: vstd/std_specs/vec.rs:420  (spec fn)
- sig: `pub uninterp spec fn spec_into_iter<T, A: Allocator>(v: Vec<T, A>) -> (iter: <Vec< T, A, > as core::iter::IntoIterator>::IntoIter)`

## spec_into_iter_borrowed
- path: vstd/std_specs/vec.rs:425  (spec fn)
- sig: `pub uninterp spec fn spec_into_iter_borrowed<T, A: Allocator>(v: &Vec<T, A>) -> (iter: <&Vec< T, A, > as core::iter::IntoIterator>::IntoIter)`

## axiom_spec_into_iter
- path: vstd/std_specs/vec.rs:431  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_into_iter<T, A: Allocator>(v: Vec<T, A>)`
- ensures: #[trigger] spec_into_iter(v).remaining() == v@,

## axiom_spec_into_iter_borrowed
- path: vstd/std_specs/vec.rs:438  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_into_iter_borrowed<T, A: Allocator>(v: &Vec<T, A>)`
- ensures: #[trigger] spec_into_iter_borrowed(v).remaining() == v@.as_ref(),

## Vec::into_iter
- path: vstd/std_specs/vec.rs:446  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ Vec::<T, A>::into_iter ](vec: Vec<T, A>) -> (iter: <Vec< T, A, > as core::iter::IntoIterator>::IntoIter)`
- ensures: iter == spec_into_iter(vec), IteratorSpec::decrease(&iter) is Some, IteratorSpec::initial_value_relation(&iter, &iter),

## &'a Vec::into_iter
- path: vstd/std_specs/vec.rs:457  (exec spec, assume_specification)
- trait: core::iter::IntoIterator
- sig: `pub assume_specification<'a, T, A: Allocator> [<&'a Vec<T, A> as core::iter::IntoIterator>::into_iter] (vec: &'a Vec<T, A>) -> (iter: <&'a Vec<T, A> as core::iter::IntoIterator>::IntoIter)`
- ensures: iter == spec_into_iter_borrowed(vec), IteratorSpec::decrease(&iter) is Some, IteratorSpec::initial_value_relation(&iter, &iter),

## lemma_vec_obeys_eq_spec
- path: vstd/std_specs/vec.rs:471  (proof fn)
- sig: `pub broadcast proof fn lemma_vec_obeys_eq_spec<T: PartialEq>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: super::super::laws_eq::obeys_eq::<T>(),
- ensures: #[trigger] super::super::laws_eq::obeys_eq::<Vec<T>>(),

## lemma_vec_obeys_view_eq
- path: vstd/std_specs/vec.rs:481  (proof fn)
- sig: `pub broadcast proof fn lemma_vec_obeys_view_eq<T: PartialEq + View>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: super::super::laws_eq::obeys_concrete_eq::<T>(),
- ensures: #[trigger] super::super::laws_eq::obeys_view_eq::<Vec<T>>(),

## lemma_vec_obeys_deep_eq
- path: vstd/std_specs/vec.rs:495  (proof fn)
- sig: `pub broadcast proof fn lemma_vec_obeys_deep_eq<T: PartialEq + DeepView>()`
- note: NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed); no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom).
- requires: super::super::laws_eq::obeys_deep_eq::<T>(),
- ensures: #[trigger] super::super::laws_eq::obeys_deep_eq::<Vec<T>>(),

## group_vec_axioms
- path: vstd/std_specs/vec.rs  (broadcast group)
- members: axiom_spec_len axiom_vec_index_decreases vec_clone_deep_view_proof axiom_spec_into_iter axiom_spec_into_iter_borrowed axiom_vec_has_resolved axiom_vec_decreases_to_view

## spec_vec_dequeue_len
- path: vstd/std_specs/vecdeque.rs:52  (spec fn)
- sig: `pub uninterp spec fn spec_vec_dequeue_len<T, A: Allocator>(v: &VecDeque<T, A>) -> usize`
- doc: /// Len (with autospec)

## axiom_spec_len
- path: vstd/std_specs/vecdeque.rs:56  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_len<T, A: Allocator>(v: &VecDeque<T, A>)`
- ensures: #[trigger] spec_vec_dequeue_len(v) == v@.len(),

## VecDeque::index
- path: vstd/std_specs/vecdeque.rs:69  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ VecDeque::<T, A>::index ]( v: &VecDeque<T, A>, i: usize, ) -> (result: &T)`
- ensures: result == v.spec_index(i as int),

## VecDeque::len
- path: vstd/std_specs/vecdeque.rs:78  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ VecDeque::<T, A>::len ](v: &VecDeque<T, A>) -> (len: usize)`
- ensures: len == spec_vec_dequeue_len(v),

## VecDeque::new
- path: vstd/std_specs/vecdeque.rs:84  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ VecDeque::<T>::new ]() -> (v: VecDeque<T>)`
- ensures: v@ == Seq::<T>::empty(),

## VecDeque::default
- path: vstd/std_specs/vecdeque.rs:89  (exec spec, assume_specification)
- trait: core::default::Default
- sig: `pub assume_specification<T>[ <VecDeque<T> as core::default::Default>::default ]() -> (v: VecDeque< T, >)`
- ensures: v@ == Seq::<T>::empty(),

## VecDeque::with_capacity
- path: vstd/std_specs/vecdeque.rs:96  (exec spec, assume_specification)
- sig: `pub assume_specification<T>[ VecDeque::<T>::with_capacity ](capacity: usize) -> (v: VecDeque<T>)`
- ensures: v@ == Seq::<T>::empty(),

## VecDeque::reserve
- path: vstd/std_specs/vecdeque.rs:101  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ VecDeque::<T, A>::reserve ]( v: &mut VecDeque<T, A>, additional: usize, )`
- ensures: final(v)@ == old(v)@,

## VecDeque::push_back
- path: vstd/std_specs/vecdeque.rs:109  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ VecDeque::<T, A>::push_back ]( v: &mut VecDeque<T, A>, value: T, )`
- ensures: final(v)@ == old(v)@.push(value),

## VecDeque::push_front
- path: vstd/std_specs/vecdeque.rs:117  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ VecDeque::<T, A>::push_front ]( v: &mut VecDeque<T, A>, value: T, )`
- ensures: final(v)@ == seq![value] + old(v)@,

## VecDeque::pop_back
- path: vstd/std_specs/vecdeque.rs:125  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ VecDeque::<T, A>::pop_back ]( v: &mut VecDeque<T, A>, ) -> (value: Option<T>)`
- ensures: match value { Some(x) => { &&& old(v)@.len() > 0 &&& x == old(v)@[old(v)@.len() - 1] &&& final(v)@ == old(v)@.subrange(0, old(v)@.len() as int - 1)

## VecDeque::pop_front
- path: vstd/std_specs/vecdeque.rs:142  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ VecDeque::<T, A>::pop_front ]( v: &mut VecDeque<T, A>, ) -> (value: Option<T>)`
- ensures: match value { Some(x) => { &&& old(v)@.len() > 0 &&& x == old(v)@[0] &&& final(v)@ == old(v)@.subrange(1, old(v)@.len() as int)

## VecDeque::append
- path: vstd/std_specs/vecdeque.rs:159  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ VecDeque::<T, A>::append ]( v: &mut VecDeque<T, A>, other: &mut VecDeque<T, A>, )`
- ensures: final(v)@ == old(v)@ + old(other)@, final(other)@ == Seq::<T>::empty(),

## VecDeque::insert
- path: vstd/std_specs/vecdeque.rs:168  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ VecDeque::<T, A>::insert ]( v: &mut VecDeque<T, A>, i: usize, element: T, )`
- requires: i <= old(v).len(),
- ensures: final(v)@ == old(v)@.insert(i as int, element),

## VecDeque::remove
- path: vstd/std_specs/vecdeque.rs:179  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ VecDeque::<T, A>::remove ]( v: &mut VecDeque<T, A>, i: usize, ) -> (element: Option<T>)`
- ensures: match element { Some(x) => { &&& i < old(v)@.len() &&& x == old(v)@[i as int] &&& final(v)@ == old(v)@.remove(i as int)

## VecDeque::clear
- path: vstd/std_specs/vecdeque.rs:197  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ VecDeque::<T, A>::clear ](v: &mut VecDeque<T, A>)`
- ensures: final(v).view() == Seq::<T>::empty(),

## VecDeque::split_off
- path: vstd/std_specs/vecdeque.rs:202  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator + core::clone::Clone>[ VecDeque::<T, A>::split_off ]( v: &mut VecDeque<T, A>, at: usize, ) -> (return_value: VecDeque<T, A>)`
- requires: at <= old(v)@.len(),
- ensures: final(v)@ == old(v)@.subrange(0, at as int), return_value@ == old(v)@.subrange(at as int, old(v)@.len() as int),

## vec_dequeue_clone_trigger
- path: vstd/std_specs/vecdeque.rs:213  (spec fn)
- sig: `pub open spec fn vec_dequeue_clone_trigger<T, A: Allocator>( v1: VecDeque<T, A>, v2: VecDeque<T, A>,`

## VecDeque::clone
- path: vstd/std_specs/vecdeque.rs:220  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification<T: Clone, A: Allocator + Clone>[ <VecDeque<T, A> as Clone>::clone ]( v: &VecDeque<T, A>, ) -> (res: VecDeque<T, A>)`
- ensures: res.len() == v.len(), forall|i| #![all_triggers] 0 <= i < v.len() ==> cloned::<T>(v[i], res[i]), vec_dequeue_clone_trigger(*v, res), v@ =~= res@ ==> v@ == res@,

## VecDeque::truncate
- path: vstd/std_specs/vecdeque.rs:230  (exec spec, assume_specification)
- sig: `pub assume_specification<T, A: Allocator>[ VecDeque::<T, A>::truncate ]( v: &mut VecDeque<T, A>, len: usize, )`
- ensures: len <= old(v).len() ==> final(v)@ == old(v)@.subrange(0, len as int), len > old(v).len() ==> final(v)@ == old(v)@,

## VecDeque::resize
- path: vstd/std_specs/vecdeque.rs:239  (exec spec, assume_specification)
- sig: `pub assume_specification<T: Clone, A: Allocator>[ VecDeque::<T, A>::resize ]( v: &mut VecDeque<T, A>, len: usize, value: T, )`
- ensures: len <= old(v).len() ==> final(v)@ == old(v)@.subrange(0, len as int), len > old(v).len() ==> { &&& final(v)@.len() == len &&& final(v)@.subrange(0, old(v).len() as int) == old(v)@ &&& forall|i|

## axiom_vec_dequeue_index_decreases
- path: vstd/std_specs/vecdeque.rs:255  (proof fn)
- sig: `pub broadcast proof fn axiom_vec_dequeue_index_decreases<A>(v: VecDeque<A>, i: int)`
- requires: 0 <= i < v.len(),
- ensures: #[trigger] (decreases_to!(v => v[i])),

## into_iter_elts
- path: vstd/std_specs/vecdeque.rs:273  (spec fn)
- sig: `pub uninterp spec fn into_iter_elts<'a, T: 'a>(i: Iter<'a, T>) -> Seq<&'a T>`

## spec_iter
- path: vstd/std_specs/vecdeque.rs:317  (spec fn)
- sig: `pub uninterp spec fn spec_iter<'a, T, A: Allocator>(v: &'a VecDeque<T, A>) -> (r: Iter<'a, T>)`

## axiom_spec_iter
- path: vstd/std_specs/vecdeque.rs:319  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_iter<'a, T, A: Allocator>(v: &'a VecDeque<T, A>)`
- ensures: #[trigger] spec_iter(v).remaining() == v@.as_ref(),

## VecDeque::iter
- path: vstd/std_specs/vecdeque.rs:327  (exec spec, assume_specification)
- sig: `pub assume_specification<'a, T, A: Allocator>[ VecDeque::<T, A>::iter ]( v: &'a VecDeque<T, A>, ) -> (iter: Iter<'a, T>)`
- ensures: iter == spec_iter(v), IteratorSpec::decrease(&iter) is Some, IteratorSpec::initial_value_relation(&iter, &iter),

## group_vec_dequeue_axioms
- path: vstd/std_specs/vecdeque.rs  (broadcast group)
- members: axiom_spec_len axiom_vec_dequeue_index_decreases axiom_spec_iter

## is_ascii
- path: vstd/string.rs:51  (spec fn)
- sig: `pub open spec fn is_ascii(s: &str) -> bool`

## is_ascii_spec_bytes
- path: vstd/string.rs:56  (proof fn)
- sig: `pub broadcast proof fn is_ascii_spec_bytes(s: &str)`
- ensures: #[trigger] is_ascii(s) ==> #[trigger] s.spec_bytes() =~= Seq::new( s@.len(), |i| s@.index(i) as u8, ),

## is_ascii_concat
- path: vstd/string.rs:69  (proof fn)
- sig: `pub broadcast proof fn is_ascii_concat(s1: &str, s2: &str, s3: &str)`
- requires: s1@ =~= s2@ + s3@,
- ensures: #![trigger s2@ + s3@, is_ascii(s1), is_ascii(s2), is_ascii(s3)] is_ascii(s1) <==> is_ascii(s2) && is_ascii(s3),

## str::is_ascii
- path: vstd/string.rs:85  (exec spec, assume_specification)
- sig: `pub assume_specification[ str::is_ascii ](s: &str) -> (b: bool)`
- ensures: b == is_ascii(s),

## str::to_owned
- path: vstd/string.rs:94  (exec spec, assume_specification)
- sig: `pub assume_specification[ str::to_owned ](s: &str) -> (res: String)`
- ensures: s@ == res@,

## str::as_bytes
- path: vstd/string.rs:100  (exec spec, assume_specification)
- sig: `pub assume_specification[ str::as_bytes ](s: &str) -> (b: &[u8])`
- ensures: b@ == s.spec_bytes(),

## str::len
- path: vstd/string.rs:107  (exec spec, assume_specification)
- sig: `pub assume_specification[ str::len ](s: &str) -> usize`

## str::is_empty
- path: vstd/string.rs:114  (exec spec, assume_specification)
- sig: `pub assume_specification[ str::is_empty ](s: &str) -> bool`

## str::is_char_boundary
- path: vstd/string.rs:121  (exec spec, assume_specification)
- sig: `pub assume_specification[ str::is_char_boundary ](s: &str, index: usize) -> bool`

## str::split_at
- path: vstd/string.rs:127  (exec spec, assume_specification)
- sig: `pub assume_specification[ str::split_at ](s: &str, mid: usize) -> (res: (&str, &str))`
- requires: is_char_boundary(s.spec_bytes(), mid as int),
- ensures: res.0.spec_bytes() =~= s.spec_bytes().subrange(0, mid as int), res.1.spec_bytes() =~= s.spec_bytes().subrange(mid as int, s.spec_bytes().len() as int),

## str::from_utf8_unchecked
- path: vstd/string.rs:136  (exec spec, assume_specification)
- sig: `pub assume_specification[ str::from_utf8_unchecked ](v: &[u8]) -> (res: &str)`
- requires: valid_utf8(v@),
- ensures: res.spec_bytes() =~= v@,

## to_string_from_display_ensures
- path: vstd/string.rs:144  (spec fn)
- sig: `pub uninterp spec fn to_string_from_display_ensures<T: core::fmt::Display + ?Sized>( t: &T, s: String, ) -> bool`

## to_string_from_display_ensures_for_str
- path: vstd/string.rs:150  (proof fn)
- sig: `pub broadcast proof fn to_string_from_display_ensures_for_str(t: &str, res: String)`
- ensures: #[trigger] to_string_from_display_ensures::<str>(t, res) <==> (t@ == res@),

## T::to_string
- path: vstd/string.rs:158  (exec spec, assume_specification)
- trait: ToString
- sig: `pub assume_specification<T: core::fmt::Display + ?Sized>[ <T as ToString>::to_string ]( t: &T, ) -> (res: String)`
- ensures: to_string_from_display_ensures::<T>(t, res),

## group_string_axioms
- path: vstd/string.rs  (broadcast group)
- members: axiom_str_literal_len axiom_str_literal_get_char is_ascii_spec_bytes is_ascii_concat

## group_string_axioms
- path: vstd/string.rs  (broadcast group)
- members: axiom_str_literal_len axiom_str_literal_get_char to_string_from_display_ensures_for_str axiom_spec_iter is_ascii_spec_bytes is_ascii_concat

## string_is_ascii
- path: vstd/string.rs:327  (spec fn)
- sig: `pub open spec fn string_is_ascii(s: &String) -> bool`

## String::as_str
- path: vstd/string.rs:332  (exec spec, assume_specification)
- sig: `pub assume_specification<'a>[ String::as_str ](s: &'a String) -> (res: &'a str)`
- ensures: res@ == s@,

## String::deref
- path: vstd/string.rs:339  (exec spec, assume_specification)
- trait: core::ops::Deref
- sig: `pub assume_specification<'a>[ <String as core::ops::Deref>::deref ](s: &'a String) -> (res: &'a str)`
- ensures: res@ == s@,

## String::clone
- path: vstd/string.rs:345  (exec spec, assume_specification)
- trait: Clone
- sig: `pub assume_specification[ <String as Clone>::clone ](s: &String) -> (res: String)`
- ensures: res == s,

## String::eq
- path: vstd/string.rs:351  (exec spec, assume_specification)
- trait: PartialEq
- sig: `pub assume_specification[ <String as PartialEq>::eq ](s: &String, other: &String) -> (res: bool)`
- ensures: res == (s@ == other@),

## String::new
- path: vstd/string.rs:357  (exec spec, assume_specification)
- sig: `pub assume_specification[ String::new ]() -> (res: String)`
- ensures: res@ == Seq::<char>::empty(),

## String::default
- path: vstd/string.rs:363  (exec spec, assume_specification)
- trait: core::default::Default
- sig: `pub assume_specification[ <String as core::default::Default>::default ]() -> (r: String)`
- ensures: r@ == Seq::<char>::empty(),

## into_iter_elts
- path: vstd/string.rs:432  (spec fn)
- sig: `pub uninterp spec fn into_iter_elts<'a>(i: Chars<'a>) -> Seq<char>`

## spec_iter
- path: vstd/string.rs:441  (spec fn)
- sig: `pub uninterp spec fn spec_iter<'a>(s: &'a str) -> (r: Chars<'a>)`

## axiom_spec_iter
- path: vstd/string.rs:444  (proof fn)
- sig: `pub broadcast proof fn axiom_spec_iter<'a>(s: &'a str)`
- ensures: #[trigger] spec_iter(s).remaining() == s@,

## str::chars
- path: vstd/string.rs:452  (exec spec, assume_specification)
- sig: `pub assume_specification[ str::chars ](s: &str) -> (iter: Chars<'_>)`
- ensures: iter == spec_iter(s), IteratorSpec::decrease(&iter) is Some, IteratorSpec::initial_value_relation(&iter, &iter),

## JoinHandle::predicate
- path: vstd/thread.rs:23  (spec fn)
- sig: `pub uninterp spec fn predicate(&self, ret: Ret) -> bool`
- doc: Predicate restricting the possible return values. This is determined by the

## JoinHandle::join
- path: vstd/thread.rs:27  (fn)
- sig: `pub fn join(self) -> (r_result: Result<Ret, ()>)`
- ensures: match r_result { Result::Ok(r) => self.predicate(r), Result::Err(_) => true, },
- doc: Wait for a thread to complete.

## spawn
- path: vstd/thread.rs:107  (fn)
- sig: `pub fn spawn<F, Ret>(f: F) -> (handle: JoinHandle<Ret>) where F: FnOnce() -> Ret, F: Send + 'static, Ret: Send + 'static,`
- requires: f.requires(()),
- ensures: forall|ret: Ret| #[trigger] handle.predicate(ret) ==> f.ensures((), ret),
- doc: Spawns a thread. (Wrapper around [`std::thread::spawn`](https://doc.rust-lang.org/std/thread/fn.spawn.html).)

## IsThread::view
- path: vstd/thread.rs:170  (spec fn)
- sig: `pub uninterp spec fn view(&self) -> ThreadId`

## thread_id
- path: vstd/thread.rs:200  (fn)
- sig: `pub fn thread_id() -> (res: (ThreadId, Tracked<IsThread>))`
- ensures: res.1@@ == res.0,
- doc: Gets the current thread ID using Rust's [`Thread::id()`](https://doc.rust-lang.org/std/thread/struct.Thread.html#method.id)

## ThreadShareable::view
- path: vstd/thread.rs:232  (spec fn)
- sig: `pub uninterp spec fn view(&self) -> V`

## ThreadShareable::id
- path: vstd/thread.rs:234  (spec fn)
- sig: `pub uninterp spec fn id(&self) -> ThreadId`

## IMapToken::instance_id
- path: vstd/tokens.rs:271  (spec fn)
- sig: `pub closed spec fn instance_id(self) -> InstanceId`

## IMapToken::map
- path: vstd/tokens.rs:275  (spec fn)
- sig: `pub closed spec fn map(self) -> IMap<Key, Value>`

## IMapToken::dom
- path: vstd/tokens.rs:283  (spec fn)
- sig: `pub open spec fn dom(self) -> ISet<Key>`

## IMapToken::spec_index
- path: vstd/tokens.rs:288  (spec fn)
- sig: `pub open spec fn spec_index(self, k: Key) -> Value`

## IMapToken::index
- path: vstd/tokens.rs:293  (spec fn)
- sig: `pub open spec fn index(self, k: Key) -> Value`

## MapToken::instance_id
- path: vstd/tokens.rs:386  (spec fn)
- sig: `pub closed spec fn instance_id(self) -> InstanceId`

## MapToken::map
- path: vstd/tokens.rs:390  (spec fn)
- sig: `pub closed spec fn map(self) -> Map<Key, Value>`

## MapToken::dom
- path: vstd/tokens.rs:398  (spec fn)
- sig: `pub open spec fn dom(self) -> Set<Key>`

## MapToken::spec_index
- path: vstd/tokens.rs:403  (spec fn)
- sig: `pub open spec fn spec_index(self, k: Key) -> Value`

## MapToken::index
- path: vstd/tokens.rs:408  (spec fn)
- sig: `pub open spec fn index(self, k: Key) -> Value`

## ISetToken::instance_id
- path: vstd/tokens.rs:500  (spec fn)
- sig: `pub closed spec fn instance_id(self) -> InstanceId`

## ISetToken::set
- path: vstd/tokens.rs:504  (spec fn)
- sig: `pub closed spec fn set(self) -> ISet<Element>`

## ISetToken::contains
- path: vstd/tokens.rs:511  (spec fn)
- sig: `pub open spec fn contains(self, element: Element) -> bool`

## SetToken::instance_id
- path: vstd/tokens.rs:599  (spec fn)
- sig: `pub closed spec fn instance_id(self) -> InstanceId`

## SetToken::set
- path: vstd/tokens.rs:603  (spec fn)
- sig: `pub closed spec fn set(self) -> Set<Element>`

## SetToken::contains
- path: vstd/tokens.rs:608  (spec fn)
- sig: `pub open spec fn contains(self, element: Element) -> bool`

## MultisetToken::instance_id
- path: vstd/tokens.rs:741  (spec fn)
- sig: `pub closed spec fn instance_id(self) -> InstanceId`

## MultisetToken::multiset
- path: vstd/tokens.rs:749  (spec fn)
- sig: `pub closed spec fn multiset(self) -> Multiset<Element>`

## option_value_eq_option_token
- path: vstd/tokens.rs:804  (spec fn)
- sig: `pub open spec fn option_value_eq_option_token<Value, Token: ValueToken<Value>>( opt_value: Option<Value>, opt_token: Option<Token>, instance_id: InstanceId,`

## option_value_le_option_token
- path: vstd/tokens.rs:817  (spec fn)
- sig: `pub open spec fn option_value_le_option_token<Value, Token: ValueToken<Value>>( opt_value: Option<Value>, opt_token: Option<Token>, instance_id: InstanceId,`

## bool_value_eq_option_token
- path: vstd/tokens.rs:830  (spec fn)
- sig: `pub open spec fn bool_value_eq_option_token<Token: SimpleToken>( b: bool, opt_token: Option<Token>, instance_id: InstanceId,`

## bool_value_le_option_token
- path: vstd/tokens.rs:842  (spec fn)
- sig: `pub open spec fn bool_value_le_option_token<Token: SimpleToken>( b: bool, opt_token: Option<Token>, instance_id: InstanceId,`

## is_leading_byte_width_1
- path: vstd/utf8.rs:38  (spec fn)
- sig: `pub open spec fn is_leading_byte_width_1(byte: u8) -> bool`
- doc: True when the given byte conforms to the bit pattern for the first byte of a 1-byte UTF-8 encoding of a single codepoint.

## is_leading_byte_width_2
- path: vstd/utf8.rs:44  (spec fn)
- sig: `pub open spec fn is_leading_byte_width_2(byte: u8) -> bool`
- doc: True when the given byte conforms to the bit pattern for the first byte of a 2-byte UTF-8 encoding of a single codepoint.

## is_leading_byte_width_3
- path: vstd/utf8.rs:50  (spec fn)
- sig: `pub open spec fn is_leading_byte_width_3(byte: u8) -> bool`
- doc: True when the given byte conforms to the bit pattern for the first byte of a 3-byte UTF-8 encoding of a single codepoint.

## is_leading_byte_width_4
- path: vstd/utf8.rs:56  (spec fn)
- sig: `pub open spec fn is_leading_byte_width_4(byte: u8) -> bool`
- doc: True when the given byte conforms to the bit pattern for the first byte of a 4-byte UTF-8 encoding of a single codepoint.

## is_continuation_byte
- path: vstd/utf8.rs:62  (spec fn)
- sig: `pub open spec fn is_continuation_byte(byte: u8) -> bool`
- doc: True when the given byte conforms to the bit pattern for a continuation byte of a UTF-8 encoding of a single codepoint.

## continuation_bits
- path: vstd/utf8.rs:67  (spec fn)
- sig: `pub open spec fn continuation_bits(byte: u8) -> u32 recommends is_continuation_byte(byte),`
- doc: Value of the 6 data bits from the given continuation byte, assuming that it is a valid continuation byte for a UTF-8 encoding.

## leading_bits_width_1
- path: vstd/utf8.rs:76  (spec fn)
- sig: `pub open spec fn leading_bits_width_1(byte: u8) -> u32 recommends is_leading_byte_width_1(byte),`
- doc: Value of the 7 data bits from the given byte, assuming that it is a valid leading byte for a 1-byte UTF-8 encoding.

## leading_bits_width_2
- path: vstd/utf8.rs:85  (spec fn)
- sig: `pub open spec fn leading_bits_width_2(byte: u8) -> u32 recommends is_leading_byte_width_2(byte),`
- doc: Value of the 5 data bits from the given byte, assuming that it is a valid leading byte for a 2-byte UTF-8 encoding.

## leading_bits_width_3
- path: vstd/utf8.rs:94  (spec fn)
- sig: `pub open spec fn leading_bits_width_3(byte: u8) -> u32 recommends is_leading_byte_width_3(byte),`
- doc: Value of the 4 data bits from the given byte, assuming that it is a valid leading byte for a 3-byte UTF-8 encoding.

## leading_bits_width_4
- path: vstd/utf8.rs:103  (spec fn)
- sig: `pub open spec fn leading_bits_width_4(byte: u8) -> u32 recommends is_leading_byte_width_4(byte),`
- doc: Value of the 3 data bits from the given byte, assuming that it is a valid leading byte for a 4-byte UTF-8 encoding.

## codepoint_width_1
- path: vstd/utf8.rs:112  (spec fn)
- sig: `pub open spec fn codepoint_width_1(byte1: u8) -> u32 recommends is_leading_byte_width_1(byte1),`
- doc: The codepoint encoded by the given byte, assuming that it is a valid leading byte for a 1-byte UTF-8 encoding.

## codepoint_width_2
- path: vstd/utf8.rs:125  (spec fn)
- sig: `pub open spec fn codepoint_width_2(byte1: u8, byte2: u8) -> u32 recommends is_leading_byte_width_2(byte1), is_continuation_byte(byte2),`
- doc: The codepoint encoded by the given 2 bytes, assuming that they are a valid leading and continuation byte, respectively, for 2-byte UTF-8 encoding.

## codepoint_width_3
- path: vstd/utf8.rs:134  (spec fn)
- sig: `pub open spec fn codepoint_width_3(byte1: u8, byte2: u8, byte3: u8) -> u32 recommends is_leading_byte_width_3(byte1), is_continuation_byte(byte2), is_continuation_byte(byte3),`
- doc: The codepoint encoded by the given 3 bytes, assuming that they are a valid leading and continuation bytes, respectively, for 3-byte UTF-8 encoding.

## codepoint_width_4
- path: vstd/utf8.rs:150  (spec fn)
- sig: `pub open spec fn codepoint_width_4(byte1: u8, byte2: u8, byte3: u8, byte4: u8) -> u32 recommends is_leading_byte_width_4(byte1), is_continuation_byte(byte2), is_continuation_byte(byte3), is_continuation_byte(byte4),`
- doc: The codepoint encoded by the given 4 bytes, assuming that they are a valid leading and continuation bytes, respectively, for 4-byte UTF-8 encoding.

## valid_leading_and_continuation_bytes_first_codepoint
- path: vstd/utf8.rs:163  (spec fn)
- sig: `pub open spec fn valid_leading_and_continuation_bytes_first_codepoint(bytes: Seq<u8>) -> bool`
- doc: True when the given byte sequence begins with a well-formed leading byte and an appropriate number of well-formed continuation bytes for a UTF-8 encoding of a single codepoint.

## decode_first_codepoint
- path: vstd/utf8.rs:173  (spec fn)
- sig: `pub open spec fn decode_first_codepoint(bytes: Seq<u8>) -> u32 recommends valid_leading_and_continuation_bytes_first_codepoint(bytes),`
- doc: Returns the first codepoint encoded in UTF-8 in the given byte sequence, assuming that the sequence begins with a well-formed leading byte and an appropriate number of well-formed continuation bytes.

## length_of_first_codepoint
- path: vstd/utf8.rs:189  (spec fn)
- sig: `pub open spec fn length_of_first_codepoint(bytes: Seq<u8>) -> int recommends valid_leading_and_continuation_bytes_first_codepoint(bytes),`
- doc: The length in bytes of the first codepoint encoded in UTF-8 in the given byte sequence, assuming that the sequence begins with a well-formed leading byte and an appropriate number of well-formed continuation bytes.

## not_overlong_encoding
- path: vstd/utf8.rs:206  (spec fn)
- sig: `pub open spec fn not_overlong_encoding(codepoint: u32, len: int) -> bool`
- doc: True when the given codepoint, when encoded in UTF-8 using `len` number of bytes, would not be an "overlong encoding".

## not_surrogate
- path: vstd/utf8.rs:214  (spec fn)
- sig: `pub open spec fn not_surrogate(codepoint: u32) -> bool`
- doc: True when the given codepoint does not fall into the "surrogate range" of the Unicode standard.

## valid_first_scalar
- path: vstd/utf8.rs:221  (spec fn)
- sig: `pub open spec fn valid_first_scalar(bytes: Seq<u8>) -> bool`
- doc: True when the given byte sequence begins with a well-formed UTF-8 encoding of a single scalar.

## decode_first_scalar
- path: vstd/utf8.rs:228  (spec fn)
- sig: `pub open spec fn decode_first_scalar(bytes: Seq<u8>) -> u32 recommends valid_first_scalar(bytes),`
- doc: The first scalar encoded in UTF-8 in the given byte sequence, assuming that the sequence begins with a well-formed encoding of a single scalar.

## length_of_first_scalar
- path: vstd/utf8.rs:236  (spec fn)
- sig: `pub open spec fn length_of_first_scalar(bytes: Seq<u8>) -> int recommends valid_first_scalar(bytes),`
- doc: The length in bytes of first scalar encoded in UTF-8 in the given byte sequence, assuming that the sequence begins with a well-formed encoding of a single scalar.

## pop_first_scalar
- path: vstd/utf8.rs:244  (spec fn)
- sig: `pub open spec fn pop_first_scalar(bytes: Seq<u8>) -> Seq<u8> recommends valid_first_scalar(bytes),`
- doc: Removes the first scalar encoded in UTF-8 in the given byte sequence and returns the rest of the sequence, assuming that the sequence begins with a well-formed encoding of a single scalar.

## take_first_scalar
- path: vstd/utf8.rs:264  (spec fn)
- sig: `pub open spec fn take_first_scalar(bytes: Seq<u8>) -> Seq<u8> recommends valid_first_scalar(bytes),`
- doc: Takes the bytes corresponding to the first scalar encoded in UTF-8 in the given byte sequence, assuming that the sequence begins with a well-formed encoding of a single scalar.

## valid_utf8
- path: vstd/utf8.rs:272  (spec fn)
- sig: `pub open spec fn valid_utf8(bytes: Seq<u8>) -> bool`
- doc: True when the given bytes form a valid UTF-8 encoding.

## decode_utf8
- path: vstd/utf8.rs:279  (spec fn)
- sig: `pub open spec fn decode_utf8(bytes: Seq<u8>) -> Seq<char> recommends valid_utf8(bytes),`
- doc: The sequence of characters encoded as Unicode scalars in the given bytes, assuming that the bytes form a valid UTF-8 encoding.

## length_of_last_scalar
- path: vstd/utf8.rs:293  (spec fn)
- sig: `pub open spec fn length_of_last_scalar(bytes: Seq<u8>) -> int recommends valid_utf8(bytes), bytes.len() > 0,`
- doc: The length in bytes of the last scalar encoded in UTF-8 in the given byte sequence, assuming that the bytes form a valid UTF-8 encoding.

## take_last_scalar
- path: vstd/utf8.rs:311  (spec fn)
- sig: `pub open spec fn take_last_scalar(bytes: Seq<u8>) -> Seq<u8> recommends valid_utf8(bytes), bytes.len() > 0,`
- doc: Takes the bytes corresponding to the last scalar encoded in UTF-8 in the given byte sequence, assuming that the bytes form a valid UTF-8 encoding.

## decode_last_scalar
- path: vstd/utf8.rs:321  (spec fn)
- sig: `pub open spec fn decode_last_scalar(bytes: Seq<u8>) -> u32 recommends valid_utf8(bytes), bytes.len() > 0,`
- doc: The last scalar encoded in UTF-8 in the given byte sequence, assuming that the bytes form a valid UTF-8 encoding.

## has_width_1_encoding
- path: vstd/utf8.rs:341  (spec fn)
- sig: `pub open spec fn has_width_1_encoding(v: u32) -> bool`
- doc: True when the given value is a Unicode scalar with a 1-byte UTF-8 encoding.

## has_width_2_encoding
- path: vstd/utf8.rs:346  (spec fn)
- sig: `pub open spec fn has_width_2_encoding(v: u32) -> bool`
- doc: True when the given value is a Unicode scalar with a 2-byte UTF-8 encoding.

## has_width_3_encoding
- path: vstd/utf8.rs:351  (spec fn)
- sig: `pub open spec fn has_width_3_encoding(v: u32) -> bool`
- doc: True when the given value is a Unicode scalar with a 3-byte UTF-8 encoding.

## has_width_4_encoding
- path: vstd/utf8.rs:356  (spec fn)
- sig: `pub open spec fn has_width_4_encoding(v: u32) -> bool`
- doc: True when the given value is a Unicode scalar with a 4-byte UTF-8 encoding.

## is_scalar
- path: vstd/utf8.rs:362  (spec fn)
- sig: `pub open spec fn is_scalar(v: u32) -> bool`
- doc: True when the given `u32` represents a Unicode scalar, i.e., a value that can be encoded in UTF-8.

## leading_byte_width_1
- path: vstd/utf8.rs:370  (spec fn)
- sig: `pub open spec fn leading_byte_width_1(scalar: u32) -> u8 recommends has_width_1_encoding(scalar),`
- doc: The first (and only) byte of the UTF-8 encoding of the given scalar value, assuming that the scalar has a 1-byte UTF-8 encoding.

## leading_byte_width_2
- path: vstd/utf8.rs:378  (spec fn)
- sig: `pub open spec fn leading_byte_width_2(scalar: u32) -> u8 recommends has_width_2_encoding(scalar),`
- doc: The first byte of the UTF-8 encoding of the given scalar value, assuming that the scalar has a 2-byte UTF-8 encoding.

## leading_byte_width_3
- path: vstd/utf8.rs:386  (spec fn)
- sig: `pub open spec fn leading_byte_width_3(scalar: u32) -> u8 recommends has_width_3_encoding(scalar),`
- doc: The first byte of the UTF-8 encoding of the given scalar value, assuming that the scalar has a 3-byte UTF-8 encoding.

## leading_byte_width_4
- path: vstd/utf8.rs:394  (spec fn)
- sig: `pub open spec fn leading_byte_width_4(scalar: u32) -> u8 recommends has_width_4_encoding(scalar),`
- doc: The first byte of the UTF-8 encoding of the given scalar value, assuming that the scalar has a 4-byte UTF-8 encoding.

## last_continuation_byte
- path: vstd/utf8.rs:402  (spec fn)
- sig: `pub open spec fn last_continuation_byte(scalar: u32) -> u8 recommends has_width_2_encoding(scalar) || has_width_3_encoding(scalar) || has_width_4_encoding( scalar, ),`
- doc: The last continuation byte of the UTF-8 encoding of the given scalar value, assuming that the scalar has a 2, 3, or 4-byte UTF-8 encoding.

## second_last_continuation_byte
- path: vstd/utf8.rs:412  (spec fn)
- sig: `pub open spec fn second_last_continuation_byte(scalar: u32) -> u8 recommends has_width_3_encoding(scalar) || has_width_4_encoding(scalar),`
- doc: The second-to-last continuation byte of the UTF-8 encoding of the given scalar value, assuming that the scalar has a 3 or 4-byte UTF-8 encoding.

## third_last_continuation_byte
- path: vstd/utf8.rs:420  (spec fn)
- sig: `pub open spec fn third_last_continuation_byte(scalar: u32) -> u8 recommends has_width_4_encoding(scalar),`
- doc: The third-to-last continuation byte of the UTF-8 encoding of the given scalar value, assuming that the scalar has a 4-byte UTF-8 encoding.

## encode_scalar
- path: vstd/utf8.rs:428  (spec fn)
- sig: `pub open spec fn encode_scalar(scalar: u32) -> Seq<u8> recommends is_scalar(scalar),`
- doc: The UTF-8 encoding of the given value, assuming that it is a Unicode scalar.

## encode_utf8
- path: vstd/utf8.rs:453  (spec fn)
- sig: `pub open spec fn encode_utf8(chars: Seq<char>) -> Seq<u8>`
- doc: The UTF-8 encoding of the given `char` sequence.

## char_is_scalar
- path: vstd/utf8.rs:606  (proof fn)
- sig: `pub broadcast proof fn char_is_scalar(c: char)`
- ensures: is_scalar(#[trigger] (c as u32)),
- doc: A `char` always represents a Unicode scalar value.

## char_u32_cast
- path: vstd/utf8.rs:613  (proof fn)
- sig: `pub broadcast proof fn char_u32_cast(c: char, u: u32)`
- requires: u == #[trigger] (c as u32),
- ensures: #[trigger] (u as char) == c,
- doc: Ensures that a `char`, when cast to a `u32`, can be cast back to a `char`.

## encode_utf8_valid_utf8
- path: vstd/utf8.rs:644  (proof fn)
- sig: `pub broadcast proof fn encode_utf8_valid_utf8(chars: Seq<char>)`
- ensures: valid_utf8(#[trigger] encode_utf8(chars)),
- doc: Ensures the result of [`encode_utf8`] always satisfies [`valid_utf8`].

## encode_utf8_decode_utf8
- path: vstd/utf8.rs:659  (proof fn)
- sig: `pub broadcast proof fn encode_utf8_decode_utf8(chars: Seq<char>)`
- ensures: #[trigger] decode_utf8(encode_utf8(chars)) == chars,
- doc: Ensures that performing [`encode_utf8`] followed by [`decode_utf8`] results in the original `char` sequence.

## decode_utf8_encode_utf8
- path: vstd/utf8.rs:698  (proof fn)
- sig: `pub broadcast proof fn decode_utf8_encode_utf8(bytes: Seq<u8>)`
- requires: valid_utf8(bytes),
- ensures: #[trigger] encode_utf8(decode_utf8(bytes)) == bytes,
- doc: Ensures that performing [`decode_utf8`] followed by [`encode_utf8`] results in the original byte sequence.

## partial_valid_utf8
- path: vstd/utf8.rs:726  (spec fn)
- sig: `pub open spec fn partial_valid_utf8(bytes: Seq<u8>, i: int) -> bool`
- doc: True when the first `i` bytes in the given sequence represent a valid UTF-8 encoding.

## valid_utf8_concat
- path: vstd/utf8.rs:774  (proof fn)
- sig: `pub broadcast proof fn valid_utf8_concat(b1: Seq<u8>, b2: Seq<u8>)`
- requires: #[trigger] valid_utf8(b1), #[trigger] valid_utf8(b2),
- ensures: #[trigger] valid_utf8(b1 + b2),
- doc: Ensures that concatenating two valid UTF-8 byte sequence results in a valid UTF-8 byte sequence.

## partial_valid_utf8_extend
- path: vstd/utf8.rs:796  (proof fn)
- sig: `pub broadcast proof fn partial_valid_utf8_extend(bytes: Seq<u8>, i: int)`
- requires: #[trigger] partial_valid_utf8(bytes, i), #[trigger] valid_first_scalar(bytes.subrange(i, bytes.len() as int)),
- ensures: #[trigger] partial_valid_utf8( bytes, i + length_of_first_scalar(bytes.subrange(i, bytes.len() as int)), ),
- doc: Ensures that if the prefix of a byte sequence is valid UTF-8, and remainder of the sequence begins with a valid UTF-8 encoding of a single scalar,

## partial_valid_utf8_extend_ascii_block
- path: vstd/utf8.rs:820  (proof fn)
- sig: `pub broadcast proof fn partial_valid_utf8_extend_ascii_block(bytes: Seq<u8>, start: int, end: int)`
- requires: forall|i: int| 0 <= start <= i < end <= bytes.len() ==> #[trigger] is_leading_byte_width_1(bytes[i]), partial_valid_utf8(bytes, start), 0 <= start <= end <= bytes.len(),
- ensures: #![trigger partial_valid_utf8(bytes, start), partial_valid_utf8(bytes, end)] partial_valid_utf8(bytes, end),
- doc: Ensures that if the prefix of a byte sequence is valid UTF-8, and remainder of the sequence begins with a subsequence of valid UTF-8 encodings for 1-byte scalars (i.e. ASCII characters),

## is_char_boundary
- path: vstd/utf8.rs:844  (spec fn)
- sig: `pub open spec fn is_char_boundary(bytes: Seq<u8>, index: int) -> bool recommends valid_utf8(bytes),`
- doc: True when the given index into the byte sequence is the first byte of a character's encoding or the end of the sequence, assuming that the sequence is valid UTF-8.

## valid_utf8_split
- path: vstd/utf8.rs:869  (proof fn)
- sig: `pub broadcast proof fn valid_utf8_split(bytes: Seq<u8>, index: int)`
- requires: valid_utf8(bytes), is_char_boundary(bytes, index),
- ensures: #![trigger valid_utf8(bytes.subrange(0, index)), is_char_boundary(bytes, index)] #![trigger valid_utf8(bytes.subrange(index, bytes.len() as int)), is_char_boundary(bytes, index)] valid_utf8(bytes.subrange(0, index)), valid_utf8(bytes.subrange(index, bytes.len() as int)),
- doc: Ensures that the two subsequences formed by splitting a valid UTF-8 byte sequence at a character boundary are also valid UTF-8 byte sequences.

## decode_utf8_split
- path: vstd/utf8.rs:910  (proof fn)
- sig: `pub broadcast proof fn decode_utf8_split(bytes: Seq<u8>, index: int)`
- requires: valid_utf8(bytes), is_char_boundary(bytes, index),
- ensures: #![trigger decode_utf8(bytes.subrange(0, index)), is_char_boundary(bytes, index)] #![trigger decode_utf8(bytes.subrange(index, bytes.len() as int)), is_char_boundary(bytes, index)] decode_utf8(bytes) =~= decode_utf8(bytes.subrange(0, index)) + decode_utf8( bytes.subrange(index, bytes.len() as int), ),
- doc: Ensures that a valid UTF-8 byte sequence can be decoded by separately decoding the two subsequences formed by splitting the original sequence at a character boundary.

## is_char_boundary_start_end_of_seq
- path: vstd/utf8.rs:951  (proof fn)
- sig: `pub broadcast proof fn is_char_boundary_start_end_of_seq(bytes: Seq<u8>)`
- requires: valid_utf8(bytes),
- ensures: #![trigger is_char_boundary(bytes, 0)] #![trigger is_char_boundary(bytes, bytes.len() as int)] is_char_boundary(bytes, 0), is_char_boundary(bytes, bytes.len() as int),
- doc: Ensures that the start and end of a valid UTF-8 byte sequence are character boundaries.

## is_char_boundary_iff_not_is_continuation_byte
- path: vstd/utf8.rs:968  (proof fn)
- sig: `pub broadcast proof fn is_char_boundary_iff_not_is_continuation_byte(bytes: Seq<u8>, index: int)`
- requires: valid_utf8(bytes), 0 <= index < bytes.len(),
- ensures: #[trigger] is_char_boundary(bytes, index) <==> !(#[trigger] is_continuation_byte( bytes[index], )),
- doc: Ensures that any byte in a valid UTF-8 byte sequence falls on a character boundary (i.e. the first byte in a codepoint's encoding) if and only if it does not have the form of a UTF-8 continuation byte.

## is_char_boundary_iff_is_leading_byte
- path: vstd/utf8.rs:989  (proof fn)
- sig: `pub broadcast proof fn is_char_boundary_iff_is_leading_byte(bytes: Seq<u8>, index: int)`
- requires: valid_utf8(bytes), 0 <= index < bytes.len(),
- ensures: #![trigger is_char_boundary(bytes, index), is_leading_byte_width_1(bytes[index])] #![trigger is_char_boundary(bytes, index), is_leading_byte_width_2(bytes[index])] #![trigger is_char_boundary(bytes, index), is_leading_byte_width_3(bytes[index])] #![trigger is_char_boundary(bytes, index), is_leading_byte_width_4(bytes[index])] is_char_boundary(bytes, index) <==> (is_leading_byte_width_1(bytes[index])
- doc: Ensures that any byte in a valid UTF-8 byte sequence falls on a character boundary (i.e. the first byte in a codepoint's encoding) if and only if it has the form of a UTF-8 leading byte.

## valid_utf8_last
- path: vstd/utf8.rs:1013  (proof fn)
- sig: `pub broadcast proof fn valid_utf8_last(s: Seq<u8>)`
- requires: valid_utf8(s), s.len() > 0,
- ensures: #![trigger is_continuation_byte(s.last())] #![trigger is_leading_byte_width_1(s.last())] !is_continuation_byte(s.last()) ==> is_leading_byte_width_1(s.last()),

## utf8_byte_ranges_bitwise
- path: vstd/utf8.rs:1040  (proof fn)
- sig: `pub broadcast proof fn utf8_byte_ranges_bitwise(b: u8) by (bit_vector)`
- ensures: #![trigger b & 0x80] #![trigger b & 0xf0] #![trigger b & 0xf8] #![trigger b & 0xe0] #![trigger b & 0xc0]
- doc: Formulates the byte ranges for each type of byte in UTF-8 (leading and continuation) in terms of bitwise operators instead of ranges.

## is_ascii_chars
- path: vstd/utf8.rs:1059  (spec fn)
- sig: `pub open spec fn is_ascii_chars(chars: Seq<char>) -> bool`
- doc: True when the given character sequence only contains ASCII characters.

## is_ascii_chars_encode_utf8
- path: vstd/utf8.rs:1064  (proof fn)
- sig: `pub broadcast proof fn is_ascii_chars_encode_utf8(chars: Seq<char>)`
- requires: #[trigger] is_ascii_chars(chars),
- ensures: chars.len() == encode_utf8(chars).len(), forall|i| #![trigger chars[i]] #![trigger encode_utf8(chars)[i]] 0 <= i < chars.len() ==> chars[i] as u8 == encode_utf8(chars)[i],
- doc: Ensures that the UTF-8 encoding for an ASCII character sequence has the same length of the original sequence and corresponds byte-by-byte to the characters in the original sequence.

## is_ascii_chars_nat_bound
- path: vstd/utf8.rs:1087  (proof fn)
- sig: `pub broadcast proof fn is_ascii_chars_nat_bound(chars: Seq<char>)`
- ensures: #[trigger] is_ascii_chars(chars) ==> forall|i: int| 0 <= i < chars.len() ==> (chars.index(i) as nat) < 128,
- doc: Ensures that all characters in an ASCII character sequence have a numerical representation that falls in the range 0 (inclusive) to 128 (exclusive).

## is_ascii_chars_concat
- path: vstd/utf8.rs:1095  (proof fn)
- sig: `pub broadcast proof fn is_ascii_chars_concat(c1: Seq<char>, c2: Seq<char>, c3: Seq<char>)`
- requires: c1 =~= c2 + c3,
- ensures: #![trigger c2 + c3, is_ascii_chars(c1), is_ascii_chars(c2), is_ascii_chars(c3)] is_ascii_chars(c1) <==> is_ascii_chars(c2) && is_ascii_chars(c3),
- doc: Ensures that an ASCII character sequence is formed by the concatenation of two ASCII character sequences.

## group_utf8_lib
- path: vstd/utf8.rs  (broadcast group)
- members: encode_utf8_valid_utf8 encode_utf8_decode_utf8 decode_utf8_encode_utf8 char_is_scalar char_u32_cast valid_utf8_concat partial_valid_utf8_extend partial_valid_utf8_extend_ascii_block valid_utf8_split decode_utf8_split is_char_boundary_start_end_of_seq is_char_boundary_iff_not_is_continuation_byte is_char_boundary_iff_is_leading_byte valid_utf8_last utf8_byte_ranges_bitwise is_ascii_chars_encode_utf8 is_ascii_chars_nat_bound is_ascii_chars_concat

## group_vstd_default
- path: vstd/vstd.rs  (broadcast group)
- members: // // basic Verus math, types, and features // seq::group_seq_lemmas seq_lib::group_seq_lib_default map::group_map_lemmas set::group_set_lemmas imap::group_imap_lemmas iset::group_iset_lemmas set_lib::group_set_lib_default multiset::group_multiset_axioms compute::all_spec_ensures function::group_function_axioms laws_eq::group_laws_eq laws_cmp::group_laws_cmp // // Rust types // slice::group_slice_axioms array::group_array_axioms #[cfg(not(verus_verify_core))] string::group_string_axioms raw_ptr::group_raw_ptr_axioms layout::group_layout_axioms // // core std_specs // std_specs::range::group_range_axioms std_specs::bits::group_bits_axioms std_specs::control_flow::group_control_flow_axioms std_specs::slice::group_slice_axioms std_specs::manually_drop::group_manually_drop_axioms std_specs::iter::group_iter_axioms // // std_specs for alloc (with or without std) // #[cfg(feature = "alloc")] std_specs::vec::group_vec_axioms #[cfg(feature = "alloc")] std_specs::vecdeque::group_vec_dequeue_axioms // // std_specs for alloc + std // #[cfg(all(feature = "alloc", feature = "std"))] std_specs::hash::group_hash_axioms #[cfg(feature = "alloc")] std_specs::btree::group_btree_axioms // // std_specs for nonzero_internals // #[cfg(feature = "nonzero_internals")] std_specs::nonzero::group_nonzero_axioms

## wrapping_add
- path: vstd/wrapping.rs:18  (spec fn)
- sig: `pub open spec fn wrapping_add(x: $uN, y: $uN) -> $uN`

## wrapping_add_signed
- path: vstd/wrapping.rs:26  (spec fn)
- sig: `pub open spec fn wrapping_add_signed(x: $uN, y: $iN) -> $uN`

## wrapping_sub
- path: vstd/wrapping.rs:36  (spec fn)
- sig: `pub open spec fn wrapping_sub(x: $uN, y: $uN) -> $uN`

## wrapping_mul
- path: vstd/wrapping.rs:44  (spec fn)
- sig: `pub open spec fn wrapping_mul(x: $uN, y: $uN) -> $uN`

## wrapping_shl
- path: vstd/wrapping.rs:48  (spec fn)
- sig: `pub open spec fn wrapping_shl(x: $uN, shift: u32) -> $uN`

## wrapping_shr
- path: vstd/wrapping.rs:51  (spec fn)
- sig: `pub open spec fn wrapping_shr(x: $uN, shift: u32) -> $uN`

## wrapping_add
- path: vstd/wrapping.rs:59  (spec fn)
- sig: `pub open spec fn wrapping_add(x: $iN, y: $iN) -> $iN`

## wrapping_add_unsigned
- path: vstd/wrapping.rs:69  (spec fn)
- sig: `pub open spec fn wrapping_add_unsigned(x: $iN, y: $uN) -> $iN`

## wrapping_sub
- path: vstd/wrapping.rs:77  (spec fn)
- sig: `pub open spec fn wrapping_sub(x: $iN, y: $iN) -> $iN`

## signed_crop
- path: vstd/wrapping.rs:87  (spec fn)
- sig: `pub open spec fn signed_crop(x: int) -> $iN`

## wrapping_mul
- path: vstd/wrapping.rs:95  (spec fn)
- sig: `pub open spec fn wrapping_mul(x: $iN, y: $iN) -> $iN`

## wrapping_shl
- path: vstd/wrapping.rs:99  (spec fn)
- sig: `pub open spec fn wrapping_shl(x: $iN, shift: u32) -> $iN`

## wrapping_shr
- path: vstd/wrapping.rs:102  (spec fn)
- sig: `pub open spec fn wrapping_shr(x: $iN, shift: u32) -> $iN`
