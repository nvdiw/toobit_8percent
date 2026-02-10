import requests
import time
import argparse
import os
import hmac
import hashlib
import uuid
from urllib.parse import urlencode
from datetime import datetime, timezone

# My Files
from indicators import Indicator
from telegram_bot import TelegramNotifier
from database import Database
from rammonitor import RamMonitor
from trademanager import TradeManager
from trade_csv_logger import TradeCSVLogger

VALID_MINUTES = {0, 15, 30, 45}
FETCH_WINDOW_SECONDS = 10
BOT_TOKEN = None
CHAT_ID = None
api_key = None
api_secret = None

# ---- Toobit settings ----
TOOBIT_ENABLED = True
TOOBIT_EXECUTE_ORDERS = True  # set False for dry-run without live orders
TOOBIT_BASE_URL = "https://api.toobit.com"
TOOBIT_CATEGORY = "USDT"
TOOBIT_SYMBOL = "BTC-SWAP-USDT"
TOOBIT_BALANCE_ASSET = "USDT"
TOOBIT_RECV_WINDOW = 5000
TOOBIT_REFRESH_BALANCE_EACH_CYCLE = True
TOOBIT_SYNC_BALANCE = False  # keep local demo balance if False
TOOBIT_KEY_FILE = "API KEY.txt"

# ---- settings is here ----
balance = 1000
leverage = 5
trade_amount_percent = 0.5  # 50% of balance per trade
monthly_profit_percent_stop_trade = 8    # if 8% per month profit --> don't trade on that month 
monthly_compound = 3    # after get 'monthly_profit_percent_stop_trade' per month how much money goes for next month
monthly_close_filter = False
adx_filter = True
volume_filter = True

ma_distance_threshold = 0.00204  # 0.2٪
candle_move_threshold = 0.0082 # 0.8٪

cooldown_after_big_pnl = 4 * 24  # 4 * 48  # 4 * x   [x] ---> number of candles per hour
cooldown_until_index = -1

# fee rate
fee_rate = 0.0005  # 0.05% per trade (entry or exit)

save_money = 0
total_wins = 0
total_wins_long = 0
total_wins_short = 0
total_losses = 0
total_long = 0
total_short = 0
total_profit_percent = 0
deducting_fee_total = 0
count_closed_orders = 0
profit_percent_per_month = 0
lst_profit_percent_per_month = []
# lists / trackers
profits_lst = []
equity_curve = []
max_drawdown = 0
toobit_balance = None

entry_price = None
position_size = None
position_size_no_fee = None
margin = 0
margin_no_fee = 0
balance_before_trade = None
balance_before_trade_no_fee = None
open_time_value = None

trade_power = True

balance_without_fee = balance
first_balance = balance
tactical_balance = first_balance

current_position = None  # None | "long" | "short"


