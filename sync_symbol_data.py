def sync_recent_symbol_data(
    db,
    symbol,
    open_times,
    open_prices,
    high_prices,
    low_prices,
    close_prices,
    volume_prices,
    close_times,
    lookback=200,
):
    if not close_times:
        return 0, 0

    last_n = min(lookback, len(close_times))
    start_idx = len(close_times) - last_n

    # Keep one candle per close_time in case input contains duplicates.
    recent_by_close_time = {}
    for i in range(start_idx, len(close_times)):
        close_time = str(close_times[i])
        recent_by_close_time[close_time] = (
            symbol,
            str(open_times[i]),
            str(open_prices[i]),
            str(high_prices[i]),
            str(low_prices[i]),
            str(close_prices[i]),
            str(volume_prices[i]),
            close_time,
        )

    rows = list(recent_by_close_time.values())
    if not rows:
        return 0, 0

    target_close_times = [row[7] for row in rows]
    placeholders = ",".join("?" for _ in target_close_times)

    db.cursor.execute(
        f"""
        SELECT close_times
        FROM symbol_data
        WHERE symbol = ?
          AND close_times IN ({placeholders})
        """,
        [symbol, *target_close_times],
    )
    existing_close_times = {str(item[0]) for item in db.cursor.fetchall()}

    missing_rows = [row for row in rows if row[7] not in existing_close_times]
    if not missing_rows:
        return 0, len(rows)

    db.cursor.executemany(
        """
        INSERT INTO symbol_data (
            symbol, open_times, open_prices, high_prices,
            low_prices, close_prices, volume_prices, close_times
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        missing_rows,
    )
    db.conn.commit()

    return len(missing_rows), len(rows)
