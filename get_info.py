import requests
import time
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import numpy as np
import logging

import os

# My Files
from indicators import Indicator
from telegram_bot import create_telegram_notifier
from database import Database
from rammonitor import RamMonitor
from trademanager import TradeManager
from trade_csv_logger import TradeCSVLogger
from toobit_client import ToobitClient
from env_loader import load_dotenv_file
from sync_symbol_data import sync_recent_symbol_data
from get_ohlcv import get_ohlcv_binance, get_ohlcv_toobit
from logging_utils import (
    DailyDirectoryFileHandler,
    RecordCategoryFilter,
    UTCFormatter,
    format_utc_timestamp,
)

VALID_MINUTES = {0, 15, 30, 45}
FETCH_WINDOW_SECONDS = 10
load_dotenv_file()


# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("bot")
logger.setLevel(logging.INFO)

# Prevent duplicate handlers if this file is imported multiple times
if not logger.handlers:
    formatter = UTCFormatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    def _daily_handler(filename, *, level=None, category=None):
        handler = DailyDirectoryFileHandler(
            base_dir="logs",
            filename=filename,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        if level is not None:
            handler.setLevel(level)
        if category is not None:
            handler.addFilter(RecordCategoryFilter(category))
        return handler

    # Every record is kept in all.log and copied to its specialized log.
    all_handler = _daily_handler("all.log")
    error_handler = _daily_handler("errors.log", level=logging.ERROR)
    trade_handler = _daily_handler("trades.log", category="trade")
    check_handler = _daily_handler("checks.log", category="check")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    for handler in (
        all_handler,
        error_handler,
        trade_handler,
        check_handler,
        console_handler,
    ):
        logger.addHandler(handler)

# ---- Toobit settings ----
TOOBIT_ENABLED = True
TOOBIT_EXECUTE_ORDERS = True  # set False for dry-run without live orders
TOOBIT_BASE_URL = "https://api.toobit.com"
TOOBIT_CATEGORY = "USDT"
TOOBIT_SYMBOL = "BTC-SWAP-USDT"
TOOBIT_BALANCE_ASSET = "USDT"
TOOBIT_RECV_WINDOW = 5000
TOOBIT_TIMEOUT_SECONDS = 30
TOOBIT_MAX_RETRIES = 3
TOOBIT_BACKOFF_BASE_SECONDS = 1.0
TOOBIT_BACKOFF_MAX_SECONDS = 8.0
TOOBIT_REFRESH_BALANCE_EACH_CYCLE = True
TOOBIT_SYNC_BALANCE = False  # keep local demo balance if False
LOCK_FIRST_BALANCE_ON_FIRST_TICK = True  # lock first/tactical balance when first candle is processed
TOOBIT_CLIENT = ToobitClient(
    base_url=TOOBIT_BASE_URL,
    category=TOOBIT_CATEGORY,
    balance_asset=TOOBIT_BALANCE_ASSET,
    recv_window=TOOBIT_RECV_WINDOW,
    timeout=TOOBIT_TIMEOUT_SECONDS,
    max_retries=TOOBIT_MAX_RETRIES,
    backoff_base_seconds=TOOBIT_BACKOFF_BASE_SECONDS,
    max_backoff_seconds=TOOBIT_BACKOFF_MAX_SECONDS,
)

# ---- TELEGRAM setting ----
telegram_alerts = False

# ---- settings is here ----
balance = 1000
leverage = 10
safe_leverage_high = 4
safe_leverage_med = 3
safe_leverage_low = 2
trade_amount_percent = 0.5  # 50% of balance per trade
monthly_profit_percent_stop_trade = 8    # if 8% per month profit --> don't trade on that month 
monthly_compound = 3    # after get 'monthly_profit_percent_stop_trade' per month how much money goes for next month
monthly_close_filter = True
adx_filter = True
volume_filter = True
atr_filter = True
skip_logic = False

ma_distance_threshold = 0.00159  # 0.16%
candle_move_threshold = 0.008  # 0.8%

impulse_move_threshold_pct = 1.5
impulse_lookback = 5
late_entry_atr_mult = 0.8
late_entry_body_ratio = 0.6
late_entry_ema_pct = 0.005

# Entry/exit tuning
slope_window = 5
entry_score_threshold = 10
exit_score_threshold = 6
trail_activate_pct = 0.007
trail_retrace_pct = 0.003
loss_exit_pct = 0.06
adx_exit_threshold = 15.0
adx_exit_lookback = 1
entry_adx_threshold = 20.5
entry_atr_threshold = 1.2
opposite_atr_body_mult = 0.6
period_adx = 14
period_atr = 14
period_atr_ma = 21
period_vol_avg = 12
volume_spike_multiplier = 1.24

# score weights (entry/exit)
entry_score_cross = 1
entry_score_ema_vs_ma50 = 3
entry_score_close_vs_ema16 = 1
entry_score_ma_trend = 1
entry_score_ma_distance_or_candle = 1
entry_score_adx = 1
entry_score_volume = 2
entry_late_penalty = 1

exit_score_loss_guard = 3
exit_score_ema_slope = 1
exit_score_ema_cross = 3
exit_score_ma_trend = 1
exit_score_trailing = 1
exit_score_adx = 1
exit_score_opposite_candle = 1

cooldown_after_big_pnl = 4 * 3
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
entry_index = None

trade_power = True
trade_power_locked_month = None

balance_without_fee = balance
first_balance = None
tactical_balance = None
initial_balance_locked = False
toobit_first_balance = None
toobit_tactical_balance = None
toobit_initial_balance_locked = False

current_position = None  # None | "long" | "short"

# cross/skip runtime state (persist across cycles)
last_trade_cross_time = None
consecutive_losses = 0
skip_trades_left = 0
runtime_state_loaded = False


@dataclass
class BotState:
    balance: float = 1000.0
    leverage: int = 10
    save_money: float = 0.0
    total_wins: int = 0
    total_wins_long: int = 0
    total_wins_short: int = 0
    total_losses: int = 0
    total_long: int = 0
    total_short: int = 0
    total_profit_percent: float = 0.0
    deducting_fee_total: float = 0.0
    count_closed_orders: int = 0
    profit_percent_per_month: float = 0.0
    lst_profit_percent_per_month: list = field(default_factory=list)
    profits_lst: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    max_drawdown: float = 0.0
    toobit_balance: float = None
    entry_price: float = None
    position_size: float = None
    position_size_no_fee: float = None
    margin: float = 0.0
    margin_no_fee: float = 0.0
    balance_before_trade: float = None
    balance_before_trade_no_fee: float = None
    open_time_value: str = None
    entry_index: int = None
    trade_power: bool = True
    trade_power_locked_month: str = None
    balance_without_fee: float = 1000.0
    first_balance: float = None
    tactical_balance: float = None
    initial_balance_locked: bool = False
    toobit_first_balance: float = None
    toobit_tactical_balance: float = None
    toobit_initial_balance_locked: bool = False
    current_position: str = None
    last_trade_cross_time: str = None
    consecutive_losses: int = 0
    skip_trades_left: int = 0
    runtime_state_loaded: bool = False
    cooldown_until_index: int = -1


BOT_STATE = BotState(
    balance=balance,
    leverage=leverage,
    save_money=save_money,
    total_wins=total_wins,
    total_wins_long=total_wins_long,
    total_wins_short=total_wins_short,
    total_losses=total_losses,
    total_long=total_long,
    total_short=total_short,
    total_profit_percent=total_profit_percent,
    deducting_fee_total=deducting_fee_total,
    count_closed_orders=count_closed_orders,
    profit_percent_per_month=profit_percent_per_month,
    lst_profit_percent_per_month=lst_profit_percent_per_month,
    profits_lst=profits_lst,
    equity_curve=equity_curve,
    max_drawdown=max_drawdown,
    toobit_balance=toobit_balance,
    entry_price=entry_price,
    position_size=position_size,
    position_size_no_fee=position_size_no_fee,
    margin=margin,
    margin_no_fee=margin_no_fee,
    balance_before_trade=balance_before_trade,
    balance_before_trade_no_fee=balance_before_trade_no_fee,
    open_time_value=open_time_value,
    entry_index=entry_index,
    trade_power=trade_power,
    trade_power_locked_month=trade_power_locked_month,
    balance_without_fee=balance_without_fee,
    first_balance=first_balance,
    tactical_balance=tactical_balance,
    initial_balance_locked=initial_balance_locked,
    toobit_first_balance=toobit_first_balance,
    toobit_tactical_balance=toobit_tactical_balance,
    toobit_initial_balance_locked=toobit_initial_balance_locked,
    current_position=current_position,
    last_trade_cross_time=last_trade_cross_time,
    consecutive_losses=consecutive_losses,
    skip_trades_left=skip_trades_left,
    runtime_state_loaded=runtime_state_loaded,
    cooldown_until_index=cooldown_until_index,
)


def _get_balance_state_mode():
    return "toobit" if TOOBIT_SYNC_BALANCE else "local"


def _lock_initial_balances(state, source_balance, reason, db=None, mode=None):
    if state.initial_balance_locked:
        return
    try:
        base = float(source_balance)
    except Exception:
        return
    if base <= 0:
        return
    state.first_balance = base
    state.tactical_balance = base
    state.initial_balance_locked = True
    print(f"Initial balance locked at {base} ({reason})")
    if db is not None:
        state_mode = mode or _get_balance_state_mode()
        try:
            db.set_balance_state(state_mode, state.first_balance, state.tactical_balance, locked=1)
        except Exception as e:
            logger.exception(f"set_balance_state failed: {e}")


def _lock_toobit_balances(state, source_balance, reason, db=None):
    if state.toobit_initial_balance_locked:
        return
    try:
        base = float(source_balance)
    except Exception:
        return
    if base <= 0:
        return
    state.toobit_first_balance = base
    state.toobit_tactical_balance = base
    state.toobit_initial_balance_locked = True
    print(f"Toobit initial balance locked at {base} ({reason})")
    if db is not None:
        try:
            db.set_balance_state("toobit", state.toobit_first_balance, state.toobit_tactical_balance, locked=1)
        except Exception as e:
            logger.exception(f"set_balance_state failed: {e}")


def _calc_live_value_quantity(tb_balance, percent, leverage, tactical_balance=None):
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
    if tactical_balance is not None:
        try:
            tactical_balance = float(tactical_balance)
        except Exception:
            tactical_balance = None
    if tactical_balance is not None and tactical_balance > 0:
        if tb_balance >= 50 / 100 * tactical_balance:
            live_margin = tactical_balance * percent
        else:
            live_margin = tb_balance * percent
    else:
        live_margin = tb_balance * percent
    return live_margin * leverage


def init_toobit_balance(state):
    state.toobit_balance = TOOBIT_CLIENT.get_balance(asset=TOOBIT_BALANCE_ASSET)
    if TOOBIT_SYNC_BALANCE:
        state.balance = state.toobit_balance
        state.balance_without_fee = state.toobit_balance
        if not LOCK_FIRST_BALANCE_ON_FIRST_TICK:
            _lock_initial_balances(state, state.toobit_balance, "toobit init")
        print(f"Toobit balance synced: {state.balance}")
    else:
        print(f"Toobit balance fetched (not synced): {state.toobit_balance}")


# ---- load Telegram notifier at startup ----
SIGNAL_MESSAGE = create_telegram_notifier(
    default_symbol="BTCUSDT",
)


def _safe_parse_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        pass
    try:
        text = text.replace(" UTC", "")
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
    except Exception:
        pass
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _month_key(value):
    dt = _safe_parse_dt(value)
    if dt is None:
        return None
    return f"{dt.year:04d}-{dt.month:02d}"


def _find_entry_index(close_times, open_time):
    target_dt = _safe_parse_dt(open_time)
    if target_dt is None:
        return None
    target_str = target_dt.strftime("%Y-%m-%d %H:%M:%S")
    for idx, value in enumerate(close_times):
        cur_dt = _safe_parse_dt(value)
        if cur_dt is None:
            continue
        if cur_dt.strftime("%Y-%m-%d %H:%M:%S") == target_str:
            return idx
    return None


def _save_runtime_state(db, mode, last_cross, skips, losses, power, locked_month):
    try:
        db.set_runtime_state(
            mode=mode,
            last_trade_cross_time=last_cross,
            skip_trades_left=int(skips) if skips is not None else 0,
            consecutive_losses=int(losses) if losses is not None else 0,
            trade_power=1 if power else 0,
            trade_power_locked_month=locked_month,
        )
    except Exception as e:
        logger.exception(f"set_runtime_state failed: {e}")

# Main Trading Logic
def ma_strategy(state, manual_action=None):
    logger.info(
        f"CHECK START | mode={'manual' if manual_action else 'scheduled'}"
        f" | action={manual_action or 'none'}",
        extra={"category": "check"},
    )
    balance = state.balance
    balance_without_fee = state.balance_without_fee
    current_position = state.current_position
    margin = state.margin
    trade_power = state.trade_power
    cooldown_until_index = state.cooldown_until_index
    leverage = state.leverage
    position_size_no_fee = state.position_size_no_fee
    margin_no_fee = state.margin_no_fee
    balance_before_trade = state.balance_before_trade
    balance_before_trade_no_fee = state.balance_before_trade_no_fee
    deducting_fee_total = state.deducting_fee_total
    profits_lst = state.profits_lst
    total_profit_percent = state.total_profit_percent
    count_closed_orders = state.count_closed_orders
    equity_curve = state.equity_curve
    max_drawdown = state.max_drawdown
    total_wins = state.total_wins
    total_wins_long = state.total_wins_long
    total_wins_short = state.total_wins_short
    total_losses = state.total_losses
    total_long = state.total_long
    total_short = state.total_short
    profit_percent_per_month = state.profit_percent_per_month
    lst_profit_percent_per_month = state.lst_profit_percent_per_month
    save_money = state.save_money
    toobit_balance = state.toobit_balance
    first_balance = state.first_balance
    tactical_balance = state.tactical_balance
    initial_balance_locked = state.initial_balance_locked
    toobit_first_balance = state.toobit_first_balance
    toobit_tactical_balance = state.toobit_tactical_balance
    toobit_initial_balance_locked = state.toobit_initial_balance_locked
    entry_price = state.entry_price
    position_size = state.position_size
    open_time_value = state.open_time_value
    entry_index = state.entry_index
    trade_power_locked_month = state.trade_power_locked_month
    last_trade_cross_time = state.last_trade_cross_time
    consecutive_losses = state.consecutive_losses
    skip_trades_left = state.skip_trades_left
    runtime_state_loaded = state.runtime_state_loaded

    def _persist_state():
        state.balance = balance
        state.balance_without_fee = balance_without_fee
        state.current_position = current_position
        state.margin = margin
        state.trade_power = trade_power
        state.cooldown_until_index = cooldown_until_index
        state.leverage = leverage
        state.position_size_no_fee = position_size_no_fee
        state.margin_no_fee = margin_no_fee
        state.balance_before_trade = balance_before_trade
        state.balance_before_trade_no_fee = balance_before_trade_no_fee
        state.deducting_fee_total = deducting_fee_total
        state.profits_lst = profits_lst
        state.total_profit_percent = total_profit_percent
        state.count_closed_orders = count_closed_orders
        state.equity_curve = equity_curve
        state.max_drawdown = max_drawdown
        state.total_wins = total_wins
        state.total_wins_long = total_wins_long
        state.total_wins_short = total_wins_short
        state.total_losses = total_losses
        state.total_long = total_long
        state.total_short = total_short
        state.profit_percent_per_month = profit_percent_per_month
        state.lst_profit_percent_per_month = lst_profit_percent_per_month
        state.save_money = save_money
        state.toobit_balance = toobit_balance
        state.first_balance = first_balance
        state.tactical_balance = tactical_balance
        state.initial_balance_locked = initial_balance_locked
        state.toobit_first_balance = toobit_first_balance
        state.toobit_tactical_balance = toobit_tactical_balance
        state.toobit_initial_balance_locked = toobit_initial_balance_locked
        state.entry_price = entry_price
        state.position_size = position_size
        state.open_time_value = open_time_value
        state.entry_index = entry_index
        state.trade_power_locked_month = trade_power_locked_month
        state.last_trade_cross_time = last_trade_cross_time
        state.consecutive_losses = consecutive_losses
        state.skip_trades_left = skip_trades_left
        state.runtime_state_loaded = runtime_state_loaded

    csv_logger = TradeCSVLogger()

    signal_message = SIGNAL_MESSAGE

    open_times = []
    open_prices = []
    high_prices = []
    low_prices = []
    close_prices = []
    volume_prices = []
    close_times = []

    # get data from binance
    required_candles = 201
    data = get_ohlcv_toobit(symbol="BTCUSDT", interval="15m", limit=required_candles)  # BTCUSDT by default

    # If fetch failed (e.g. transient network), retry for a short grace period so the bot doesn't exit
    if not data or len(data) < 2:
        start_ts = time.time()
        grace = 60  # seconds to tolerate transient outage
        retry_interval = 5
        logger.warning(
            f"CHECK RETRY | no OHLCV | grace={grace}s | interval={retry_interval}s",
            extra={"category": "check"},
        )
        while time.time() - start_ts < grace:
            time.sleep(retry_interval)
            data = get_ohlcv_toobit(symbol="BTCUSDT", interval="15m", limit=required_candles)
            if data and len(data) >= 2:
                logger.info("CHECK RECOVERED | OHLCV available", extra={"category": "check"})
                break
            print(".", end="", flush=True)
        else:
            # grace period expired — do NOT crash; skip this cycle and remain running
            logger.error(
                "CHECK FAILED | no OHLCV after grace period | cycle skipped",
                extra={"category": "check"},
            )
            _persist_state()
            return

    # validate we have enough candles for indicators (warn but continue with available data)
    if len(data) < required_candles:
        logger.warning(
            f"CHECK PARTIAL | candles={len(data)} | expected={required_candles}",
            extra={"category": "check"},
        )

    # Fetch OHLCV data from Binance and normalize candle timestamps (UTC)
    for i in range(len(data) - 1):
        open_times.append(str(datetime.fromtimestamp(data[i][0] / 1000, tz=timezone.utc)))
        open_prices.append(float(data[i][1]))
        high_prices.append(float(data[i][2]))
        low_prices.append(float(data[i][3]))
        close_prices.append(float(data[i][4]))
        volume_prices.append(float(data[i][5]))
        close_times.append(str(datetime.fromtimestamp((data[i][6] / 1000) + 0.001, tz=timezone.utc)))

    # setup DB and restore persisted balance state
    db = Database(db_name="database.db")
    state_mode = _get_balance_state_mode()
    if not initial_balance_locked:
        balance_state = db.get_balance_state(state_mode)
        if balance_state and balance_state.get('first_balance') is not None:
            try:
                first_balance = float(balance_state.get('first_balance'))
            except Exception:
                first_balance = balance_state.get('first_balance')
            if balance_state.get('tactical_balance') is not None:
                try:
                    tactical_balance = float(balance_state.get('tactical_balance'))
                except Exception:
                    tactical_balance = balance_state.get('tactical_balance')
            else:
                tactical_balance = first_balance
            initial_balance_locked = True
            print(f"Initial balance loaded from DB ({state_mode}): {first_balance}")

    if TOOBIT_ENABLED and not toobit_initial_balance_locked:
        tstate = db.get_balance_state("toobit")
        if tstate and tstate.get('first_balance') is not None:
            try:
                toobit_first_balance = float(tstate.get('first_balance'))
            except Exception:
                toobit_first_balance = tstate.get('first_balance')
            if tstate.get('tactical_balance') is not None:
                try:
                    toobit_tactical_balance = float(tstate.get('tactical_balance'))
                except Exception:
                    toobit_tactical_balance = tstate.get('tactical_balance')
            else:
                toobit_tactical_balance = toobit_first_balance
            toobit_initial_balance_locked = True
            print(f"Toobit initial balance loaded from DB: {toobit_first_balance}")

    # lock first_balance/tactical_balance on the first candle we process
    if not initial_balance_locked:
        base = balance
        reason = "local balance (first tick)"
        if state_mode == "toobit":
            base = None
            reason = "toobit balance (first tick)"
            if toobit_balance is not None:
                base = toobit_balance
            elif TOOBIT_ENABLED:
                try:
                    base = TOOBIT_CLIENT.get_balance(asset=TOOBIT_BALANCE_ASSET)
                    toobit_balance = base
                except Exception as e:
                    logger.exception(f"Toobit balance fetch failed (first tick): {e}")
            if base is None:
                base = balance
                reason = "local balance fallback (first tick)"
        _lock_initial_balances(state, base, reason, db=db, mode=state_mode)
        first_balance = state.first_balance
        tactical_balance = state.tactical_balance
        initial_balance_locked = state.initial_balance_locked

    if TOOBIT_ENABLED and not toobit_initial_balance_locked:
        tb_base = toobit_balance
        if tb_base is None:
            try:
                tb_base = TOOBIT_CLIENT.get_balance(asset=TOOBIT_BALANCE_ASSET)
                toobit_balance = tb_base
            except Exception as e:
                logger.exception(f"Toobit balance fetch failed (first tick): {e}")
                tb_base = None
        if tb_base is not None:
            _lock_toobit_balances(state, tb_base, "toobit balance (first tick)", db=db)
            toobit_first_balance = state.toobit_first_balance
            toobit_tactical_balance = state.toobit_tactical_balance
            toobit_initial_balance_locked = state.toobit_initial_balance_locked

    # restore runtime strategy state once (persist across restarts)
    if not runtime_state_loaded:
        rstate = db.get_runtime_state(state_mode)
        if rstate:
            last_trade_cross_time = rstate.get("last_trade_cross_time")
            try:
                skip_trades_left = int(rstate.get("skip_trades_left") or 0)
            except Exception:
                skip_trades_left = 0
            try:
                consecutive_losses = int(rstate.get("consecutive_losses") or 0)
            except Exception:
                consecutive_losses = 0
            trade_power = bool(rstate.get("trade_power")) if rstate.get("trade_power") is not None else True
            trade_power_locked_month = rstate.get("trade_power_locked_month")
        runtime_state_loaded = True

    # sync the latest (required_candles - 1) closed candles so missed rows are backfilled after outages
    inserted_count, checked_count = sync_recent_symbol_data(
        db=db,
        symbol="BTCUSDT",
        open_times=open_times,
        open_prices=open_prices,
        high_prices=high_prices,
        low_prices=low_prices,
        close_prices=close_prices,
        volume_prices=volume_prices,
        close_times=close_times,
        lookback=required_candles - 1,
    )
    logger.info(
        f"CHECK COMPLETE | candle_time={format_utc_timestamp(close_times[-1])} | "
        f"candles={len(close_times)} | checked={checked_count} | "
        f"inserted_missing={inserted_count}",
        extra={"category": "check"},
    )

    # --- restore open order if exists (persist across restarts)
    open_order = db.get_open_order()
    order_id = None
    client_order_id = None
    exchange_order_id = None
    bot_quantity = None
    if open_order is not None:
        order_id = open_order['id']
        current_position = open_order['side']
        entry_price = open_order['entry_price']
        position_size = open_order['position_size']
        margin = open_order['margin']
        leverage = open_order['leverage']
        open_time_value = open_order['open_time']
        client_order_id = open_order.get('client_order_id')
        exchange_order_id = open_order.get('exchange_order_id')
        bot_quantity = open_order.get('bot_quantity')
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
                tb_balance = TOOBIT_CLIENT.get_balance(asset=TOOBIT_BALANCE_ASSET)
                toobit_balance = tb_balance
                if TOOBIT_SYNC_BALANCE:
                    balance = tb_balance
                    balance_without_fee = tb_balance
        except Exception as e:
            logger.exception(f"Toobit balance fetch failed: {e}")
            if TOOBIT_SYNC_BALANCE:
                _persist_state()
                return

        try:
            # The exchange position may contain manual trades. Only a local DB
            # order carrying our BOT_ client id establishes bot ownership.
            if order_id is None:
                current_position = None
                entry_price = None
                position_size = None
                open_time_value = None
                entry_index = None
            else:
                expected_side = str(current_position or open_order.get("side", "")).upper()
                pos = TOOBIT_CLIENT.get_open_position(
                    symbol=TOOBIT_SYMBOL,
                    side=expected_side,
                )
                if not pos:
                    print("Warning: bot-owned Toobit position is no longer open; no close order will be sent.")
                    current_position = None
                    entry_index = None
                elif not str(client_order_id or "").startswith("BOT_"):
                    print("Warning: open DB order has no BOT_ client id; live close is disabled for safety.")
                elif bot_quantity in (None, 0):
                    bot_quantity = TOOBIT_CLIENT.resolve_executed_quantity(
                        client_order_id=client_order_id,
                    )
                    if bot_quantity is not None:
                        db.update_order_execution(
                            order_id,
                            exchange_order_id=exchange_order_id,
                            bot_quantity=bot_quantity,
                        )
                    else:
                        print("Warning: bot order quantity could not be verified; live close is disabled for safety.")
        except Exception as e:
            logger.exception(f"Toobit position sync failed: {e}")
    else:
        if TOOBIT_SYNC_BALANCE:
            balance, balance_without_fee = db.get_current_balances(initial_balance=first_balance)

    # ---- indicators (full lists; evaluate on latest candle) ----
    indicator = Indicator(close_prices, period=None)
    ema_16_list = indicator.get_EMA(16)
    ma_50_list = indicator.get_MA(50)
    ma_100_list = indicator.get_MA(102)
    ma_200_list = indicator.get_MA(198)
    adx_list = indicator.get_ADX(high_prices, low_prices, close_prices, period=period_adx)
    atr_list = indicator.get_ATR(high_prices, low_prices, close_prices, period=period_atr)
    atr_ma_list = indicator.get_ATR_MA(atr_list, period=period_atr_ma)
    vol_avg_15_list = indicator.get_volume_avg(volume_prices, period=period_vol_avg)

    i = len(close_prices) - 1
    if i <= 0:
        _persist_state()
        return

    ema_16 = ema_16_list[i]
    ma_50 = ma_50_list[i]
    ma_100 = ma_100_list[i]
    ma_200 = ma_200_list[i]
    adx = adx_list[i]
    atr = atr_list[i]
    atr_ma = atr_ma_list[i]

    if ema_16 is None or ma_50 is None or ma_100 is None or ma_200 is None:
        _persist_state()
        return

    # ---- MANAGE TRADES ----
    trade_manager = TradeManager(
        csv_logger,
        first_balance,
        monthly_profit_percent_stop_trade,
        tactical_balance,
        monthly_close_filter,
        monthly_compound,
        leverage,
        safe_leverage_low,
        safe_leverage_med,
        safe_leverage_high,
    )

    # ----- Detect last EMA16 / MA50 cross inside fetched window -----
    cross_seen = False
    last_cross_dir = None
    last_cross_index = None
    for idx in range(1, len(close_prices)):
        if (
            ema_16_list[idx - 1] is None
            or ma_50_list[idx - 1] is None
            or ema_16_list[idx] is None
            or ma_50_list[idx] is None
        ):
            continue
        if ema_16_list[idx - 1] <= ma_50_list[idx - 1] and ema_16_list[idx] > ma_50_list[idx]:
            cross_seen = True
            last_cross_dir = "bull"
            last_cross_index = idx
        elif ema_16_list[idx - 1] >= ma_50_list[idx - 1] and ema_16_list[idx] < ma_50_list[idx]:
            cross_seen = True
            last_cross_dir = "bear"
            last_cross_index = idx
    last_cross_time = close_times[last_cross_index] if last_cross_index is not None else None

    ma_distance = abs(ema_16 - ma_50) / ma_50 if ma_50 else 0
    last_candle_move = abs(close_prices[i] - open_prices[i]) / open_prices[i] if open_prices[i] else 0
    margin_balance = balance + (margin if current_position is not None else 0)
    current_month = _month_key(close_times[i])

    manual_action = (manual_action or "").strip().lower()
    manual_mode = bool(manual_action)
    force_open_long = manual_action == "open_long"
    force_close_long = manual_action == "close_long"
    force_open_short = manual_action == "open_short"
    force_close_short = manual_action == "close_short"

    # If monthly filter is disabled manually, always allow trading to continue.
    if not monthly_close_filter:
        trade_power = True
        trade_power_locked_month = None
    # Monthly close filter: re-enable trading at the first candle of next month.
    elif not trade_power and not manual_mode:
        if trade_power_locked_month is None:
            trade_power_locked_month = current_month
            _save_runtime_state(
                db,
                state_mode,
                last_trade_cross_time,
                skip_trades_left,
                consecutive_losses,
                trade_power,
                trade_power_locked_month,
            )
        if (
            trade_power_locked_month is not None
            and current_month is not None
            and current_month != trade_power_locked_month
        ):
            lst_profit_percent_per_month.append(profit_percent_per_month)
            profit_percent_per_month = 0
            trade_power = True
            trade_power_locked_month = None
        else:
            _persist_state()
            return

    if cooldown_until_index > 0 and not manual_mode:
        cooldown_until_index -= 1
        _save_runtime_state(
            db,
            state_mode,
            last_trade_cross_time,
            skip_trades_left,
            consecutive_losses,
            trade_power,
            trade_power_locked_month,
        )
        _persist_state()
        return

    # Refresh entry index for trailing logic (restart-safe).
    if current_position is not None and open_time_value is not None:
        found_entry = _find_entry_index(close_times, open_time_value)
        if found_entry is not None:
            entry_index = found_entry
        elif entry_index is None:
            entry_index = 0

    if force_close_long and current_position != "long":
        print("Manual close_long ignored: no active LONG position.")
        _persist_state()
        return
    if force_close_short and current_position != "short":
        print("Manual close_short ignored: no active SHORT position.")
        _persist_state()
        return
    if (force_open_long or force_open_short) and current_position is not None:
        print(f"Manual open ignored: active position is {current_position}. Close it first.")
        _persist_state()
        return

    # ===================== OPEN LONG =====================
    if current_position is None and (
        force_open_long
        or (cross_seen and last_cross_time is not None and last_trade_cross_time != last_cross_time)
    ):
        entry_score = 0
        can_try_open = True

        if force_open_long:
            entry_score = entry_score_threshold
        elif atr_filter:
            if atr is None or atr_ma is None or atr_ma <= 0:
                can_try_open = False
            else:
                atr_ratio = atr / atr_ma
                if atr_ratio < entry_atr_threshold:
                    can_try_open = False

        if can_try_open:
            # ---- positive scores ----
            # 1) confirmed bull cross
            if last_cross_dir == "bull" and last_cross_index is not None:
                if i > last_cross_index and close_prices[i] > ema_16:
                    entry_score += entry_score_cross

            # 2) EMA16 above MA50
            if ema_16 > ma_50:
                entry_score += entry_score_ema_vs_ma50

            # 3) close above EMA16
            if close_prices[i] > ema_16:
                entry_score += entry_score_close_vs_ema16

            # 4) MA100 trend above MA200
            if ma_100 >= ma_200:
                entry_score += entry_score_ma_trend

            # 5) MA distance or candle move is strong
            if ma_distance > ma_distance_threshold or last_candle_move > candle_move_threshold:
                entry_score += entry_score_ma_distance_or_candle

            # 6) ADX confirmation
            if adx_filter and adx is not None and adx >= entry_adx_threshold:
                entry_score += entry_score_adx

            # 7) volume confirmation
            if volume_filter:
                vol_now = volume_prices[i]
                vol_avg15 = vol_avg_15_list[i]
                if vol_avg15 and vol_now >= volume_spike_multiplier * vol_avg15:
                    entry_score += entry_score_volume

            # ---- negative score (late-entry guard) ----
            if i >= impulse_lookback:
                impulse_pct = (close_prices[i] / close_prices[i - impulse_lookback] - 1.0) * 100
                if impulse_pct > impulse_move_threshold_pct:
                    if atr is not None and atr > 0:
                        extension = (close_prices[i] - ema_16) / atr
                        overextended = extension > late_entry_atr_mult
                    else:
                        extension = (close_prices[i] - ema_16) / ema_16 if ema_16 else 0
                        overextended = extension > late_entry_ema_pct

                    body_now = close_prices[i] - open_prices[i]
                    body_prev = close_prices[i - 1] - open_prices[i - 1]
                    cooling = (body_now <= 0) or (body_prev > 0 and body_now < body_prev * late_entry_body_ratio)
                    if overextended and cooling:
                        entry_score -= entry_late_penalty

            if entry_score >= entry_score_threshold:
                if (not force_open_long) and skip_logic and skip_trades_left > 0:
                    skip_trades_left -= 1
                    last_trade_cross_time = last_cross_time
                    print(f"SKIP LONG | skips left: {skip_trades_left}")
                else:
                    updates = trade_manager.open_long(
                        close_prices[i],
                        close_times[i],
                        balance,
                        balance_without_fee,
                        first_balance,
                        trade_amount_percent,
                        margin_balance,
                        leverage,
                    )

                    if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                        try:
                            if toobit_balance is None:
                                toobit_balance = TOOBIT_CLIENT.get_balance(asset=TOOBIT_BALANCE_ASSET)
                            live_value_qty = _calc_live_value_quantity(
                                toobit_balance,
                                trade_amount_percent,
                                updates["leverage"],
                                toobit_tactical_balance,
                            )
                            if live_value_qty is None:
                                raise RuntimeError("Cannot size live order from Toobit balance.")
                            TOOBIT_CLIENT.set_leverage(TOOBIT_SYMBOL, updates["leverage"])
                            result = TOOBIT_CLIENT.place_order(
                                symbol=TOOBIT_SYMBOL,
                                side="BUY_OPEN",
                                value_quantity=live_value_qty,
                                price_type="MARKET",
                                order_type="LIMIT",
                                strategy="MA",
                            )
                            client_order_id = result["client_order_id"]
                            exchange_order_id = TOOBIT_CLIENT.exchange_order_id(result)
                            bot_quantity = TOOBIT_CLIENT.resolve_executed_quantity(
                                response=result,
                                client_order_id=client_order_id,
                            )
                            if bot_quantity is None:
                                logger.warning(
                                    "Toobit LONG opened but executed quantity is not verified yet; "
                                    "live closing will remain disabled until it can be verified."
                                )
                        except Exception as e:
                            logger.exception(f"Toobit open LONG failed: {e}")
                            _persist_state()
                            return

                    entry_price = updates["entry_price"]
                    balance = updates["balance"]
                    balance_without_fee = updates["balance_without_fee"]
                    balance_before_trade = updates["balance_before_trade"]
                    balance_before_trade_no_fee = updates["balance_before_trade_no_fee"]
                    margin = updates["margin"]
                    leverage = updates["leverage"]
                    position_size = updates["position_size"]
                    margin_no_fee = updates["margin_no_fee"]
                    position_size_no_fee = updates["position_size_no_fee"]
                    open_time_value = updates["open_time_value"]
                    current_position = updates["current_position"]
                    entry_index = i
                    if not force_open_long:
                        last_trade_cross_time = last_cross_time
                    updates = None

                    if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                        try:
                            tb_balance = TOOBIT_CLIENT.get_balance(asset=TOOBIT_BALANCE_ASSET)
                            toobit_balance = tb_balance
                            if TOOBIT_SYNC_BALANCE:
                                balance = tb_balance
                                balance_without_fee = tb_balance
                        except Exception as e:
                            logger.exception(f"Toobit balance refresh failed: {e}")

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
                        current_position=current_position,
                        client_order_id=client_order_id,
                        exchange_order_id=exchange_order_id,
                        bot_quantity=bot_quantity,
                        position_value=margin * leverage,
                        position_value_no_fee=margin_no_fee * leverage,
                        trade_amount_percent=account_trade_amount_percent,
                        fee_rate=fee_rate,
                    )

                    logger.info(
                        f"ORDER OPENED #{order_id}: LONG @ {entry_price} | "
                        f"margin={margin} | lev={leverage} | "
                        f"trade_time={format_utc_timestamp(open_time_value)}",
                        extra={"category": "trade"},
                    )
                    if telegram_alerts:
                        signal_message.send_open_long(
                            price=close_prices[i],
                            time_str=close_times[i],
                            margin=margin,
                            position_size=position_size,
                            leverage=leverage,
                        )

    # ===================== CLOSE LONG =====================
    if current_position == "long":
        # exit scoring system (points accumulate; mirrored for short)
        exit_score = 0
        start_idx = max(0, min(entry_index if entry_index is not None else i, i))
        highest_since_entry = max(high_prices[start_idx : i + 1]) if start_idx <= i else high_prices[i]

        # 0) loss guard (no leverage): if price drops >= loss_exit_pct from entry
        if entry_price is not None and close_prices[i] <= entry_price * (1 - loss_exit_pct):
            exit_score += exit_score_loss_guard

        # 1) EMA slope weakness (look back `slope_window` candles)
        if i - slope_window >= 0 and ema_16_list[i - slope_window] is not None:
            if ema_16 < ema_16_list[i - slope_window]:
                exit_score += exit_score_ema_slope

        # 2) EMA crossing below MA50
        if ema_16 < ma_50:
            exit_score += exit_score_ema_cross

        # 3) long-term trend weakening (MA100 < MA200)
        if ma_100 < ma_200:
            exit_score += exit_score_ma_trend

        # 4) trailing stop based on pullback from peak (armed after min profit)
        if entry_index is not None and i > entry_index:
            if highest_since_entry >= entry_price * (1 + trail_activate_pct):
                if close_prices[i] <= highest_since_entry * (1 - trail_retrace_pct):
                    exit_score += exit_score_trailing

        # 5) ADX weakening (trend strength fading)
        if i - adx_exit_lookback >= 0:
            adx_now = adx
            adx_prev = adx_list[i - adx_exit_lookback]
            if adx_now is not None and adx_prev is not None:
                if np.isfinite(adx_now) and np.isfinite(adx_prev):
                    if adx_now < adx_exit_threshold and adx_now < adx_prev:
                        exit_score += exit_score_adx

        # 6) strong opposite candle (body >= ATR * mult)
        if atr is not None and atr > 0 and close_prices[i] < open_prices[i]:
            body = open_prices[i] - close_prices[i]
            if body >= atr * opposite_atr_body_mult:
                exit_score += exit_score_opposite_candle

        if force_close_long or exit_score >= exit_score_threshold:
            if position_size is None:
                print("Cannot close LONG: position_size unknown.")
                _persist_state()
                return
            if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                try:
                    if order_id is None or not str(client_order_id or "").startswith("BOT_"):
                        raise RuntimeError("Cannot prove this LONG belongs to the bot; refusing live close.")
                    if bot_quantity in (None, 0):
                        bot_quantity = TOOBIT_CLIENT.resolve_executed_quantity(
                            client_order_id=client_order_id,
                        )
                        if bot_quantity is not None:
                            db.update_order_execution(order_id, bot_quantity=bot_quantity)
                    if bot_quantity in (None, 0):
                        raise RuntimeError("Bot-owned LONG quantity is unknown; refusing live close.")
                    TOOBIT_CLIENT.close_position(
                        TOOBIT_SYMBOL,
                        side="LONG",
                        strategy="MA",
                        quantity=bot_quantity,
                    )
                except Exception as e:
                    logger.exception(f"Toobit close LONG failed: {e}")
                    _persist_state()
                    return

            prev_trade_power = trade_power
            updates = trade_manager.close_long(
                close_prices[i],
                close_times[i],
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
                trade_power,
            )

            balance = updates["balance"]
            balance_without_fee = updates["balance_without_fee"]
            margin = updates["margin"]
            margin_no_fee = updates["margin_no_fee"]
            deducting_fee_total = updates["deducting_fee_total"]
            profits_lst = updates["profits_lst"]
            total_profit_percent = updates["total_profit_percent"]
            count_closed_orders = updates["count_closed_orders"]
            equity_curve = updates["equity_curve"]
            max_drawdown = updates["max_drawdown"]
            total_wins = updates["total_wins"]
            total_wins_long = updates["total_wins_long"]
            total_losses = updates["total_losses"]
            total_long = updates["total_long"]
            cooldown_until_index = updates["cooldown_until_index"]
            current_position = updates["current_position"]
            profit_percent_per_month = updates["profit_percent_per_month"]
            save_money = updates["save_money"]
            trade_power = updates["trade_power"]
            profit = updates.get("profit")
            profit_percent = updates.get("profit_percent")
            pnl = updates.get("pnl")
            pnl_percent = updates.get("pnl_percent")
            ledger_metrics = {
                key: updates.get(key)
                for key in (
                    "pnl", "pnl_percent", "pnl_no_fee", "entry_fee", "exit_fee",
                    "total_fee", "fee_rate", "balance_after_trade",
                    "trade_amount_percent", "position_value", "position_value_no_fee",
                    "duration_seconds", "price_change_percent",
                )
            }
            updates = None
            entry_index = None
            entry_price = None
            position_size = None
            open_time_value = None
            tactical_balance = trade_manager.tactical_balance
            if prev_trade_power and not trade_power and current_month is not None:
                trade_power_locked_month = current_month

            if profits_lst and profits_lst[-1] < 0:
                consecutive_losses += 1
            else:
                consecutive_losses = 0
            if consecutive_losses >= 2:
                skip_trades_left = 2
                consecutive_losses = 0

            try:
                db.set_balance_state(state_mode, first_balance, tactical_balance, locked=1)
            except Exception as e:
                logger.exception(f"set_balance_state failed: {e}")

            if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                try:
                    tb_balance = TOOBIT_CLIENT.get_balance(asset=TOOBIT_BALANCE_ASSET)
                    toobit_balance = tb_balance
                    if TOOBIT_SYNC_BALANCE:
                        balance = tb_balance
                        balance_without_fee = tb_balance
                except Exception as e:
                    logger.exception(f"Toobit balance refresh failed: {e}")

            total_balance = balance + (margin if current_position is not None else 0) + save_money

            if order_id is not None:
                try:
                    db.update_order_close(
                        order_id=order_id,
                        close_price=close_prices[i],
                        close_time=close_times[i],
                        profit=profit,
                        profit_percent=profit_percent,
                        balance=balance,
                        balance_without_fee=balance_without_fee,
                        margin=margin,
                        margin_no_fee=margin_no_fee,
                        **ledger_metrics,
                    )
                except Exception as e:
                    logger.exception(f"DB update_order_close failed: {e}")

            logger.info(
                f"ORDER CLOSED #{order_id}: LONG | "
                f"exit={close_prices[i]} | profit={profit} | "
                f"trade_time={format_utc_timestamp(close_times[i])}",
                extra={"category": "trade"},
            )
            if telegram_alerts:
                signal_message.send_close_long(
                    price=close_prices[i],
                    time_str=close_times[i],
                    profit=profit,
                    profit_percent=profit_percent,
                    pnl=pnl,
                    pnl_percent=pnl_percent,
                    balance_before=balance_before_trade,
                    balance_after=total_balance,
                    margin=margin,
                )


    # ===================== OPEN SHORT =====================
    if current_position is None and (
        force_open_short
        or (cross_seen and last_cross_time is not None and last_trade_cross_time != last_cross_time)
    ):
        entry_score = 0
        can_try_open = True

        if force_open_short:
            entry_score = entry_score_threshold
        elif atr_filter:
            if atr is None or atr_ma is None or atr_ma <= 0:
                can_try_open = False
            else:
                atr_ratio = atr / atr_ma
                if atr_ratio < entry_atr_threshold:
                    can_try_open = False

        if can_try_open:
            # ---- positive scores ----
            # 1) confirmed bear cross
            if last_cross_dir == "bear" and last_cross_index is not None:
                if i > last_cross_index and close_prices[i] < ema_16:
                    entry_score += entry_score_cross

            # 2) EMA16 below MA50
            if ema_16 <= ma_50:
                entry_score += entry_score_ema_vs_ma50

            # 3) close below EMA16
            if close_prices[i] < ema_16:
                entry_score += entry_score_close_vs_ema16

            # 4) MA100 trend below MA200
            if ma_100 < ma_200:
                entry_score += entry_score_ma_trend

            # 5) MA distance or candle move is strong
            if ma_distance > ma_distance_threshold or last_candle_move > candle_move_threshold:
                entry_score += entry_score_ma_distance_or_candle

            # 6) ADX confirmation
            if adx_filter and adx is not None and adx >= entry_adx_threshold:
                entry_score += entry_score_adx

            # 7) volume confirmation
            if volume_filter:
                vol_now = volume_prices[i]
                vol_avg15 = vol_avg_15_list[i]
                if vol_avg15 and vol_now >= volume_spike_multiplier * vol_avg15:
                    entry_score += entry_score_volume

            # ---- negative score (late-entry guard) ----
            if i >= impulse_lookback:
                impulse_pct = (close_prices[i - impulse_lookback] / close_prices[i] - 1.0) * 100
                if impulse_pct > impulse_move_threshold_pct:
                    if atr is not None and atr > 0:
                        extension = (ema_16 - close_prices[i]) / atr
                        overextended = extension > late_entry_atr_mult
                    else:
                        extension = (ema_16 - close_prices[i]) / ema_16 if ema_16 else 0
                        overextended = extension > late_entry_ema_pct

                    body_now = close_prices[i] - open_prices[i]
                    body_prev = close_prices[i - 1] - open_prices[i - 1]
                    cooling = (body_now >= 0) or (
                        body_prev < 0 and abs(body_now) < abs(body_prev) * late_entry_body_ratio
                    )
                    if overextended and cooling:
                        entry_score -= entry_late_penalty

            if entry_score >= entry_score_threshold:
                if (not force_open_short) and skip_logic and skip_trades_left > 0:
                    skip_trades_left -= 1
                    last_trade_cross_time = last_cross_time
                    print(f"SKIP SHORT | skips left: {skip_trades_left}")
                else:
                    updates = trade_manager.open_short(
                        close_prices[i],
                        close_times[i],
                        balance,
                        balance_without_fee,
                        first_balance,
                        trade_amount_percent,
                        margin_balance,
                        leverage,
                    )

                    if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                        try:
                            if toobit_balance is None:
                                toobit_balance = TOOBIT_CLIENT.get_balance(asset=TOOBIT_BALANCE_ASSET)
                            live_value_qty = _calc_live_value_quantity(
                                toobit_balance,
                                trade_amount_percent,
                                updates["leverage"],
                                toobit_tactical_balance,
                            )
                            if live_value_qty is None:
                                raise RuntimeError("Cannot size live order from Toobit balance.")
                            TOOBIT_CLIENT.set_leverage(TOOBIT_SYMBOL, updates["leverage"])
                            result = TOOBIT_CLIENT.place_order(
                                symbol=TOOBIT_SYMBOL,
                                side="SELL_OPEN",
                                value_quantity=live_value_qty,
                                price_type="MARKET",
                                order_type="LIMIT",
                                strategy="MA",
                            )
                            client_order_id = result["client_order_id"]
                            exchange_order_id = TOOBIT_CLIENT.exchange_order_id(result)
                            bot_quantity = TOOBIT_CLIENT.resolve_executed_quantity(
                                response=result,
                                client_order_id=client_order_id,
                            )
                            if bot_quantity is None:
                                logger.warning(
                                    "Toobit SHORT opened but executed quantity is not verified yet; "
                                    "live closing will remain disabled until it can be verified."
                                )
                        except Exception as e:
                            logger.exception(f"Toobit open SHORT failed: {e}")
                            _persist_state()
                            return

                    entry_price = updates["entry_price"]
                    balance = updates["balance"]
                    balance_without_fee = updates["balance_without_fee"]
                    balance_before_trade = updates["balance_before_trade"]
                    balance_before_trade_no_fee = updates["balance_before_trade_no_fee"]
                    margin = updates["margin"]
                    leverage = updates["leverage"]
                    position_size = updates["position_size"]
                    margin_no_fee = updates["margin_no_fee"]
                    position_size_no_fee = updates["position_size_no_fee"]
                    open_time_value = updates["open_time_value"]
                    current_position = updates["current_position"]
                    entry_index = i
                    if not force_open_short:
                        last_trade_cross_time = last_cross_time
                    updates = None

                    if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                        try:
                            tb_balance = TOOBIT_CLIENT.get_balance(asset=TOOBIT_BALANCE_ASSET)
                            toobit_balance = tb_balance
                            if TOOBIT_SYNC_BALANCE:
                                balance = tb_balance
                                balance_without_fee = tb_balance
                        except Exception as e:
                            logger.exception(f"Toobit balance refresh failed: {e}")

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
                        current_position=current_position,
                        client_order_id=client_order_id,
                        exchange_order_id=exchange_order_id,
                        bot_quantity=bot_quantity,
                        position_value=margin * leverage,
                        position_value_no_fee=margin_no_fee * leverage,
                        trade_amount_percent=account_trade_amount_percent,
                        fee_rate=fee_rate,
                    )

                    logger.info(
                        f"ORDER OPENED #{order_id}: SHORT @ {entry_price} | "
                        f"margin={margin} | lev={leverage} | "
                        f"trade_time={format_utc_timestamp(open_time_value)}",
                        extra={"category": "trade"},
                    )
                    if telegram_alerts:
                        signal_message.send_open_short(
                            price=close_prices[i],
                            time_str=close_times[i],
                            margin=margin,
                            position_size=position_size,
                            leverage=leverage,
                        )


    # ===================== CLOSE SHORT =====================
    if current_position == "short":
        # exit scoring (mirrored logic)
        exit_score = 0
        start_idx = max(0, min(entry_index if entry_index is not None else i, i))
        lowest_since_entry = min(low_prices[start_idx : i + 1]) if start_idx <= i else low_prices[i]

        # 0) loss guard (no leverage): if price rises >= loss_exit_pct from entry
        if entry_price is not None and close_prices[i] >= entry_price * (1 + loss_exit_pct):
            exit_score += exit_score_loss_guard

        # 1) EMA slope weakness for short (EMA trending up)
        if i - slope_window >= 0 and ema_16_list[i - slope_window] is not None:
            if ema_16 > ema_16_list[i - slope_window]:
                exit_score += exit_score_ema_slope

        # 2) EMA crossing above MA50
        if ema_16 > ma_50:
            exit_score += exit_score_ema_cross

        # 3) long-term trend weakening for short (MA100 >= MA200)
        if ma_100 >= ma_200:
            exit_score += exit_score_ma_trend

        # 4) trailing stop based on pullback from trough (armed after min profit)
        if entry_index is not None and i > entry_index:
            if lowest_since_entry <= entry_price * (1 - trail_activate_pct):
                if close_prices[i] >= lowest_since_entry * (1 + trail_retrace_pct):
                    exit_score += exit_score_trailing

        # 5) ADX weakening (trend strength fading)
        if i - adx_exit_lookback >= 0:
            adx_now = adx
            adx_prev = adx_list[i - adx_exit_lookback]
            if adx_now is not None and adx_prev is not None:
                if np.isfinite(adx_now) and np.isfinite(adx_prev):
                    if adx_now < adx_exit_threshold and adx_now < adx_prev:
                        exit_score += exit_score_adx

        # 6) strong opposite candle (body >= ATR * mult)
        if atr is not None and atr > 0 and close_prices[i] > open_prices[i]:
            body = close_prices[i] - open_prices[i]
            if body >= atr * opposite_atr_body_mult:
                exit_score += exit_score_opposite_candle

        if force_close_short or exit_score >= exit_score_threshold:
            if position_size is None:
                print("Cannot close SHORT: position_size unknown.")
                _persist_state()
                return
            if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                try:
                    if order_id is None or not str(client_order_id or "").startswith("BOT_"):
                        raise RuntimeError("Cannot prove this SHORT belongs to the bot; refusing live close.")
                    if bot_quantity in (None, 0):
                        bot_quantity = TOOBIT_CLIENT.resolve_executed_quantity(
                            client_order_id=client_order_id,
                        )
                        if bot_quantity is not None:
                            db.update_order_execution(order_id, bot_quantity=bot_quantity)
                    if bot_quantity in (None, 0):
                        raise RuntimeError("Bot-owned SHORT quantity is unknown; refusing live close.")
                    TOOBIT_CLIENT.close_position(
                        TOOBIT_SYMBOL,
                        side="SHORT",
                        strategy="MA",
                        quantity=bot_quantity,
                    )
                except Exception as e:
                    logger.exception(f"Toobit close SHORT failed: {e}")
                    _persist_state()
                    return

            prev_trade_power = trade_power
            updates = trade_manager.close_short(
                close_prices[i],
                close_times[i],
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
                trade_power,
            )

            balance = updates["balance"]
            balance_without_fee = updates["balance_without_fee"]
            margin = updates["margin"]
            margin_no_fee = updates["margin_no_fee"]
            deducting_fee_total = updates["deducting_fee_total"]
            profits_lst = updates["profits_lst"]
            total_profit_percent = updates["total_profit_percent"]
            count_closed_orders = updates["count_closed_orders"]
            equity_curve = updates["equity_curve"]
            max_drawdown = updates["max_drawdown"]
            total_wins = updates["total_wins"]
            total_wins_short = updates["total_wins_short"]
            total_losses = updates["total_losses"]
            total_short = updates["total_short"]
            cooldown_until_index = updates["cooldown_until_index"]
            current_position = updates["current_position"]
            profit_percent_per_month = updates["profit_percent_per_month"]
            save_money = updates["save_money"]
            trade_power = updates["trade_power"]
            profit = updates.get("profit")
            profit_percent = updates.get("profit_percent")
            pnl = updates.get("pnl")
            pnl_percent = updates.get("pnl_percent")
            ledger_metrics = {
                key: updates.get(key)
                for key in (
                    "pnl", "pnl_percent", "pnl_no_fee", "entry_fee", "exit_fee",
                    "total_fee", "fee_rate", "balance_after_trade",
                    "trade_amount_percent", "position_value", "position_value_no_fee",
                    "duration_seconds", "price_change_percent",
                )
            }
            updates = None
            entry_index = None
            entry_price = None
            position_size = None
            open_time_value = None
            tactical_balance = trade_manager.tactical_balance
            if prev_trade_power and not trade_power and current_month is not None:
                trade_power_locked_month = current_month

            if profits_lst and profits_lst[-1] < 0:
                consecutive_losses += 1
            else:
                consecutive_losses = 0
            if consecutive_losses >= 2:
                skip_trades_left = 2
                consecutive_losses = 0

            try:
                db.set_balance_state(state_mode, first_balance, tactical_balance, locked=1)
            except Exception as e:
                logger.exception(f"set_balance_state failed: {e}")

            if TOOBIT_ENABLED and TOOBIT_EXECUTE_ORDERS:
                try:
                    tb_balance = TOOBIT_CLIENT.get_balance(asset=TOOBIT_BALANCE_ASSET)
                    toobit_balance = tb_balance
                    if TOOBIT_SYNC_BALANCE:
                        balance = tb_balance
                        balance_without_fee = tb_balance
                except Exception as e:
                    logger.exception(f"Toobit balance refresh failed: {e}")

            total_balance = balance + (margin if current_position is not None else 0) + save_money

            if order_id is not None:
                try:
                    db.update_order_close(
                        order_id=order_id,
                        close_price=close_prices[i],
                        close_time=close_times[i],
                        profit=profit,
                        profit_percent=profit_percent,
                        balance=balance,
                        balance_without_fee=balance_without_fee,
                        margin=margin,
                        margin_no_fee=margin_no_fee,
                        **ledger_metrics,
                    )
                except Exception as e:
                    logger.exception(f"DB update_order_close failed: {e}")

            logger.info(
                f"ORDER CLOSED #{order_id}: SHORT | "
                f"exit={close_prices[i]} | profit={profit} | "
                f"trade_time={format_utc_timestamp(close_times[i])}",
                extra={"category": "trade"},
            )
            if telegram_alerts:
                signal_message.send_close_short(
                    price=close_prices[i],
                    time_str=close_times[i],
                    profit=profit,
                    profit_percent=profit_percent,
                    pnl=pnl,
                    pnl_percent=pnl_percent,
                    balance_before=balance_before_trade,
                    balance_after=total_balance,
                    margin=margin,
                )

    _save_runtime_state(
        db,
        state_mode,
        last_trade_cross_time,
        skip_trades_left,
        consecutive_losses,
        trade_power,
        trade_power_locked_month,
    )
    _persist_state()


