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
            status TEXT
        )
        """)

        self.conn.commit()

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
    def insert_order(self, symbol, side, entry_price, open_time, position_size, margin, leverage, status="open"):
        self.cursor.execute("""
        INSERT INTO orders (symbol, side, entry_price, open_time, position_size, margin, leverage, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, side, entry_price, open_time, position_size, margin, leverage, status))
        self.conn.commit()
        return self.cursor.lastrowid

    def update_order_close(self, order_id, close_price, close_time, profit, profit_percent, status="closed"):
        self.cursor.execute("""
        UPDATE orders
        SET close_price = ?, close_time = ?, profit = ?, profit_percent = ?, status = ?
        WHERE id = ?
        """, (close_price, close_time, profit, profit_percent, status, order_id))
        self.conn.commit()

    def get_open_order(self):
        self.cursor.execute("""
        SELECT id, symbol, side, entry_price, open_time, position_size, margin, leverage
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
            'leverage': row[7]
        }
