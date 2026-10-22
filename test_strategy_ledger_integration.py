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
        rows = self.candles(price, end)
        report = dict(level="warning", requested_source=self.bot.OHLCV_SOURCE,
            actual_sources=["toobit"], fallback_count=len(rows),
            expected_candles=len(rows), missing_count=0,
            providers={"binance": dict(available=False, candles=0, error="fixture offline"),
                       "toobit": dict(available=True, candles=len(rows), error="")})
        with (patch.object(self.bot, "TOOBIT_CLIENT", self.client),
              patch.object(self.bot, "Database", side_effect=self.database),
              patch.object(self.bot, "TradeCSVLogger", return_value=Mock()),
              patch.object(self.bot, "logger", Mock()),
              patch.object(self.bot, "fetch_dual_ohlcv", return_value=(rows, report)) as feed,
              patch("requests.sessions.Session.request",
                    side_effect=AssertionError("Integration fixtures must not contact the network")),
              contextlib.redirect_stdout(io.StringIO())):
            self.bot.ma_strategy(state, manual_action=action)
        feed.assert_called_once_with(self.bot.OHLCV_SOURCE,
            symbol="BTCUSDT", interval="15m", limit=201)

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

    def test_demo_leverage_survives_live_budget_and_wallet_changes(self):
        for side in ("long", "short"):
            for demo_balance, expected_leverage in ((809.4731445074965, 2), (1000., 10)):
                for budget, available in ((200., 550.), (550., 550.), (200., 75.), (2000., 400.)):
                    with self.subTest(side=side, demo=demo_balance, budget=budget, available=available):
                        self.path = Path(self.temp.name) / f"{side}-{demo_balance}-{budget}-{available}.db"
                        db = self.database()
                        db.set_balance_state("local", 1000, 1030)
                        db.set_balance_state("toobit", budget, budget)
                        db.insert_open_order("BTCUSDT", side, 100, "2026-09-06T00:00:00+00:00",
                            position_size=1, margin=50, leverage=2, status="closed",
                            balance=demo_balance, balance_without_fee=demo_balance, ledger_mode="local")
                        self.client.reset_mock()
                        self.client.get_balance.return_value = available
                        # The previous position's 2x must not become the next entry ceiling.
                        state = self.bot.BotState(leverage=2)
                        self.cycle(state, "open_" + side, 80341.82, "2026-09-07T00:00:00+00:00")
                        self.client.set_leverage.assert_called_once_with(self.bot.TOOBIT_SYMBOL, expected_leverage)
                        value = self.client.place_order.call_args.kwargs["value_quantity"]
                        self.assertEqual(value, min(available, budget * .5) * expected_leverage)
                        opened = db.get_open_order()
                        self.assertEqual(opened["leverage"], expected_leverage)
                        self.assertEqual(opened["margin"], 515.)
                        self.assertEqual(opened["balance_before_trade"], demo_balance)
                        self.assertEqual(db.get_balance_state("local")["tactical_balance"], 1030.)

    def test_existing_ten_x_order_is_unchanged_after_restart_and_budget_change(self):
        self.cycle(self.bot.BotState(), "open_long", 80341.82, "2026-09-07T00:00:00+00:00")
        db = self.connections[-1]
        original = db.get_open_order()
        db.set_balance_state("toobit", 200, 200)
        self.client.reset_mock()
        self.client.get_balance.return_value = 75.
        self.client.get_open_position.return_value = {"side": "LONG"}
        state = self.bot.BotState()
        with patch.object(self.bot, "exit_score_threshold", 1000):
            self.cycle(state, None, 80341.82, "2026-09-07T00:15:00+00:00")
        self.assertEqual(db.get_open_order(), original)
        self.assertEqual(state.leverage, 10)
        self.client.set_leverage.assert_not_called()
        self.client.place_order.assert_not_called()
        self.client.close_position.assert_not_called()
