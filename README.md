<div align="center">
  <img alt="Billerikay Logo" src="https://raw.githubusercontent.com/billpwchan/futu_algo/master/docs/img/author-logo.png" width="400px" />

**billpwchan/futu-algo API Reference Documentation**

[![Issues](https://img.shields.io/github/issues/billpwchan/futu_algo?style=for-the-badge)](https://github.com/billpwchan/futu_algo/issues)
[![License](https://img.shields.io/github/license/billpwchan/futu_algo?style=for-the-badge)](https://github.com/billpwchan/futu_algo/blob/master/LICENSE)
[![Downloads](https://img.shields.io/github/downloads/billpwchan/futu_algo/total?style=for-the-badge)](https://github.com/billpwchan/futu_algo)
[![CommitActivity](https://img.shields.io/github/commit-activity/y/billpwchan/futu_algo?style=for-the-badge)](https://github.com/billpwchan/futu_algo/commits/master)
[![RepoSize](https://img.shields.io/github/repo-size/billpwchan/futu_algo?style=for-the-badge)](https://github.com/billpwchan/futu_algo)
[![Languages](https://img.shields.io/github/languages/top/billpwchan/futu_algo?style=for-the-badge)](https://github.com/billpwchan/futu_algo)

</div>

## Features

- Developed based on FutoOpenD and FutuOpenAPI
- Auto-Download Historical K-Line Data (up to 1M level for max. 2 years, or 1D level for max. 10 years)
- Low-latency Trading Support (up to 1M level)
- Daily Stock Filtering and Email Notification
- Strategy Backtesting and Reporting

## Issues

- [x] ~~[ADX & RSI Trading Strategy Support](https://github.com/billpwchan/futu_algo/issues/1)~~

## Releases

**Important:** Program still in Alpha Phase now.

## Version Guidance

| FutuAlgo Release | Futu OpenAPI Specification |
|:-----------------|:---------------------------|
| 0.0.2-alpha.x    | 4.0                        |

## Deployment

### Pre-Requisite: Configuration File (Config.ini)

```ini
[FutuOpenD.Config]
Host = <OpenD Host>
Port = <OpenD Port>
WebSocketPort = <OpenD WebSocketPort>
WebSocketKey = <OpenD WebSocketKey>
TrdEnv = <SIMULATE or REAL>

[FutuOpenD.Credential]
Username = <Futu Login Username>
Password_md5 = <Futu Login Password Md5 Value>

[FutuOpenD.DataFormat]
HistoryDataFormat = ["code","time_key","open","close","high","low","pe_ratio","turnover_rate","volume","turnover","change_rate","last_close"]
SubscribedDataFormat = None

[Database]
Database_path = <Your SQLite Database File Path>

[TradePreference]
Lot_size_multiplier = <# of Stocks to Buy per Signal>
StockList = <Subscribed Stocks in List Format>

[Backtesting.Commission.HK]
Fixed_Charge = <Fixed Transaction Fee and Tax in HKD - 15.5>
Perc_Charge = <Percentage Transaction Fee in % - 0.1097>

[Email]
Port = <Server SMTP Setting>
Smtp_server = <Server SMTP Setting>
Sender = <Sender Email Address - account1@example.com>
Login = <Sender Email Address - account1@example.com>
Password = <Sender Email Password>
SubscriptionList = ["account1@example.com", "account2@example.com"]
```

**IMPORTANT NOTE:** The format may be changed in later commits. Please refer to this README if exception is raised.

### 1. Install Dependencies

Install using [conda](https://docs.conda.io/en/latest/):

    conda create --name <env> --file requirements.txt

### 2. Install FutuOpenD

For **Windows/MacOS/CentOS/Ubuntu**:

https://www.futunn.com/download/OpenAPI

Please do make sure that you have at least a LV1 subscription level on your interested quotes. For details, please refer
to https://openapi.futunn.com/futu-api-doc/qa/quote.html

### 3. Initialize SQLite Database

Go to [SQLite official website](https://www.sqlite.org/quickstart.html) and follow the QuickStart instruction to install
SQLite tools in the device.

Create a folder named 'database' in the root folder, and execute the SQLite DDL file stored in *./util/database_ddl.sql*
.

```
./
  ├── database
  │       └── stock_data.sqlite
```

### 4. Download Data (e.g. 1M Data for max. 2 Years)

For **Windows**:

    python main.py -u

For **MacOS/Linux**:

    python3 main.py -u

### 4. Enjoy :smile:

## Usages

Update all `K_1M` and `K_DAY` interval historical K-line data

    python main.py -u   /   python main.py --update

**IMPORTANT NOTE:** This will not override existing historical data if the file exists.

If you want to refresh all data, use the following command instead (WITH CAUTION!)

    python main.py -fu  /   python main.py --force_update

Store all data from CSV to SQLite Database

    python main.py -d   /   python main.py --database

Execute High-Frequency Trading (HFT) with a Pre-defined Strategy

    python main.py -s MACD_Cross    /   python main.py --strategy MACD_Cross

Execute Stock Filtering with Pre-defined Filtering Strategies

    python main.py -f Volume_Threshold Price_Threshold   /   python main.py --filter Volume_Threshold Price_Threshold

-----------

## Contributor

[Bill Chan -- Main Developer](https://github.com/billpwchan/)