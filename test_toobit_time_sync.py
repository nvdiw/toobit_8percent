import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from toobit_client import ToobitClient


def response(status, body):
    result = Mock(status_code=status)
    result.json.return_value = body
    return result


class TimeSyncTests(unittest.TestCase):
    def client(self, retries=3):
        return ToobitClient(api_key="test", api_secret="secret", max_retries=retries)

    @patch("toobit_client.requests.get")
    @patch("toobit_client.time.time", side_effect=[100.0, 100.2])
    def test_sync_corrects_clock_using_round_trip_midpoint(self, clock, get):
        get.return_value = response(200, {"serverTime": 110300})
        client = self.client()
        self.assertEqual(client.sync_server_time(), 10200)
        get.assert_called_once_with("https://api.toobit.com/api/v1/time", timeout=client.timeout)

    @patch("toobit_client.time.sleep")
    @patch("toobit_client.requests.request")
    def test_timestamp_rejection_resyncs_and_keeps_order_id(self, request, sleep):
        client = self.client()
        request.side_effect = [response(400, {"code": -1021}), response(200, {"orderId": "123"})]
        offsets = iter([0, 10200])
        def sync():
            client._server_time_offset_ms = next(offsets)
            client._last_time_sync = 1
        with patch.object(client, "sync_server_time", side_effect=sync) as synchronize, \
             patch("toobit_client.time.monotonic", return_value=1), \
             patch("toobit_client.time.time", return_value=100):
            result = client.place_order("BTC-SWAP-USDT", "SELL_OPEN", quantity=1, client_order_id="fixed-id")
        self.assertEqual(result["client_order_id"], "fixed-id")
        self.assertEqual(synchronize.call_count, 2)
        queries = [parse_qs(urlsplit(call.args[1]).query) for call in request.call_args_list]
        self.assertEqual([q["timestamp"][0] for q in queries], ["100000", "110200"])
        self.assertEqual([q["newClientOrderId"][0] for q in queries], ["fixed-id", "fixed-id"])
        self.assertNotEqual(queries[0]["signature"], queries[1]["signature"])
        sleep.assert_not_called()

    @patch("toobit_client.time.sleep")
    @patch("toobit_client.requests.request")
    def test_persistent_clock_rejection_is_bounded_and_reported(self, request, sleep):
        client = self.client(retries=2)
        request.return_value = response(400, {"code": -1021, "msg": "clock error"})
        with patch.object(client, "sync_server_time"), self.assertRaisesRegex(RuntimeError, "-1021"):
            client._signed_request("GET", "/test")
        self.assertEqual(request.call_count, 3)

    @patch("toobit_client.requests.request")
    def test_authentication_error_is_not_retried(self, request):
        client = self.client()
        request.return_value = response(400, {"code": -2015, "msg": "invalid key"})
        with patch.object(client, "sync_server_time"), self.assertRaisesRegex(RuntimeError, "-2015"):
            client._signed_request("GET", "/test")
        request.assert_called_once()

    @patch("toobit_client.time.sleep")
    @patch("toobit_client.requests.request")
    def test_http_retry_regenerates_timestamp(self, request, sleep):
        client = self.client()
        request.side_effect = [response(503, {}), response(200, {})]
        with patch.object(client, "sync_server_time"), \
             patch("toobit_client.time.time", side_effect=[100, 107]):
            client._signed_request("GET", "/test")
        times = [parse_qs(urlsplit(c.args[1]).query)["timestamp"][0] for c in request.call_args_list]
        self.assertEqual(times, ["100000", "107000"])

    @patch("toobit_client.requests.request")
    def test_failed_time_sync_sends_no_signed_request(self, request):
        client = self.client()
        with patch.object(client, "sync_server_time", side_effect=RuntimeError("offline")), \
             self.assertRaisesRegex(RuntimeError, "offline"):
            client._signed_request("POST", "/api/v1/futures/order")
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
