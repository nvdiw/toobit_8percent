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
