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
            client_order_id TEXT
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
                     margin_no_fee=None, position_size_no_fee=None, current_position=None, client_order_id=None,):
        # extended insert supporting additional balance and fee-related fields
        self.cursor.execute("""
        INSERT INTO orders (
            symbol, side, entry_price, open_time, position_size, margin, leverage, status,
            balance, balance_without_fee, balance_before_trade, balance_before_trade_no_fee,
            margin_no_fee, position_size_no_fee, current_position, client_order_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol, side, entry_price, open_time, position_size, margin, leverage, status,
            balance, balance_without_fee, balance_before_trade, balance_before_trade_no_fee,
            margin_no_fee, position_size_no_fee, current_position, client_order_id
        ))
        self.conn.commit()
        return self.cursor.lastrowid

    def update_order_close(self, order_id, close_price, close_time, profit, profit_percent, balance,
                            balance_without_fee, margin, margin_no_fee, status="closed"):
        self.cursor.execute("""
        UPDATE orders
        SET close_price = ?, close_time = ?, profit = ?, profit_percent = ?, status = ?, balance = ?,
                            balance_without_fee = ?, margin = ?, margin_no_fee = ?
        WHERE id = ?
        """, (close_price, close_time, profit, profit_percent, status, balance,
                            balance_without_fee, margin, margin_no_fee, order_id))
        self.conn.commit()

    def get_open_order(self):
        self.cursor.execute("""
        SELECT id, symbol, side, entry_price, open_time, position_size, margin, leverage,
               balance, balance_without_fee, balance_before_trade, balance_before_trade_no_fee,
               margin_no_fee, position_size_no_fee, current_position
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
            'current_position': row[14]
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
            updated_at = datetime.datetime.now().isoformat()

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
            updated_at = datetime.datetime.now().isoformat()

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
            'current_position': 'TEXT'
        }
        for col, col_type in additions.items():
            if col not in cols:
                try:
                    self.cursor.execute(f"ALTER TABLE orders ADD COLUMN {col} {col_type}")
                    self.conn.commit()
                except Exception:
                    pass

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