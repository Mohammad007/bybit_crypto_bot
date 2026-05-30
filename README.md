# BYBIT CRYPTO BREAKOUT BOT

**Multi-symbol crypto scanner for Bybit V5 USDT Perpetuals.** Each cycle it scans the
**top 30 coins by 24h volume**, runs a Trendline Break + Retest + Confirmation strategy on
every one, ranks the signals, and opens trades on the strongest — all on a **demo account**
by default, with a live Rich CLI dashboard.

> **Disclaimer.** Trading leveraged crypto perpetuals carries substantial risk of loss.
> This software is provided **as-is** with no warranty of profitability. It defaults to
> Bybit **demo trading** — test thoroughly before pointing it at a real account.

---

## ✨ Features

- **Top-30 scanner** – every tick it pulls M15 history + EMA/RSI/ATR for all 30 symbols,
  asks the strategy for a BUY/SELL/HOLD verdict on each, ranks the hits, and opens up to
  `max_new_per_tick` trades (bounded by `max_concurrent_trades`).
- **Bybit V5 (linear USDT perps)** via the official [`pybit`](https://github.com/bybit-exchange/pybit) SDK.
  Demo / testnet / live selectable by env flag.
- **Percentage-based strategy** – SL/TP/ATR thresholds are all expressed as a *percent of
  price*, so the identical config works on $100k BTC and $0.40 DOGE.
- **Live top-30 universe** – resolved from Bybit by 24h turnover at startup (with a static
  fallback list for offline/paper mode).
- **Strict risk engine** – % risk per trade, max concurrent trades, max trades/day, kill switch.
- **Native SL/TP** – attached to each position (`tpslMode=Full`); positions close at the broker.
- **Live dashboard** – Rich terminal UI: focus-symbol ASCII candles, a live scanner table of
  all 30 symbols, open trades, and account/PnL.
- **Paper mode** – fully offline synthetic broker for testing the engine with no API keys.
- **Alerts** – Telegram + Discord webhooks (opt-in).
- **Trade journal** – SQLite store of every trade & signal, with a win-rate report.

---

## 🚀 Quick Start

```powershell
cd d:\Trading\crypto_bot
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell
# source .venv/bin/activate       # Linux / macOS

pip install -r requirements.txt

copy .env.example .env            # Windows  (cp on Linux/macOS)
# edit .env → set BYBIT_API_KEY / BYBIT_API_SECRET (demo keys)

python main.py start              # demo trading + live dashboard
```

No API keys yet? Run the offline simulator: `python main.py start --paper`.
Exit the dashboard with `Ctrl+C`.

### Getting Bybit demo API keys

1. Log in at [bybit.com](https://www.bybit.com/) → switch to **Demo Trading**.
2. **API Management** → create a key with *Contract → Orders/Positions* + *Wallet* read/trade
   permissions.
3. Put the key/secret in `.env` and keep `BYBIT_DEMO=true`.

---

## 🖥️ CLI Commands

| Command                                          | Description                                          |
|--------------------------------------------------|------------------------------------------------------|
| `start [--paper\|--demo\|--live] [--no-dashboard]` | Start the scanner + dashboard                        |
| `dashboard`                                      | Open the live dashboard with the scanner             |
| `status`                                         | Show config + journal stats                          |
| `universe [--live]`                              | Show the trading universe (`--live` = query Bybit)   |
| `symbol [SYMBOL]`                                | View / set the default focus symbol for the chart    |
| `paper-mode` / `demo-mode` / `live-mode`         | Switch the persisted `MODE` in `.env`                |
| `winrate [--since today\|week\|all]`             | Win-rate report by entry timeframe                   |
| `reconcile`                                      | Force-sync the journal with the broker               |
| `wipe-journal [--yes]`                           | Delete all journal trades & signals                  |
| `test-alerts`                                    | Send a test Telegram/Discord alert                   |
| `emergency-stop`                                 | Close all positions + write a kill-switch file       |

---

## 🧠 How a Trade Is Made

1. The engine resolves the **universe**: the live top-30 USDT perps by 24h turnover.
2. Each cycle (`bot.refresh_seconds`, default 6s) it pulls M15 OHLCV for every symbol and adds
   **EMA20 / EMA50 / RSI / ATR**.
3. The **Trendline Breakout** strategy checks 5 rules per symbol:
   - **Trend** — EMA20 vs EMA50 and RSI vs `rsi_bull/bear`
   - **Volatility** — `ATR/price*100 > atr_pct_min`
   - **Liquidity** — prior swing sweep
   - **Breakout** — close beyond the previous candle's high/low (market mode)
   - **Confirmation** — candle body `> body_pct_min` of price (market mode)
4. Actionable signals are **ranked** (by confidence or turnover) and the top
   `scanner.max_new_per_tick` are opened, subject to the risk envelope and one position/symbol.
5. `RiskEngine.size_position` turns *risk%* into a coin quantity: `qty = (capital·risk%) / |entry−SL|`.
   The broker rounds it to the instrument's `qtyStep` / `minOrderQty`.
6. A **market order** with attached SL (`±sl_pct`) and TP (`±tp_pct`) goes to Bybit; the trade is
   journalled. Positions close at the broker on SL/TP and are reconciled into the journal.

---

## 📁 Project Structure

```
crypto_bot/
├── core/                 # BotEngine (multi-symbol scanner), state
├── indicators/           # EMA / RSI / ATR
├── execution/            # base broker, Bybit V5 broker, paper broker, factory
├── dashboard/            # Rich live dashboard + ASCII charts
├── risk_management/      # risk engine, qty sizing, trailing/BE (disabled by default)
├── database/             # SQLite trade journal (SQLAlchemy)
├── strategies/           # trendline_breakout (percentage-based), registry
├── config/               # settings.py + config.yaml (universe, scanner, risk, strategy)
├── tests/                # pytest suite
├── logs/                 # rotating daily / trade / error logs
└── main.py               # Typer CLI entry-point
```

---

## ⚙️ Configuration

Two layers, merged at startup: **`config/config.yaml`** (logic & knobs) and **`.env`** (secrets
& runtime overrides). Most-touched knobs:

```yaml
universe:
  auto_top30: true        # resolve the live top-30 by turnover at startup
  count: 30

scanner:
  max_new_per_tick: 2      # open at most N new trades per scan cycle
  rank_by: "confidence"    # confidence | turnover

risk:
  risk_per_trade_pct: 1.0
  max_concurrent_trades: 5 # how many coins the scanner may hold at once
  max_trades_per_day: 40

strategies:
  trendline_breakout:
    order_type: "market"   # market | stop (conditional order at breakout level)
    sl_pct: 1.0            # stop distance as % of entry
    tp_pct: 2.0            # take-profit distance as % of entry (1:2 R:R)
    atr_pct_min: 0.30      # min ATR as % of price
```

`.env` controls the broker target:

```
MODE=demo                  # paper | demo | live
BYBIT_API_KEY=...
BYBIT_API_SECRET=...
BYBIT_DEMO=true            # api-demo.bybit.com
BYBIT_TESTNET=false        # public testnet (overrides demo)
BYBIT_LEVERAGE=5
```

---

## 🧪 Testing

```powershell
pytest -q
```

The smoke tests run entirely against the paper broker (no network), so they're safe in CI.

---

## 🐳 Docker / VPS

Because Bybit is a REST/WebSocket API (no Windows-only SDK), the bot runs anywhere — including
Linux containers and Railway — in **demo or live** mode.

```bash
docker build -t bybit-crypto-bot .
docker run --env-file .env -it bybit-crypto-bot
```

See [DEPLOY.md](DEPLOY.md) for VPS / Railway instructions.

---

## 📜 License

Internal / proprietary unless redistributed by the author.