# wait on 0, 15, 30, 45 minutes for get data
def wait_for_next_quarter():
    while True:
        now = datetime.now(timezone.utc)

        if (
            now.minute in VALID_MINUTES
            and 20 <= now.second < 25
        ):
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

manual_group = parser.add_mutually_exclusive_group()
manual_group.add_argument(
    "--open_long",
    action="store_true",
    help="Force open LONG using live execution path (Toobit/DB/Telegram)."
)
manual_group.add_argument(
    "--close_long",
    action="store_true",
    help="Force close LONG using live execution path (Toobit/DB/Telegram)."
)
manual_group.add_argument(
    "--open_short",
    action="store_true",
    help="Force open SHORT using live execution path (Toobit/DB/Telegram)."
)
manual_group.add_argument(
    "--close_short",
    action="store_true",
    help="Force close SHORT using live execution path (Toobit/DB/Telegram)."
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
        init_toobit_balance(BOT_STATE)
    except Exception as e:
        logger.exception(f"Toobit init failed, disabling live trading: {e}")
        TOOBIT_ENABLED = False
        TOOBIT_EXECUTE_ORDERS = False

manual_action = None
if args.open_long:
    manual_action = "open_long"
elif args.close_long:
    manual_action = "close_long"
elif args.open_short:
    manual_action = "open_short"
elif args.close_short:
    manual_action = "close_short"

# MAIN LOOP 
while True:
    if manual_action is not None:
        ma_strategy(BOT_STATE, manual_action=manual_action)
        break
    elif args.test:
        ma_strategy(BOT_STATE)
        break

    else:
        wait_for_next_quarter()
        ma_strategy(BOT_STATE)

    time.sleep(FETCH_WINDOW_SECONDS + 1)
