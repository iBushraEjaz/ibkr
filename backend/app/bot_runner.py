import asyncio
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ib_insync import IB

from .strategies.orb import ORBStrategy
from .ws_manager import ws_manager
from .database import SessionLocal
from .models import Trade, Position, BotRun

ET = ZoneInfo("America/New_York")
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Global state                                                         #
# ------------------------------------------------------------------ #

_bot_thread: threading.Thread | None = None
_bot_loop: asyncio.AbstractEventLoop | None = None
_bot_status: str = "stopped"
_current_run_id: int | None = None
_fastapi_loop: asyncio.AbstractEventLoop | None = None  # set on first start


def get_status() -> str:
    return _bot_status


# ------------------------------------------------------------------ #
# Config / tickers                                                     #
# ------------------------------------------------------------------ #

def _load_config() -> dict:
    path = Path(__file__).parents[2] / "config.json"
    with open(path) as f:
        return json.load(f)


def _load_tickers() -> list[str]:
    path = Path(__file__).parents[2] / "tickers.txt"
    tickers = [l.strip().upper() for l in path.read_text().splitlines() if l.strip()]
    return tickers[:15]


# ------------------------------------------------------------------ #
# DB helpers                                                           #
# ------------------------------------------------------------------ #

def _start_run() -> int:
    with SessionLocal() as db:
        run = BotRun(status="running")
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id


def _end_run(run_id: int, status: str):
    with SessionLocal() as db:
        run = db.get(BotRun, run_id)
        if run:
            run.stopped_at = datetime.utcnow()
            run.status = status
            db.commit()


def _upsert_position(symbol: str, shares: int, entry_price: float, current_price: float, stop: float, status: str = "pending"):
    pnl = round((current_price - entry_price) * shares, 2) if current_price else None
    with SessionLocal() as db:
        pos = db.query(Position).filter_by(symbol=symbol).first()
        if pos:
            pos.shares = shares
            pos.entry_price = entry_price
            pos.current_price = current_price
            pos.stop = stop
            pos.pnl = pnl
            pos.status = status
        else:
            db.add(Position(symbol=symbol, shares=shares, entry_price=entry_price,
                            current_price=current_price, stop=stop, pnl=pnl, status=status))
        db.commit()


def _close_position(symbol: str, exit_price: float):
    with SessionLocal() as db:
        pos = db.query(Position).filter_by(symbol=symbol).first()
        if not pos:
            return
        pnl = round((exit_price - pos.entry_price) * pos.shares, 2)
        db.add(Trade(
            symbol=symbol, side="SELL", shares=pos.shares,
            entry_price=pos.entry_price, exit_price=exit_price,
            pnl=pnl, timestamp=datetime.utcnow(),
        ))
        db.delete(pos)
        db.commit()


def _record_entry(symbol: str, shares: int, entry_price: float):
    with SessionLocal() as db:
        db.add(Trade(symbol=symbol, side="BUY", shares=shares,
                     entry_price=entry_price, timestamp=datetime.utcnow()))
        db.commit()


# ------------------------------------------------------------------ #
# WS bridge — safely emit from bot thread → FastAPI loop              #
# ------------------------------------------------------------------ #

def _emit(event: str, data: dict):
    if _fastapi_loop and _fastapi_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast(event, data), _fastapi_loop
        )


# ------------------------------------------------------------------ #
# Strategy patching                                                    #
# ------------------------------------------------------------------ #

