import asyncio
import logging
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ib_insync import IB, Stock, Forex, StopOrder

from .base import Strategy

ET = ZoneInfo("America/New_York")
log = logging.getLogger(__name__)


def _valid_price(p) -> bool:
    return p is not None and not math.isnan(p) and p > 0


def _get_account_value(ib: IB, account: str = "") -> float:
    vals = ib.accountValues(account)
    for v in vals:
        if v.tag == "NetLiquidation" and v.currency == "USD":
            return float(v.value)
    for v in vals:
        if v.tag == "NetLiquidation":
            log.warning(f"Using {v.currency} NetLiquidation for position sizing")
            return float(v.value)
    raise RuntimeError("Cannot read account value from IBKR")


class ORBStrategy(Strategy):
    """
    Opening Range Breakout strategy.
    - Tracks the first 1-min candle at 9:30 ET
    - Places a stop-buy at candle high, stop-loss at candle low
    - Trails the stop using N-min candle lows after entry
    """

    def __init__(self, ib: IB, symbol: str, cfg: dict):
        self.ib = ib
        self.symbol = symbol
        self.cfg = cfg
        if cfg.get("instrument") == "forex":
            self.contract = Forex(symbol)  # e.g. Forex("EURUSD")
        else:
            self.contract = Stock(symbol, "SMART", "USD")

        self._state = "idle"
        self.entry_trade = None
        self.stop_trade = None
        self.current_stop: float = None
        self.shares: int = 0
        self.ticker_obj = None

        # 9:30 opening candle
        self.c_open: float = None
        self.c_high: float = None
        self.c_low: float = None

        # trailing stop
        self.trail_tf: int = cfg.get("trailing_timeframe_minutes", 5)
        self.trail_window_low: float = float("inf")
        self.trail_window_start: datetime = None

        self.cancel_handle = None

    @property
    def state(self) -> str:
        return self._state

    # ------------------------------------------------------------------ #
    # Strategy interface                                                   #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        try:
            await self.ib.qualifyContractsAsync(self.contract)
        except Exception as e:
            log.error(f"[{self.symbol}] Contract qualify failed: {e}")
            self._state = "done"
            return

        self._state = "watching"
        now = datetime.now(ET)
        is_forex = self.cfg.get("instrument") == "forex"

        if self.cfg.get("test_mode"):
            open_time = now + timedelta(seconds=7)
            log.info(f"[{self.symbol}] TEST MODE — candle tracking starts at {open_time.strftime('%H:%M:%S')} ET")
        elif is_forex:
            open_time = now + timedelta(seconds=2)
            log.info(f"[{self.symbol}] FOREX — starting immediately")
        else:
            open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)

        if not self.cfg.get("test_mode") and not is_forex:
            deadline = open_time + timedelta(minutes=self.cfg["cancel_after_minutes"])
            if now > deadline:
                log.info(f"[{self.symbol}] Past cancel window — skipping today")
                self._state = "done"
                return

        delay = max(0.0, (open_time - now).total_seconds())
        log.info(f"[{self.symbol}] Candle tracking starts in {delay:.0f}s")
        asyncio.get_running_loop().call_later(
            delay,
            lambda: asyncio.ensure_future(self._begin_candle_tracking()),
        )

    def on_tick(self, ticker) -> None:
        """Dispatched by the bot loop — routes to the active tick handler."""
        if self._state == "watching":
            self._on_tick_candle(ticker)
        elif self._state == "order_placed":
            self._on_tick_candle(ticker)
        elif self._state == "in_position":
            self._on_tick_trail(ticker)

    def cleanup(self) -> None:
        self._cancel_mktdata()
        if self.cancel_handle:
            self.cancel_handle.cancel()
        try:
            self.ib.pendingTickersEvent -= self._on_pending_tickers
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Opening candle                                                       #
    # ------------------------------------------------------------------ #

    def _on_pending_tickers(self, tickers):
        for t in tickers:
            if t.contract == self.contract:
                self.on_tick(t)

    async def _begin_candle_tracking(self):
        if self._state != "watching":
            return

        self.c_open = None
        self.c_high = -float("inf")
        self.c_low = float("inf")

        delayed = self.cfg.get("delayed_data", False)
        self.ib.reqMarketDataType(3 if delayed else 1)
        self.ticker_obj = self.ib.reqMktData(self.contract, "", False, False)
        self.ticker_obj.updateEvent += self.on_tick
        self.ib.pendingTickersEvent += self._on_pending_tickers
        log.info(f"[{self.symbol}] Tracking candle via {'delayed' if delayed else 'live'} ticks")

        candle_secs = 30 if self.cfg.get("test_mode") else 61

        # poll ticker every second as fallback for forex
        for _ in range(candle_secs):
            await asyncio.sleep(1)
            if self._state != "watching":
                return
            t = self.ticker_obj
            price = None
            if _valid_price(t.bid):
                price = t.bid
            elif _valid_price(t.ask):
                price = t.ask
            elif _valid_price(t.last):
                price = t.last
            if price:
                if self.c_open is None:
                    self.c_open = price
                if price > self.c_high:
                    self.c_high = price
                if price < self.c_low:
                    self.c_low = price

        await self._finalize_opening_candle()

    def _on_tick_candle(self, ticker):
        price = ticker.last
        if not _valid_price(price):
            price = ticker.bid
        if not _valid_price(price):
            price = ticker.ask
        if not _valid_price(price):
            return
        if self.c_open is None:
            self.c_open = price
        if price > self.c_high:
            self.c_high = price
        if price < self.c_low:
            self.c_low = price

    async def _finalize_opening_candle(self):
        if self._state != "watching":
            return

        if self.ticker_obj:
            self.ticker_obj.updateEvent -= self.on_tick
        try:
            self.ib.pendingTickersEvent -= self._on_pending_tickers
        except Exception:
            pass

        # if no ticks received via event, read directly from ticker object
        if self.c_open is None and self.ticker_obj:
            t = self.ticker_obj
            price = t.bid if _valid_price(t.bid) else t.ask if _valid_price(t.ask) else t.last
            if _valid_price(price):
                self.c_open = price
                self.c_high = price
                self.c_low = price
                log.info(f"[{self.symbol}] Using snapshot price {price} for candle")

        if self.cfg.get("test_mode") and self.c_open is not None:
            # set entry BELOW current price so order fills immediately in paper trading
            decimals = 4 if self.cfg.get("instrument") == "forex" else 2
            self.c_high = round(self.c_open * 0.995, decimals)
            self.c_low = round(self.c_open * 0.990, decimals)
            log.info(f"[{self.symbol}] TEST MODE — forcing candle H={self.c_high} L={self.c_low} (below market for instant fill)")

        if self.c_open is None or self.c_high == -float("inf"):
            log.error(
                f"[{self.symbol}] No tick data for 9:30 candle. "
                "Check your IBKR market data subscription."
            )
            self._cancel_mktdata()
            self._state = "done"
            return

        candle_high = round(self.c_high, 2)
        candle_low = round(self.c_low, 2)
        log.info(f"[{self.symbol}] 9:30 candle | H={candle_high} L={candle_low}")
        await self._place_entry(candle_high, candle_low)

    # ------------------------------------------------------------------ #
    # Entry order                                                          #
    # ------------------------------------------------------------------ #

    async def _place_entry(self, entry_price: float, stop_price: float):
        if entry_price <= stop_price:
            log.warning(f"[{self.symbol}] High ({entry_price}) <= Low ({stop_price}) — skipping")
            self._cancel_mktdata()
            self._state = "done"
            return

        try:
            account_value = _get_account_value(self.ib, self.cfg.get("account", ""))
        except RuntimeError as e:
            log.error(f"[{self.symbol}] {e}")
            self._cancel_mktdata()
            self._state = "done"
            return

        risk_amount = account_value * (self.cfg["risk_percent"] / 100)
        risk_per_share = entry_price - stop_price
        shares = max(1, math.floor(risk_amount / risk_per_share))
        max_size = self.cfg.get("max_position_size")
        if max_size:
            shares = min(shares, max_size)
        self.shares = shares
        self.current_stop = stop_price

        log.info(
            f"[{self.symbol}] ENTRY ORDER | stop-buy @ {entry_price} | "
            f"stop-loss @ {stop_price} | shares={self.shares} | "
            f"risk=${risk_amount:.2f} | risk/share=${risk_per_share:.2f}"
        )

        buy_order = StopOrder("BUY", self.shares, entry_price)
        buy_order.tif = "DAY"
        self.entry_trade = self.ib.placeOrder(self.contract, buy_order)
        self.entry_trade.filledEvent += self._on_entry_filled
        self._state = "order_placed"

        self.cancel_handle = asyncio.get_running_loop().call_later(
            self.cfg["cancel_after_minutes"] * 60,
            lambda: asyncio.ensure_future(self._cancel_unfilled()),
        )

    async def _cancel_unfilled(self):
        if self._state != "order_placed":
            return
        log.info(f"[{self.symbol}] {self.cfg['cancel_after_minutes']} min elapsed — cancelling unfilled buy")
        self.ib.cancelOrder(self.entry_trade.order)
        self._cancel_mktdata()
        self._state = "done"

    def _on_entry_filled(self, trade):
        if self.cancel_handle:
            self.cancel_handle.cancel()
        fill_px = trade.orderStatus.avgFillPrice
        log.info(f"[{self.symbol}] BUY FILLED @ {fill_px} | placing stop @ {self.current_stop}")
        asyncio.ensure_future(self._activate_stop_and_trail())

    # ------------------------------------------------------------------ #
    # Stop + trailing                                                      #
    # ------------------------------------------------------------------ #

    async def _activate_stop_and_trail(self):
        self._state = "in_position"

        stop_order = StopOrder("SELL", self.shares, self.current_stop)
        stop_order.tif = "DAY"
        self.stop_trade = self.ib.placeOrder(self.contract, stop_order)
        self.stop_trade.filledEvent += lambda t: self._on_stop_filled()

        self.trail_window_low = float("inf")
        self.trail_window_start = None

        delayed = self.cfg.get("delayed_data", False)
        self.ib.reqMarketDataType(3 if delayed else 1)
        if self.ticker_obj:
            self.ticker_obj.updateEvent += self.on_tick
        else:
            self.ticker_obj = self.ib.reqMktData(self.contract, "", False, False)
            self.ticker_obj.updateEvent += self.on_tick

        log.info(f"[{self.symbol}] Trailing stop active | tracking {self.trail_tf}-min candle lows")

    def _on_tick_trail(self, ticker):
        price = ticker.last
        if not _valid_price(price):
            return

        now = datetime.now(ET)
        candle_minute = (now.minute // self.trail_tf) * self.trail_tf
        candle_start = now.replace(minute=candle_minute, second=0, microsecond=0)

        if self.trail_window_start is None:
            self.trail_window_start = candle_start
            self.trail_window_low = price
            return

        if candle_start > self.trail_window_start:
            completed_low = round(self.trail_window_low, 2)
            if completed_low > self.current_stop:
                log.info(f"[{self.symbol}] TRAIL STOP {self.current_stop} -> {completed_low}")
                self.current_stop = completed_low
                self.stop_trade.order.auxPrice = completed_low
                self.ib.placeOrder(self.contract, self.stop_trade.order)
            self.trail_window_start = candle_start
            self.trail_window_low = price
        else:
            if price < self.trail_window_low:
                self.trail_window_low = price

    def _on_stop_filled(self):
        log.info(f"[{self.symbol}] STOP FILLED — position closed")
        self._cancel_mktdata()
        self._state = "done"

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _cancel_mktdata(self):
        if self.ticker_obj:
            try:
                self.ib.cancelMktData(self.contract)
            except Exception:
                pass
            self.ticker_obj = None
