import argparse
import unittest
from unittest.mock import patch

from trade_executor import CopyTradeExecutor, FutureTradeExecutor, add_api_trade_argument, get_trade_executor


class TradeExecutorRoutingTests(unittest.TestCase):
    def test_cli_default_and_explicit_modes(self):
        parser = argparse.ArgumentParser()
        add_api_trade_argument(parser)
        self.assertEqual(parser.parse_args([]).api_trade, "future-trade")
        self.assertEqual(parser.parse_args(["--api-trade", "future-trade"]).api_trade, "future-trade")
        self.assertEqual(parser.parse_args(["--api-trade", "copy-trade"]).api_trade, "copy-trade")

    def test_factory_routes_modes(self):
        self.assertIsInstance(get_trade_executor("future-trade"), FutureTradeExecutor)
        self.assertIsInstance(get_trade_executor("copy-trade"), CopyTradeExecutor)

    def test_all_sides_use_selected_executor(self):
        for cls in (FutureTradeExecutor, CopyTradeExecutor):
            client = cls(api_key="key", api_secret="secret")
            with patch.object(client, "_signed_request", return_value={"orderId": "1"}) as request:
                for side in ("BUY_OPEN", "SELL_OPEN", "SELL_CLOSE", "BUY_CLOSE"):
                    client.place_order("BTC-SWAP-USDT", side, quantity=1)
                    self.assertEqual(request.call_args.args[1], "/api/v1/futures/order")

    def test_copy_positions_use_leader_endpoint(self):
        client = CopyTradeExecutor(api_key="key", api_secret="secret")
        with patch.object(client, "_signed_request", return_value={"code": 200, "data": []}) as request:
            client.get_positions()
            self.assertEqual(request.call_args.args[1], client.leader_positions_path)

    def test_copy_position_quantity_remains_contract_quantity(self):
        client = CopyTradeExecutor(api_key="key", api_secret="secret")
        payload = {"code": 200, "data": [{"symbolId": "BTC-SWAP-USDT", "isLong": 1, "quantity": "2.6"}]}
        with patch.object(client, "_signed_request", return_value=payload):
            position = client.get_positions()[0]
        self.assertEqual(position["position"], 2.6)
        self.assertEqual(position["copyQuantity"], "2.6")

    def test_copy_close_uses_the_reported_contract_quantity(self):
        client = CopyTradeExecutor(api_key="key", api_secret="secret")
        payload = {
            "code": 200,
            "data": [{"symbolId": "BTC-SWAP-USDT", "isLong": 0, "quantity": "2.6"}],
        }
        with (
            patch.object(client, "_signed_request", return_value=payload),
            patch.object(
                client,
                "place_order",
                return_value={"orderId": "1", "client_order_id": "close-1"},
            ) as place_order,
            patch.object(client, "resolve_executed_quantity", return_value=2.6),
        ):
            client.close_position("BTC-SWAP-USDT", "SHORT", "MA", 2.6)
        self.assertEqual(place_order.call_args.kwargs["quantity"], 2.6)

    def test_spot_balance_values_every_asset_in_usdt(self):
        client = FutureTradeExecutor(api_key="key", api_secret="secret")
        account = {
            "balances": [
                {"coin": "USDT", "total": "10", "free": "8", "locked": "2"},
                {"coin": "BTC", "total": "2", "free": "1.5", "locked": "0.5"},
            ]
        }
        exchange_info = {
            "symbols": [
                {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"}
            ]
        }
        tickers = [{"s": "BTCUSDT", "p": "100"}]
        with (
            patch.object(client, "_signed_request", return_value=account),
            patch.object(client, "_public_get", side_effect=[exchange_info, tickers]),
        ):
            details = client.get_spot_balance_details("USDT")
        self.assertEqual(details["total"], 210.0)
        self.assertEqual(details["available"], 158.0)
        self.assertEqual(details["locked"], 52.0)

    def test_total_account_balance_keeps_spot_and_futures_components(self):
        client = FutureTradeExecutor(api_key="key", api_secret="secret")
        with (
            patch.object(
                client,
                "get_balance_details",
                return_value={"total": 500.0, "available": 480.0},
            ),
            patch.object(
                client,
                "get_spot_balance_details",
                return_value={"total": 25.0, "available": 20.0},
            ),
        ):
            details = client.get_total_account_balance_details("USDT")
        self.assertEqual(details["total"], 525.0)
        self.assertEqual(details["available"], 500.0)


if __name__ == "__main__":
    unittest.main()