# ------------------ Toobit API helpers ------------------
def _load_toobit_keys():
    api_key = os.getenv("TOOBIT_API_KEY")
    api_secret = os.getenv("TOOBIT_API_SECRET")

    if api_key and api_secret:
        return api_key.strip(), api_secret.strip()

    key_path = os.path.join(os.path.dirname(__file__), TOOBIT_KEY_FILE)
    if not os.path.exists(key_path):
        raise RuntimeError(
            "Toobit API keys not found. Set TOOBIT_API_KEY/TOOBIT_API_SECRET env vars "
            f"or create '{TOOBIT_KEY_FILE}'."
        )

    file_key = None
    file_secret = None
    with open(key_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("api_key"):
                file_key = line.split("=", 1)[1].strip().strip("\"'")
            elif line.startswith("secret_key"):
                file_secret = line.split("=", 1)[1].strip().strip("\"'")

    if not file_key or not file_secret:
        raise RuntimeError(f"Could not parse api_key/secret_key from '{TOOBIT_KEY_FILE}'.")

    return file_key, file_secret


def _load_telegram_config():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if bot_token and chat_id:
        try:
            return bot_token.strip(), int(chat_id)
        except Exception:
            raise RuntimeError("Invalid TELEGRAM_CHAT_ID env var; must be integer.")

    key_path = os.path.join(os.path.dirname(__file__), TOOBIT_KEY_FILE)
    if not os.path.exists(key_path):
        raise RuntimeError(
            "Telegram config not found. Set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID env vars "
            f"or add BOT_TOKEN_TELEGRAM/CHAT_ID to '{TOOBIT_KEY_FILE}'."
        )

    file_token = None
    file_chat_id = None
    with open(key_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("BOT_TOKEN_TELEGRAM") or line.startswith("BOT_TOKEN"):
                file_token = line.split("=", 1)[1].strip().strip("\"'")
            elif line.startswith("CHAT_ID"):
                file_chat_id = line.split("=", 1)[1].strip().strip("\"'")

    if not file_token or not file_chat_id:
        raise RuntimeError(f"Could not parse BOT_TOKEN_TELEGRAM/CHAT_ID from '{TOOBIT_KEY_FILE}'.")

    try:
        return file_token, int(file_chat_id)
    except Exception:
        raise RuntimeError("Invalid CHAT_ID in key file; must be integer.")


def _toobit_format_number(value, precision=8):
    if value is None:
        return None
    try:
        value = float(value)
    except Exception:
        return str(value)
    formatted = f"{value:.{precision}f}".rstrip("0").rstrip(".")
    return formatted if formatted else "0"


def _calc_live_value_quantity(tb_balance, percent, leverage):
    if tb_balance is None:
        return None
    try:
        tb_balance = float(tb_balance)
        percent = float(percent)
        leverage = float(leverage)
    except Exception:
        return None
    if tb_balance <= 0 or percent <= 0 or leverage <= 0:
        return None
    live_margin = tb_balance * percent
    return live_margin * leverage


def _toobit_signed_request(method, path, params=None):
    api_key, api_secret = _load_toobit_keys()

    params = params or {}
    # remove None values
    params = {k: v for k, v in params.items() if v is not None}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = TOOBIT_RECV_WINDOW

    # build query string in a stable order
    query = urlencode([(k, str(params[k])) for k in params])
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    url = f"{TOOBIT_BASE_URL}{path}?{query}&signature={signature}"
    headers = {"X-BB-APIKEY": api_key}

    response = requests.request(method, url, headers=headers, timeout=10)
    try:
        data = response.json()
    except Exception:
        raise RuntimeError(f"Toobit non-JSON response: HTTP {response.status_code} -> {response.text}")

    if response.status_code != 200:
        raise RuntimeError(f"Toobit HTTP {response.status_code}: {data}")

    if isinstance(data, dict) and data.get("code") not in (None, 200):
        raise RuntimeError(f"Toobit error {data.get('code')}: {data.get('msg')}")

    return data


def toobit_get_balance(asset=TOOBIT_BALANCE_ASSET):
    data = _toobit_signed_request(
        "GET",
        "/api/v1/futures/balance",
        params={"category": TOOBIT_CATEGORY}
    )

    # some responses wrap the list in "data"
    if isinstance(data, dict) and "data" in data:
        data = data["data"]

    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected Toobit balance response: {data}")

    for item in data:
        if item.get("asset") == asset:
            available = item.get("availableBalance")
            total = item.get("balance")
            return float(available if available is not None else total)

    raise RuntimeError(f"Asset {asset} not found in Toobit balance response.")


def toobit_get_positions(symbol=None, side=None):
    params = {"category": TOOBIT_CATEGORY}
    if symbol:
        params["symbol"] = symbol
    if side:
        params["side"] = side
    data = _toobit_signed_request("GET", "/api/v1/futures/positions", params=params)

    if isinstance(data, dict) and "data" in data:
        data = data["data"]

    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected Toobit positions response: {data}")

    return data


def toobit_get_open_position(symbol=TOOBIT_SYMBOL, side=None):
    positions = toobit_get_positions(symbol=symbol, side=side)
    for pos in positions:
        try:
            qty = float(pos.get("position", 0))
        except Exception:
            qty = 0
        if pos.get("symbol") == symbol and qty > 0:
            return pos
    return None


def toobit_set_leverage(symbol, leverage):
    return _toobit_signed_request(
        "POST",
        "/api/v1/futures/leverage",
        params={
            "symbol": symbol,
            "leverage": int(leverage),
            "category": TOOBIT_CATEGORY
        }
    )


def toobit_place_order(symbol, side, quantity=None, value_quantity=None, price_type="MARKET", order_type="LIMIT"):
    if quantity is None and value_quantity is None:
        raise RuntimeError("Toobit order requires quantity or value_quantity.")

    if order_type:
        order_type = str(order_type).upper()
    if price_type:
        price_type = str(price_type).upper()

    # Toobit futures order API expects type=LIMIT/STOP; market orders use priceType=MARKET.
    if order_type == "MARKET":
        order_type = "LIMIT"
        if not price_type:
            price_type = "MARKET"

    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "priceType": price_type,
        "newClientOrderId": f"bot_{uuid.uuid4().hex[:12]}",
        "category": TOOBIT_CATEGORY
    }

    if quantity is not None:
        qty_val = float(quantity)
        if qty_val <= 0:
            raise RuntimeError("Toobit order quantity must be > 0.")
        params["quantity"] = _toobit_format_number(qty_val, precision=6)
    if value_quantity is not None:
        val_qty = float(value_quantity)
        if val_qty <= 0:
            raise RuntimeError("Toobit order value_quantity must be > 0.")
        params["valueQuantity"] = _toobit_format_number(val_qty, precision=2)

    return _toobit_signed_request("POST", "/api/v1/futures/order", params=params)


def toobit_close_position(symbol, side):
    side = side.upper()
    pos = toobit_get_open_position(symbol=symbol, side=side)
    if not pos:
        raise RuntimeError("No open Toobit position to close.")

    qty = pos.get("available")
    if qty is None:
        qty = pos.get("position")

    try:
        qty = float(qty)
    except Exception:
        qty = 0

    if qty <= 0:
        try:
            qty = float(pos.get("position", 0))
        except Exception:
            qty = 0

    if qty <= 0:
        raise RuntimeError("Toobit position quantity is zero.")

    if side == "LONG":
        close_side = "SELL_CLOSE"
    elif side == "SHORT":
        close_side = "BUY_CLOSE"
    else:
        raise RuntimeError(f"Unknown position side: {side}")

    return toobit_place_order(
        symbol=symbol,
        side=close_side,
        quantity=qty,
        price_type="MARKET",
        order_type="LIMIT"
    )


def init_toobit_balance():
    global balance, balance_without_fee, first_balance, tactical_balance, toobit_balance
    toobit_balance = toobit_get_balance()
    if TOOBIT_SYNC_BALANCE:
        balance = toobit_balance
        balance_without_fee = toobit_balance
        first_balance = toobit_balance
        tactical_balance = first_balance
        print(f"Toobit balance synced: {balance}")
    else:
        print(f"Toobit balance fetched (not synced): {toobit_balance}")


# ---- load Telegram config at startup ----
BOT_TOKEN, CHAT_ID = _load_telegram_config()


# get open, high, low, close, volume with json data
def get_ohlcv(
    symbol="BTCUSDT",
    interval="15m",
    limit=100):
    """
    Fetch OHLCV data from Binance
    
    symbol   : trading pair (default BTCUSDT)
    interval : timeframe (1m, 5m, 15m, 1h, 4h, 1d, ...)
    limit    : number of candles
    """

    url = "https://api.binance.com/api/v3/klines"

    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit
    }
    print("📊 Fetching OHLCV data...")
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        return data
    
    except Exception as e:
        # more helpful debug message and explicit None return for callers to handle
        print("Fetching OHLCV Error:", repr(e))
        return None

