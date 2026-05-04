
### How it works (engineering view)

1. **Initialization**  
   - Load API keys from `.env`  
   - Connect to Toobit, fetch initial balance  
   - Restore previous state (balance, open positions, cooldowns) from SQLite  
   - Setup Telegram notifier

2. **Main Loop** (scheduled or single test)  
   - Fetch latest 200+ 15m candles from Binance  
   - Calculate indicators (EMA, MA, ADX, ATR, volume)  
   - Update local database with latest candle  
   - Sync with Toobit if live trading enabled

3. **Position Management**  
   - **No open position** → evaluate entry score (based on cross signals, trend, ADX, volume)  
     - If score ≥ threshold → open Long or Short via Toobit API  
     - Save order details in DB, send Telegram alert  
   - **Open position** → evaluate exit score (loss guard, trend reversal, trailing, ADX drop)  
     - If score ≥ threshold → close position via Toobit, calculate PnL  
     - Update balance, apply monthly profit filters, save to DB, send alert

4. **Risk & Runtime Controls**  
   - Monthly profit cap (stop trading after `monthly_profit_percent_stop_trade`)  
   - Cooldown after large win (`cooldown_after_big_pnl`)  
   - Skip trades after 2 consecutive losses  
   - Drawdown tracking & max drawdown calculation

5. **State Persistence**  
   - All critical variables (balance, open positions, entry index, cooldown counters) are saved to SQLite  
   - Bot can be restarted without losing state

---

## 📊 Database Schema (simplified)

| Table | Purpose |
|-------|---------|
| `balance_state` | stores `first_balance`, `tactical_balance` for local and Toobit modes |
| `open_orders` | current open position (side, entry price, size, margin, leverage, timestamps) |
| `runtime_state` | last trade cross time, skip trades left, consecutive losses, trade power flag |
| `symbol_data` | historical OHLCV (for debugging/backtesting) |

All DB operations are wrapped in the `Database` class.

---

## 🚀 Getting Started

### 1. Clone & install dependencies
```bash
git clone https://github.com/nvdiw/toobit_8percent.git
cd toobit_8percent
pip install requests python-dotenv numpy

2. Set up environment
Create a .env file:
add to .env:
TOOBIT_API_KEY=your_toobit_api_key
TOOBIT_API_SECRET=your_toobit_secret
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

3. Run the bot:
# Normal scheduled mode (every 15 min)
python main.py

# Test mode (run once immediately)
python main.py --test

# With RAM monitor
python main.py --rammonitor

📈 Example Output (console & Telegram)
📊 Fetching OHLCV data...
Initial balance locked at 1000.0 (local balance (first tick))
Toobit balance fetched (not synced): 1000.0
ORDER OPENED #1: LONG @ 65000 | size=0.00769 | margin=50.0 | lev=10
[Telegram] 🔔 LONG opened at 65000
ORDER CLOSED #2: LONG closed @ 65500 | P/L: 3.85 (7.7%)
[Telegram] 📉 LONG closed with profit 3.85 USDT

📬 Contact & Links

    GitHub: github.com/nvdiw
    Telegram: @nvdiw