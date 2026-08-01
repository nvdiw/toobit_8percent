import tempfile
import unittest
from pathlib import Path

from database import Database
from toobit_client import ToobitClient
from trademanager import trade_duration


class TradeDurationTests(unittest.TestCase):
    def test_accepts_space_and_iso_t_separator(self):
        self.assertEqual(
            trade_duration(
                "2026-08-01T02:30:00+00:00",
                "2026-08-02 05:45:00+00:00",
            ),
            (1, 3, 15),
        )

    def test_handles_real_calendar_and_z_timezone(self):
        self.assertEqual(
            trade_duration("2024-02-28T23:30:00Z", "2024-03-01T00:00:00Z"),
            (1, 0, 30),
        )


class BotOrderOwnershipTests(unittest.TestCase):
    def make_client(self, available=10):
        client = object.__new__(ToobitClient)
        client.get_open_position = lambda symbol, side=None: {
            "symbol": symbol,
            "side": side,
            "position": str(available),
            "available": str(available),
        }
        submitted = []

        def place_order(**kwargs):
            submitted.append(kwargs)
            return kwargs

        client.place_order = place_order
        return client, submitted

    def test_close_uses_only_bot_owned_quantity(self):
        client, submitted = self.make_client(available=10)

        client.close_position("BTC-SWAP-USDT", "LONG", "MA", quantity=3)

        self.assertEqual(submitted[0]["side"], "SELL_CLOSE")
        self.assertEqual(submitted[0]["quantity"], 3)

    def test_close_refuses_when_available_is_less_than_bot_quantity(self):
        client, submitted = self.make_client(available=2)

        with self.assertRaisesRegex(RuntimeError, "ambiguous position"):
            client.close_position("BTC-SWAP-USDT", "SHORT", "MA", quantity=3)

        self.assertEqual(submitted, [])

    def test_close_refuses_unknown_quantity(self):
        client, submitted = self.make_client()

        with self.assertRaisesRegex(RuntimeError, "missing or invalid"):
            client.close_position("BTC-SWAP-USDT", "LONG", "MA", quantity=None)

        self.assertEqual(submitted, [])

    def test_extracts_executed_contract_quantity(self):
        self.assertEqual(
            ToobitClient.executed_quantity({"executedQty": "7"}),
            7,
        )

    def test_open_position_enforces_requested_side(self):
        client = object.__new__(ToobitClient)
        client.get_positions = lambda symbol=None, side=None: [
            {"symbol": symbol, "side": "SHORT", "position": "9"},
            {"symbol": symbol, "side": "LONG", "position": "3"},
        ]
        position = client.get_open_position("BTC-SWAP-USDT", side="LONG")
        self.assertEqual(position["side"], "LONG")

    def test_database_persists_bot_ownership(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(str(Path(temp_dir) / "test.db"))
            order_id = db.insert_open_order(
                "BTCUSDT",
                "long",
                100.0,
                "2026-08-01T00:00:00+00:00",
                0.1,
                10.0,
                2,
                client_order_id="BOT_MA_000001",
                exchange_order_id="12345",
                bot_quantity=4,
            )

            order = db.get_open_order()
            self.assertEqual(order["id"], order_id)
            self.assertEqual(order["client_order_id"], "BOT_MA_000001")
            self.assertEqual(order["exchange_order_id"], "12345")
            self.assertEqual(order["bot_quantity"], 4)
            db.close()


if __name__ == "__main__":
    unittest.main()
