import contextlib
import io
import unittest
from unittest.mock import Mock, patch

import requests
import get_ohlcv as feed


def response(rows):
    reply = Mock()
    reply.json.return_value = rows
    return reply


class CandleSourceTests(unittest.TestCase):
    def test_only_public_selected_endpoint_is_called_and_rows_are_compatible(self):
        for source in feed.OHLCV_SOURCES:
            with self.subTest(source=source):
                raw = [0, '100', '102', '99', '101', '5', 899999, '500', 3, '2', '200']
                request = Mock(return_value=response([raw]))
                rows = feed.fetch_ohlcv(source, start_time=0, request=request)
                params = dict(symbol='BTCUSDT', interval='15m', limit=100, startTime=0)
                if source == 'toobit':
                    params['endTime'] = 100 * 900000 - 1
                request.assert_called_once_with(feed.KLINE_URLS[source],
                    params=params, timeout=(5, 20))
                self.assertEqual(rows[0][:7], raw[:7])
                self.assertEqual(len(rows[0]), 12)

    def test_provider_failure_has_no_fallback(self):
        for getter, source in ((feed.get_ohlcv_binance, 'binance'), (feed.get_ohlcv_toobit, 'toobit')):
            with patch.object(feed.requests, 'get', side_effect=requests.Timeout('unavailable')) as request:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertIsNone(getter())
                self.assertEqual(request.call_count, 1)
                self.assertEqual(request.call_args.args[0], feed.KLINE_URLS[source])

    def test_rejects_bad_payload_and_unsupported_provider(self):
        request = Mock(return_value=response({'code': -1, 'msg': 'error'}))
        with self.assertRaises(ValueError):
            feed.fetch_ohlcv('binance', request=request)
        request.reset_mock()
        with self.assertRaises(ValueError):
            feed.fetch_ohlcv('wrong', request=request)
        request.assert_not_called()

    def test_cli_returns_failure_on_network_error(self):
        with patch.object(feed.requests, 'get', side_effect=requests.Timeout('unavailable')):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(feed.main(['--ohlcv-source', 'binance']), 1)


if __name__ == '__main__':
    unittest.main()
