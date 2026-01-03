# existing file
"""
Fetch BTCUSDT 15m candles from Binance and store them in SQLite.

Usage:
  - Run with --test to enable TEST_MODE (fetch every 5 seconds).
  - Run without --test for REAL mode (fetch only at 00,15,30,45:00 UTC).

This script is suitable as a backend component for a trading bot
or for building a backtesting dataset.
"""

import argparse
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import requests

# Configuration
SYMBOL = "BTCUSDT"
TIMEFRAME = "15m"
BINANCE_KLINES_ENDPOINT = "https://api.binance.com/api/v3/klines"
DB_FILENAME = "database.db"


def get_db_path() -> str:
	# Place database next to this script for convenience
	base_dir = os.path.dirname(os.path.abspath(__file__))
	return os.path.join(base_dir, DB_FILENAME)


def init_db(conn: sqlite3.Connection) -> None:
	"""
	Create the `candles` table if it does not exist.

	Database logic:
	- `timestamp` column is UNIQUE to prevent duplicate inserts.
	- Other columns store numeric OHLCV and human-readable datetime.
	"""
	create_table_sql = """
	CREATE TABLE IF NOT EXISTS candles (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		symbol TEXT,
		timeframe TEXT,
		open REAL,
		high REAL,
		low REAL,
		close REAL,
		volume REAL,
		timestamp INTEGER UNIQUE,
		datetime TEXT
	)
	"""
	conn.execute(create_table_sql)
	conn.commit()


def fetch_candle_from_binance(symbol: str = SYMBOL, interval: str = TIMEFRAME, limit: int = 1) -> Optional[Dict]:
	"""
	Fetch the most recent kline(s) from Binance REST API.

	Binance API usage:
	- Endpoint: GET /api/v3/klines
	- Query params: symbol, interval, limit
	- Response: list of klines (arrays). Each kline array fields:
	  [0] open time (ms), [1] open, [2] high, [3] low, [4] close, [5] volume, ...

	Returns a dict with the extracted fields required by the DB, or None on error.
	"""
	params = {"symbol": symbol, "interval": interval, "limit": limit}
	try:
		resp = requests.get(BINANCE_KLINES_ENDPOINT, params=params, timeout=10)
		resp.raise_for_status()
		data = resp.json()
		if not data:
			return None
		# Use the last element (most recent) when limit>1; here limit==1 so data[0]
		k = data[-1]
		open_time_ms = int(k[0])
		open_p = float(k[1])
		high_p = float(k[2])
		low_p = float(k[3])
		close_p = float(k[4])
		volume = float(k[5])

		dt = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
		dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")

		return {
			"open": open_p,
			"high": high_p,
			"low": low_p,
			"close": close_p,
			"volume": volume,
			"timestamp": open_time_ms,
			"datetime": dt_str,
		}

	except requests.RequestException as e:
		print(f"Error fetching from Binance: {e}")
		return None


def insert_candle_to_db(conn: sqlite3.Connection, symbol: str, timeframe: str, candle: Dict) -> None:
	"""
	Insert a candle into the database, skipping duplicates.

	Duplicate prevention:
	- `timestamp` column has a UNIQUE constraint. We catch IntegrityError
	  and skip insertion when a duplicate exists.
	"""
	sql = """
	INSERT INTO candles (symbol, timeframe, open, high, low, close, volume, timestamp, datetime)
	VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
	"""
	try:
		conn.execute(
			sql,
			(
				symbol,
				timeframe,
				candle["open"],
				candle["high"],
				candle["low"],
				candle["close"],
				candle["volume"],
				candle["timestamp"],
				candle["datetime"],
			),
		)
		conn.commit()
		print("Saved to database")
	except sqlite3.IntegrityError:
		print("Candle already exists, skipping")


def seconds_until_next_15m() -> float:
	"""
	Compute the number of seconds until the next quarter-hour (00,15,30,45)
	at second == 0 in UTC.

	Timing logic:
	- Use UTC to avoid local timezone ambiguity.
	- If we're exactly on a valid timestamp (minute%15==0 and second==0), returns 0.
	"""
	now = datetime.now(tz=timezone.utc)
	minute = now.minute
	second = now.second
	# Compute next quarter hour minute
	next_minute = (minute - (minute % 15)) + 15
	# When minute % 15 == 0 and second == 0, next_minute equals minute+15; but we want 0 wait
	if minute % 15 == 0 and second == 0:
		return 0.0
	# Construct next run time
	next_hour = now.hour
	if next_minute >= 60:
		next_minute = next_minute % 60
		next_hour = (next_hour + 1) % 24
	next_run = datetime(
		year=now.year,
		month=now.month,
		day=now.day,
		hour=next_hour,
		minute=next_minute,
		second=0,
		tzinfo=timezone.utc,
	)
	# If next_run is earlier than now (day wrap), add a day
	if next_run <= now:
		next_run += timedelta(days=1)
	return (next_run - now).total_seconds()


def wait_until_next_15m() -> None:
	"""
	Sleep until the next quarter-hour boundary at second 0 (UTC).

	This function computes the precise seconds to wait and sleeps.
	It prints a user-friendly log before sleeping.
	"""
	sec = seconds_until_next_15m()
	if sec <= 0:
		# We're exactly on a boundary
		return
	print("Waiting for next 15m candle...")
	# Sleep in a single interval; precise enough for this use-case
	time.sleep(sec)


def main_loop(test_mode: bool) -> None:
	db_path = get_db_path()
	conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
	init_db(conn)

	if test_mode:
		print("TEST MODE: fetching every 5 seconds")
		# In test mode we fetch the latest available candle frequently
		while True:
			candle = fetch_candle_from_binance(symbol=SYMBOL, interval=TIMEFRAME, limit=1)
			if candle:
				print(f"Fetched {SYMBOL} candle at {candle['datetime']} UTC")
				insert_candle_to_db(conn, SYMBOL, TIMEFRAME, candle)
			time.sleep(5)
	else:
		# REAL MODE: fetch only at 00,15,30,45:00 UTC
		while True:
			# Wait until next quarter-hour boundary
			wait_until_next_15m()
			# After waiting, fetch the latest closed candle. We request 1 candle.
			candle = fetch_candle_from_binance(symbol=SYMBOL, interval=TIMEFRAME, limit=1)
			if candle:
				print(f"Fetched {SYMBOL} candle at {candle['datetime']} UTC")
				insert_candle_to_db(conn, SYMBOL, TIMEFRAME, candle)
			# To avoid accidental rapid loops in case of timing anomalies, small sleep
			time.sleep(1)


def parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(description="Fetch BTCUSDT 15m candles from Binance and store into SQLite")
	p.add_argument("--test", dest="test", action="store_true", help="Enable TEST_MODE: fetch every 5 seconds")
	return p.parse_args()


if __name__ == "__main__":
	args = parse_args()
	try:
		main_loop(test_mode=args.test)
	except KeyboardInterrupt:
		print("Exiting on user interrupt")
