import requests

# get open, high, low, close, volume with json data from binance
def get_ohlcv_binance(
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


# get open, high, low, close, volume with json data from toobit
def get_ohlcv_toobit(
    symbol="BTCUSDT",
    interval="15m",
    limit=100
):
    """
    Return candles in Binance format:
    [
        open_time,
        open,
        high,
        low,
        close,
        volume,
        close_time,
        ...
    ]
    """

    url = "https://api.toobit.com/quote/v1/klines"

    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit
    }

    print("📊 Fetching OHLCV data...")

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        raw_data = response.json()

        data = []

        interval_ms = {
            "1m": 60_000,
            "3m": 180_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "2h": 7_200_000,
            "4h": 14_400_000,
            "6h": 21_600_000,
            "8h": 28_800_000,
            "12h": 43_200_000,
            "1d": 86_400_000,
        }

        candle_ms = interval_ms.get(interval, 900_000)

        for c in raw_data:
            open_time = c[0]
            close_time = open_time + candle_ms - 1

            data.append([
                open_time,      # 0
                c[1],           # 1 open
                c[2],           # 2 high
                c[3],           # 3 low
                c[4],           # 4 close
                c[5],           # 5 volume
                close_time,     # 6 close_time (ساخته شده)
                c[7],           # 7 quote volume
                c[8],           # 8 trades
                c[9],           # 9 taker buy base
                c[10],          # 10 taker buy quote
                "0"             # 11 ignore
            ])

        return data

    except Exception as e:
        print(f"❌ Error fetching OHLCV: {e}")
        return None
