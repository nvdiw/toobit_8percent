import ast
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parent.parent / 'magnal'
spec = importlib.util.spec_from_file_location('magnal_database_for_test', ROOT / 'database.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MagnalExternalCloseTests(unittest.TestCase):
    def test_actual_strategy_sync_block_closes_only_selected_account_and_clears_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            db = module.Database(str(Path(temp) / 'db.sqlite3'))
            try:
                for account in ('web_9', 'web_10'):
                    db.insert_open_order('BTCUSDT', 'short', 80000., '2026-09-11T00:00:00+00:00',
                                         .01, 80., 10, account_id=account,
                                         balance=920., balance_without_fee=920.,
                                         balance_before_trade=1000., balance_before_trade_no_fee=1000.,
                                         position_size_no_fee=.01, margin_no_fee=80.,
                                         current_position='short', client_order_id=f'BOT_{account.upper()}_TEST')
                tree = ast.parse((ROOT / 'ma_strategy.py').read_text(encoding='utf-8-sig'))
                fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'ma_strategy')
                block = next(n for n in ast.walk(fn) if isinstance(n, ast.Try) and
                             any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == 'get_open_position'
                                 for c in ast.walk(n)))
                # Execute the actual production sync block with isolated DB and
                # mocked exchange; no strategy import or live API calls.
                code = 'def check():\n' + '\n'.join('    '+line for line in ast.unparse(block).splitlines())
                env = dict(db=db, order_id=1, current_position='short', open_order={'side':'short'},
                           toobit_client=Mock(), TOOBIT_SYMBOL='BTC-SWAP-USDT', account_id='web_9',
                           first_balance=1000., expected_bot_prefix='BOT_WEB_9_',
                           close_times=['2026-09-11T00:15:00+00:00'], close_prices=[80100.],
                           logger=Mock(), _persist_state=Mock())
                # Assignments in the extracted block use globals in this harness.
                names = 'current_position,entry_price,position_size,position_size_no_fee,open_time_value,entry_index,margin,margin_no_fee,balance,balance_without_fee,bot_quantity'
                code = code.replace('def check():', 'def check():\n    global '+names)
                env['toobit_client'].get_open_position.return_value = None
                exec(code, env)
                env['check']()
                self.assertEqual(db.cursor.execute('SELECT status FROM orders WHERE id=1').fetchone()[0], 'closed')
                self.assertEqual(db.cursor.execute('SELECT status FROM orders WHERE id=2').fetchone()[0], 'open')
                self.assertIsNone(env['current_position'])
                self.assertEqual(env['margin'], 0)
                self.assertAlmostEqual(env['balance'], 998.1995)
                self.assertFalse(db.mark_order_closed_externally(1, '2026-09-11T00:30:00+00:00', 90000.))
                env['toobit_client'].close_position.assert_not_called()
            finally:
                db.close()
