# ClickHouse 日行情 CSV 导入

当前样例 `data/证券行情表数据.csv` 为 **GB18030 编码、带表头的 17 列 CSV**，共 50,374 条数据。导入脚本会校验完整表头，避免列错位或漏列。

| CSV 字段 | ClickHouse 字段 | 类型/处理 |
|---|---|---|
| SecuMarket | secu_market | UInt8 |
| SecuCode | secu_code | String，保留前导零 |
| SecuAbbr | secu_abbr | String |
| ChiName | chi_name | String |
| ID | id | UInt64 |
| InnerCode | inner_code_raw | String，保留 CSV 原文 |
| TradingDay | trading_day | Date |
| PrevClosePrice | prev_close_price | Decimal(18,4) |
| OpenPrice | open_price | Decimal(18,4) |
| HighPrice | high_price | Decimal(18,4) |
| LowPrice | low_price | Decimal(18,4) |
| ClosePrice | close_price | Decimal(18,4) |
| TurnoverVolume | turnover_volume | UInt64 |
| TurnoverValue | turnover_value | Decimal(24,2) |
| TurnoverDeals | turnover_deals_raw | String，保留 CSV 原文 |
| XGRQ | xgrq_raw | String，保留 CSV 原文 |
| JSID | jsid | UInt64 |

注意：当前 CSV 中 `InnerCode` 显示为类似 `1924/5/1 0:00` 的日期文本，`TurnoverDeals` 和 `XGRQ` 部分值显示为类似时间的文本。这些字段在源文件中可能已经被表格软件的单元格格式改变，脚本按原文保存，不猜测或转换可能已经丢失的原始值。若需要准确的 InnerCode、成交笔数和 XGRQ，请从上游以未格式化的原始数据重新导出。

## 建表

在 ClickHouse 客户端执行 [建表 SQL](../sql/clickhouse/001_create_stock_daily_quotes.sql)：

```powershell
clickhouse-client --host qq5273175.dsmynas.com --port 8123 --user admin --password --multiquery --queries-file sql/clickhouse/001_create_stock_daily_quotes.sql
```

提示输入密码，不要把密码写进命令历史或代码文件。建表使用 MergeTree，按月份分区、按市场/证券代码/交易日排序。

## 安装与导入

项目依赖为 `clickhouse-connect`：

```powershell
pip install -e .
$env:CLICKHOUSE_PASSWORD = '<ClickHouse 密码>'
python scripts/import_stock_quotes.py data/2026年全年行情.csv
```

默认连接 `qq5273175.dsmynas.com:8123`、用户 `admin`，目标表 `market_data.stock_daily_quotes`。可通过 `CLICKHOUSE_HOST`、`CLICKHOUSE_PORT`、`CLICKHOUSE_USER`、`CLICKHOUSE_PASSWORD`、`CLICKHOUSE_DATABASE`、`CLICKHOUSE_TABLE` 覆盖默认值，也可用同名命令行参数指定连接。默认每批 5,000 行并追加数据；全量重导时加 `--truncate` 清空目标表后导入。

## 样例验证

用前 10 行验证连接、类型转换和插入，不导入整份文件：

```powershell
python scripts/import_stock_quotes.py data/证券行情表数据.csv --limit 10 --truncate
```

验证后清空这 10 行，保留空表：

```powershell
clickhouse-client --host qq5273175.dsmynas.com --port 8123 --user admin --password --query "TRUNCATE TABLE market_data.stock_daily_quotes"
```

查看当前行数和日期范围：

```sql
SELECT count(), min(trading_day), max(trading_day)
FROM market_data.stock_daily_quotes;
```
