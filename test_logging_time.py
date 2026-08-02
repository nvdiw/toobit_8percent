import logging
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from logging_utils import (
    DailyDirectoryFileHandler,
    RecordCategoryFilter,
    UTCFormatter,
    format_utc_timestamp,
)


class LoggingTimeTests(unittest.TestCase):
    def test_formatter_uses_explicit_utc(self):
        record = logging.LogRecord("bot", logging.INFO, __file__, 1, "ok", (), None)
        record.created = 1785717000.123

        rendered = UTCFormatter("%(asctime)s | %(message)s").format(record)

        self.assertEqual(rendered, "2026-08-03T00:30:00.123Z | ok")

    def test_normalizes_tehran_offset_to_utc(self):
        self.assertEqual(
            format_utc_timestamp("2026-08-02T22:15:00+03:30"),
            "2026-08-02T18:45:00.000Z",
        )

    def test_naive_market_time_is_treated_as_utc(self):
        self.assertEqual(
            format_utc_timestamp("2026-08-02 18:45:00"),
            "2026-08-02T18:45:00.000Z",
        )

    def test_daily_handler_separates_year_month_and_day(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            handler = DailyDirectoryFileHandler(base_dir=temp_dir)
            handler.setFormatter(UTCFormatter("%(asctime)s | %(message)s"))

            first = logging.LogRecord("bot", logging.INFO, __file__, 1, "last", (), None)
            first.created = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc).timestamp()
            handler.emit(first)

            second = logging.LogRecord("bot", logging.INFO, __file__, 1, "first", (), None)
            second.created = datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp()
            handler.emit(second)

            old_day = Path(temp_dir) / "2026" / "12" / "31" / "trade.log"
            new_day = Path(temp_dir) / "2027" / "01" / "01" / "trade.log"
            self.assertIn("2026-12-31T23:59:00.000Z | last", old_day.read_text("utf-8"))
            self.assertIn("2027-01-01T00:00:00.000Z | first", new_day.read_text("utf-8"))

    def test_specialized_logs_are_also_written_to_all_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = logging.getLogger(f"test-log-routing-{id(self)}")
            logger.handlers.clear()
            logger.setLevel(logging.INFO)
            logger.propagate = False
            formatter = UTCFormatter("%(levelname)s | %(message)s")

            def add_handler(filename, level=None, category=None):
                handler = DailyDirectoryFileHandler(temp_dir, filename)
                handler.setFormatter(formatter)
                if level is not None:
                    handler.setLevel(level)
                if category is not None:
                    handler.addFilter(RecordCategoryFilter(category))
                logger.addHandler(handler)

            add_handler("all.log")
            add_handler("errors.log", level=logging.ERROR)
            add_handler("trades.log", category="trade")
            add_handler("checks.log", category="check")

            logger.info("cycle", extra={"category": "check"})
            logger.info("opened", extra={"category": "trade"})
            logger.error("failed")

            today = datetime.now(timezone.utc)
            daily_dir = Path(temp_dir) / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
            self.assertIn("cycle", (daily_dir / "checks.log").read_text("utf-8"))
            self.assertIn("opened", (daily_dir / "trades.log").read_text("utf-8"))
            self.assertIn("failed", (daily_dir / "errors.log").read_text("utf-8"))

            all_text = (daily_dir / "all.log").read_text("utf-8")
            self.assertIn("cycle", all_text)
            self.assertIn("opened", all_text)
            self.assertIn("failed", all_text)
            self.assertNotIn("opened", (daily_dir / "checks.log").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
