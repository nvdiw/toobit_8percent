"""Public candle data only; balances and order execution remain on Toobit."""
import argparse
from datetime import datetime, timezone
import json
import math
import sys

import requests

OHLCV_SOURCES = ("toobit", "binance")
KLINE_URLS = {
    "toobit": "https://api.toobit.com/quote/v1/klines",
    "binance": "https://data-api.binance.vision/api/v3/klines",
}
INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
    "4h": 14_400_000, "6h": 21_600_000, "8h": 28_800_000,
    "12h": 43_200_000, "1d": 86_400_000, "3d": 259_200_000,
    "1w": 604_800_000,
}


def add_ohlcv_source_argument(parser, *, default="toobit"):
    parser.add_argument(
        "--ohlcv-source", type=str.lower, choices=OHLCV_SOURCES, default=default,
        help="Candle provider only. Balances and all orders remain on Toobit.",
    )


def validate_source(source):
    if source not in OHLCV_SOURCES:
        raise ValueError(f"Unsupported OHLCV source: {source!r}")
    return source


def fetch_ohlcv(source="toobit", symbol="BTCUSDT", interval="15m", limit=100,
                *, start_time=None, request=None, timeout=(5, 20)):
    """Fetch public candles, normalizing Toobit rows to the Binance row format.

    No credentials, private clients, order APIs or automatic provider fallback.
    ``start_time`` also supports the native runner's historical pagination.
    """
    validate_source(source)
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported candle interval: {interval!r}")
    if not 1 <= limit <= 1000:
        raise ValueError("Candle limit must be between 1 and 1000")
    params = dict(symbol=symbol.upper(), interval=interval, limit=limit)
    if start_time is not None:
        params["startTime"] = int(start_time)
        if source == "toobit":
            # Toobit ignores startTime alone; bound both ends for forward pages.
            params["endTime"] = int(start_time) + limit * INTERVAL_MS[interval] - 1
    response = (request or requests.get)(KLINE_URLS[source], params=params, timeout=timeout)
    response.raise_for_status()
    raw_rows = response.json()
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError(f"{source} returned no valid candle rows")
    result = []
    for row in raw_rows:
        if not isinstance(row, (list, tuple)) or len(row) < (7 if source == "binance" else 6):
            raise ValueError(f"Malformed {source} candle")
        prices = [float(value) for value in row[1:6]]
        if not all(math.isfinite(value) for value in prices):
            raise ValueError("Non-finite OHLCV data")
        op, high, low, close, volume = prices
        if min(op, high, low, close) <= 0 or volume < 0 or low > min(op, close) or high < max(op, close):
            raise ValueError("Invalid OHLCV price range or volume")
        opened = int(row[0])
        closed = opened + INTERVAL_MS[interval] - 1 if source == "toobit" else int(row[6])
        if closed - opened + 1 != INTERVAL_MS[interval]:
            raise ValueError("Unexpected candle duration")
        if result and opened <= result[-1][0]:
            raise ValueError("Candle timestamps must be strictly increasing")
        tail = list(row[7:12])
        result.append([opened, *row[1:6], closed, *tail, *(["0"] * (5 - len(tail)))])
    return result


def _legacy_fetch(source, symbol, interval, limit):
    print(f"Fetching {source} OHLCV: {symbol} {interval}")
    try:
        return fetch_ohlcv(source, symbol, interval, limit)
    except (requests.RequestException, ValueError, TypeError) as exc:
        print(f"OHLCV fetch failed ({source}): {exc}")
        return None


def get_ohlcv_binance(symbol="BTCUSDT", interval="15m", limit=100):
    return _legacy_fetch("binance", symbol, interval, limit)


def get_ohlcv_toobit(symbol="BTCUSDT", interval="15m", limit=100):
    return _legacy_fetch("toobit", symbol, interval, limit)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Test public OHLCV only; no bot, database, keys or orders.")
    add_ohlcv_source_argument(parser)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", choices=tuple(INTERVAL_MS), default="15m")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        rows = fetch_ohlcv(args.ohlcv_source, args.symbol, args.interval, args.limit)
    except (requests.RequestException, ValueError, TypeError) as exc:
        print(f"OHLCV test failed ({args.ohlcv_source}): {exc}", file=sys.stderr)
        return 1
    last = rows[-1]
    print(json.dumps({
        "source": args.ohlcv_source, "symbol": args.symbol.upper(),
        "interval": args.interval, "candles": len(rows), "endpoint": KLINE_URLS[args.ohlcv_source],
        "latest": {"open_time_utc": datetime.fromtimestamp(last[0] / 1000, timezone.utc).isoformat(),
                   "open": last[1], "high": last[2], "low": last[3], "close": last[4],
                   "volume": last[5], "close_ms": last[6]},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
