"""``futu-algo`` command line.

    futu-algo init config.yaml             write a commented starter config (+ .env.example)
    futu-algo check -c config.yaml         validate config and test the OpenD connection
    futu-algo web -c config.yaml           web console (add --engine to start trading)
    futu-algo web --demo                   web console on a simulated OpenD, no account needed
    futu-algo trade -c config.yaml         run the paper-trading engine headless
    futu-algo backtest -c config.yaml      run the configured backtest (flags override)
    futu-algo replay -c config.yaml        replay cached bars through the live engine
    futu-algo screen -c config.yaml -p X   run a screener preset
    futu-algo data fetch|list|quota        manage the local bar cache
    futu-algo strategies                   list strategies and parameters
    futu-algo account|positions|orders     inspect the Futu account
    futu-algo cancel-all | flatten         emergency order/position controls
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from futu_algo import __version__
from futu_algo.config import EXAMPLE_CONFIG, AppConfig, apply_overrides, load_config, secret
from futu_algo.errors import FutuAlgoError
from futu_algo.logging_setup import setup_logging

log = logging.getLogger("futu_algo.cli")

ENV_EXAMPLE = """\
# Secrets for futu_algo. Copy to .env next to your config (never commit it).
FUTU_TRADE_PASSWORD_MD5=
FUTU_ALGO_SMTP_PASSWORD=
FUTU_ALGO_TELEGRAM_TOKEN=
FUTU_ALGO_WEB_TOKEN=
# Only if you deliberately enable REAL trading (trading.allow_real: true):
# FUTU_ALGO_ALLOW_REAL=1
"""


# --------------------------------------------------------------------------- helpers


def _load(args: argparse.Namespace) -> AppConfig:
    cfg = load_config(args.config)
    cfg = apply_overrides(cfg, getattr(args, "set", None) or [])
    return cfg


def _setup(cfg: AppConfig, args: argparse.Namespace, bus: Any = None) -> None:
    level = "DEBUG" if getattr(args, "verbose", False) else cfg.logging.level
    setup_logging(level, cfg.path(cfg.logging.dir) if cfg.logging.dir else None, bus)


def _pct(x: Any) -> str:
    return "" if x is None or x != x else f"{x:+.2%}"


def _num(x: Any, digits: int = 2) -> str:
    return "" if x is None or x != x else f"{x:,.{digits}f}"


def _table(rows: list[dict[str, Any]], cols: list[str]) -> str:
    if not rows:
        return "(none)"
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    line = "  ".join(c.ljust(widths[c]) for c in cols)
    out = [line, "  ".join("-" * widths[c] for c in cols)]
    out += ["  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols) for r in rows]
    return "\n".join(out)


def _parse_params(items: list[str] | None) -> dict[str, Any]:
    import yaml

    out: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise FutuAlgoError(f"Parameter {item!r} must look like name=value")
        k, v = item.split("=", 1)
        out[k.strip()] = yaml.safe_load(v)
    return out


# --------------------------------------------------------------------------- commands


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if target.exists() and not args.force:
        print(f"{target} exists; use --force to overwrite", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(EXAMPLE_CONFIG, target)
    env_example = target.parent / ".env.example"
    if not env_example.exists():
        env_example.write_text(ENV_EXAMPLE, encoding="utf-8")
    print(f"Wrote {target} and {env_example}. Edit trading.universe, then run: futu-algo check -c {target}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    cfg = _load(args)
    _setup(cfg, args)
    from futu_algo.app import App

    print(f"Config OK: {cfg.source_path}")
    print(f"  trading: {cfg.trading.env}/{cfg.trading.mode}, {cfg.trading.timeframe}, {len(cfg.trading.symbols)} symbol(s)")
    app = App(cfg)
    ok = True
    try:
        app.check_real_allowed()
    except FutuAlgoError as exc:
        print(f"  REAL trading gate: {exc}")
        ok = False
    try:
        _, state = app.gateway.call("default", "get_global_state", lambda ctx: ctx.get_global_state())
        print(f"  OpenD quote connection OK at {cfg.futu.host}:{cfg.futu.port}: market_hk={state.get('market_hk')}, logined={state.get('qot_logined')}")
        quota = app.data.source.quota()
        if quota:
            print(f"  history K-line quota: {quota.used} used, {quota.remaining} remaining")
        if cfg.trading.symbols:
            inst = app.instruments(cfg.trading.symbols)
            for sym, i in inst.items():
                print(f"    {sym} {i.name} lot {i.lot_size}")
    except FutuAlgoError as exc:
        print(f"  OpenD quote connection FAILED: {exc}")
        ok = False
    if cfg.trading.mode == "paper":
        try:
            from futu_algo.live.futu_broker import FutuBroker

            broker = FutuBroker(host=cfg.futu.host, port=cfg.futu.port, env=cfg.trading.env,
                                security_firm=cfg.futu.security_firm,
                                password_md5=os.environ.get(cfg.futu.trade_password_md5_env),
                                encrypt=bool(cfg.futu.rsa_private_key))
            broker.connect()
            acct = broker.account()
            print(f"  {cfg.trading.env} account {broker.acc_id}: equity {acct.equity:,.2f} {acct.currency}, cash {acct.cash:,.2f}")
            broker.close()
        except FutuAlgoError as exc:
            print(f"  Trade connection FAILED: {exc}")
            ok = False
    for name in ("email", "telegram"):
        ch = getattr(cfg.notify, name)
        if ch.enabled:
            has_credential = bool(secret(ch.password_env if name == "email" else ch.token_env))
            print(f"  notify.{name}: enabled, credential {'found' if has_credential else 'MISSING'}")
    app.shutdown()
    return 0 if ok else 2


def cmd_strategies(args: argparse.Namespace) -> int:
    from futu_algo.strategy.registry import available, load_strategy_paths

    if args.config:
        cfg = load_config(args.config)
        if cfg.strategy_paths:
            load_strategy_paths([cfg.path(p) for p in cfg.strategy_paths])
    out: list[dict[str, Any]] = []
    for name, cls in available().items():
        inst = cls()
        out.append({"name": name, "title": cls.title, "params": inst.params.model_dump(),
                    "warmup_bars": inst.warmup_bars(), "description": cls.description,
                    **({"schema": cls.param_schema()} if args.json else {})})
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        for s in out:
            params = ", ".join(f"{k}={v}" for k, v in s["params"].items())
            print(f"{s['name']:<12} {s['title']}\n{'':<12} {s['description']}\n{'':<12} params: {params}\n")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    cfg = _load(args)
    _setup(cfg, args)
    from futu_algo.app import App
    from futu_algo.backtest.runner import run_backtest, save_result

    updates: dict[str, Any] = {}
    if args.strategy:
        updates["strategy"] = {"name": args.strategy, "params": _parse_params(args.param)}
    elif args.param:
        updates["strategy"] = {"name": cfg.backtest.strategy.name, "params": {**cfg.backtest.strategy.params, **_parse_params(args.param)}}
    for field in ("symbols", "timeframe", "start", "end", "mode", "capital"):
        value = getattr(args, field)
        if value not in (None, []):
            updates[field] = value
    bt = cfg.backtest.model_validate({**cfg.backtest.model_dump(), **updates})
    app = App(cfg)
    result = run_backtest(cfg, app.fresh_data(True if args.offline else None), bt)
    out = save_result(result, cfg.path(args.out or bt.output_dir))
    summary = result.summary()
    rows = [
        {"book": name, "return": _pct(r["total_return"]), "cagr": _pct(r["cagr"]), "sharpe": _num(r["sharpe"]),
         "max_dd": _pct(r["max_drawdown"]), "trades": int(r["trades"] or 0), "win": _pct(r["win_rate"]).lstrip("+"),
         "fees": _num(r["total_fees"], 0), "buy&hold": _pct(r["buy_hold_return"])}
        for name, r in summary.iterrows()
    ]
    print(f"\n{result.strategy['name']} {result.strategy['params']} on {bt.timeframe}, {bt.start}..{bt.end or 'today'} ({bt.mode})\n")
    print(_table(rows, ["book", "return", "cagr", "sharpe", "max_dd", "trades", "win", "fees", "buy&hold"]))
    for w in result.warnings:
        print(f"  ! {w}")
    print(f"\nReport: {out}/result.json (open it in the web console's Backtest page)")
    app.shutdown()
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    cfg = _load(args)
    _setup(cfg, args)
    from futu_algo.app import App
    from futu_algo.live.replay import replay
    from futu_algo.timeframe import Timeframe

    app = App(cfg)
    tc = cfg.trading
    symbols = args.symbols or tc.symbols
    tf = Timeframe.parse(tc.timeframe)
    end = args.end or date.today()
    start = args.start or (end - timedelta(days=5))
    dm = app.fresh_data(True if args.offline else None)
    instruments = dm.instruments(symbols, cfg.data.lot_sizes)
    from futu_algo.strategy.registry import create_strategy

    warm = max(create_strategy(tc.strategy_for(s).name, tc.strategy_for(s).params).warmup_bars() for s in symbols)
    bars = {s: dm.load_bars(s, tf, start, end, warmup_bars=warm + 5) for s in symbols}
    tz = app.market.tz
    result = replay(cfg, bars, instruments, start=pd.Timestamp(start, tz=tz), capital=tc.capital or 1_000_000)
    fills = result.fills
    print(_table([{k: f[k] for k in ("time", "symbol", "side", "quantity", "price")} for f in fills[-50:]],
                 ["time", "symbol", "side", "quantity", "price"]))
    acct = result.broker.account()
    print(f"\n{len(fills)} fill(s); final equity {acct.equity:,.2f} (P/L {acct.equity - (tc.capital or 1_000_000):+,.2f}); fees {result.broker.fees_paid:,.2f}")
    app.shutdown()
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    cfg = _load(args)
    _setup(cfg, args)
    from futu_algo.app import App

    if args.preset not in cfg.screener.presets:
        print(f"Unknown preset {args.preset!r}; available: {', '.join(cfg.screener.presets)}", file=sys.stderr)
        return 1
    app = App(cfg)
    if args.notify:
        app.notifier.start()
    result = app.screener().run(args.preset, cfg.screener.presets[args.preset], notify=args.notify)
    cols = [c for c in ("symbol", "name", "last_price", "change_pct", "turnover_today", "signal") if any(c in r for r in result.rows)]
    rows = [{c: (_num(r.get(c)) if isinstance(r.get(c), float) else r.get(c, "")) for c in cols} for r in result.rows]
    print(_table(rows, cols))
    print(f"\n{len(result.rows)} of {result.matched} matched; saved {result.path}")
    for w in result.warnings:
        print(f"  ! {w}")
    if args.notify:
        import time as _t

        _t.sleep(2)  # let the background sender flush
        app.notifier.stop()
    app.shutdown()
    return 0


def cmd_data(args: argparse.Namespace) -> int:
    cfg = _load(args)
    _setup(cfg, args)
    from futu_algo.app import App
    from futu_algo.timeframe import Timeframe

    app = App(cfg)
    if args.data_cmd == "list":
        rows = [{"symbol": m["symbol"], "ktype": m["ktype"], "adjust": m["adjust"], "rows": m["rows"],
                 "coverage": " .. ".join(m["coverage"]), "updated": m["updated_at"]} for m in app.store.list_series()]
        print(_table(rows, ["symbol", "ktype", "adjust", "rows", "coverage", "updated"]))
    elif args.data_cmd == "quota":
        q = app.data.source.quota()
        print("quota unavailable" if q is None else f"{q.used} used, {q.remaining} remaining: {', '.join(sorted(q.codes))}")
    else:
        tf = Timeframe.parse(args.timeframe)
        symbols = args.symbols or cfg.trading.symbols
        dm = app.fresh_data(False)
        dm.instruments(symbols, cfg.data.lot_sizes)
        for sym in symbols:
            bars = dm.load_bars(sym, tf, args.start, args.end or date.today())
            print(f"{sym} {tf}: {len(bars)} bars")
        for w in dm.warnings:
            print(f"  ! {w}")
    app.shutdown()
    return 0


def _run_until_signal(stop: threading.Event) -> None:
    def handler(signum: int, _frame: Any) -> None:
        stop.set()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    while not stop.wait(1):
        pass


def cmd_trade(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if args.dry_run:
        cfg = apply_overrides(cfg, ["trading.mode=dry_run"])
    from futu_algo.app import App

    app = App(cfg)
    _setup(cfg, args, app.bus)
    app.start_services()
    engine = app.start_engine()
    print(f"Engine running ({engine.env}, {engine.tf}) on {', '.join(engine.symbols)}. Ctrl-C to stop.")
    stop = threading.Event()
    _run_until_signal(stop)
    print("Stopping...")
    app.shutdown()
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    import uvicorn

    from futu_algo.app import App
    from futu_algo.web.server import create_app

    if args.demo:
        from futu_algo.demo import build_demo_app

        work = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="futu_algo_demo_"))
        app, _opend, _clock = build_demo_app(work, speed=args.speed)
        cfg = app.cfg
        token: str | None = ""
        print(f"Demo mode: simulated OpenD, synthetic prices, virtual clock x{args.speed}. Workspace: {work}")
    else:
        cfg = _load(args)
        app = App(cfg)
        token = secret(cfg.web.token_env)
    host = args.host or cfg.web.host
    port = args.port or cfg.web.port
    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        print(f"Refusing to listen on {host} without a token: set {cfg.web.token_env}.", file=sys.stderr)
        return 1
    _setup(cfg, args, app.bus)
    app.start_services()
    if args.engine or cfg.web.autostart_engine:
        try:
            app.start_engine()
        except FutuAlgoError as exc:
            log.error("Engine not started: %s", exc)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
    print(f"Console: {url}{'?token=<your token>' if token else ''}")
    try:
        uvicorn.run(create_app(app, token=token, allowed_hosts=[host]), host=host, port=port, log_level="warning")
    finally:
        app.shutdown()
    return 0


def _broker(cfg: AppConfig) -> Any:
    from futu_algo.live.futu_broker import FutuBroker

    if cfg.trading.env == "REAL" and (not cfg.trading.allow_real or os.environ.get("FUTU_ALGO_ALLOW_REAL") != "1"):
        raise FutuAlgoError("REAL account access is gated: set trading.allow_real and FUTU_ALGO_ALLOW_REAL=1")
    broker = FutuBroker(host=cfg.futu.host, port=cfg.futu.port, env=cfg.trading.env,
                        security_firm=cfg.futu.security_firm,
                        password_md5=os.environ.get(cfg.futu.trade_password_md5_env),
                        encrypt=bool(cfg.futu.rsa_private_key))
    broker.connect()
    return broker


def cmd_account(args: argparse.Namespace) -> int:
    cfg = _load(args)
    _setup(cfg, args)
    broker = _broker(cfg)
    try:
        if args.command == "account":
            a = broker.account()
            print(json.dumps(a.to_dict(), indent=2))
        elif args.command == "positions":
            rows = [{"symbol": p.symbol, "name": p.name, "qty": p.quantity, "can_sell": p.can_sell,
                     "cost": _num(p.cost_price, 3), "last": _num(p.last_price, 3), "value": _num(p.market_value),
                     "pl": _num(p.unrealized_pl)} for p in broker.positions().values()]
            print(_table(rows, ["symbol", "name", "qty", "can_sell", "cost", "last", "value", "pl"]))
        elif args.command == "orders":
            rows = [{"id": o.order_id, "symbol": o.symbol, "side": o.side, "qty": o.quantity, "price": o.price,
                     "state": str(o.state), "filled": o.filled_qty, "avg": _num(o.avg_fill_price, 3), "remark": o.remark}
                    for o in broker.orders()]
            print(_table(rows, ["id", "symbol", "side", "qty", "price", "state", "filled", "avg", "remark"]))
        elif args.command == "cancel-all":
            n = 0
            for o in broker.orders():
                if o.state.is_open:
                    broker.cancel(o.order_id)
                    n += 1
            print(f"Cancelled {n} open order(s)")
        elif args.command == "flatten":
            from futu_algo.app import App
            from futu_algo.live.executor import limit_price
            from futu_algo.live.futu_broker import FutuQuoteProvider
            from futu_algo.live.models import OrderRequest

            app = App(cfg)
            quotes = FutuQuoteProvider(app.gateway)
            positions = broker.positions()
            targets = [p for s, p in positions.items() if not args.symbol or s == args.symbol]
            if not targets:
                print("No positions to flatten")
            inst = app.instruments([p.symbol for p in targets]) if targets else {}
            for p in targets:
                if not args.yes:
                    reply = input(f"Sell {p.can_sell} {p.symbol}? [y/N] ")
                    if reply.strip().lower() != "y":
                        continue
                q = quotes.quotes([p.symbol])[p.symbol]
                price = limit_price("SELL", q, inst[p.symbol], cfg.trading.order, pd.Timestamp.now(tz=app.market.tz).to_pydatetime())
                o = broker.place(OrderRequest(p.symbol, "SELL", p.can_sell, price, reason="cli flatten", remark="futu_algo:cli"))
                print(f"Sent SELL {p.can_sell} {p.symbol} @ {price}: {o.order_id} {o.state}")
            app.shutdown()
    finally:
        broker.close()
    return 0


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="futu-algo", description="Algorithmic trading for HK equities on Futu OpenAPI.")
    p.add_argument("--version", action="version", version=f"futu-algo {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def with_config(sp: argparse.ArgumentParser, required: bool = True) -> argparse.ArgumentParser:
        sp.add_argument("-c", "--config", required=required, help="YAML config file")
        sp.add_argument("--set", action="append", metavar="KEY=VALUE", help="override a config value (repeatable)")
        sp.add_argument("-v", "--verbose", action="store_true")
        return sp

    s = sub.add_parser("init", help="write a starter config")
    s.add_argument("path", nargs="?", default="config.yaml")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    with_config(sub.add_parser("check", help="validate config and connectivity")).set_defaults(func=cmd_check)

    s = sub.add_parser("strategies", help="list strategies")
    s.add_argument("-c", "--config")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_strategies)

    s = with_config(sub.add_parser("backtest", help="run a backtest"))
    s.add_argument("-s", "--strategy")
    s.add_argument("-p", "--param", action="append", metavar="NAME=VALUE")
    s.add_argument("--symbols", nargs="+")
    s.add_argument("-t", "--timeframe")
    s.add_argument("--start", type=date.fromisoformat)
    s.add_argument("--end", type=date.fromisoformat)
    s.add_argument("--mode", choices=["portfolio", "scan"])
    s.add_argument("--capital", type=float)
    s.add_argument("--offline", action="store_true", help="use cached data only")
    s.add_argument("--out", help="report directory (default backtest.output_dir)")
    s.set_defaults(func=cmd_backtest)

    s = with_config(sub.add_parser("replay", help="replay cached bars through the live engine"))
    s.add_argument("--symbols", nargs="+")
    s.add_argument("--start", type=date.fromisoformat)
    s.add_argument("--end", type=date.fromisoformat)
    s.add_argument("--offline", action="store_true")
    s.set_defaults(func=cmd_replay)

    s = with_config(sub.add_parser("screen", help="run a screener preset"))
    s.add_argument("-p", "--preset", required=True)
    s.add_argument("--notify", action="store_true", help="send the result via the configured channels")
    s.set_defaults(func=cmd_screen)

    s = with_config(sub.add_parser("data", help="bar cache"))
    s.add_argument("data_cmd", choices=["fetch", "list", "quota"])
    s.add_argument("--symbols", nargs="+")
    s.add_argument("-t", "--timeframe", default="DAY")
    s.add_argument("--start", type=date.fromisoformat, default=date.today() - timedelta(days=365))
    s.add_argument("--end", type=date.fromisoformat)
    s.set_defaults(func=cmd_data)

    s = with_config(sub.add_parser("trade", help="run the live (paper) engine headless"))
    s.add_argument("--dry-run", action="store_true", help="fill locally; send nothing to Futu")
    s.set_defaults(func=cmd_trade)

    s = with_config(sub.add_parser("web", help="web console"), required=False)
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--engine", action="store_true", help="start the trading engine too")
    s.add_argument("--demo", action="store_true", help="simulated OpenD and synthetic market")
    s.add_argument("--speed", type=float, default=1.0, help="demo clock speed")
    s.add_argument("--workdir", help="demo workspace (default: a temp dir)")
    s.set_defaults(func=cmd_web)

    for name, helptext in (("account", "account summary"), ("positions", "positions"), ("orders", "today's orders"),
                           ("cancel-all", "cancel all open orders")):
        with_config(sub.add_parser(name, help=helptext)).set_defaults(func=cmd_account)
    s = with_config(sub.add_parser("flatten", help="sell positions at an aggressive limit"))
    s.add_argument("--symbol")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_account)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "web" and not args.demo and not args.config:
        parser.error("web needs -c/--config (or --demo)")
    try:
        return int(args.func(args) or 0)
    except FutuAlgoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
