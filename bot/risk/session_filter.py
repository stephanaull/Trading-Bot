"""Market session filter — NYSE regular trading hours.

Blocks trades outside regular market hours:
- NYSE: 9:30 AM - 4:00 PM Eastern Time (ET)
- Handles US holidays (major ones hardcoded)
- Handles half-days (1:00 PM close)

The strategies also have their own session filters (e.g., 14:35-19:45 UTC),
but this provides an engine-level safety net.
"""

import logging
from datetime import datetime, date, time
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Eastern timezone
ET = ZoneInfo("America/New_York")

# NYSE regular hours
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

# Early close days (1:00 PM ET)
EARLY_CLOSE = time(13, 0)

# US market holidays 2026 (NYSE closed)
# Source: NYSE holiday calendar
HOLIDAYS_2026 = {
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
}

# Early close days 2026 (1:00 PM ET)
EARLY_CLOSE_DAYS_2026 = {
    date(2026, 11, 27), # Day after Thanksgiving
    date(2026, 12, 24), # Christmas Eve
}


class SessionFilter:
    """Filter for NYSE regular trading hours."""

    def is_market_hours(self, now: datetime = None) -> bool:
        """Check if the current time is within NYSE regular trading hours.

        Args:
            now: Optional datetime (defaults to current time in ET)

        Returns:
            True if market is open for regular trading
        """
        if now is None:
            now = datetime.now(ET)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=ET)
        else:
            now = now.astimezone(ET)

        today = now.date()
        current_time = now.time()

        # Weekend
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        # Holiday
        if today in HOLIDAYS_2026:
            return False

        # Early close day
        close_time = EARLY_CLOSE if today in EARLY_CLOSE_DAYS_2026 else MARKET_CLOSE

        # Regular hours check
        return MARKET_OPEN <= current_time <= close_time

    def is_holiday(self, check_date: date = None) -> bool:
        """Check if a date is a market holiday."""
        if check_date is None:
            check_date = date.today()
        return check_date in HOLIDAYS_2026

    def is_early_close(self, check_date: date = None) -> bool:
        """Check if a date is an early close day."""
        if check_date is None:
            check_date = date.today()
        return check_date in EARLY_CLOSE_DAYS_2026

    def time_to_open(self, now: datetime = None) -> float:
        """Minutes until market opens. Returns 0 if already open."""
        if now is None:
            now = datetime.now(ET)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=ET)
        else:
            now = now.astimezone(ET)

        if self.is_market_hours(now):
            return 0.0

        # Calculate time to next open
        open_dt = datetime.combine(now.date(), MARKET_OPEN, tzinfo=ET)
        if now.time() > MARKET_CLOSE:
            # After close — next open is tomorrow (skip weekends/holidays)
            open_dt = self._next_trading_day_open(now.date())
        elif now.time() < MARKET_OPEN:
            # Before open today
            pass
        else:
            # Weekend or holiday
            open_dt = self._next_trading_day_open(now.date())

        diff = (open_dt - now).total_seconds() / 60
        return max(0, diff)

    def _next_trading_day_open(self, from_date: date) -> datetime:
        """Get the datetime of the next market open."""
        from datetime import timedelta
        d = from_date + timedelta(days=1)
        for _ in range(10):  # Max 10 days forward (handles long weekends)
            if d.weekday() < 5 and d not in HOLIDAYS_2026:
                return datetime.combine(d, MARKET_OPEN, tzinfo=ET)
            d += timedelta(days=1)
        # Fallback
        return datetime.combine(d, MARKET_OPEN, tzinfo=ET)
