# Setup Guide

## 1. Prerequisites

- Python **3.11+** (tested on 3.13)
- Any OS — Windows / Linux / macOS (Bybit is a REST API, no platform-specific SDK)
- A Bybit account with **Demo Trading** enabled

## 2. Install Python deps

```powershell
cd d:\Trading\crypto_bot
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Bybit demo API keys

1. Log in at https://www.bybit.com/ and switch the account to **Demo Trading**.
2. Go to **API Management** → **Create New Key** (System-generated).
3. Permissions: enable **Contract → Orders & Positions** and **Wallet** (read).
4. Copy the API key + secret.

## 4. Environment

```powershell
copy .env.example .env
notepad .env
```

Required keys:

| Key                       | Default   | Purpose                                       |
|---------------------------|-----------|-----------------------------------------------|
| `MODE`                    | `demo`    | `paper` (offline) · `demo` · `live`           |
| `BYBIT_API_KEY/SECRET`    | –         | required for `demo` / `live`                  |
| `BYBIT_DEMO`              | `true`    | `true` = api-demo.bybit.com (demo trading)    |
| `BYBIT_TESTNET`           | `false`   | `true` = public testnet (overrides demo)      |
| `BYBIT_LEVERAGE`          | `5`       | leverage applied per symbol                   |
| `RISK_PER_TRADE`          | `1.0`     | % of equity risked per trade                  |
| `CAPITAL`                 | `1000`    | used for sizing in paper mode (live reads real balance) |
| `TELEGRAM_BOT_TOKEN/CHAT` | –         | optional alerts                               |
| `DISCORD_WEBHOOK_URL`     | –         | optional alerts                               |

## 5. Run

```powershell
python main.py start --paper      # offline simulator, no keys needed
python main.py start              # Bybit demo trading (uses MODE from .env)
```

## 6. Smoke test

```powershell
pytest -q
```

## 7. Useful commands

```powershell
python main.py status             # config + journal summary
python main.py universe --live    # live top-30 by Bybit 24h turnover
python main.py test-alerts        # verify Telegram/Discord
python main.py winrate --since week
python main.py emergency-stop     # close everything now
```

## 8. Going live (do this last)

1. Paper- and demo-trade until the strategy behaves as expected.
2. `python main.py live-mode` (asks for confirmation, sets `MODE=live`).
3. Set `BYBIT_DEMO=false` and provide **real-account** API keys.
4. Start small: `RISK_PER_TRADE=0.5`, low `BYBIT_LEVERAGE`, low `max_concurrent_trades`.
5. `python main.py start --live`.
