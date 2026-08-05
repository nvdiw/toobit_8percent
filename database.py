from datetime import datetime, timezone
import math
import sqlite3


class Database:
    def __init__(self, db_name="database.db"):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        # users
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT UNIQUE,
            created_at TEXT
        )
        """)

        # symbol_data
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS symbol_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            open_times TEXT NOT NULL,
            open_prices TEXT NOT NULL,
            high_prices TEXT NOT NULL,
            low_prices TEXT NOT NULL,
            close_prices TEXT NOT NULL,
            volume_prices TEXT NOT NULL,
            close_times TEXT NOT NULL
        )
        """)

        self.conn.commit()

        # orders table
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL,
            open_time TEXT,
            close_price REAL,
            close_time TEXT,
            position_size REAL,
            margin REAL,
            leverage INTEGER,
            profit REAL,
            profit_percent REAL,
            status TEXT,
            balance REAL,
            balance_without_fee REAL,
            balance_before_trade REAL,
            balance_before_trade_no_fee REAL,
            margin_no_fee REAL,
            position_size_no_fee REAL,
            current_position TEXT,
            client_order_id TEXT,
            exchange_order_id TEXT,
            bot_quantity REAL,
            pnl REAL,
            pnl_percent REAL,
            pnl_no_fee REAL,
            entry_fee REAL,
            exit_fee REAL,
            total_fee REAL,
            fee_rate REAL,
            balance_after_trade REAL,
            trade_amount_percent REAL,
            position_value REAL,
            position_value_no_fee REAL,
            duration_seconds INTEGER,
            price_change_percent REAL
        )
        """)

        self.conn.commit()

        # balance state table (persist first/tactical balances across restarts)
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS balance_state (
            mode TEXT PRIMARY KEY,
            first_balance REAL,
            tactical_balance REAL,
            locked INTEGER,
            updated_at TEXT
        )
        """)

        self.conn.commit()

        # runtime state table (persist strategy state across restarts)
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS runtime_state (
            mode TEXT PRIMARY KEY,
            last_trade_cross_time TEXT,
            skip_trades_left INTEGER,
            consecutive_losses INTEGER,
            trade_power INTEGER,
            trade_power_locked_month TEXT,
            updated_at TEXT
        )
        """)

        self.conn.commit()

        # order counter
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_counter (
            strategy TEXT PRIMARY KEY,
            counter INTEGER NOT NULL
        )
        """)

        self.conn.commit()

        # ensure any missing columns are added for older DBs
        self._ensure_order_columns()
        self._backfill_order_metrics()

    # ---------- INSERT METHODS ----------

    def insert_user(self, username, email, created_at):
        self.cursor.execute("""
        INSERT INTO users (username, email, created_at)
        VALUES (?, ?, ?)
        """, (username, email, created_at))
        self.conn.commit()

    def insert_data(self, symbol, open_times, open_prices, high_prices, low_prices, close_prices, volume_prices, close_times):
        self.cursor.execute("""
        INSERT INTO symbol_data (symbol, open_times, open_prices, high_prices, low_prices, close_prices, volume_prices, close_times)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, open_times, open_prices, high_prices, low_prices, close_prices, volume_prices, close_times))
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ---------- ORDER METHODS ----------
    def insert_open_order(self, symbol, side, entry_price, open_time, position_size, margin, leverage, status="open",
                     balance=None, balance_without_fee=None, balance_before_trade=None, balance_before_trade_no_fee=None,
                     margin_no_fee=None, position_size_no_fee=None, current_position=None, client_order_id=None,
                     exchange_order_id=None, bot_quantity=None, position_value=None,
                     position_value_no_fee=None, trade_amount_percent=None, fee_rate=None):
        # extended insert supporting additional balance and fee-related fields
        self.cursor.execute("""
        INSERT INTO orders (
            symbol, side, entry_price, open_time, position_size, margin, leverage, status,
            balance, balance_without_fee, balance_before_trade, balance_before_trade_no_fee,
            margin_no_fee, position_size_no_fee, current_position, client_order_id,
            exchange_order_id, bot_quantity, position_value, position_value_no_fee,
            trade_amount_percent, fee_rate
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol, side, entry_price, open_time, position_size, margin, leverage, status,
            balance, balance_without_fee, balance_before_trade, balance_before_trade_no_fee,
            margin_no_fee, position_size_no_fee, current_position, client_order_id,
            exchange_order_id, bot_quantity, position_value, position_value_no_fee,
            trade_amount_percent, fee_rate
        ))
        self.conn.commit()
        return self.cursor.lastrowid

    def update_order_close(self, order_id, close_price, close_time, profit, profit_percent, balance,
                            balance_without_fee, margin, margin_no_fee, status="closed", *, pnl=None,
                            pnl_percent=None, pnl_no_fee=None, entry_fee=None, exit_fee=None,
                            total_fee=None, fee_rate=None, balance_after_trade=None,
                            trade_amount_percent=None, position_value=None,
                            position_value_no_fee=None, duration_seconds=None,
                            price_change_percent=None):
        self.cursor.execute("""
        UPDATE orders
        SET close_price = ?, close_time = ?, profit = ?, profit_percent = ?, status = ?, balance = ?,
            balance_without_fee = ?, margin = ?, margin_no_fee = ?, pnl = ?, pnl_percent = ?,
            pnl_no_fee = ?, entry_fee = ?, exit_fee = ?, total_fee = ?, fee_rate = ?,
            balance_after_trade = ?, trade_amount_percent = ?, position_value = ?,
            position_value_no_fee = ?, duration_seconds = ?, price_change_percent = ?
        WHERE id = ?
        """, (close_price, close_time, profit, profit_percent, status, balance,
            balance_without_fee, margin, margin_no_fee, pnl, pnl_percent, pnl_no_fee,
            entry_fee, exit_fee, total_fee, fee_rate, balance_after_trade,
            trade_amount_percent, position_value, position_value_no_fee,
            duration_seconds, price_change_percent, order_id))
        self.conn.commit()

    def update_order_execution(self, order_id, exchange_order_id=None, bot_quantity=None):
        self.cursor.execute("""
        UPDATE orders
        SET exchange_order_id = COALESCE(?, exchange_order_id),
            bot_quantity = COALESCE(?, bot_quantity)
        WHERE id = ?
        """, (exchange_order_id, bot_quantity, order_id))
        self.conn.commit()

    def get_open_order(self):
        self.cursor.execute("""
        SELECT id, symbol, side, entry_price, open_time, position_size, margin, leverage,
               balance, balance_without_fee, balance_before_trade, balance_before_trade_no_fee,
               margin_no_fee, position_size_no_fee, current_position, client_order_id,
               exchange_order_id, bot_quantity
        FROM orders
        WHERE status = 'open'
        ORDER BY id DESC
        LIMIT 1
        """)
        row = self.cursor.fetchone()
        if not row:
            return None
        return {
            'id': row[0],
            'symbol': row[1],
            'side': row[2],
            'entry_price': row[3],
            'open_time': row[4],
            'position_size': row[5],
            'margin': row[6],
            'leverage': row[7],
            'balance': row[8],
            'balance_without_fee': row[9],
            'balance_before_trade': row[10],
            'balance_before_trade_no_fee': row[11],
            'margin_no_fee': row[12],
            'position_size_no_fee': row[13],
            'current_position': row[14],
            'client_order_id': row[15],
            'exchange_order_id': row[16],
            'bot_quantity': row[17],
        }

    def get_current_balances(self, initial_balance=1000):
        """
        Get latest balance and balance_without_fee from last order (any status).
        If no order exists or balances are NULL, return initial balance.
        """

        self.cursor.execute("""
            SELECT balance, balance_without_fee
            FROM orders
            ORDER BY id DESC
            LIMIT 1
        """)

        row = self.cursor.fetchone()

        if row and row[0] is not None:
            balance = row[0]
            balance_without_fee = row[1] if row[1] is not None else row[0]
        else:
            balance = initial_balance
            balance_without_fee = initial_balance

        return balance, balance_without_fee


    # ---------- BALANCE STATE METHODS ----------
    def get_balance_state(self, mode):
        self.cursor.execute("""
            SELECT first_balance, tactical_balance, locked
            FROM balance_state
            WHERE mode = ?
            LIMIT 1
        """, (mode,))
        row = self.cursor.fetchone()
        if not row:
            return None
        return {
            'first_balance': row[0],
            'tactical_balance': row[1],
            'locked': row[2]
        }

    def set_balance_state(self, mode, first_balance, tactical_balance, locked=1, updated_at=None):
        if updated_at is None:
            import datetime
            updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        self.cursor.execute("""
            SELECT mode
            FROM balance_state
            WHERE mode = ?
            LIMIT 1
        """, (mode,))
        exists = self.cursor.fetchone() is not None

        if exists:
            self.cursor.execute("""
                UPDATE balance_state
                SET first_balance = ?, tactical_balance = ?, locked = ?, updated_at = ?
                WHERE mode = ?
            """, (first_balance, tactical_balance, locked, updated_at, mode))
        else:
            self.cursor.execute("""
                INSERT INTO balance_state (mode, first_balance, tactical_balance, locked, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (mode, first_balance, tactical_balance, locked, updated_at))

        self.conn.commit()

    def get_runtime_state(self, mode):
        self.cursor.execute("""
            SELECT last_trade_cross_time, skip_trades_left, consecutive_losses, trade_power, trade_power_locked_month
            FROM runtime_state
            WHERE mode = ?
            LIMIT 1
        """, (mode,))
        row = self.cursor.fetchone()
        if not row:
            return None
        return {
            'last_trade_cross_time': row[0],
            'skip_trades_left': row[1],
            'consecutive_losses': row[2],
            'trade_power': row[3],
            'trade_power_locked_month': row[4],
        }

    def set_runtime_state(
        self,
        mode,
        last_trade_cross_time=None,
        skip_trades_left=0,
        consecutive_losses=0,
        trade_power=1,
        trade_power_locked_month=None,
        updated_at=None,
    ):
        if updated_at is None:
            import datetime
            updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        self.cursor.execute("""
            SELECT mode
            FROM runtime_state
            WHERE mode = ?
            LIMIT 1
        """, (mode,))
        exists = self.cursor.fetchone() is not None

        if exists:
            self.cursor.execute("""
                UPDATE runtime_state
                SET last_trade_cross_time = ?, skip_trades_left = ?, consecutive_losses = ?,
                    trade_power = ?, trade_power_locked_month = ?, updated_at = ?
                WHERE mode = ?
            """, (
                last_trade_cross_time,
                int(skip_trades_left) if skip_trades_left is not None else 0,
                int(consecutive_losses) if consecutive_losses is not None else 0,
                int(trade_power) if trade_power is not None else 1,
                trade_power_locked_month,
                updated_at,
                mode,
            ))
        else:
            self.cursor.execute("""
                INSERT INTO runtime_state (
                    mode, last_trade_cross_time, skip_trades_left, consecutive_losses,
                    trade_power, trade_power_locked_month, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                mode,
                last_trade_cross_time,
                int(skip_trades_left) if skip_trades_left is not None else 0,
                int(consecutive_losses) if consecutive_losses is not None else 0,
                int(trade_power) if trade_power is not None else 1,
                trade_power_locked_month,
                updated_at,
            ))

        self.conn.commit()


    def _ensure_order_columns(self):
        # Check existing columns and add missing ones (for existing DBs)
        self.cursor.execute("PRAGMA table_info('orders')")
        cols = {r[1] for r in self.cursor.fetchall()}
        additions = {
            'balance': 'REAL',
            'balance_without_fee': 'REAL',
            'balance_before_trade': 'REAL',
            'balance_before_trade_no_fee': 'REAL',
            'margin_no_fee': 'REAL',
            'position_size_no_fee': 'REAL',
            'current_position': 'TEXT',
            'client_order_id': 'TEXT',
            'exchange_order_id': 'TEXT',
            'bot_quantity': 'REAL',
            'pnl': 'REAL',
            'pnl_percent': 'REAL',
            'pnl_no_fee': 'REAL',
            'entry_fee': 'REAL',
            'exit_fee': 'REAL',
            'total_fee': 'REAL',
            'fee_rate': 'REAL',
            'balance_after_trade': 'REAL',
            'trade_amount_percent': 'REAL',
            'position_value': 'REAL',
            'position_value_no_fee': 'REAL',
            'duration_seconds': 'INTEGER',
            'price_change_percent': 'REAL',
        }
        for col, col_type in additions.items():
            if col not in cols:
                try:
                    self.cursor.execute(f"ALTER TABLE orders ADD COLUMN {col} {col_type}")
                    self.conn.commit()
                except Exception:
                    pass

    @staticmethod
    def _metric_float(value):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _metric_duration_seconds(open_time, close_time):
        def parse(value):
            if value in (None, ""):
                return None
            if isinstance(value, datetime):
                parsed = value
            else:
                text = str(value).strip().replace("Z", "+00:00")
                try:
                    parsed = datetime.fromisoformat(text)
                except (TypeError, ValueError):
                    return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

        opened = parse(open_time)
        closed = parse(close_time)
        if opened is None or closed is None:
            return None
        return max(0, int((closed - opened).total_seconds()))

    def _backfill_order_metrics(self):
        self.cursor.execute("""
            SELECT id, side, entry_price, close_price, open_time, close_time,
                   position_size, position_size_no_fee, margin, leverage,
                   profit, balance_before_trade, pnl, pnl_percent, pnl_no_fee,
                   entry_fee, exit_fee, total_fee, fee_rate, balance_after_trade,
                   trade_amount_percent, position_value, position_value_no_fee,
                   duration_seconds, price_change_percent
            FROM orders
        """)
        rows = self.cursor.fetchall()
        for row in rows:
            (
                order_id, side, entry_price, close_price, open_time, close_time,
                position_size, position_size_no_fee, margin, leverage, profit,
                balance_before, stored_pnl, stored_pnl_percent, stored_pnl_no_fee,
                stored_entry_fee, stored_exit_fee, stored_total_fee, stored_fee_rate,
                stored_balance_after, stored_trade_percent, stored_position_value,
                stored_position_value_no_fee, stored_duration, stored_price_change,
            ) = row
            entry = self._metric_float(entry_price)
            close = self._metric_float(close_price)
            size = self._metric_float(position_size)
            size_no_fee = self._metric_float(position_size_no_fee)
            used_margin = self._metric_float(margin)
            used_leverage = self._metric_float(leverage)
            net_profit = self._metric_float(profit)
            before = self._metric_float(balance_before)
            direction = -1.0 if str(side or "").strip().lower() in {"short", "sell"} else 1.0

            position_value = self._metric_float(stored_position_value)
            if position_value is None:
                if entry is not None and size is not None:
                    position_value = entry * size
                elif used_margin is not None and used_leverage is not None:
                    position_value = used_margin * used_leverage
            position_value_no_fee = self._metric_float(stored_position_value_no_fee)
            if position_value_no_fee is None and entry is not None and size_no_fee is not None:
                position_value_no_fee = entry * size_no_fee
            pnl = self._metric_float(stored_pnl)
            if pnl is None and None not in (entry, close, size):
                pnl = size * (close - entry) * direction
            pnl_no_fee = self._metric_float(stored_pnl_no_fee)
            if pnl_no_fee is None and None not in (entry, close, size_no_fee):
                pnl_no_fee = size_no_fee * (close - entry) * direction
            pnl_percent = self._metric_float(stored_pnl_percent)
            if pnl_percent is None and pnl is not None and used_margin:
                pnl_percent = pnl * 100 / used_margin
            total_fee = self._metric_float(stored_total_fee)
            if total_fee is None and pnl is not None and net_profit is not None:
                total_fee = max(0.0, pnl - net_profit)
            fee_rate = self._metric_float(stored_fee_rate)
            entry_notional = entry * size if None not in (entry, size) else None
            exit_notional = close * size if None not in (close, size) else None
            if fee_rate is None and total_fee is not None and entry_notional is not None and exit_notional is not None:
                denominator = entry_notional + exit_notional
                fee_rate = total_fee / denominator if denominator else None
            entry_fee = self._metric_float(stored_entry_fee)
            if entry_fee is None and fee_rate is not None and entry_notional is not None:
                entry_fee = entry_notional * fee_rate
            exit_fee = self._metric_float(stored_exit_fee)
            if exit_fee is None and fee_rate is not None and exit_notional is not None:
                exit_fee = exit_notional * fee_rate
            balance_after = self._metric_float(stored_balance_after)
            if balance_after is None and before is not None and net_profit is not None:
                balance_after = before + net_profit
            trade_percent = self._metric_float(stored_trade_percent)
            if trade_percent is None and used_margin is not None and before:
                trade_percent = used_margin / before
            duration = stored_duration if stored_duration is not None else self._metric_duration_seconds(open_time, close_time)
            price_change = self._metric_float(stored_price_change)
            if price_change is None and entry and close is not None:
                price_change = (close - entry) * direction * 100 / entry

            self.cursor.execute("""
                UPDATE orders
                SET pnl = COALESCE(pnl, ?), pnl_percent = COALESCE(pnl_percent, ?),
                    pnl_no_fee = COALESCE(pnl_no_fee, ?), entry_fee = COALESCE(entry_fee, ?),
                    exit_fee = COALESCE(exit_fee, ?), total_fee = COALESCE(total_fee, ?),
                    fee_rate = COALESCE(fee_rate, ?), balance_after_trade = COALESCE(balance_after_trade, ?),
                    trade_amount_percent = COALESCE(trade_amount_percent, ?),
                    position_value = COALESCE(position_value, ?),
                    position_value_no_fee = COALESCE(position_value_no_fee, ?),
                    duration_seconds = COALESCE(duration_seconds, ?),
                    price_change_percent = COALESCE(price_change_percent, ?)
                WHERE id = ?
            """, (
                pnl, pnl_percent, pnl_no_fee, entry_fee, exit_fee, total_fee,
                fee_rate, balance_after, trade_percent, position_value,
                position_value_no_fee, duration, price_change, order_id,
            ))
        self.conn.commit()

    # get number of count orderID's of any strategy
    def get_order_counter(self, strategy):
        self.cursor.execute("""
            SELECT counter
            FROM order_counter
            WHERE strategy = ?
            LIMIT 1
        """, (strategy,))

        row = self.cursor.fetchone()

        if row is None:
            return 0

        return row[0]

    # increase number of orderID
    def increment_order_counter(self, strategy):
        counter = self.get_order_counter(strategy) + 1

        self.cursor.execute("""
            INSERT OR REPLACE INTO order_counter(strategy, counter)
            VALUES (?, ?)
        """, (strategy, counter))

        self.conn.commit()

        return counter

# db = Database()
# x = db.get_balance_state("local")
# print(x)
