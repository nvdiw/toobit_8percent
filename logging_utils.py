import logging
from datetime import datetime, timezone
from pathlib import Path


class UTCFormatter(logging.Formatter):
    """Render log creation times as unambiguous ISO-8601 UTC timestamps."""

    def formatTime(self, record, datefmt=None):
        created_at = datetime.fromtimestamp(record.created, tz=timezone.utc)
        if datefmt:
            return created_at.strftime(datefmt)
        return created_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def format_utc_timestamp(value):
    """Normalize a datetime-like value to ISO-8601 UTC for log messages."""

    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)

    # Market candle timestamps without an offset are treated as UTC.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)

    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class DailyDirectoryFileHandler(logging.Handler):
    """Write each UTC day's records to logs/YYYY/MM/DD/<filename>."""

    terminator = "\n"

    def __init__(self, base_dir="logs", filename="trade.log", encoding="utf-8"):
        super().__init__()
        self.base_dir = Path(base_dir)
        self.filename = filename
        self.encoding = encoding

    def path_for_record(self, record):
        created_at = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return (
            self.base_dir
            / f"{created_at.year:04d}"
            / f"{created_at.month:02d}"
            / f"{created_at.day:02d}"
            / self.filename
        )

    def emit(self, record):
        try:
            log_path = self.path_for_record(record)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            message = self.format(record)
            with log_path.open("a", encoding=self.encoding) as stream:
                stream.write(message + self.terminator)
        except Exception:
            self.handleError(record)


class RecordCategoryFilter(logging.Filter):
    """Allow only records explicitly assigned to one category."""

    def __init__(self, category):
        super().__init__()
        self.category = category

    def filter(self, record):
        return getattr(record, "category", None) == self.category
