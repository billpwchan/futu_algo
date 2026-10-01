# Architecture

This document explains how futu_algo is put together, the guarantees it makes and what it
does not model. Read it before trusting a number or letting the engine trade.

## Module map

```
src/futu_algo/
├── config.py          one YAML file validated by pydantic; secrets via environment variables
├── futu_gateway.py    lazy OpenQuoteContext, per-API rate limits, retries, RSA encryption
├── market/            instruments and sessions, trading calendar, HKEX tick table, dated costs
├── data/              bar schema, Parquet cache with coverage, Futu source, session resampling
├── indicators/        TDX-exact formula functions (MA, EMA, recursive SMA, KDJ, RSI, MACD, ...)
├── strategy/          Strategy API, registry, built-in strategies, look-ahead check
├── backtest/          simulator, metrics, runner and JSON/CSV reports
├── live/              engine, executor, brokers (Futu, local sim), bar feed, risk, SQLite state
├── screener/          Futu server-side screening + optional strategy confirmation
├── notify/            email and Telegram channels, event routing
├── events.py          in-process event bus (engine -> notifier, web console, audit log)
├── app.py             application container, background jobs, daily scheduler
├── web/               FastAPI JSON API + static single-page console
├── demo/              simulated OpenD and synthetic HK market (tests and --demo)
└── cli.py             the futu-algo command
```

## One strategy, two runtimes

A strategy is two vectorised, causal steps: `indicators(bars)` and `signals(bars, ind)`, where
a signal is `1` (be long), `0` (be flat) or `NaN` (no opinion). The backtester runs them over
the whole history once; the live engine calls `decide_last(window)` on every completed bar.
Because the functions are causal, the value at the last bar of a window is exactly the value
the backtest computed for that bar. `check_lookahead` enforces causality on every backtest by
recomputing on truncated history.

Both runtimes apply the same entry rules:

- **Fresh signal.** A symbol whose signal is already `1` when trading starts, or right after a
  stop, target or max-hold exit, waits until the signal leaves `1` before it can be bought
  again. Without this, state-style strategies would buy mid-trend on day one.
- **Slots.** `max_positions` counts held symbols (excluding those being sold) plus working buys.
- **Timing.** A decision at bar *t*'s close becomes an order at once; the backtester fills it at
  bar *t+1*'s open. The live engine only sends orders in continuous trading, so a decision made
  on the 12:00 bar is sent at 13:00 and one made on the 16:00 bar at 09:30 the next day.

