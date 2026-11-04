"""Import the complete 17-column UTF-8 daily quote CSV into ClickHouse."""

from __future__ import annotations

import argparse
import csv
import itertools
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

COLUMNS = (
    "secu_market",
    "secu_code",
    "secu_abbr",
    "chi_name",
    "id",
    "inner_code_raw",
    "trading_day",
    "prev_close_price",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "turnover_volume",
    "turnover_value",
    "turnover_deals_raw",
    "xgrq_raw",
    "jsid",
)

EXPECTED_HEADER = (
    "SecuMarket",
    "SecuCode",
    "SecuAbbr",
    "ChiName",
    "ID",
    "InnerCode",
    "TradingDay",
    "PrevClosePrice",
    "OpenPrice",
    "HighPrice",
    "LowPrice",
    "ClosePrice",
    "TurnoverVolume",
    "TurnoverValue",
    "TurnoverDeals",
    "XGRQ",
    "JSID",
)


def parse_date(value: str) -> date:
    """Parse the date portion of values such as 2026/10/26 0:00."""
    return date.fromisoformat(value.strip().split()[0].replace("/", "-"))


def parse_row(row: list[str], line_number: int) -> tuple[Any, ...]:
    if len(row) != len(COLUMNS):
        raise ValueError(f"第 {line_number} 行应有 17 列，实际为 {len(row)} 列")
    try:
        return (
            int(row[0]),
            row[1].strip(),
            row[2].strip(),
            row[3].strip(),
            int(row[4]),
            row[5].strip(),
            parse_date(row[6]),
            Decimal(row[7]),
            Decimal(row[8]),
            Decimal(row[9]),
            Decimal(row[10]),
            Decimal(row[11]),
            int(row[12]),
            Decimal(row[13]),
            row[14].strip(),
            row[15].strip(),
            int(row[16]),
        )
    except (ValueError, ArithmeticError) as exc:
        raise ValueError(f"第 {line_number} 行字段格式错误: {exc}") from exc


def iter_batches(reader: Any, batch_size: int):
    batch = []
    for line_number, row in enumerate(reader, start=2):
        batch.append(parse_row(row, line_number))
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", nargs="?", default="data/证券行情表数据.csv")
    parser.add_argument("--host", default=os.getenv("CLICKHOUSE_HOST", "qq5273175.dsmynas.com"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CLICKHOUSE_PORT", "8123")))
    parser.add_argument("--user", default=os.getenv("CLICKHOUSE_USER", "admin"))
    parser.add_argument("--password", default=os.getenv("CLICKHOUSE_PASSWORD", ""))
    parser.add_argument("--database", default=os.getenv("CLICKHOUSE_DATABASE", "market_data"))
    parser.add_argument("--table", default=os.getenv("CLICKHOUSE_TABLE", "stock_daily_quotes"))
    parser.add_argument("--encoding", default="utf-8-sig", help="默认 UTF-8，可兼容 UTF-8 BOM")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--limit", type=int, help="最多导入指定行数，适合样例验证")
    parser.add_argument("--truncate", action="store_true", help="导入前清空目标表")
    args = parser.parse_args()

    if args.batch_size <= 0:
        parser.error("--batch-size 必须大于 0")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit 必须大于 0")
    csv_path = Path(args.csv_file)
    if not csv_path.is_file():
        parser.error(f"CSV 文件不存在: {csv_path}")
    if not args.database.replace("_", "").isalnum() or not args.table.replace("_", "").isalnum():
        parser.error("数据库名和表名只允许字母、数字、下划线")

    try:
        import clickhouse_connect
    except ImportError:
        parser.error("缺少 clickhouse-connect，请先运行 pip install -e .")

    client = clickhouse_connect.get_client(
        host=args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        database=args.database,
    )
    target = f"`{args.database}`.`{args.table}`"
    try:
        client.query("SELECT 1")
        if args.truncate:
            client.command(f"TRUNCATE TABLE {target}")

        inserted = 0
        with csv_path.open("r", encoding=args.encoding, newline="") as source:
            reader = csv.reader(source)
            try:
                header = tuple(next(reader))
            except StopIteration:
                parser.error("CSV 文件为空")
            if header != EXPECTED_HEADER:
                raise ValueError(
                    "CSV 表头与预期的 17 列不一致。"
                    f"\n预期: {EXPECTED_HEADER}\n实际: {header}"
                )
            data_rows = itertools.islice(reader, args.limit) if args.limit else reader
            for batch in iter_batches(data_rows, args.batch_size):
                client.insert(target, batch, column_names=list(COLUMNS))
                inserted += len(batch)
                print(f"已导入 {inserted} 行", file=sys.stderr)

        print(f"导入完成，共 {inserted} 行到 {target}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
