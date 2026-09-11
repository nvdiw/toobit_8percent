from unittest.mock import patch
from test_strategy_ledger_integration import StrategyLedgerIntegrationTests
import pending_entry


class PendingStrategyTests(StrategyLedgerIntegrationTests):
    def test_rejected_entry_retries_after_restart_without_second_manual_action(self):
        state = self.bot.BotState()
        self.client.place_order.side_effect = RuntimeError('HTTP 400 -1021')
        self.cycle(state, 'open_short', 80341.82, '2026-09-07T00:00:00+00:00')
        db = self.connections[-1]
        self.assertIsNone(db.get_open_order())
        self.assertEqual(pending_entry.eligible_side(db.conn, None, None), 'short')
        self.client.place_order.side_effect = None
        state = self.bot.BotState()
        self.cycle(state, None, 80341.82, '2026-09-07T00:15:00+00:00')
        db = self.connections[-1]
        self.assertEqual(db.get_open_order()['side'], 'short')
        self.assertIsNone(pending_entry.eligible_side(db.conn, None, None))
        self.assertEqual(self.client.place_order.call_count, 2)

    def test_accepted_order_with_failed_fill_query_does_not_queue_new_entry(self):
        self.client.resolve_executed_quantity.side_effect = RuntimeError('HTTP 400 -1021')
        state = self.bot.BotState()
        self.cycle(state, 'open_short', 80341.82, '2026-09-07T00:00:00+00:00')
        db = self.connections[-1]
        self.assertIsNone(pending_entry.eligible_side(db.conn, None, None))
        self.client.place_order.assert_called_once()

    def test_existing_queue_is_cleared_on_unknown_submission_outcome(self):
        db = self.database()
        pending_entry.remember(db.conn, 'short', None, '-1021')
        self.client.place_order.side_effect = RuntimeError('Read timeout')
        self.cycle(self.bot.BotState(), None, 80341.82, '2026-09-07T00:00:00+00:00')
        self.assertFalse(pending_entry.has_pending(self.connections[-1].conn))
        self.client.place_order.assert_called_once()

    def test_wrapper_retries_immediately_then_in_two_seconds(self):
        state = self.bot.BotState()
        calls = []
        def strategy(current, manual_action=None):
            calls.append(manual_action)
            db = self.database()
            if len(calls) < 3:
                pending_entry.remember(db.conn, 'short', None, '-1021')
            else:
                pending_entry.clear(db.conn)
        with patch.object(self.bot, 'Database', side_effect=self.database), \
             patch.object(self.bot, 'ma_strategy', side_effect=strategy), \
             patch.object(self.bot.time, 'sleep') as sleep:
            self.bot.run_strategy_with_immediate_retries(state, 'open_short')
        self.assertEqual(calls, ['open_short', None, None])
        sleep.assert_called_once_with(2)
