"""NSE event calendar — flags high-risk event windows."""
from datetime import date, timedelta
from typing import List


def _build_events_for_year(year: int) -> List[dict]:
    """Build a list of major market events for the given year."""
    from app.core.options.expiry import monthly_expiry
    events = []

    # Monthly expiry for NIFTY (last Tuesday since Sep 2025) — the primary index
    for m in range(1, 13):
        events.append({
            "name": "NSE Monthly Expiry",
            "date": monthly_expiry(year, m, "NIFTY"),
            "type": "expiry",
        })

    # RBI MPC: first week of Feb, Apr, Jun, Aug, Oct, Dec (alternate months)
    for m in [2, 4, 6, 8, 10, 12]:
        # Approximate: first Wednesday of the month
        first_day = date(year, m, 1)
        days_to_wed = (2 - first_day.weekday()) % 7  # Wednesday = 2
        mpc_date = first_day + timedelta(days=days_to_wed + 3)  # ~day 4-10
        events.append({
            "name": "RBI MPC Decision",
            "date": mpc_date,
            "type": "central_bank",
        })

    # FOMC: 8 times/year — approximate last Wednesday of Jan,Mar,May,Jun,Jul,Sep,Nov,Dec
    fomc_months = [1, 3, 5, 6, 7, 9, 11, 12]
    for m in fomc_months:
        if m == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, m + 1, 1) - timedelta(days=1)
        offset = (last_day.weekday() - 2) % 7  # Wednesday
        fomc_date = last_day - timedelta(days=offset)
        events.append({
            "name": "FOMC Meeting",
            "date": fomc_date,
            "type": "fomc",
        })

    return sorted(events, key=lambda e: e["date"])


class EventCalendar:
    """NSE and global event calendar."""

    def _all_events(self, from_date: date) -> List[dict]:
        """Get events for current and next year."""
        events = _build_events_for_year(from_date.year)
        events += _build_events_for_year(from_date.year + 1)
        return sorted(events, key=lambda e: e["date"])

    def days_to_next_event(self, today: date) -> int:
        """Return number of days to the next upcoming event."""
        events = self._all_events(today)
        for ev in events:
            if ev["date"] >= today:
                return (ev["date"] - today).days
        return 999

    def is_event_risk(self, today: date, dte: int = 2) -> bool:
        """Return True if within `dte` days of any UPCOMING (future) event.
        Only looks forward — past events do not trigger the block."""
        events = self._all_events(today)
        for ev in events:
            days_ahead = (ev["date"] - today).days
            if 0 <= days_ahead <= dte:
                return True
        return False

    def next_events(self, today: date, count: int = 3) -> List[dict]:
        """Return the next `count` upcoming events."""
        events = self._all_events(today)
        upcoming = [
            {"name": ev["name"], "date": ev["date"].isoformat(), "type": ev["type"]}
            for ev in events
            if ev["date"] >= today
        ]
        return upcoming[:count]
