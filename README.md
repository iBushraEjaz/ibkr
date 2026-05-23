# IBKR Intraday Bot — Dashboard

Automated intraday trading bot for Interactive Brokers with a live web dashboard.
The bot runs an Opening Range Breakout strategy and is controlled entirely from the browser.

---

## Architecture

```
ibkr-intraday-bot/
├── bot.py                  Original CLI bot (reference only)
├── config.json             Bot configuration (shared by backend)
├── tickers.txt             Tickers to trade (update each morning)
├── backend/
│   ├── app/
│   │   ├── main.py         FastAPI entry point + WebSocket endpoint
│   │   ├── bot_runner.py   Runs bot in background thread
│   │   ├── ws_manager.py   WebSocket broadcast manager
│   │   ├── database.py     SQLite engine + session
│   │   ├── models.py       DB models (trades, positions, bot_runs, config)
│   │   ├── routers/
│   │   │   ├── bot.py      POST /bot/start, POST /bot/stop, GET /bot/status
│   │   │   ├── positions.py GET /positions/
│   │   │   └── trades.py   GET /trades/today
│   │   └── strategies/
│   │       ├── base.py     Strategy abstract base class
│   │       └── orb.py      Opening Range Breakout strategy
│   └── requirements.txt
└── frontend/               Next.js dashboard (App Router + Tailwind + TypeScript)
```

---

## Prerequisites

- Python 3.10+
- Node.js 18+
- IBKR paper or live account
- TWS (Trader Workstation) or IB Gateway installed and running

---

## Backend Setup

### 1. Create virtual environment

```
cd backend
py -m venv venv
venv\Scripts\activate
```

### 2. Install dependencies

```
pip install -r requirements.txt
```

### 3. Configure the bot

Edit `config.json` in the project root:

```json
{
    "host": "127.0.0.1",
    "port": 7497,
    "client_id": 1,
    "risk_percent": 0.5,
    "cancel_after_minutes": 15,
    "trailing_timeframe_minutes": 5,
    "account": "",
    "test_mode": false
}
```

| Field | Description |
|---|---|
| `host` | Always `127.0.0.1` |
| `port` | `7497` = TWS paper, `7496` = TWS live, `4002` = Gateway paper, `4001` = Gateway live |
| `client_id` | Any integer — must be unique per connected client |
| `risk_percent` | % of account to risk per trade (e.g. `0.5` = 0.5%) |
| `cancel_after_minutes` | Cancel unfilled buy orders after this many minutes |
| `trailing_timeframe_minutes` | Candle size for trailing stop (default 5) |
| `account` | Leave empty for single accounts |
| `test_mode` | `true` = triggers candle tracking 2 min after start instead of waiting for 9:30 ET |

### 4. Add tickers

Edit `tickers.txt` — one ticker per line, max 15:

```
AAPL
MSFT
TSLA
```

### 5. Run the backend

```
uvicorn app.main:app --reload --port 8000
```

API docs available at: `http://localhost:8000/docs`

---

## Frontend Setup

### 1. Install dependencies

```
cd frontend
npm install
```

### 2. Run the frontend

```
npm run dev
```

Dashboard available at: `http://localhost:3000`

---

## TWS / IB Gateway Setup

1. Open TWS and log in (use paper account for testing)
2. Go to **Edit → Global Configuration → API → Settings**
3. Check **Enable ActiveX and Socket Clients**
4. Set **Socket port** to `7497` (paper) or `7496` (live)
5. Check **Allow connections from localhost only**
6. Uncheck **Read-Only API**
7. Click **Apply → OK**

---

## Port Reference

| Mode | TWS | IB Gateway |
|---|---|---|
| Paper trading | `7497` | `4002` |
| Live trading | `7496` | `4001` |

---

## REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/bot/start` | Start the bot |
| `POST` | `/bot/stop` | Stop the bot |
| `GET` | `/bot/status` | Get current bot status |
| `GET` | `/positions/` | Get all open positions |
| `GET` | `/trades/today` | Get today's trade log |
| `WS` | `/ws` | WebSocket — real-time events |

### WebSocket Events

All events are JSON: `{ "event": "<name>", "data": { ... } }`

| Event | Description |
|---|---|
| `bot_status` | Bot started, stopped, or errored |
| `position_update` | Position opened or updated |
| `trade_fill` | Buy or sell order filled |
| `stop_update` | Trailing stop moved up |

---

## Daily Workflow

1. Update `tickers.txt` before 9:30 AM ET
2. Open TWS and log in
3. Start backend: `uvicorn app.main:app --reload --port 8000`
4. Start frontend: `npm run dev`
5. Open `http://localhost:3000`
6. Click **Start Bot**
7. Bot waits for 9:30 candle, places orders, manages stops automatically
8. Bot shuts down automatically at 4:00 PM ET or click **Stop Bot** anytime

---

## Strategy — Opening Range Breakout

| Step | Detail |
|---|---|
| Candle | First 1-minute candle (9:30–9:31 ET) |
| Entry | Stop-market buy at candle high |
| Initial stop | Candle low |
| Cancel window | `cancel_after_minutes` after open if not triggered |
| Trailing stop | Trails below completed N-minute candle lows |
| Stop direction | Only moves up, never down |
| Position sizing | `floor(account × risk% ÷ (entry − stop))` |

---

## Troubleshooting

**Connection refused on port 7497**
- TWS is not running or API is not enabled
- Check port matches between `config.json` and TWS settings

**`ZoneInfoNotFoundError: America/New_York`**
- Run `pip install tzdata` (required on Windows)

**`No module named 'ib_insync'`**
- Make sure venv is activated: `venv\Scripts\activate`

**Bot status shows "error" after clicking Start**
- TWS is not running — start TWS first, then click Start Bot

**Orders not placing**
- Make sure `test_mode` is `false` for live/paper sessions
- Verify market data subscription is active on the IBKR account
