"""Shared local calendar for planning prompts and real scenario defaults."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

TIMEZONE = 'Europe/Warsaw'


def planning_date(instant: datetime | None = None) -> date:
    reference = instant if instant is not None else datetime.now(UTC)
    return reference.astimezone(ZoneInfo(TIMEZONE)).date()
