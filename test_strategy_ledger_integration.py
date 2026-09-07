import contextlib
import importlib
import io
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from database import Database
from trademanager import calculate_trade_metrics


class StrategyLedgerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/"ledger.db"
        self.connections=[]
        self.client=Mock()
        self.client.get_balance.return_value=550.
        self.client.get_open_position.return_value=None
        self.client.get_positions.return_value=[]
        self.client.get_contract_multiplier.return_value=.001
        self.client.place_order.return_value={"client_order_id":"BOT_MA_TEST","orderId":"123"}
        self.client.exchange_order_id.return_value="123"
        self.client.resolve_executed_quantity.return_value=34.1
        self.client.resolve_average_fill_price.return_value=80276.3
        self.client.close_position.return_value={"client_order_id":"BOT_CLOSE_TEST"}
        with patch("trade_executor.get_trade_executor",return_value=self.client), patch("telegram_bot.create_telegram_notifier",return_value=Mock()):
            self.bot=importlib.import_module("get_info")
        db=Database(str(self.path));db.set_balance_state("local",1000,1030);db.set_balance_state("toobit",550,550);db.close()

    def tearDown(self):
        for db in self.connections: db.close()
        self.temp.cleanup()

    def candles(self,price,end):
        finish=int(datetime.fromisoformat(end).timestamp()*1000)
        return [[finish+(i-200)*900000,price,price+1,price-1,price,100,finish+(i-199)*900000-1] for i in range(201)]

    def database(self,*args,**kwargs):
        db=Database(str(self.path));self.connections.append(db);return db

    def cycle(self,state,action,price,end):
        with patch.object(self.bot,"TOOBIT_CLIENT",self.client),patch.object(self.bot,"Database",side_effect=self.database),patch.object(self.bot,"TradeCSVLogger",return_value=Mock()),patch.object(self.bot,"logger",Mock()),patch.object(self.bot,"get_ohlcv_toobit",return_value=self.candles(price,end)),contextlib.redirect_stdout(io.StringIO()):
            self.bot.ma_strategy(state,manual_action=action)

    def check_side(self,side):
        state=self.bot.BotState()
        self.cycle(state,"open_"+side,80341.82,"2026-09-07T00:00:00+00:00")
        db=self.connections[-1]
        order=db.get_open_order()
        self.assertIsNotNone(order)
        self.assertAlmostEqual(order["entry_price"],80341.82)
        self.assertAlmostEqual(order["position_size"],5150/80341.82)
        self.assertAlmostEqual(order["margin"],515.)
        self.assertAlmostEqual(order["bot_quantity"],34.1)
        self.assertAlmostEqual(order["balance"],485.)
        execution=db.cursor.execute("SELECT ledger_mode,execution_entry_price,execution_base_quantity FROM order_accounting").fetchone()
        self.assertEqual(execution[0],"local")
        self.assertAlmostEqual(execution[1],80276.3)
        self.assertAlmostEqual(execution[2],.0341)
        # A fresh state reproduces a process restart. Remote fills still must
        # not overwrite the strategy's candle exit or its account-sized PnL.
        state=self.bot.BotState()
        self.client.get_open_position.return_value={"side":side.upper()}
        self.client.resolve_average_fill_price.return_value=79700.
        self.cycle(state,"close_"+side,79759.46,"2026-09-07T06:00:00+00:00")
        db=self.connections[-1]
        row=db.cursor.execute("SELECT close_price,profit,balance FROM orders").fetchone()
        expected=calculate_trade_metrics(side,80341.82,79759.46,5150/80341.82,515,.0005,1000)
        self.assertAlmostEqual(row[0],79759.46)
        self.assertAlmostEqual(row[1],expected["profit"])
        self.assertAlmostEqual(row[2],1000+expected["profit"])
        self.assertAlmostEqual(state.balance,row[2])
        self.assertAlmostEqual(db.get_runtime_state("local")["profit_percent_per_month"],expected["profit_percent"])
        self.assertAlmostEqual(db.cursor.execute("SELECT execution_close_price FROM order_accounting").fetchone()[0],79700.)
        self.client.close_position.assert_called_once_with(self.bot.TOOBIT_SYMBOL,side=side.upper(),strategy="MA",quantity=34.1)

    def test_long_open_restart_close_preserves_local_balance(self): self.check_side("long")
    def test_short_open_restart_close_preserves_local_balance(self): self.check_side("short")