# Main Trading Logic
def ma_strategy():
    global balance, balance_without_fee, current_position, margin, trade_power, cooldown_until_index, leverage, position_size_no_fee, margin_no_fee, balance_before_trade, balance_before_trade_no_fee, deducting_fee_total, profits_lst, total_profit_percent, count_closed_orders, equity_curve, max_drawdown, total_wins, total_wins_long, total_wins_short, total_losses, total_long, total_short, profit_percent_per_month, save_money, toobit_balance

    entry_price = None
    position_size = None
    open_time_value = None

    csv_logger = TradeCSVLogger()

    # send message to telegram
    signal_message = TelegramNotifier(bot_token=BOT_TOKEN, chat_id = CHAT_ID)

    open_times = []
    open_prices = []
    high_prices = []
    low_prices = []
    close_prices = []
    volume_prices = []
    close_times = []

    # get data from binance
    required_candles = 201
    data = get_ohlcv(symbol="BTCUSDT", interval="15m", limit=required_candles)  # BTCUSDT by default

    # If fetch failed (e.g. transient network), retry for a short grace period so the bot doesn't exit
    if not data or len(data) < 2:
        start_ts = time.time()
        grace = 60  # seconds to tolerate transient outage
        retry_interval = 5
        print(f"⚠️ No OHLCV received — retrying for up to {grace}s (interval={retry_interval}s)...")
        while time.time() - start_ts < grace:
            time.sleep(retry_interval)
            data = get_ohlcv(symbol="BTCUSDT", interval="15m", limit=required_candles)
            if data and len(data) >= 2:
                print("✅ OHLCV recovered")
                break
            print(".", end="", flush=True)
        else:
            # grace period expired — do NOT crash; skip this cycle and remain running
            print("\n⚠️ Still no OHLCV after grace period — skipping this cycle but staying alive.")
            return

    # validate we have enough candles for indicators (warn but continue with available data)
    if len(data) < required_candles:
        print(f"⚠️ Warning: fetched {len(data)} candles (expected {required_candles}); continuing with available data.")

    # Fetch OHLCV data from Binance and normalize candle timestamps (UTC)
    for i in range(len(data) - 1):
        open_times.append(str(datetime.fromtimestamp(data[i][0] / 1000, tz=timezone.utc)))
        open_prices.append(float(data[i][1]))
        high_prices.append(float(data[i][2]))
        low_prices.append(float(data[i][3]))
        close_prices.append(float(data[i][4]))
        volume_prices.append(float(data[i][5]))
        close_times.append(str(datetime.fromtimestamp((data[i][6] / 1000) + 0.001, tz=timezone.utc)))

    # move data to database.db
    db = Database(db_name="database.db")
    print(f"inserting data to database.db at {close_times[-1]}")
    db.insert_data(symbol= "BTCUSDT",
                   open_times= open_times[-1],
                   open_prices= open_prices[-1],
                   high_prices= high_prices[-1],
                   low_prices= low_prices[-1],
                   close_prices= close_prices[-1],
                   volume_prices= volume_prices[-1],
                   close_times= close_times[-1]
                   )

    # --- restore open order if exists (persist across restarts)
    open_order = db.get_open_order()
    order_id = None
    if open_order is not None:
        order_id = open_order['id']
        current_position = open_order['side']
        entry_price = open_order['entry_price']
        position_size = open_order['position_size']
        margin = open_order['margin']
        leverage = open_order['leverage']
        open_time_value = open_order['open_time']
        # restore additional saved fields if present
        if open_order.get('balance') is not None:
            balance = open_order.get('balance')
        if open_order.get('balance_without_fee') is not None:
            balance_without_fee = open_order.get('balance_without_fee')
        if open_order.get('balance_before_trade') is not None:
            balance_before_trade = open_order.get('balance_before_trade')
        if open_order.get('balance_before_trade_no_fee') is not None:
            balance_before_trade_no_fee = open_order.get('balance_before_trade_no_fee')
        if open_order.get('margin_no_fee') is not None:
            margin_no_fee = open_order.get('margin_no_fee')
        if open_order.get('position_size_no_fee') is not None:
            position_size_no_fee = open_order.get('position_size_no_fee')
        if open_order.get('current_position') is not None:
            current_position = open_order.get('current_position')

        print(f"Restored open order #{order_id}: {current_position} @ {entry_price} (time={open_time_value}, margin={margin}, lev={leverage})")
    
    # restore demo balance from DB when not syncing to Toobit
    if not TOOBIT_SYNC_BALANCE:
        balance, balance_without_fee = db.get_current_balances(initial_balance=first_balance)

    if TOOBIT_ENABLED:
        try:
            if TOOBIT_REFRESH_BALANCE_EACH_CYCLE:
                tb_balance = toobit_get_balance()
                toobit_balance = tb_balance
                if TOOBIT_SYNC_BALANCE:
                    balance = tb_balance
                    balance_without_fee = tb_balance
        except Exception as e:
            print("Toobit balance fetch failed:", e)
            if TOOBIT_SYNC_BALANCE:
                return

        try:
            pos = toobit_get_open_position(symbol=TOOBIT_SYMBOL)
            if pos:
                pos_side = pos.get("side")
                if pos_side == "LONG":
                    current_position = "long"
                elif pos_side == "SHORT":
                    current_position = "short"
                sync_live_to_local = TOOBIT_SYNC_BALANCE or order_id is None or margin in (None, 0)
                avg_price = pos.get("avgPrice")
                if sync_live_to_local and avg_price not in (None, "", "0", 0):
                    try:
                        entry_price = float(avg_price)
                    except Exception:
                        pass
                pos_lev = pos.get("leverage")
                if sync_live_to_local and pos_lev not in (None, "", "0", 0):
                    try:
                        leverage = int(float(pos_lev))
                    except Exception:
                        pass
                pos_margin = pos.get("margin")
                live_margin = None
                if pos_margin not in (None, "", "0", 0):
                    try:
                        live_margin = float(pos_margin)
                    except Exception:
                        live_margin = None
                if sync_live_to_local and live_margin not in (None, 0):
                    margin = live_margin
                if position_size is None and entry_price and margin and leverage:
                    try:
                        position_size = (float(margin) * float(leverage)) / float(entry_price)
                    except Exception:
                        pass
                if position_size_no_fee in (None, 0) and position_size is not None:
                    position_size_no_fee = position_size
                if margin_no_fee in (None, 0) and margin:
                    margin_no_fee = margin
                if balance_before_trade is None:
                    balance_before_trade = balance
                if balance_before_trade_no_fee is None:
                    balance_before_trade_no_fee = balance_without_fee
                if open_time_value is None:
                    open_time_value = datetime.now(timezone.utc).isoformat()
            else:
                if current_position is not None:
                    print("Warning: Toobit shows no open position; clearing local position.")
                current_position = None
        except Exception as e:
            print("Toobit position sync failed:", e)
    else:
        if TOOBIT_SYNC_BALANCE:
            balance, balance_without_fee = db.get_current_balances(initial_balance=first_balance)

    # ---- get MA/EMA ----
    indicator = Indicator(close_prices, period=None)
    ema_14 = indicator.get_EMA(14)[-1]
    ma_50 = indicator.get_MA(50)[-1]
    ma_130 = indicator.get_MA(130)[-1]
    ma_200 = indicator.get_MA(200)[-1]

    # ---- get_ADX ----
    indicator = Indicator(close_prices)
    adx = indicator.get_ADX(
        high_prices,
        low_prices,
        close_prices,
        period=14)[-1]
    
    # ---- MANAGE TRADES ----
    trade_manager = TradeManager(csv_logger, first_balance, monthly_profit_percent_stop_trade, 
                                 tactical_balance, monthly_close_filter, monthly_compound)

    # Calculate MA Distance
    ma_distance = abs(ema_14 - ma_50) / ma_50

    # Calculate Distance New Candle Move and Last Candle Move
    last_candle_move = abs(close_prices[-1] - close_prices[-2]) / close_prices[-2]

    margin_balance = balance + (margin if current_position is not None else 0)

    # ---- Monthly close filter: if trading is disabled (trade_power==False)
    # detect month boundaries from `close_times` and re-enable trading
    # when a new month starts. Uses indices within the fetched data
    # (avoids relying on an undefined `start` or `i`).
    if monthly_close_filter:
        # build set of month-start indices in the fetched data
        lst_month_starts = set()
        prev_month = None
        for idx, t in enumerate(close_times):
            try:
                dt = datetime.fromisoformat(t)
            except Exception:
                # fallback if formatting differs
                dt = datetime.fromtimestamp(datetime.fromisoformat(t).timestamp(), tz=timezone.utc)
            if prev_month is None or dt.month != prev_month:
                lst_month_starts.add(idx)
            prev_month = dt.month

        current_index = len(close_times) - 1

        if not trade_power:
            if current_index in lst_month_starts:
                lst_profit_percent_per_month.append(profit_percent_per_month)
                profit_percent_per_month = 0
                trade_power = True
            else:
                return

    # ---- Cooldown handling: if cooldown is active, decrement and skip
    if cooldown_until_index > 0:
        cooldown_until_index -= 1
        return

    # ===================== OPEN LONG =====================
    if ma_130 >= ma_200 and ema_14 > ma_50 and current_position is None:
        if ma_distance > ma_distance_threshold or last_candle_move > candle_move_threshold:
            
            # ===== ADX FILTER =====
            if adx_filter == True :
                if adx is None or adx < 20.5:
                    return
            
            # ===== Volume FILTER =====
            if volume_filter == True :

                vol_now = volume_prices[-1]
                vol_avg15 = indicator.get_avg_volume_last(volume_prices, window=15)

                # ---- Volume Condition ----
                volume_pass = vol_now >= 1.2 * vol_avg15

                if not volume_pass:
                    return

            # ---- open order ----
            updates = trade_manager.open_long(
                close_prices[-1],
                close_times[-1],
                balance,
                balance_without_fee,
                first_balance,
                trade_amount_percent,
                margin_balance,
                leverage)
            
            if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                try:
                    if toobit_balance is None:
                        toobit_balance = toobit_get_balance()
                    live_value_qty = _calc_live_value_quantity(
                        toobit_balance,
                        trade_amount_percent,
                        updates['leverage']
                    )
                    if live_value_qty is None:
                        raise RuntimeError("Cannot size live order from Toobit balance.")
                    toobit_set_leverage(TOOBIT_SYMBOL, updates['leverage'])
                    toobit_place_order(
                        symbol=TOOBIT_SYMBOL,
                        side="BUY_OPEN",
                        value_quantity=live_value_qty,
                        price_type="MARKET",
                        order_type="LIMIT"
                    )
                except Exception as e:
                    print("Toobit open LONG failed:", e)
                    return


            entry_price = updates['entry_price']
            balance = updates['balance']
            balance_without_fee = updates['balance_without_fee']
            balance_before_trade = updates['balance_before_trade']
            balance_before_trade_no_fee = updates['balance_before_trade_no_fee']
            margin = updates['margin']
            leverage = updates['leverage']
            position_size = updates['position_size']
            margin_no_fee = updates['margin_no_fee']
            position_size_no_fee = updates['position_size_no_fee']
            open_time_value = updates['open_time_value']
            current_position = updates['current_position']
            updates = None

            if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                try:
                    tb_balance = toobit_get_balance()
                    toobit_balance = tb_balance
                    if TOOBIT_SYNC_BALANCE:
                        balance = tb_balance
                        balance_without_fee = tb_balance
                except Exception as e:
                    print("Toobit balance refresh failed:", e)

            # persist open order to DB
            order_id = db.insert_open_order(
                symbol="BTCUSDT",
                side="long",
                entry_price=entry_price,
                open_time=open_time_value,
                position_size=position_size,
                margin=margin,
                leverage=leverage,
                status="open",
                balance=balance,
                balance_without_fee=balance_without_fee,
                balance_before_trade=balance_before_trade,
                balance_before_trade_no_fee=balance_before_trade_no_fee,
                margin_no_fee=margin_no_fee,
                position_size_no_fee=position_size_no_fee,
                current_position=current_position
            )

            # terminal + telegram notification with details
            print(f"ORDER OPENED #{order_id}: LONG @ {entry_price} | size={position_size} | margin={margin} | lev={leverage}")
            signal_message.send_open_long(price=close_prices[-1], time_str=close_times[-1], margin=margin, position_size=position_size, leverage=leverage)

    # ===================== CLOSE LONG =====================
    if current_position == "long":
        if (ema_14 < ma_50) or (ma_130 < ma_200):
            # CLOSE LONG
            if position_size is None:
                print("Cannot close LONG: position_size unknown.")
                return
            if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                try:
                    toobit_close_position(TOOBIT_SYMBOL, side="LONG")
                except Exception as e:
                    print("Toobit close LONG failed:", e)
                    return

            updates = trade_manager.close_long(
                close_prices[-1],
                close_times[-1],
                entry_price,
                position_size,
                position_size_no_fee,
                fee_rate,
                margin,
                margin_no_fee,
                balance,
                balance_without_fee,
                balance_before_trade,
                balance_before_trade_no_fee,
                deducting_fee_total,
                profits_lst,
                total_profit_percent,
                count_closed_orders,
                equity_curve,
                max_drawdown,
                total_wins,
                total_wins_long,
                total_losses,
                total_long,
                cooldown_after_big_pnl,
                leverage,
                cooldown_until_index,
                open_time_value,
                csv_logger,
                trade_amount_percent,
                profit_percent_per_month,
                save_money,
                trade_power)
            

            balance = updates['balance']
            balance_without_fee = updates['balance_without_fee']
            margin = updates['margin']
            margin_no_fee = updates['margin_no_fee']
            deducting_fee_total = updates['deducting_fee_total']
            profits_lst = updates['profits_lst']
            total_profit_percent = updates['total_profit_percent']
            count_closed_orders = updates['count_closed_orders']
            equity_curve = updates['equity_curve']
            max_drawdown = updates['max_drawdown']
            total_wins = updates['total_wins']
            total_wins_long = updates['total_wins_long']
            total_losses = updates['total_losses']
            total_long = updates['total_long']
            cooldown_until_index = updates['cooldown_until_index']
            current_position = updates['current_position']
            profit_percent_per_month = updates['profit_percent_per_month']
            save_money = updates["save_money"]
            trade_power = updates['trade_power']
            # capture profit info before clearing updates
            profit = updates.get('profit')
            profit_percent = updates.get('profit_percent')
            pnl = updates.get('pnl')
            pnl_percent = updates.get('pnl_percent')
            updates = None

            if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                try:
                    tb_balance = toobit_get_balance()
                    toobit_balance = tb_balance
                    if TOOBIT_SYNC_BALANCE:
                        balance = tb_balance
                        balance_without_fee = tb_balance
                except Exception as e:
                    print("Toobit balance refresh failed:", e)

            total_balance = balance + (margin if current_position is not None else 0) + save_money
            
            # update DB for this order
            if order_id is not None:
                try:
                    db.update_order_close(order_id=order_id,
                                          close_price=close_prices[-1],
                                          close_time=close_times[-1],
                                          profit=profit,
                                          profit_percent=profit_percent,
                                          balance=balance,
                                          balance_without_fee=balance_without_fee,
                                          margin=margin,
                                          margin_no_fee=margin_no_fee)
                except Exception as e:
                    print("DB update_order_close failed:", e)

            print(f"ORDER CLOSED #{order_id}: LONG closed @ {close_prices[-1]} | P/L: {profit} ({profit_percent}%)")
            signal_message.send_close_long(price= close_prices[-1], time_str= close_times[-1], profit=profit, profit_percent=profit_percent, pnl=pnl, pnl_percent=pnl_percent, 
                                           balance_before=balance_before_trade, balance_after=total_balance, margin=margin)


    # ===================== OPEN SHORT =====================
    if ma_130 < ma_200 and ema_14 < ma_50 and current_position is None:
        if ma_distance > ma_distance_threshold or last_candle_move > candle_move_threshold:
            
            # ===== ADX FILTER =====
            if adx_filter == True :
                if adx is None or adx < 20.5:
                    return
            
            # ===== Volume FILTER =====
            if volume_filter == True :

                vol_now = volume_prices[-1]
                vol_avg15 = indicator.get_avg_volume_last(volume_prices, window=15)

                # ---- Volume Condition ----
                volume_pass = vol_now >= 1.2 * vol_avg15

                if not volume_pass:
                    return
    
            # ---- open SHORT ----
            updates = trade_manager.open_short(
                close_prices[-1],
                close_times[-1],
                balance,
                balance_without_fee,
                first_balance,
                trade_amount_percent,
                margin_balance,
                leverage)
            
            if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                try:
                    if toobit_balance is None:
                        toobit_balance = toobit_get_balance()
                    live_value_qty = _calc_live_value_quantity(
                        toobit_balance,
                        trade_amount_percent,
                        updates['leverage']
                    )
                    if live_value_qty is None:
                        raise RuntimeError("Cannot size live order from Toobit balance.")
                    toobit_set_leverage(TOOBIT_SYMBOL, updates['leverage'])
                    toobit_place_order(
                        symbol=TOOBIT_SYMBOL,
                        side="SELL_OPEN",
                        value_quantity=live_value_qty,
                        price_type="MARKET",
                        order_type="LIMIT"
                    )
                except Exception as e:
                    print("Toobit open SHORT failed:", e)
                    return


            entry_price = updates['entry_price']
            balance = updates['balance']
            balance_without_fee = updates['balance_without_fee']
            balance_before_trade = updates['balance_before_trade']
            balance_before_trade_no_fee = updates['balance_before_trade_no_fee']
            margin = updates['margin']
            leverage = updates['leverage']
            position_size = updates['position_size']
            margin_no_fee = updates['margin_no_fee']
            position_size_no_fee = updates['position_size_no_fee']
            open_time_value = updates['open_time_value']
            current_position = updates['current_position']
            updates = None

            if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                try:
                    tb_balance = toobit_get_balance()
                    toobit_balance = tb_balance
                    if TOOBIT_SYNC_BALANCE:
                        balance = tb_balance
                        balance_without_fee = tb_balance
                except Exception as e:
                    print("Toobit balance refresh failed:", e)

            # persist open order to DB
            order_id = db.insert_open_order(
                symbol="BTCUSDT",
                side="short",
                entry_price=entry_price,
                open_time=open_time_value,
                position_size=position_size,
                margin=margin,
                leverage=leverage,
                status="open",
                balance=balance,
                balance_without_fee=balance_without_fee,
                balance_before_trade=balance_before_trade,
                balance_before_trade_no_fee=balance_before_trade_no_fee,
                margin_no_fee=margin_no_fee,
                position_size_no_fee=position_size_no_fee,
                current_position=current_position
            )

            print(f"ORDER OPENED #{order_id}: SHORT @ {entry_price} | size={position_size} | margin={margin} | lev={leverage}")
            signal_message.send_open_short(price=close_prices[-1], time_str=close_times[-1], margin=margin, position_size=position_size, leverage=leverage)


    # ===================== CLOSE SHORT =====================
    if current_position == "short":
        if (ema_14 > ma_50) or (ma_130 >= ma_200):
            # CLOSE SHORT
            if position_size is None:
                print("Cannot close SHORT: position_size unknown.")
                return
            if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                try:
                    toobit_close_position(TOOBIT_SYMBOL, side="SHORT")
                except Exception as e:
                    print("Toobit close SHORT failed:", e)
                    return

            updates = trade_manager.close_short(
                close_prices[-1],
                close_times[-1],
                entry_price,
                position_size,
                position_size_no_fee,
                fee_rate,
                margin,
                margin_no_fee,
                balance,
                balance_without_fee,
                balance_before_trade,
                balance_before_trade_no_fee,
                deducting_fee_total,
                profits_lst,
                total_profit_percent,
                count_closed_orders,
                equity_curve,
                max_drawdown,
                total_wins,
                total_wins_short,
                total_losses,
                total_short,
                cooldown_after_big_pnl,
                leverage,
                cooldown_until_index,
                open_time_value,
                csv_logger,
                trade_amount_percent,
                profit_percent_per_month,
                save_money,
                trade_power
                )
                

            balance = updates['balance']
            balance_without_fee = updates['balance_without_fee']
            margin = updates['margin']
            margin_no_fee = updates['margin_no_fee']
            deducting_fee_total = updates['deducting_fee_total']
            profits_lst = updates['profits_lst']
            total_profit_percent = updates['total_profit_percent']
            count_closed_orders = updates['count_closed_orders']
            equity_curve = updates['equity_curve']
            max_drawdown = updates['max_drawdown']
            total_wins = updates['total_wins']
            total_wins_short = updates['total_wins_short']
            total_losses = updates['total_losses']
            total_short = updates['total_short']
            cooldown_until_index = updates['cooldown_until_index']
            current_position = updates['current_position']
            profit_percent_per_month = updates['profit_percent_per_month']
            save_money = updates['save_money']
            trade_power = updates['trade_power']
            # capture profit info before clearing updates
            profit = updates.get('profit')
            profit_percent = updates.get('profit_percent')
            pnl = updates.get('pnl')
            pnl_percent = updates.get('pnl_percent')
            updates = None

            if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                try:
                    tb_balance = toobit_get_balance()
                    toobit_balance = tb_balance
                    if TOOBIT_SYNC_BALANCE:
                        balance = tb_balance
                        balance_without_fee = tb_balance
                except Exception as e:
                    print("Toobit balance refresh failed:", e)

            total_balance = balance + (margin if current_position is not None else 0) + save_money
            
            # update DB for this order
            if order_id is not None:
                try:
                    db.update_order_close(order_id=order_id,
                                          close_price=close_prices[-1],
                                          close_time=close_times[-1],
                                          profit=profit,
                                          profit_percent=profit_percent,
                                          balance=balance,
                                          balance_without_fee=balance_without_fee,
                                          margin=margin,
                                          margin_no_fee=margin_no_fee)
                except Exception as e:
                    print("DB update_order_close failed:", e)

            print(f"ORDER CLOSED #{order_id}: SHORT closed @ {close_prices[-1]} | P/L: {profit} ({profit_percent}%)")
            signal_message.send_close_short(price= close_prices[-1], time_str= close_times[-1], profit=profit, profit_percent=profit_percent, pnl=pnl, pnl_percent=pnl_percent, 
                                            balance_before=balance_before_trade, balance_after=total_balance, margin=margin)


