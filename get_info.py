import requests
import time
from datetime import datetime, timezone
from indicators import Indicator

VALID_MINUTES = {0, 15, 30, 45}
FETCH_WINDOW_SECONDS = 10

current_position = None  # None | "long" | "short"

# get open, high, low, close, volume with json data
def get_ohlcv(
    symbol="BTCUSDT",
    interval="15m",
    limit=100
):
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
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    return data


# Main Trading Logic
def ma_strategy():
    global current_position

    open_times = []
    open_prices = []
    high_prices = []
    low_prices = []
    close_prices = []
    volume_prices = []
    close_times = []
    
    adx_filter = True
    volume_filter = True

    ma_distance_threshold = 0.00204  # 0.2٪
    candle_move_threshold = 0.0082 # 0.8٪

    data = (get_ohlcv("BTCUSDT", interval= "15m", limit= 201))  # BTCUSDT by default

    for i in range(len(data) - 1):
        open_times.append(str(datetime.fromtimestamp(data[i][0] / 1000, tz=timezone.utc)))
        open_prices.append(float(data[i][1]))
        high_prices.append(float(data[i][2]))
        low_prices.append(float(data[i][3]))
        close_prices.append(float(data[i][4]))
        volume_prices.append(float(data[i][5]))
        close_times.append(str(datetime.fromtimestamp(data[i][6] / 1000, tz=timezone.utc)))

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
        period=14
    )[-1]
    
    print("the price is:", open_prices[-1])
    print("volume:", volume_prices[-1])
    print("ADX:", adx)
    print("ma_200:", ma_200)

    # Calculate MA Distance
    ma_distance = abs(ema_14 - ma_50) / ma_50

    # Calculate Distance New Candle Move and Last Candle Move
    last_candle_move = abs(close_prices[-1] - close_prices[-2]) / close_prices[-2]

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

                # ---- Strong Candle ----
                body = abs(close_prices[-1] - open_prices[-1])
                range_ = high_prices[-1] - low_prices[-1]

                strong_candle = range_ > 0 and body >= 0.6 * range_

                # ---- Volume Condition ----
                volume_pass = vol_now >= 1.2 * vol_avg15

                if not (volume_pass and strong_candle):
                    return

    # ===================== CLOSE LONG =====================
    if current_position == "long":
        if (ema_14 < ma_50) or (ma_130 < ma_200):
            # CLOSE LONG
            print("close long now")
            current_position = None


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

                # ---- Strong Candle ----
                body = abs(close_prices[-1] - open_prices[-1])
                range_ = high_prices[-1] - low_prices[-1]

                strong_candle = range_ > 0 and body >= 0.6 * range_

                # ---- Volume Condition ----
                volume_pass = vol_now >= 1.2 * vol_avg15

                if not (volume_pass and strong_candle):
                    return
    

    # ===================== CLOSE SHORT =====================
    if current_position == "short":
        if (ema_14[i] > ma_50[i]) or (ma_130[i] >= ma_200[i]):
            # CLOSE SHORT
            print("close short now")
            current_position = None


# wait on 0, 15, 30, 45 minutes for get data
def wait_for_next_quarter():
    while True:
        now = datetime.now(timezone.utc)
        minute = now.minute
        second = now.second

        if minute in VALID_MINUTES and second < FETCH_WINDOW_SECONDS:
            return
        time.sleep(0.3)


# main 
while True:
    wait_for_next_quarter()
    ma_strategy()

    time.sleep(FETCH_WINDOW_SECONDS + 1)