import requests
import time
import argparse
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
BOT_TOKEN = "TOKEN"
CHAT_ID = int("CHAT_ID")

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

entry_price = None
position_size = None
position_size_no_fee = None
balance_before_trade = None
balance_before_trade_no_fee = None
open_time_value = None

trade_power = True

balance_without_fee = balance
first_balance = balance
tactical_balance = first_balance

current_position = None  # None | "long" | "short"

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
    global balance, balance_without_fee, current_position, margin, trade_power, cooldown_until_index, leverage, position_size_no_fee, margin_no_fee, balance_before_trade, balance_before_trade_no_fee, deducting_fee_total, profits_lst, total_profit_percent, count_closed_orders, equity_curve, max_drawdown, total_wins, total_wins_long, total_wins_short, total_losses, total_long, total_short, profit_percent_per_month, save_money

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

# MAIN LOOP 
while True:
    if args.test:
        ma_strategy()
        break

    else:
        wait_for_next_quarter()
        ma_strategy()

    time.sleep(FETCH_WINDOW_SECONDS + 1)