The test suite replays two days of real one-minute bars through the live engine (with the
local simulated broker filling at the next bar's open) and through the backtester, and asserts
that every fill (symbol, side, quantity, time, price), the total fees and the final equity are
identical, for five strategies.

## Live engine

```
Futu OpenD ──K-line push──► FutuBarFeed ──► BarAssembler ──completed bar──► engine queue
                                                                                │
         ┌────────────── worker thread ─────────────────────────────────────────┘
         ▼
 sync(): executor.sync ─► broker.orders() ─► new fills ─► SQLite + FILL event
         refresh account/positions, day rollover, daily-loss halt, flatten-before-close
 on_bar(): window += bar ─► strategy.decide_last ─► entry/exit rules ─► intent
 executor: intent ─► quote ─► tick-rounded limit ─► risk check ─► broker.place
           timeout ─► cancel ─► re-price (max_replaces) ─► give up + REJECTION event
```

**Completed bars.** Futu pushes the in-progress bar, labelled with its end time, whenever it
changes. The assembler finalises a bar when a push for a later bar arrives, or when the clock
passes the bar's end plus `bar_grace_seconds`. The clock rule is what finalises the 12:00 and
16:00 bars, where no next bar arrives for an hour or a night. A daily bar is final after the
closing auction (16:10). Pushes for an already-final bar are ignored. A safety-net poll re-reads
the last bars every 30 seconds in case a push was lost. Non-native timeframes (10M, 2H, ...) are
assembled with the same session-anchored buckets the backtester uses.

**Warm-up.** On start the engine subscribes first (Futu serves `get_cur_kline` only for
subscribed symbols), then seeds each window from the subscription cache (up to 1,000 bars) and,
when that is not enough, from the local Parquet cache.

**Orders.** Prices come from a market snapshot (no subscription quota). `aggressive` crosses the
spread, rounding buys up and sells down on the HKEX tick table in force that day. Paper accounts
receive order pushes but no deal pushes, so fills are derived from each order's cumulative
filled quantity on every sync; pushes only trigger an early sync. Trade queries use OpenD's
cache and force a refresh at most every 20 seconds, which keeps within Futu's 10-per-30-seconds
limit on refreshed queries.

**State and restarts.** SQLite (WAL) holds signals, intents, orders, fills, equity snapshots,
events and small key/value state (entry blocks, bars held, peaks, kill switch, the day's
starting equity). On restart, working intents are re-adopted with their orders; orders are
tagged `futu_algo:<intent id>` in Futu's remark field so they can be matched even if the
database was lost.

**Risk.** Every order passes `RiskManager.check`: continuous session only, daily order count,
price band against the last price, and no selling more than is sellable. Entries additionally
face the kill switch, the no-entries-before-close window, per-order and per-position value caps,
total exposure, buying power and the daily loss limit. Exits are never blocked by entry limits.
Breaching the daily loss limit halts entries until the next trading day.

**Environments.** `SIMULATE` (Futu paper account) is the default and the only environment this
release is validated for. `dry_run` fills locally against live quotes and sends nothing to
Futu. `REAL` requires `trading.allow_real: true` **and** `FUTU_ALGO_ALLOW_REAL=1`.

## Backtester

Bars of all symbols are merged on their close time. At each step: pending sells fill at the
open, then pending buys; resting stops and targets are checked against the bar's range (stop
first if both are inside); positions are marked at the close; the strategy's signal at the
close creates the next order. Quantities are whole board lots; buys shrink lot by lot until
price plus fees fits the budget, so cash never goes negative. Slippage is expressed in HKEX
ticks. HK statutory fees (stamp duty, trading fee, SFC and AFRC levies, settlement) follow the
schedule in force on the trade date; broker fees default to Futu HK's fixed plan.

## Screener

Stage one runs on Futu's servers through `get_stock_filter` and costs no historical K-line
quota, which matters because screening the whole HK market by downloading bars would exhaust a
100-300 symbol quota in one run. Stage two (optional) runs a strategy on cached daily bars for
at most `max_confirm` candidates.

## Web console security

The console binds to 127.0.0.1 by default and refuses a non-local bind without a token. With a
token, every API call must present it (header, cookie set from `/?token=`, or `?token=` for the
event stream). Every state-changing request must carry `X-Futu-Algo: 1`; browsers cannot add
that header cross-site without a CORS preflight, which the server never approves, so another
website cannot drive the engine through a visitor's browser. Pages are served with a strict
Content-Security-Policy (no inline scripts, no third-party origins).

## Known limitations

- **Stops in live trading** are evaluated on completed bars (a bar's low touching the stop
  triggers a sell), while the backtester fills stops intrabar at the level. Live exits can
  therefore be later and worse than backtested ones.
- **Opening auction.** The backtester can fill at the 09:30 auction bar's open; the live engine
  only trades in continuous sessions.
- **Board lots are today's.** Futu does not provide lot-size history; override per symbol with
  `data.lot_sizes` for older backtests.
- **Adjusted prices** (qfq) are used for signals and backtest fills; live orders trade raw
  prices.
- **Ad-hoc closures** (typhoon, black rainstorm) come from Futu's trading-day list only if Futu
  records them; otherwise the engine simply sees no bars.
- **Quotas.** Subscriptions and historical K-line requests count against Futu quotas that
  depend on account tier (100 to 2,000). Subscription quota is shared by every program using
  the same Futu account.
- **REAL trading** is implemented but not validated in this release.
