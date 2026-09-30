"""Live bars: assemble completed bars from Futu K-line pushes.

Futu pushes the *in-progress* bar every time it changes, labelled with its end time (the
09:31 one-minute bar covers 09:30-09:31; the 09:30 bar is the opening auction). A bar is
complete when either

* a push arrives for a later bar, or
* the wall clock passes the bar's end time plus a small grace period,

whichever comes first. The clock rule matters at the lunch break and the close, where no
later bar arrives for an hour or until the next day. Pushes for a bar that has already been
finalised are ignored, so a strategy sees each bar exactly once.

Timeframes Futu does not serve natively (e.g. ``10M``, ``2H``) are assembled from the largest
native divisor with the same session-anchored buckets the backtester uses, so a live 10M bar
is identical to a backtest 10M bar.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from futu_algo.data.resample import session_labels
from futu_algo.data.schema import BAR_COLUMNS, to_bars
from futu_algo.futu_gateway import RET_OK, QuoteGateway
from futu_algo.market.instrument import MarketSpec
from futu_algo.timeframe import Timeframe

log = logging.getLogger(__name__)


@dataclass
class Bar:
    symbol: str
    time: pd.Timestamp  # end label, exchange-local tz-aware (daily: the date at 00:00)
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    turnover: float = 0.0

    def as_row(self) -> dict[str, float]:
        return {c: float(getattr(self, c)) for c in BAR_COLUMNS}


def bar_end(label: pd.Timestamp, tf: Timeframe, market: MarketSpec) -> pd.Timestamp:
    """Wall-clock time at which a bar with this label is final."""
    if tf.is_intraday:
        return label
    close = market.closing_auction[1] if market.closing_auction else market.close_time
    day = label.normalize()
    if tf.unit == "week":
        day = day + pd.Timedelta(days=4 - day.weekday())
    elif tf.unit == "month":
        day = (day + pd.offsets.MonthEnd(0)).normalize()
    return day + pd.Timedelta(hours=close.hour, minutes=close.minute)


@dataclass
class _SymbolState:
    current: Bar | None = None
    last_final: pd.Timestamp | None = None
    chunk: list[Bar] = field(default_factory=list)
    chunk_label: pd.Timestamp | None = None
    last_emitted: pd.Timestamp | None = None


class BarAssembler:
    """Turns a stream of base-timeframe bar updates into completed target-timeframe bars."""

    def __init__(self, target: Timeframe, market: MarketSpec, grace_seconds: float = 2.0) -> None:
        self.target = target
        self.base = target.base
        self.market = market
        self.grace = pd.Timedelta(seconds=grace_seconds)
        self._state: dict[str, _SymbolState] = {}
        self._lock = threading.Lock()

    def _st(self, symbol: str) -> _SymbolState:
        return self._state.setdefault(symbol, _SymbolState())

    def prime(self, symbol: str, last_complete: pd.Timestamp | None) -> None:
        """Mark bars up to ``last_complete`` (base label) as already seen (after warm-up)."""
        with self._lock:
            st = self._st(symbol)
            st.last_final = last_complete
            st.last_emitted = last_complete

    def seed(self, symbol: str, completed_base: list[Bar]) -> None:
        """After warm-up: put completed base bars of a still-open target bar into its bucket."""
        with self._lock:
            st = self._st(symbol)
            for bar in completed_base:
                self._finalize_base(st, bar)

    def update(self, bar: Bar) -> list[Bar]:
        with self._lock:
            st = self._st(bar.symbol)
            if st.last_final is not None and bar.time <= st.last_final:
                return []
            out: list[Bar] = []
            if st.current is not None and bar.time > st.current.time:
                out += self._finalize_base(st, st.current)
            st.current = bar
            return out

    def tick(self, now: datetime) -> list[Bar]:
        stamp = pd.Timestamp(now).tz_convert(self.market.tz)
        out: list[Bar] = []
        with self._lock:
            for st in self._state.values():
                cur = st.current
                if cur is not None and bar_end(cur.time, self.base, self.market) + self.grace <= stamp:
                    out += self._finalize_base(st, cur)
                    st.current = None
                if st.chunk and st.chunk_label is not None and st.chunk_label + self.grace <= stamp:
                    out.append(self._flush_chunk(st))
        return out

    def _finalize_base(self, st: _SymbolState, bar: Bar) -> list[Bar]:
        st.last_final = bar.time
        if self.target == self.base:
            st.last_emitted = bar.time
            return [bar]
        label = session_labels(pd.DatetimeIndex([bar.time]), self.target.minutes, self.market)[0]
        out: list[Bar] = []
        if st.chunk and st.chunk_label is not None and label != st.chunk_label:
            out.append(self._flush_chunk(st))
        st.chunk.append(bar)
        st.chunk_label = label
        if bar.time >= label:
            out.append(self._flush_chunk(st))
        return out

    def _flush_chunk(self, st: _SymbolState) -> Bar:
        bars, label = st.chunk, st.chunk_label
        assert label is not None and bars
        st.chunk, st.chunk_label = [], None
        st.last_emitted = label
        return Bar(
            symbol=bars[0].symbol,
            time=label,
            open=bars[0].open,
            high=max(b.high for b in bars),
            low=min(b.low for b in bars),
            close=bars[-1].close,
            volume=sum(b.volume for b in bars),
            turnover=sum(b.turnover for b in bars),
        )


def bars_from_frame(symbol: str, frame: pd.DataFrame, tz: str) -> list[Bar]:
    bars = to_bars(frame, tz)
    return [
        Bar(symbol, t, r["open"], r["high"], r["low"], r["close"], r["volume"], r["turnover"] if r["turnover"] == r["turnover"] else 0.0)
        for t, r in zip(bars.index, bars.to_dict("records"), strict=True)
    ]


class FutuBarFeed:
    """Subscribes to K-line pushes and calls ``on_bar`` with each completed bar."""

    def __init__(
        self,
        gateway: QuoteGateway,
        timeframe: Timeframe,
        market: MarketSpec,
        on_bar: Callable[[Bar], None],
        *,
        grace_seconds: float = 2.0,
    ) -> None:
        self.gateway = gateway
        self.timeframe = timeframe
        self.market = market
        self.on_bar = on_bar
        self.assembler = BarAssembler(timeframe, market, grace_seconds)
        self.symbols: list[str] = []
        self.last_push: datetime | None = None
        self._handler_installed = False

    @property
    def subtype(self) -> str:
        return self.timeframe.base.futu_ktype  # SubType names match KLType names

    def _install_handler(self) -> None:
        if self._handler_installed:
            return
        from futu import CurKlineHandlerBase

        feed = self

        class _Handler(CurKlineHandlerBase):
            def on_recv_rsp(self, rsp_pb: Any) -> Any:
                ret, data = super().on_recv_rsp(rsp_pb)
                if ret == RET_OK:
                    feed._on_frame(data)
                else:
                    log.warning("K-line push error: %s", data)
                return ret, data

            def deliver(self, frame: pd.DataFrame) -> None:
                """Entry point for simulated OpenD pushes (already-decoded frames)."""
                feed._on_frame(frame)

        self.gateway.context().set_handler(_Handler())
        self._handler_installed = True

    def _on_frame(self, data: pd.DataFrame) -> None:
        self.last_push = datetime.now().astimezone()
        try:
            for code, part in data.groupby("code"):
                for bar in bars_from_frame(str(code), part, self.market.tz):
                    for done in self.assembler.update(bar):
                        self.on_bar(done)
        except Exception:
            log.exception("Failed to process K-line push")

    def subscribe(self, symbols: list[str]) -> None:
        self.symbols = list(symbols)
        if not symbols:
            return
        self._install_handler()
        self.gateway.call(
            "subscribe",
            f"subscribe({len(symbols)} x {self.subtype})",
            lambda ctx: ctx.subscribe(symbols, [self.subtype], subscribe_push=True),
        )
        log.info("Subscribed %s to %d symbol(s)", self.subtype, len(symbols))

    def unsubscribe(self) -> None:
        if not self.symbols:
            return
        try:
            self.gateway.call(
                "subscribe", "unsubscribe", lambda ctx: ctx.unsubscribe(self.symbols, [self.subtype])
            )
        except Exception as exc:  # Futu refuses unsubscribing within a minute of subscribing
            log.info("Unsubscribe skipped: %s", exc)

    def recent_bars(self, symbol: str, count: int) -> pd.DataFrame:
        """Up to 1,000 most recent base bars from the subscription cache (last may be in progress)."""
        _, data = self.gateway.call(
            "default",
            f"get_cur_kline({symbol})",
            lambda ctx: ctx.get_cur_kline(symbol, min(max(count, 2), 1000), self.subtype),
        )
        return to_bars(data, self.market.tz)

    def poll(self) -> None:
        """Safety net for lost pushes: re-read the last two bars of every symbol."""
        for sym in self.symbols:
            try:
                frame = self.recent_bars(sym, 2)
            except Exception as exc:
                log.debug("poll %s failed: %s", sym, exc)
                continue
            for t, row in zip(frame.index, frame.to_dict("records"), strict=True):
                bar = Bar(sym, t, row["open"], row["high"], row["low"], row["close"], row["volume"], row["turnover"] if row["turnover"] == row["turnover"] else 0.0)
                for done in self.assembler.update(bar):
                    self.on_bar(done)

    def tick(self, now: datetime) -> None:
        for done in self.assembler.tick(now):
            self.on_bar(done)


def split_in_progress(bars: pd.DataFrame, tf: Timeframe, market: MarketSpec, now: datetime, grace_seconds: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split base bars into (complete, in-progress) by their end time vs ``now``."""
    if bars.empty:
        return bars, bars
    stamp = pd.Timestamp(now).tz_convert(market.tz)
    ends = [bar_end(t, tf, market) + timedelta(seconds=grace_seconds) for t in bars.index]
    done = [e <= stamp for e in ends]
    mask = pd.Series(done, index=bars.index)
    return bars[mask.to_numpy()], bars[~mask.to_numpy()]
