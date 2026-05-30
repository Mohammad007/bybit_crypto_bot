# Deployment Guide

Unlike the old MT5 build, this bot talks to Bybit over a plain REST/WebSocket API, so it runs
**anywhere** — Windows, Linux, macOS, Docker, and cloud PaaS — in **paper, demo, or live** mode.

| Platform           | Paper | Demo (Bybit) | Live (Bybit) |
|--------------------|:-----:|:------------:|:------------:|
| Windows PC / VPS   | ✅    | ✅           | ✅           |
| Linux VPS          | ✅    | ✅           | ✅           |
| Docker (Linux)     | ✅    | ✅           | ✅           |
| Railway / Render   | ✅    | ✅           | ✅           |
| macOS              | ✅    | ✅           | ✅           |

---

## A) Linux VPS (recommended for 24×7)

```bash
git clone <your-repo> crypto_bot && cd crypto_bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit: BYBIT_API_KEY/SECRET, MODE=demo
python main.py start --no-dashboard      # headless loop
```

Run it under `systemd`, `tmux`, or `pm2` so it survives disconnects. For the dashboard over SSH,
just run `python main.py start` in a `tmux` session.

## B) Docker

```bash
docker build -t bybit-crypto-bot .
docker run --env-file .env -d --name crypto_bot bybit-crypto-bot
docker logs -f crypto_bot
```

The container runs `python main.py start --no-dashboard` by default (headless).

## C) Railway / Render

1. Push the repo to GitHub (the `.env` is git-ignored — set vars in the dashboard instead).
2. New Project → Deploy from GitHub repo.
3. Add environment variables:
   ```
   MODE=demo
   BYBIT_API_KEY=...
   BYBIT_API_SECRET=...
   BYBIT_DEMO=true
   BYBIT_LEVERAGE=5
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
   ```
4. `railway.toml` is provided and starts the bot headless. You'll get Telegram alerts on every
   trade open/close.

---

## 🧪 Sanity check before going live

1. `python main.py status` — verify mode, leverage, universe.
2. `python main.py universe --live` — confirm Bybit connectivity + the top-30.
3. `python main.py test-alerts` — confirm alerts work.
4. `python main.py start --demo` — watch a few hours; confirm scans, orders, SL/TP behave.
5. Only then `live-mode`, set `BYBIT_DEMO=false`, real keys, small risk.
