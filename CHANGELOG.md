# Changelog

## 2.0.0 (2026-10)

A full rewrite as the installable package `futu_algo` (`pip install -e .`, command
`futu-algo`). The 1.x code (`main.py`, `main_backend.py`, `engines/`, `strategies/`,
`filters/`, the PySide6 GUI, `config.ini`, the committed `data/` folder) is removed; it remains
in the git history at `a0ba0fd`. Nothing is backwards compatible: configuration moved from
`config.ini` + `stock_strategy_map.yml` to one YAML file (`futu-algo init` writes a commented
one).

### Why 1.x was replaced

Each item below was reproduced against futu-api 10.11 and pandas 3.0 before the rewrite.

**It no longer ran.** futu-api 10.3 (2026-04) removed `OpenHKTradeContext`; every entry point
imports `engines/__init__.py`, which imports it, so the CLI, the GUI and the tests all failed with
`ImportError`. `requirements.txt` did not pin futu-api, so any fresh install hit this.

**Live trading could open positions but not close them.** `OrderEngine.place_sell_order`
compared the whole positions DataFrame with `0` and raised `TypeError` whenever a position was
held. The trading loop called it synchronously, so the first sell signal crashed the process and
left the position open. `is_valid_quantity` called a non-existent `logger.err` on its error path.

**Other live-loop defects.** The loop busy-polled `get_cur_kline` without sleeping and unlocked
the trade account on every iteration; it checked trading hours once at start-up and never
handled the lunch break or the close; it subscribed only the first 150 symbols but iterated all
of them; it always bought exactly one board lot (`LotSizeMultiplier` and `MaxPercPerAsset` were
read only by the backtester); there was no persistent state, no reconciliation with the broker,
no risk limit and no notification of fills.

**Strategies.** `EMA_Ribbon` compared a bar with itself (`A > B and A <= B`) and could never
trade. MACD, KDJ and RSI were correct: replaying 2022-04-13 one-minute bars, their signals
match the 2.0 implementations (MACD 11/11 buys and sells, KDJ 4/4 and 5/5, RSI 19/19 and 13/14).

**Backtester.** It used `DataFrame.append` (removed in pandas 2.0), passed date strings to
`.strftime`, wrote a hard-coded `HK.01997` debug CSV and used fixed 2019-2021 dates, so it could
not run.

**Screener.** With `--market HK CHINA` it tested the whole `args.market` list instead of the
current market, so the HK result was overwritten by the A-share result, the second iteration
screened US stocks, and the email went out twice; without `--market` it crashed. The "top 30
HSI constituents" came from scraping a Yahoo page that no longer has the table (the HSI has 93
constituents since May 2026 anyway).

**Configuration and engineering.** The config was read at import time and silently fell back to
the template's placeholder account; passwords sat in plain text in `config.ini`; the TuShare
client was created at class definition, so every user needed a TuShare token. The GUI was an
unfinished PyDracula template (about 40,000 generated lines plus 300 icons) whose dependencies
were not declared. The repository shipped a Windows/Python 3.8 TA-Lib wheel that nothing used,
a Windows-only conda environment pinned to Python 3.8 (end of life), and CI that installed
unpinned dependencies on 3.8.

### New in 2.0

- **Package and tooling.** `src/` layout, Python 3.11+, pandas 2.2 or 3, futu-api 10.4+;
  ruff, mypy, pytest (hand-computed fees, accounting invariants, property tests, parity tests)
  and GitHub Actions CI including browser tests.
- **Data.** Parquet cache with coverage tracking; Futu history paging, per-API rate limits and
  a quota guard; adjusted-price consistency re-downloads; session-aware resampling to any
  minute multiple; no caching of bars still in progress.
- **Strategies.** TDX-exact indicator library (`MA`, `EMA`, recursive `SMA`, `KDJ`, `RSI`,
  `MACD`, `DMI`, `BOLL`, `ATR`, `ZIG`, ...), a strategy API with pydantic parameters, a
  look-ahead detector, and `macd`, `kdj`, `rsi`, `ma_cross`, `ema_ribbon` (fixed), `boll`,
  `donchian`. User strategies load from files.
- **Backtesting.** Next-open fills in whole board lots, dated HK statutory costs plus Futu
  broker fees, HKEX tick-table slippage, stop/trailing/take-profit/max-hold exits, portfolio
  and scan modes, benchmark metrics and JSON/CSV reports.
- **Live paper trading.** Event-driven engine on Futu K-line pushes (bars finalised on the next
  push or by the clock at lunch and the close), the same strategy code and entry rules as the
  backtester, target intents turned into tick-rounded limit orders with timeout/re-price,
  reconciliation by polling (paper accounts get no deal pushes), pre-trade risk checks and a
  kill switch, SQLite state that survives restarts, and a local `dry_run` broker.
  `OpenSecTradeContext` with an explicit `security_firm`. REAL trading is gated behind two
  explicit switches.
- **Screener.** Futu server-side filters (price, liquidity, valuation, financials, MA/MACD/KDJ/
  RSI/BOLL patterns, custom indicator comparisons) with no K-line quota, plus optional
  confirmation by a strategy on daily bars.
- **Notifications.** Email (SMTP, STARTTLS/SSL) and Telegram for fills, rejections, errors,
  risk events, daily summaries and screener results.
- **Web console.** Dashboard, watchlist, live charts, backtest runner and report viewer,
  screener, orders, data cache, config editor and event log; token auth and CSRF protection.
- **Demo mode.** `futu-algo web --demo` runs everything against a simulated OpenD and a
  synthetic market, so the console can be explored without a Futu account.

### Dropped

A-share screening via TuShare and Yahoo Finance data (screening now uses Futu's own screener),
the PySide6 desktop GUI (replaced by the web console), the SQLite `DatabaseInterface`
(deprecated in 1.x), and the cx_Freeze Windows build.