# wait on 0, 15, 30, 45 minutes for get data
def wait_for_next_quarter():
    while True:
        now = datetime.now(timezone.utc)
        minute = now.minute
        second = now.second

        if minute in VALID_MINUTES and second < FETCH_WINDOW_SECONDS:
            return
        time.sleep(0.3)



# ==== start app here ====
parser = argparse.ArgumentParser(description="Trading bot")

parser.add_argument(
    "--rammonitor",
    action="store_true",
    help="Enable RAM monitor"
)

parser.add_argument(
    "--test",
    action="store_true",
    help="Enable a test Bot with out using time filter"
)

args = parser.parse_args()

# you can turn on to see bot ram usage:  ----> True/False
# ================= RAM MONITOR =================
if args.rammonitor:
    ram_monitor = RamMonitor(interval=2, warn_mb=500)
    ram_monitor.start()

# ---- initialize Toobit balance (live trading) ----
if TOOBIT_ENABLED:
    try:
        init_toobit_balance()
    except Exception as e:
        print("Toobit init failed, disabling live trading:", e)
        TOOBIT_ENABLED = False
        TOOBIT_EXECUTE_ORDERS = False

# MAIN LOOP 
while True:
    if args.test:
        ma_strategy()
        break

    else:
        wait_for_next_quarter()
        ma_strategy()

    time.sleep(FETCH_WINDOW_SECONDS + 1)
