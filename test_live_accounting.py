import unittest
from unittest.mock import Mock
from live_accounting import reconcile_entry, resolve_close_price
from trademanager import calculate_trade_metrics

class LiveAccountingTests(unittest.TestCase):
    def test_trade_16_margin_and_equity(self):
        state = dict(entry_price=80276.3, position_size=.0341, leverage=10,
                     margin=515., balance=1146.9006922388303-515.)
        result = reconcile_entry(state)
        self.assertAlmostEqual(result["margin"], 273.742183)
        self.assertAlmostEqual(result["balance"]+result["margin"],1146.9006922388303)
        metrics=calculate_trade_metrics("long",80276.3,79759.46,.0341,result["margin"],.0005,1146.9006922388303)
        self.assertAlmostEqual(metrics["pnl"],-17.624244)
        self.assertAlmostEqual(metrics["profit"],-20.352853708)
        self.assertAlmostEqual(metrics["pnl_percent"],-6.438263846241)
        reconcile_entry(result)
        self.assertAlmostEqual(result["balance"]+result["margin"],1146.9006922388303)

    def test_close_fill_wins_over_candle(self):
        client=Mock(); client.resolve_average_fill_price.return_value=79780.
        self.assertEqual(resolve_close_price(client, {"client_order_id":"BOT_CLOSE"},79759.,Mock()),79780.)
        client.resolve_average_fill_price.assert_called_once_with(response={"client_order_id":"BOT_CLOSE"},client_order_id="BOT_CLOSE")

    def test_unavailable_fill_warns_estimate(self):
        client=Mock(); client.resolve_average_fill_price.return_value=None
        logger=Mock()
        self.assertEqual(resolve_close_price(client,{},79759.,logger),79759.)
        logger.warning.assert_called_once()
