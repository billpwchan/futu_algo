-- Schema for the current 17-column, GB18030 CSV export.
CREATE DATABASE IF NOT EXISTS market_data;

CREATE TABLE IF NOT EXISTS market_data.stock_daily_quotes
(
    secu_market       UInt8,
    secu_code         String,
    secu_abbr         String,
    chi_name          String,
    id                UInt64,
    inner_code_raw    String,
    trading_day       Date,
    prev_close_price  Decimal(18, 4),
    open_price        Decimal(18, 4),
    high_price        Decimal(18, 4),
    low_price         Decimal(18, 4),
    close_price       Decimal(18, 4),
    turnover_volume   UInt64,
    turnover_value    Decimal(24, 2),
    turnover_deals_raw String,
    xgrq_raw          String,
    jsid              UInt64
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(trading_day)
ORDER BY (secu_market, secu_code, trading_day)
SETTINGS index_granularity = 8192;
