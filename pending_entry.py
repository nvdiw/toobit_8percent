"""Persist explicitly rejected entries without consuming their crossover."""


def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS pending_entry_retry (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        side TEXT NOT NULL, cross_time TEXT NOT NULL, error TEXT NOT NULL
    )""")


def remember(conn, side, cross_time, error):
    # Unknown outcomes/timeouts must never become fresh orders automatically.
    if "-1021" not in str(error):
        return
    _ensure(conn)
    conn.execute("INSERT OR REPLACE INTO pending_entry_retry VALUES (1, ?, ?, ?)",
                 (side, str(cross_time), str(error)[:1000]))
    conn.commit()


def clear(conn):
    _ensure(conn)
    conn.execute("DELETE FROM pending_entry_retry")
    conn.commit()


def has_pending(conn):
    _ensure(conn)
    return conn.execute("SELECT 1 FROM pending_entry_retry WHERE id=1").fetchone() is not None


def eligible_side(conn, cross_time, current_position):
    _ensure(conn)
    row = conn.execute("SELECT side, cross_time FROM pending_entry_retry WHERE id=1").fetchone()
    if row is None:
        return None
    if current_position is not None or str(cross_time) != row[1]:
        clear(conn)
        return None
    return row[0]
