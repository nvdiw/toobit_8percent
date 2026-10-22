import contextlib
import argparse
import io
import logging
from threading import Barrier
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


class DualCandleTests(unittest.TestCase):
    def test_default_runner_and_dual_feed_prefer_binance(self):
        parser = argparse.ArgumentParser()
        feed.add_ohlcv_source_argument(parser)
        self.assertEqual(parser.parse_args([]).ohlcv_source, 'binance')
        request = self.request({'binance': self.rows('100'), 'toobit': self.rows('105')})
        rows, report = feed.fetch_dual_ohlcv(limit=3, now_ms=1800020, request=request)
        self.assertEqual(report['requested_source'], 'binance')
        self.assertEqual(report['actual_sources'], ['binance'])
        self.assertEqual([row[4] for row in rows], ['100'] * 3)

    def test_provider_requests_start_concurrently(self):
        started = Barrier(2)

        def request(url, **kwargs):
            started.wait(timeout=2)
            return response(self.rows('100' if url == feed.KLINE_URLS['binance'] else '105'))

        rows, report = feed.fetch_dual_ohlcv('binance', limit=3, now_ms=1800020, request=request)
        self.assertEqual(len(rows), 3)
        self.assertEqual(report['actual_sources'], ['binance'])

    def rows(self, price='100'):
        return [[opened, price, '110', '90', price, '5', opened+899999]
                for opened in (0, 900000, 1800000)]

    def request(self, payloads):
        def get(url, **kwargs):
            source = next(key for key, value in feed.KLINE_URLS.items() if value == url)
            value = payloads[source]
            if isinstance(value, Exception):
                raise value
            return response(value)
        return Mock(side_effect=get)

    def fetch(self, source, payloads):
        request = self.request(payloads)
        result = feed.fetch_dual_ohlcv(source, limit=3, now_ms=1800020, request=request)
        self.assertEqual({call.args[0] for call in request.call_args_list}, set(feed.KLINE_URLS.values()))
        return result

    def test_both_are_fetched_and_selected_source_has_priority(self):
        for source in feed.OHLCV_SOURCES:
            rows, report = self.fetch(source, {'binance': self.rows('100'), 'toobit': self.rows('105')})
            self.assertEqual(rows[0][4], '100' if source == 'binance' else '105')
            self.assertEqual(report['level'], 'ok')
            self.assertEqual(report['fallback_count'], 0)

    def test_bidirectional_fallback_and_recovery_keep_the_preference(self):
        for source in feed.OHLCV_SOURCES:
            secondary = 'toobit' if source == 'binance' else 'binance'
            rows, report = self.fetch(source, {source: requests.Timeout('offline'), secondary: self.rows()})
            self.assertEqual(len(rows), 3)
            self.assertEqual(report['requested_source'], source)
            self.assertEqual(report['actual_sources'], [secondary])
            self.assertEqual(report['fallback_count'], 3)
            self.assertEqual(report['level'], 'warning')
            _, recovered = self.fetch(source, {source: self.rows(), secondary: self.rows()})
            self.assertEqual(recovered['actual_sources'], [source])
            self.assertEqual(recovered['level'], 'ok')

    def test_only_missing_candles_are_filled_by_timestamp(self):
        primary = self.rows('105')
        primary.pop(1)
        rows, report = self.fetch('toobit', {'toobit': primary, 'binance': self.rows()})
        self.assertEqual([row[4] for row in rows], ['105', '100', '105'])
        self.assertEqual(report['fallback_count'], 1)

    def test_stale_primary_and_malformed_primary_use_the_backup(self):
        for value in (self.rows()[:-1], [[0, 'nan', '110', '90', '100', '5', 899999]]):
            rows, report = self.fetch('binance', {'binance': value, 'toobit': self.rows('105')})
            self.assertEqual(rows[-1][4], '105')
            self.assertEqual(report['level'], 'warning')

    def test_unavailable_both_or_a_shared_gap_rejects_the_whole_cycle(self):
        for payloads in ({key: requests.Timeout('offline') for key in feed.OHLCV_SOURCES},
                         {key: self.rows()[::2] for key in feed.OHLCV_SOURCES}):
            with self.assertRaises(feed.CandleUnavailable) as failure:
                self.fetch('binance', payloads)
            self.assertEqual(failure.exception.report['level'], 'error')

    def test_backup_outage_does_not_block_healthy_primary(self):
        rows, report = self.fetch('binance', {'binance': self.rows(), 'toobit': requests.Timeout('offline')})
        self.assertEqual(len(rows), 3)
        self.assertEqual(report['fallback_count'], 0)
        self.assertEqual(report['level'], 'warning')


class ReportLoggingTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.logger = logging.Logger('ohlcv-test', level=logging.INFO)
        handler = logging.StreamHandler(self.output)
        handler.setFormatter(logging.Formatter('%(levelname)s | %(message)s'))
        self.logger.addHandler(handler)

    def report(self, *, primary=True, backup=True):
        return dict(level='error' if not primary and not backup else ('ok' if primary and backup else 'warning'),
            requested_source='binance', expected_candles=201,
            actual_sources=['binance'] if primary else (['toobit'] if backup else []),
            fallback_count=201 if not primary and backup else 0,
            missing_count=201 if not primary and not backup else 0,
            providers={'binance': dict(available=primary, candles=201 if primary else 0, error='' if primary else 'HTTPError: 451 Client Error'),
                       'toobit': dict(available=backup, candles=201 if backup else 0, error='' if backup else 'Timeout: Toobit unavailable')})

    def test_primary_error_and_working_backup_are_logged_with_details(self):
        feed.log_ohlcv_report(self.report(primary=False), self.logger, context='bot')
        output = self.output.getvalue()
        self.assertIn('WARNING | OHLCV PROVIDER ERROR | context=bot | provider=binance | candles=0/201 | error=HTTPError: 451', output)
        self.assertIn('provider=toobit | candles=201/201', output)
        self.assertIn('preferred=binance | sources=toobit | candles=201 | fallback=201 | action=continue', output)

    def test_backup_error_is_logged_even_when_binance_is_healthy(self):
        feed.log_ohlcv_report(self.report(backup=False), self.logger)
        output = self.output.getvalue()
        self.assertIn('provider=toobit | candles=0/201 | error=Timeout: Toobit unavailable', output)
        self.assertIn('preferred=binance | sources=binance', output)

    def test_both_outages_log_each_error_and_skip_without_ready(self):
        feed.log_ohlcv_report(self.report(primary=False, backup=False), self.logger)
        output = self.output.getvalue()
        self.assertEqual(output.count('ERROR | OHLCV PROVIDER ERROR'), 2)
        self.assertIn('OHLCV UNAVAILABLE', output)
        self.assertIn('sources=none | missing=201 | action=skip_cycle', output)
        self.assertNotIn('OHLCV READY', output)

    def test_provider_recovery_and_return_to_binance_are_logged(self):
        feed.log_ohlcv_report(self.report(primary=False), self.logger, context='bot')
        self.output.truncate(0)
        self.output.seek(0)
        feed.log_ohlcv_report(self.report(), self.logger, context='bot')
        output = self.output.getvalue()
        self.assertIn('OHLCV PROVIDER RECOVERED | context=bot | provider=binance', output)
        self.assertIn('preferred=binance | sources=binance | candles=201 | fallback=0', output)


if __name__ == '__main__':
    unittest.main()