def _patch_strategy(strategy: ORBStrategy):
    original_on_entry_filled = strategy._on_entry_filled
    original_on_stop_filled = strategy._on_stop_filled
    original_on_tick_trail = strategy._on_tick_trail
    original_place_entry = strategy._place_entry

    async def place_entry(entry_price: float, stop_price: float):
        await original_place_entry(entry_price, stop_price)
        if strategy.state == "order_placed":
            _upsert_position(strategy.symbol, strategy.shares, entry_price, entry_price, stop_price)
            _emit("position_update", {"symbol": strategy.symbol, "shares": strategy.shares,
                                      "entry_price": entry_price, "current_price": entry_price,
                                      "stop": stop_price, "pnl": 0.0, "status": "pending"})

    def on_entry_filled(trade):
        original_on_entry_filled(trade)
        fill_px = trade.orderStatus.avgFillPrice
        _record_entry(strategy.symbol, strategy.shares, fill_px)
        _upsert_position(strategy.symbol, strategy.shares, fill_px, fill_px, strategy.current_stop, status="filled")
        _emit("trade_fill", {"symbol": strategy.symbol, "side": "BUY",
                             "shares": strategy.shares, "price": fill_px,
                             "pnl": None, "timestamp": datetime.utcnow().isoformat()})
        _emit("position_update", {"symbol": strategy.symbol, "shares": strategy.shares,
                                  "entry_price": fill_px, "current_price": fill_px,
                                  "stop": strategy.current_stop, "pnl": 0.0})

    def on_stop_filled():
        exit_px = strategy.current_stop
        _close_position(strategy.symbol, exit_px)
        _emit("trade_fill", {"symbol": strategy.symbol, "side": "SELL",
                             "shares": strategy.shares, "price": exit_px,
                             "pnl": None, "timestamp": datetime.utcnow().isoformat()})
        original_on_stop_filled()

    def on_tick_trail(ticker):
        old_stop = strategy.current_stop
        original_on_tick_trail(ticker)
        if strategy.current_stop != old_stop:
            _emit("stop_update", {"symbol": strategy.symbol,
                                  "old_stop": old_stop, "new_stop": strategy.current_stop})

    strategy._place_entry = place_entry
    strategy._on_entry_filled = on_entry_filled
    strategy._on_stop_filled = on_stop_filled
    strategy._on_tick_trail = on_tick_trail


# ------------------------------------------------------------------ #
# Bot loop — runs in its own thread + event loop                       #
# ------------------------------------------------------------------ #

async def _run_bot():
    global _bot_status, _current_run_id

    cfg = _load_config()
    tickers = _load_tickers()
    print(f"[BOT] Starting — tickers: {tickers}, port: {cfg.get('port')}", flush=True)
    log.info(f"Bot starting — tickers: {tickers}, port: {cfg.get('port')}")

    _current_run_id = _start_run()
    _bot_status = "running"
    _emit("bot_status", {"status": "running"})

    ib = IB()
    try:
        await ib.connectAsync(
            cfg.get("host", "127.0.0.1"),
            cfg.get("port", 7497),
            clientId=cfg.get("client_id", 1),
        )
    except Exception as e:
        log.error(f"IBKR connection failed: {e}")
        _bot_status = "error"
        _end_run(_current_run_id, "error")
        _emit("bot_status", {"status": "error"})
        return

    log.info("Connected to IBKR")

    strategies = [ORBStrategy(ib, sym, cfg) for sym in tickers]
    for s in strategies:
        _patch_strategy(s)

    try:
        await asyncio.gather(*[s.start() for s in strategies])
        log.info("All strategies active")

        while True:
            await asyncio.sleep(30)
            now = datetime.now(ET)
            if now.hour >= 16:
                log.info("4:00 PM ET — shutting down")
                break
            active = [s for s in strategies if s.state not in ("done", "idle")]
            if not active and all(s.state == "done" for s in strategies):
                in_position = any(s.state == "in_position" for s in strategies)
                if in_position or now.hour >= 9:
                    log.info("All strategies resolved — shutting down")
                    break

    except asyncio.CancelledError:
        log.info("Bot stopped by user")
    finally:
        for s in strategies:
            s.cleanup()
        ib.disconnect()
        _bot_status = "stopped"
        _end_run(_current_run_id, "stopped")
        _emit("bot_status", {"status": "stopped"})
        log.info("Disconnected from IBKR")


def _thread_main():
    global _bot_loop
    _bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_bot_loop)
    try:
        _bot_loop.run_until_complete(_run_bot())
    finally:
        _bot_loop.close()
        _bot_loop = None


# ------------------------------------------------------------------ #
# Public API                                                           #
# ------------------------------------------------------------------ #

async def start_bot() -> bool:
    global _bot_thread, _fastapi_loop
    if _bot_thread and _bot_thread.is_alive():
        return False
    _fastapi_loop = asyncio.get_event_loop()
    _bot_thread = threading.Thread(target=_thread_main, daemon=True, name="ibkr-bot")
    _bot_thread.start()
    return True


async def stop_bot() -> bool:
    global _bot_loop
    if _bot_loop and _bot_loop.is_running():
        _bot_loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(_cancel_all_tasks(), loop=_bot_loop)
        )
        return True
    return False


async def _cancel_all_tasks():
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
