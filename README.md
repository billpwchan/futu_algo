<div align="center">
  <img alt="Billerikay Logo" src="https://raw.githubusercontent.com/billpwchan/futu_algo/master/docs/img/author-logo.png" width="400px" />

**billpwchan/futu-algo API Reference Documentation**

[![Issues](https://img.shields.io/github/issues/billpwchan/futu_algo?style=for-the-badge)](https://github.com/billpwchan/futu_algo/issues)
[![License](https://img.shields.io/github/license/billpwchan/futu_algo?style=for-the-badge)](https://github.com/billpwchan/futu_algo/blob/master/LICENSE)
[![Downloads](https://img.shields.io/github/downloads/billpwchan/futu_algo/total?style=for-the-badge)](https://github.com/billpwchan/futu_algo)
[![CommitActivity](https://img.shields.io/github/commit-activity/m/billpwchan/futu_algo?style=for-the-badge)](https://github.com/billpwchan/futu_algo/commits/master)
[![RepoSize](https://img.shields.io/github/repo-size/billpwchan/futu_algo?style=for-the-badge)](https://github.com/billpwchan/futu_algo)
[![Languages](https://img.shields.io/github/languages/top/billpwchan/futu_algo?style=for-the-badge)](https://github.com/billpwchan/futu_algo)

</div>

## Features

- Developed based on FutoOpenD and FutuOpenAPI
- Low-latency Trading Support (up to 1M level)

## Issues

- [x] ~~[ADX & RSI Trading Strategy Support](https://github.com/billpwchan/futu_algo/issues/1)~~

## Releases

**Important:** all the 2.x releases are deployed to npm and can be used via jsdeliver:

- particular release,
  e.g. `v2.0.0-alpha.15`: https://cdn.jsdelivr.net/npm/redoc@2.0.0-alpha.17/bundles/redoc.standalone.js
- `next` release: https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js

Additionally, all the 1.x releases are hosted on our GitHub Pages-based CDN **(deprecated)**:

- particular release, e.g. `v1.2.0`: https://rebilly.github.io/ReDoc/releases/v1.2.0/redoc.min.js
- `v1.x.x` release: https://rebilly.github.io/ReDoc/releases/v1.x.x/redoc.min.js
- `latest` release: https://rebilly.github.io/ReDoc/releases/latest/redoc.min.js - it will point to latest 1.x.x release
  since 2.x releases are not hosted on this CDN but on unpkg.

## Version Guidance

| ReDoc Release | Futu OpenAPI Specification |
|:--------------|:---------------------------|
| 0.0.1-alpha.x | 4.0                  |

## Deployment

### Pre-Requisite: Configuration File (Config.ini)

```ini
[FutuOpenD.Config]
Host = <OpenD Host>
Port = <OpenD Port>
WebSocketPort = <OpenD WebSocketPort>
WebSocketKey = <OpenD WebSocketKey>
TrdEnv : <SIMULATE or REAL>

[FutuOpenD.Credential]
Username : <Futu Login Username>
Password_md5 : <Futu Login Password Md5 Value>

[FutuOpenD.DataFormat]
HistoryDataFormat : ["code","time_key","open","close","high","low","pe_ratio","turnover_rate","volume","turnover","change_rate","last_close"]
SubscribedDataFormat : None

[Database]
Database_path : <Your SQLite Database File Path>
```

**IMPORTANT NOTE:** The format may be changed in later commits. Please refer to this README if exception is raised.

### 1. Install Dependencies

Install using [pip](https://pypi.org/project/pip/):

    pip install -r requirements.txt

or using [conda](https://docs.conda.io/en/latest/):

    conda install --file requirements. txt

### 2. Install FutuOpenD

For **Windows/MacOS/CentOS/Ubuntu**:

https://www.futunn.com/download/OpenAPI

### 3. Download Data (e.g. 1M Data for max. 2 Years)

For **Windows**:

    python main.py -u

For **MacOS/Linux**:

    python3 main.py -u

### 4. Enjoy :smile:

## Common Examples

Update all `K_1M` and `K_DAY` interval historical K-line data

    python main.py -u   /   python main.py --update

**IMPORTANT NOTE:** This will not override existing historical data if the file exists.

If you want to refresh all data, use the following command instead (WITH CAUTION!)

    python main.py -fu  /   python main.py --force_update

Store all data from CSV to SQLite Database

    python main.py -d   /   python main.py --database

Execute High-Frequency Trading (HFT) with a Pre-defined Strategy

    python main.py -s MACD_Cross    /   python main.py --strategy MACD_Cross

-----------

## Contributor

[Bill Chan -- Main Developer](https://github.com/billpwchan/)