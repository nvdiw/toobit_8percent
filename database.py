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
            status TEXT,
            current_position TEXT,
            client_order_id TEXT,
            exchange_order_id TEXT,
            open_time TEXT,
            close_time TEXT,
            duration_seconds INTEGER,
            entry_price REAL,
            close_price REAL,
            price_change_percent REAL,
            leverage INTEGER,
            trade_amount_percent REAL,
            margin REAL,
            margin_no_fee REAL,
            position_value REAL,
            position_value_no_fee REAL,
            position_size REAL,
            position_size_no_fee REAL,
            bot_quantity REAL,
            balance_before_trade REAL,
            balance_before_trade_no_fee REAL,
            balance REAL,
            balance_without_fee REAL,
            balance_after_trade REAL,
            save_money REAL,
            total_assets REAL,
            profit REAL,
            profit_percent REAL,
            pnl REAL,
            pnl_percent REAL,
            pnl_no_fee REAL,
            entry_fee REAL,
            exit_fee REAL,
            total_fee REAL,
            fee_rate REAL
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
            profit_percent_per_month REAL,
            updated_at TEXT
        )
        """)

        runtime_columns = {
            row[1] for row in self.cursor.execute("PRAGMA table_info(runtime_state)").fetchall()
        }
        if "profit_percent_per_month" not in runtime_columns:
            self.cursor.execute(
                "ALTER TABLE runtime_state ADD COLUMN profit_percent_per_month REAL"
            )

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
        self._ensure_order_layout()
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
                     position_value_no_fee=None, trade_amount_percent=None, fee_rate=None, save_money=None,
                     total_assets=None):
        # extended insert supporting additional balance and fee-related fields
        self.cursor.execute("""
        INSERT INTO orders (
            symbol, side, entry_price, open_time, position_size, margin, leverage, status,
            balance, balance_without_fee, balance_before_trade, balance_before_trade_no_fee,
            margin_no_fee, position_size_no_fee, current_position, client_order_id,
            exchange_order_id, bot_quantity, position_value, position_value_no_fee,
            trade_amount_percent, fee_rate, save_money, total_assets
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol, side, entry_price, open_time, position_size, margin, leverage, status,
            balance, balance_without_fee, balance_before_trade, balance_before_trade_no_fee,
            margin_no_fee, position_size_no_fee, current_position, client_order_id,
            exchange_order_id, bot_quantity, position_value, position_value_no_fee,
            trade_amount_percent, fee_rate, save_money, total_assets
        ))
        self.conn.commit()
        return self.cursor.lastrowid

    def update_order_close(self, order_id, close_price, close_time, profit, profit_percent, balance,
                            balance_without_fee, margin, margin_no_fee, status="closed", *, pnl=None,
                            pnl_percent=None, pnl_no_fee=None, entry_fee=None, exit_fee=None,
                             total_fee=None, fee_rate=None, balance_after_trade=None,
                             trade_amount_percent=None, position_value=None,
                             position_value_no_fee=None, duration_seconds=None,
                             price_change_percent=None, save_money=None, total_assets=None):
        self.cursor.execute("""
        UPDATE orders
        SET close_price = ?, close_time = ?, profit = ?, profit_percent = ?, status = ?, balance = ?,
            balance_without_fee = ?, margin = ?, margin_no_fee = ?, pnl = ?, pnl_percent = ?,
            pnl_no_fee = ?, entry_fee = ?, exit_fee = ?, total_fee = ?, fee_rate = ?,
            balance_after_trade = ?, trade_amount_percent = ?, position_value = ?,
            position_value_no_fee = ?, duration_seconds = ?, price_change_percent = ?,
            save_money = ?, total_assets = ?
        WHERE id = ?
        """, (close_price, close_time, profit, profit_percent, status, balance,
            balance_without_fee, margin, margin_no_fee, pnl, pnl_percent, pnl_no_fee,
            entry_fee, exit_fee, total_fee, fee_rate, balance_after_trade,
            trade_amount_percent, position_value, position_value_no_fee,
            duration_seconds, price_change_percent, save_money, total_assets, order_id))
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

    def get_current_save_money(self, default=0.0):
        self.cursor.execute("""
            SELECT save_money
            FROM orders
            WHERE save_money IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
        """)
        row = self.cursor.fetchone()
        return row[0] if row else default


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
            SELECT last_trade_cross_time, skip_trades_left, consecutive_losses, trade_power,
                   trade_power_locked_month, profit_percent_per_month
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
            'profit_percent_per_month': row[5],
        }

    def set_runtime_state(
        self,
        mode,
        last_trade_cross_time=None,
        skip_trades_left=0,
        consecutive_losses=0,
        trade_power=1,
        trade_power_locked_month=None,
        profit_percent_per_month=0.0,
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
                    trade_power = ?, trade_power_locked_month = ?,
                    profit_percent_per_month = ?, updated_at = ?
                WHERE mode = ?
            """, (
                last_trade_cross_time,
                int(skip_trades_left) if skip_trades_left is not None else 0,
                int(consecutive_losses) if consecutive_losses is not None else 0,
                int(trade_power) if trade_power is not None else 1,
                trade_power_locked_month,
                float(profit_percent_per_month or 0),
                updated_at,
                mode,
            ))
        else:
            self.cursor.execute("""
                INSERT INTO runtime_state (
                    mode, last_trade_cross_time, skip_trades_left, consecutive_losses,
                    trade_power, trade_power_locked_month, profit_percent_per_month, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                mode,
                last_trade_cross_time,
                int(skip_trades_left) if skip_trades_left is not None else 0,
                int(consecutive_losses) if consecutive_losses is not None else 0,
                int(trade_power) if trade_power is not None else 1,
                trade_power_locked_month,
                float(profit_percent_per_month or 0),
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
            'save_money': 'REAL',
            'total_assets': 'REAL',
        }
        for col, col_type in additions.items():
            if col not in cols:
                try:
                    self.cursor.execute(f"ALTER TABLE orders ADD COLUMN {col} {col_type}")
                    self.conn.commit()
                except Exception:
                    pass

    def _ensure_order_layout(self):
        desired_columns = [
            ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
            ("symbol", "TEXT NOT NULL"),
            ("side", "TEXT NOT NULL"),
            ("status", "TEXT"),
            ("current_position", "TEXT"),
            ("client_order_id", "TEXT"),
            ("exchange_order_id", "TEXT"),
            ("open_time", "TEXT"),
            ("close_time", "TEXT"),
            ("duration_seconds", "INTEGER"),
            ("entry_price", "REAL"),
            ("close_price", "REAL"),
            ("price_change_percent", "REAL"),
            ("leverage", "INTEGER"),
            ("trade_amount_percent", "REAL"),
            ("margin", "REAL"),
            ("margin_no_fee", "REAL"),
            ("position_value", "REAL"),
            ("position_value_no_fee", "REAL"),
            ("position_size", "REAL"),
            ("position_size_no_fee", "REAL"),
            ("bot_quantity", "REAL"),
            ("balance_before_trade", "REAL"),
            ("balance_before_trade_no_fee", "REAL"),
            ("balance", "REAL"),
            ("balance_without_fee", "REAL"),
            ("balance_after_trade", "REAL"),
            ("save_money", "REAL"),
            ("total_assets", "REAL"),
            ("profit", "REAL"),
            ("profit_percent", "REAL"),
            ("pnl", "REAL"),
            ("pnl_percent", "REAL"),
            ("pnl_no_fee", "REAL"),
            ("entry_fee", "REAL"),
            ("exit_fee", "REAL"),
            ("total_fee", "REAL"),
            ("fee_rate", "REAL"),
        ]
        current_columns = [row[1] for row in self.cursor.execute("PRAGMA table_info('orders')")]
        desired_names = [name for name, _ in desired_columns]
        if current_columns == desired_names:
            return

        unknown_columns = [name for name in current_columns if name not in desired_names]
        if unknown_columns:
            raise RuntimeError(f"Cannot reorder orders table with unknown columns: {unknown_columns}")

        schema = ",\n                ".join(f'"{name}" {definition}' for name, definition in desired_columns)
        columns_sql = ", ".join(f'"{name}"' for name in desired_names)
        self.cursor.execute("BEGIN IMMEDIATE")
        try:
            self.cursor.execute("DROP TABLE IF EXISTS orders_reordered")
            self.cursor.execute(f"CREATE TABLE orders_reordered ({schema})")
            self.cursor.execute(
                f"INSERT INTO orders_reordered ({columns_sql}) SELECT {columns_sql} FROM orders"
            )
            self.cursor.execute("DROP TABLE orders")
            self.cursor.execute("ALTER TABLE orders_reordered RENAME TO orders")
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

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
            SELECT id, status, side, entry_price, close_price, open_time, close_time,
                   position_size, position_size_no_fee, margin, leverage,
                   profit, profit_percent, balance_before_trade, pnl, pnl_percent, pnl_no_fee,
                   entry_fee, exit_fee, total_fee, fee_rate, balance_after_trade,
                   trade_amount_percent, position_value, position_value_no_fee,
                   duration_seconds, price_change_percent, balance, save_money, total_assets
            FROM orders
        """)
        rows = self.cursor.fetchall()
        for row in rows:
            (
                order_id, status, side, entry_price, close_price, open_time, close_time,
                position_size, position_size_no_fee, margin, leverage, profit,
                stored_profit_percent, balance_before, stored_pnl, stored_pnl_percent, stored_pnl_no_fee,
                stored_entry_fee, stored_exit_fee, stored_total_fee, stored_fee_rate,
                stored_balance_after, stored_trade_percent, stored_position_value,
                stored_position_value_no_fee, stored_duration, stored_price_change,
                stored_balance, stored_save_money, stored_total_assets,
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
            if entry is not None and size is not None:
                position_value = entry * size
            elif position_value is None and used_margin is not None and used_leverage is not None:
                position_value = used_margin * used_leverage
            position_value_no_fee = self._metric_float(stored_position_value_no_fee)
            if entry is not None and size_no_fee is not None:
                position_value_no_fee = entry * size_no_fee
            pnl = self._metric_float(stored_pnl)
            if None not in (entry, close, size):
                pnl = size * (close - entry) * direction
            pnl_no_fee = self._metric_float(stored_pnl_no_fee)
            if None not in (entry, close, size_no_fee):
                pnl_no_fee = size_no_fee * (close - entry) * direction
            pnl_percent = self._metric_float(stored_pnl_percent)
            if pnl is not None and used_margin:
                pnl_percent = pnl * 100 / used_margin
            total_fee = self._metric_float(stored_total_fee)
            fee_rate = self._metric_float(stored_fee_rate)
            entry_notional = entry * size if None not in (entry, size) else None
            exit_notional = close * size if None not in (close, size) else None
            if fee_rate is None and total_fee is not None and entry_notional is not None and exit_notional is not None:
                denominator = entry_notional + exit_notional
                fee_rate = total_fee / denominator if denominator else None
            entry_fee = self._metric_float(stored_entry_fee)
            if fee_rate is not None and entry_notional is not None:
                entry_fee = entry_notional * fee_rate
            exit_fee = self._metric_float(stored_exit_fee)
            if fee_rate is not None and exit_notional is not None:
                exit_fee = exit_notional * fee_rate
            if entry_fee is not None and exit_fee is not None:
                total_fee = entry_fee + exit_fee
            elif total_fee is None and pnl is not None and net_profit is not None:
                total_fee = max(0.0, pnl - net_profit)
            if pnl is not None and total_fee is not None:
                net_profit = pnl - total_fee
            profit_percent = self._metric_float(stored_profit_percent)
            if net_profit is not None and before:
                profit_percent = net_profit * 100 / before
            balance_after = self._metric_float(stored_balance_after)
            if before is not None and net_profit is not None:
                balance_after = before + net_profit
            trade_percent = self._metric_float(stored_trade_percent)
            if trade_percent is None and used_margin is not None and before:
                trade_percent = used_margin / before
            duration = self._metric_duration_seconds(open_time, close_time)
            price_change = self._metric_float(stored_price_change)
            if entry and close is not None:
                price_change = (close - entry) * direction * 100 / entry

            active_balance = self._metric_float(stored_balance)
            save_money = self._metric_float(stored_save_money)
            total_assets = self._metric_float(stored_total_assets)
            if str(status or "").strip().lower() == "closed" and active_balance is not None:
                if save_money is not None and abs(save_money) < 1e-8:
                    save_money = 0.0
                if save_money is None:
                    asset_difference = (
                        total_assets - active_balance if total_assets is not None else None
                    )
                    if asset_difference is not None and asset_difference >= -1e-8:
                        save_money = max(0.0, asset_difference)
                    elif balance_after is not None and balance_after >= active_balance:
                        save_money = balance_after - active_balance
                    else:
                        save_money = 0.0
                if (
                    total_assets is not None
                    and not save_money
                    and total_assets - active_balance > 1e-8
                ):
                    save_money = total_assets - active_balance
                total_assets = active_balance + save_money

            self.cursor.execute("""
                UPDATE orders
                SET profit = COALESCE(?, profit), profit_percent = COALESCE(?, profit_percent),
                    pnl = COALESCE(?, pnl), pnl_percent = COALESCE(?, pnl_percent),
                    pnl_no_fee = COALESCE(?, pnl_no_fee), entry_fee = COALESCE(?, entry_fee),
                    exit_fee = COALESCE(?, exit_fee), total_fee = COALESCE(?, total_fee),
                    fee_rate = COALESCE(fee_rate, ?), balance_after_trade = COALESCE(?, balance_after_trade),
                    trade_amount_percent = COALESCE(trade_amount_percent, ?),
                    position_value = COALESCE(?, position_value),
                    position_value_no_fee = COALESCE(?, position_value_no_fee),
                    duration_seconds = COALESCE(?, duration_seconds),
                    price_change_percent = COALESCE(?, price_change_percent),
                    save_money = COALESCE(?, save_money), total_assets = COALESCE(?, total_assets)
                WHERE id = ?
            """, (
                net_profit, profit_percent, pnl, pnl_percent, pnl_no_fee, entry_fee, exit_fee, total_fee,
                fee_rate, balance_after, trade_percent, position_value,
                position_value_no_fee, duration, price_change, save_money, total_assets, order_id,
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
