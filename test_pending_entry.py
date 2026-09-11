import sqlite3
import tempfile
import unittest
from pathlib import Path

import pending_entry


class PendingEntryTests(unittest.TestCase):
    def test_explicit_rejection_survives_restart_until_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'test.db'
            conn = sqlite3.connect(path)
            pending_entry.remember(conn, 'short', 'cross-1', 'HTTP 400 -1021')
            conn.close()
            conn = sqlite3.connect(path)
            self.assertEqual(pending_entry.eligible_side(conn, 'cross-1', None), 'short')
            pending_entry.clear(conn)
            self.assertIsNone(pending_entry.eligible_side(conn, 'cross-1', None))
            conn.close()

    def test_new_cross_cancels_stale_entry(self):
        conn = sqlite3.connect(':memory:')
        pending_entry.remember(conn, 'long', 'cross-1', '-1021')
        self.assertIsNone(pending_entry.eligible_side(conn, 'cross-2', None))
        self.assertIsNone(pending_entry.eligible_side(conn, 'cross-1', None))
        conn.close()

    def test_existing_position_clears_pending_entry(self):
        conn = sqlite3.connect(':memory:')
        pending_entry.remember(conn, 'long', 'cross-1', '-1021')
        self.assertIsNone(pending_entry.eligible_side(conn, 'cross-1', 'long'))
        conn.close()

    def test_ambiguous_timeout_does_not_queue_new_order(self):
        conn = sqlite3.connect(':memory:')
        pending_entry.remember(conn, 'long', 'cross-1', 'Read timeout')
        self.assertIsNone(pending_entry.eligible_side(conn, 'cross-1', None))
        conn.close()
