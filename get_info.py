import requests
from datetime import datetime
from indicators import Indicator

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

    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    return data


# ===== Example =====
if __name__ == "__main__":
    open_times = []
    open_prices = []
    high_prices = []
    low_prices = []
    close_prices = []
    volume_prices = []
    close_times = []

    current_position = None  # None | "long" | "short"
    
    adx_filter = True
    ma_distance_threshold = 0.00204  # 0.2٪
    candle_move_threshold = 0.0082 # 0.8٪

    data = (get_ohlcv("BTCUSDT", interval= "15m", limit= 200))  # BTCUSDT by default

    for i in range(len(data)):
        open_times.append(str(datetime.fromtimestamp(data[i][0] / 1000)))
        open_prices.append(float(data[i][1]))
        high_prices.append(float(data[i][2]))
        low_prices.append(float(data[i][3]))
        close_prices.append(float(data[i][4]))
        volume_prices.append(float(data[i][5]))
        close_times.append(str(datetime.fromtimestamp(data[i][6] / 1000)))

    # ---- get MA/EMA ----
    indicator = Indicator(open_prices, period=None)
    ema_14 = indicator.get_EMA(14)[-1]
    ma_50 = indicator.get_MA(50)[-1]
    ma_130 = indicator.get_MA(130)[-1]
    ma_200 = indicator.get_MA(200)[-1]

    # ---- get_ADX ----
    indicator = Indicator(open_prices)
    adx = indicator.get_ADX(
        high_prices,
        low_prices,
        close_prices,
        period=14
    )[-1]

    # Calculate MA Distance
    ma_distance = abs(ema_14 - ma_50) / ma_50

    # Calculate Distance New Candle Move and Last Candle Move
    last_candle_move = abs(open_prices[-1] - open_prices[-2]) / open_prices[-2]

    # ===================== OPEN LONG =====================
    if ma_130 >= ma_200 and ema_14 > ma_50 and current_position is None:
        if ma_distance > ma_distance_threshold or last_candle_move > candle_move_threshold:
            
            # ===== ADX FILTER =====
            if adx_filter == True :
                if adx > 20.5:
                    # OPEN LONG
                    print("open long now")
                    current_position = "long"
            

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
                if adx > 20.5:
                    # OPEN SHORT
                    print("open short now")
                    current_position = "short"
    

    # ===================== CLOSE SHORT =====================
    if current_position == "short":
        if (ema_14[i] > ma_50[i]) or (ma_130[i] >= ma_200[i]):
            # CLOSE SHORT
            print("close short now")
            current_position = None