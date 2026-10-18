-- params: ship_lo DATE, ship_hi DATE, disc_lo DECIMAL(15,2), disc_hi DECIMAL(15,2), quantity DECIMAL(15,2)
SELECT
    sum(l_extendedprice * l_discount) AS revenue
FROM
    lineitem
WHERE
    l_shipdate >= $ship_lo
    AND l_shipdate < $ship_hi
    AND l_discount BETWEEN $disc_lo
    AND $disc_hi
    AND l_quantity < $quantity
