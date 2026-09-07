import contextlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from database import Database
from live_accounting import apply_execution_to_ledger
from repair_local_ledger import repair
from trademanager import TradeManager, calculate_trade_metrics


class LocalLedgerTests(unittest.TestCase):
    def test_local_trade_keeps_strategy_notional_with_smaller_exchange_account(self):
        manager=TradeManager(Mock(),1000,8,1030,True,3,10,2,3,4)
        opened=manager.open_long(80341.82,"2026-09-07 00:00:00+00:00",1070.7590106832627,1247.2154291997826,1000,.5,1070.7590106832627,10)
        original=opened.copy()
        apply_execution_to_ledger(opened,.0341,80276.3,False)
        self.assertEqual(opened,original)
        metrics=calculate_trade_metrics("long",opened["entry_price"],79759.46,opened["position_size"],opened["margin"],.0005,opened["balance_before_trade"])
        self.assertAlmostEqual(metrics["profit"],-42.46125860728576)
        self.assertAlmostEqual(opened["balance"]+opened["margin"]+metrics["profit"],1028.2977520759769)

    def test_sync_mode_uses_exchange_fill(self):
        values=dict(entry_price=100,position_size=50,margin=500,balance=500,leverage=10)
        apply_execution_to_ledger(values,25,101,True)
        self.assertEqual(values["position_size"],25)
        self.assertEqual(values["entry_price"],101)
        self.assertAlmostEqual(values["balance"]+values["margin"],1000)

    def make_corrupted_ledger(self,path):
        db=Database(str(path))
        db.set_balance_state("local",1000,1000)
        db.set_runtime_state("local",profit_percent_per_month=99,updated_at="2026-09-07T12:00:00+00:00")
        for timestamp,price in [("2026-09-01 00:00:00+00:00",100),("2026-09-02 00:00:00+00:00",90),("2026-09-03 00:00:00+00:00",95)]:
            db.insert_data("BTCUSDT",timestamp,str(price),str(price),str(price),str(price),"1",timestamp)
        oid=db.insert_open_order("BTCUSDT","long",99,"2026-09-01 00:00:00+00:00",position_size=25,margin=500,leverage=10,
            balance=500,balance_without_fee=500,balance_before_trade=1000,balance_before_trade_no_fee=1000,
            margin_no_fee=500,position_size_no_fee=50,client_order_id="BOT_TEST_1",bot_quantity=25000,fee_rate=.0005,save_money=0)
        db.update_order_close(oid,90,"2026-09-02 00:00:00+00:00",profit=-227.3625,profit_percent=-22.73625,balance=1100,
                              balance_without_fee=900,margin=500,margin_no_fee=500,fee_rate=.0005,save_money=0)
        db.insert_open_order("BTCUSDT","short",94,"2026-09-03 00:00:00+00:00",position_size=25,margin=200,leverage=10,
            balance=900,balance_without_fee=700,balance_before_trade=1100,balance_before_trade_no_fee=900,
            margin_no_fee=200,position_size_no_fee=2000/95,client_order_id="BOT_TEST_2",bot_quantity=123,fee_rate=.0005,save_money=0)
        db.close()

    def test_repair_rebuilds_cash_open_trade_monthly_profit_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"test.db"
            self.make_corrupted_ledger(path)
            plan=repair(path)
            self.assertAlmostEqual(plan["balance"],295.25)
            result=repair(path,True)
            self.assertTrue(Path(result["backup"]).exists())
            self.assertTrue(repair(path,True)["already_applied"])
            db=Database(str(path))
            try:
                db.assert_local_ledger()
                self.assertAlmostEqual(db.get_current_balances()[0],295.25)
                self.assertAlmostEqual(db.get_runtime_state("local")["profit_percent_per_month"],-50.475)
                self.assertAlmostEqual(db.get_monthly_profit_percent("2026-09"),-50.475)
                self.assertEqual(db.get_monthly_profit_percent("2026-10"),0)
                opened=db.get_open_order()
                self.assertEqual(opened["bot_quantity"],123)
                self.assertEqual(opened["client_order_id"],"BOT_TEST_2")
                self.assertAlmostEqual(opened["position_size"],2000/95)
                row=db.cursor.execute("SELECT profit,balance_after_trade,balance FROM orders WHERE id=1").fetchone()
                self.assertEqual(row,(-504.75,495.25,495.25))
            finally:
                db.close()

    def test_missing_candle_refuses_repair_without_touching_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"test.db"
            self.make_corrupted_ledger(path)
            with contextlib.closing(sqlite3.connect(path)) as c:
                c.execute("DELETE FROM symbol_data");c.commit()
                before=c.execute("SELECT * FROM orders").fetchall()
            with self.assertRaisesRegex(ValueError,"Missing entry candle"):
                repair(path,True)
            with contextlib.closing(sqlite3.connect(path)) as c:
                self.assertEqual(c.execute("SELECT * FROM orders").fetchall(),before)

    def test_legacy_mixed_ledger_cannot_resume_local_trading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"test.db"; self.make_corrupted_ledger(path)
            db=Database(str(path))
            try:
                with self.assertRaisesRegex(RuntimeError,"needs repair"):
                    db.assert_local_ledger()
            finally: db.close()
