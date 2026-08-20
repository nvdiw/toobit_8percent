import tempfile
import unittest
from pathlib import Path

from database import Database
from trademanager import (
    accumulate_monthly_profit_percent,
    calculate_margin,
    calculate_trade_metrics,
    select_leverage,
)


class TradeRiskTests(unittest.TestCase):
    def test_leverage_tiers_use_tactical_balance(self):
        args = (10, 2, 3, 4)
        self.assertEqual(select_leverage(901, 1000, *args), 10)
        self.assertEqual(select_leverage(900, 1000, *args), 4)
        self.assertEqual(select_leverage(850, 1000, *args), 3)
        self.assertEqual(select_leverage(800, 1000, *args), 2)

    def test_margin_falls_with_balance(self):
        self.assertEqual(calculate_margin(1000, 1000, 0.5), 500)
        self.assertEqual(calculate_margin(900, 1000, 0.5), 500)
        self.assertEqual(calculate_margin(1100, 1000, 0.5), 500)

    def test_monthly_profit_accumulates_trade_returns_not_account_cash(self):
        monthly_return = accumulate_monthly_profit_percent(-16.19, 3.41)
        self.assertAlmostEqual(monthly_return, -12.78)


class TradeMetricTests(unittest.TestCase):
    def test_long_gross_uses_margin_and_net_uses_active_balance(self):
        metrics = calculate_trade_metrics("long", 100, 110, 5, 50, 0.001, 1000)
        self.assertAlmostEqual(metrics["pnl"], 50)
        self.assertAlmostEqual(metrics["pnl_percent"], 100)
        self.assertAlmostEqual(metrics["total_fee"], 1.05)
        self.assertAlmostEqual(metrics["profit"], 48.95)
        self.assertAlmostEqual(metrics["profit_percent"], 4.895)

    def test_short_pnl_direction(self):
        metrics = calculate_trade_metrics("short", 100, 90, 5, 50, 0, 1000)
        self.assertAlmostEqual(metrics["pnl"], 50)
        self.assertAlmostEqual(metrics["profit"], 50)
        self.assertAlmostEqual(metrics["pnl_percent"], 100)

    def test_database_repairs_existing_derived_metrics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "orders.db"
            db = Database(str(db_path))
            order_id = db.insert_open_order(
                "BTCUSDT", "long", 100, "2026-01-01T00:00:00Z",
                position_size=5, margin=50, leverage=10,
                balance_before_trade=1000, fee_rate=0.001,
            )
            db.update_order_close(
                order_id, 110, "2026-01-01T01:00:00Z",
                profit=999, profit_percent=999, balance=1048.95,
                balance_without_fee=1050, margin=50, margin_no_fee=50,
                pnl=999, pnl_percent=999, total_fee=1.05,
            )
            db.close()

            repaired = Database(str(db_path))
            repaired.cursor.execute(
                "SELECT profit, profit_percent, pnl, pnl_percent, total_fee, "
                "balance_after_trade, save_money, total_assets FROM orders WHERE id = ?",
                (order_id,),
            )
            (
                profit, profit_percent, pnl, pnl_percent, total_fee,
                balance_after, save_money, total_assets,
            ) = repaired.cursor.fetchone()
            repaired.close()

            self.assertAlmostEqual(pnl, 50)
            self.assertAlmostEqual(pnl_percent, 100)
            self.assertAlmostEqual(profit, 48.95)
            self.assertAlmostEqual(profit_percent, 4.895)
            self.assertAlmostEqual(total_fee, 1.05)
            self.assertAlmostEqual(balance_after, 1048.95)
            self.assertAlmostEqual(save_money, 0)
            self.assertAlmostEqual(total_assets, 1048.95)

    def test_monthly_profit_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "runtime.db"
            db = Database(str(db_path))
            db.set_runtime_state(
                mode="toobit",
                trade_power=1,
                profit_percent_per_month=-12.7665,
            )
            db.close()

            reopened = Database(str(db_path))
            runtime = reopened.get_runtime_state("toobit")
            reopened.close()

            self.assertAlmostEqual(runtime["profit_percent_per_month"], -12.7665)


if __name__ == "__main__":
    unittest.main()
