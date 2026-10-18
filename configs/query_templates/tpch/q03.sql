-- params: segment VARCHAR, day DATE
SELECT
    l_orderkey,
    sum(l_extendedprice * (1 - l_discount)) AS revenue,
    o_orderdate,
    o_shippriority
FROM
    customer,
    orders,
    lineitem
WHERE
    c_mktsegment = $segment
    AND c_custkey = o_custkey
    AND l_orderkey = o_orderkey
    AND o_orderdate < $day
    AND l_shipdate > $day
GROUP BY
    l_orderkey,
    o_orderdate,
    o_shippriority
ORDER BY
    revenue DESC,
    o_orderdate
LIMIT 10
