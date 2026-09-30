"""Broker and quote-provider interfaces.

Two brokers implement :class:`Broker`:

* :class:`~futu_algo.live.futu_broker.FutuBroker` sends orders to a Futu account
  (``SIMULATE`` paper account by default);
* :class:`~futu_algo.live.sim_broker.SimBroker` fills orders locally, for ``dry_run`` mode and
  for tests. It never talks to Futu.

The engine only ever uses this interface, so the same trading logic runs against either.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from futu_algo.live.models import AccountSnapshot, OrderInfo, OrderRequest, PositionInfo, Quote


class Broker(Protocol):
    name: str
    env: str

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def account(self) -> AccountSnapshot: ...

    def positions(self) -> dict[str, PositionInfo]: ...

    def orders(self) -> list[OrderInfo]:
        """Today's orders (open and closed)."""
        ...

    def place(self, request: OrderRequest) -> OrderInfo: ...

    def cancel(self, order_id: str) -> None: ...

    def set_order_listener(self, callback: Callable[[], None]) -> None:
        """Called (from any thread) when the broker pushes an order or fill update."""
        ...


class QuoteProvider(Protocol):
    def quotes(self, symbols: list[str]) -> dict[str, Quote]: ...
