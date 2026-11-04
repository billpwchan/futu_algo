WITH
    -- 前200个成交额最大的股票
    eligible AS
    (
        SELECT
            secu_market,
            secu_code,
            round(avg(turnover_value)/10000/10000, 1) AS avg_turnover_value
        FROM market_data.stock_daily_quotes
        WHERE trading_day >= today() - 60
        GROUP BY secu_market, secu_code
        ORDER BY avg(turnover_value) DESC
        LIMIT 200
    ),
    --每日涨跌幅,也是取前200个成交额最大的股票
    returns AS
    (
        SELECT
            secu_market,
            secu_code,
            trading_day,
            toFloat64(close_price) / nullIf(toFloat64(prev_close_price), 0) - 1
                AS daily_return
        FROM market_data.stock_daily_quotes
        WHERE trading_day >= today() - 365
          AND prev_close_price > 0
          AND (secu_market, secu_code) IN
          (
              SELECT secu_market, secu_code
              FROM eligible
          )
    )
SELECT
    a.secu_market AS market_a,
    a.secu_code AS stock_a,
    b.secu_market AS market_b,
    b.secu_code AS stock_b,
    countIf(
        (a.daily_return > 0 AND b.daily_return > 0)
        OR (a.daily_return < 0 AND b.daily_return < 0)
    ) AS same_direction_days,
    countIf(a.daily_return != 0 AND b.daily_return != 0) AS comparable_days,
    round(
        same_direction_days / nullIf(comparable_days, 0),
        4
    ) AS same_direction_probability,
    round(corr(a.daily_return, b.daily_return), 4) AS return_correlation
FROM returns AS a
INNER JOIN returns AS b
    ON a.trading_day = b.trading_day
WHERE (a.secu_market, a.secu_code) < (b.secu_market, b.secu_code)
GROUP BY
    market_a,
    stock_a,
    market_b,
    stock_b
HAVING comparable_days >= 120
   AND same_direction_probability >= 0.80
ORDER BY
    same_direction_probability DESC,
    return_correlation DESC
LIMIT 100;