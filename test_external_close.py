from test_strategy_ledger_integration import StrategyLedgerIntegrationTests


class ExternalCloseTests(StrategyLedgerIntegrationTests):
    def test_external_close_settles_once_and_can_open_again_without_restart(self):
        state = self.bot.BotState()
        for side in ('long', 'short'):
            self.cycle(state, 'open_' + side, 80000., '2026-09-11T00:00:00+00:00')
            order_id = self.connections[-1].get_open_order()['id']
            self.client.get_open_position.return_value = None
            self.cycle(state, None, 80100., '2026-09-11T00:15:00+00:00')
            db = self.connections[-1]
            self.assertIsNone(db.get_open_order())
            self.assertIsNone(state.current_position)
            self.assertEqual(state.margin, 0)
            self.assertEqual(state.balance, db.get_current_balances()[0])
            self.client.close_position.assert_not_called()
            balances = db.get_current_balances()
            self.assertFalse(db.mark_order_closed_externally(order_id, '2026-09-11T00:30:00+00:00', 90000.))
            self.assertEqual(balances, db.get_current_balances())
            self.assertEqual(db.conn.execute('SELECT close_price_source FROM order_accounting WHERE order_id=?', (order_id,)).fetchone()[0], 'last_candle_estimate')

    def test_remote_query_error_does_not_close_or_send_an_order(self):
        state = self.bot.BotState()
        self.cycle(state, 'open_short', 80000., '2026-09-11T00:00:00+00:00')
        self.client.get_open_position.side_effect = RuntimeError('network unavailable')
        self.cycle(state, 'close_short', 80100., '2026-09-11T00:15:00+00:00')
        self.assertIsNotNone(self.connections[-1].get_open_order())
        self.client.close_position.assert_not_called()

    def test_database_repair_clears_old_in_memory_position(self):
        state = self.bot.BotState()
        self.cycle(state, 'open_short', 80000., '2026-09-11T00:00:00+00:00')
        db = self.connections[-1]
        db.mark_order_closed_externally(db.get_open_order()['id'], '2026-09-11T00:15:00+00:00', 80100.)
        self.assertEqual(state.current_position, 'short')
        self.cycle(state, None, 80100., '2026-09-11T00:30:00+00:00')
        self.assertIsNone(state.current_position)
        self.assertEqual(state.margin, 0)
        self.client.close_position.assert_not_called()

    def test_remaining_remote_position_is_not_marked_closed(self):
        state = self.bot.BotState()
        self.cycle(state, 'open_short', 80000., '2026-09-11T00:00:00+00:00')
        self.client.get_open_position.return_value = {'side': 'SHORT', 'position': 1}
        self.cycle(state, None, 80000., '2026-09-11T00:15:00+00:00')
        self.assertIsNotNone(self.connections[-1].get_open_order())
