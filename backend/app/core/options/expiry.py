"""
NSE expiry date calculator — exact dates with holiday awareness.

Weekly expiry: every Thursday (index options — NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY)
Monthly expiry: last Thursday of the month (stock options + index monthly)
If Thursday is a NSE holiday, expiry moves to the previous trading day.
"""
from datetime import date, timedelta
from functools import lru_cache


# NSE trading holidays 2025-2026 (gazetted + exchange-declared)
NSE_HOLIDAYS_2025_2026: frozenset[date] = frozenset([
    # 2025
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-ul-Fitr
    date(2025, 4, 10),   # Good Friday
    date(2025, 4, 14),   # Dr. Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday (state)
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Gandhi Jayanti
    date(2025, 10, 24),  # Dussehra
    date(2025, 11, 5),   # Diwali Laxmi Puja
    date(2025, 12, 25),  # Christmas
    # 2026
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 20),   # Holi
    date(2026, 3, 26),   # Id-ul-Fitr (tentative)
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 8, 15),   # Independence Day
    date(2026, 8, 27),   # Ganesh Chaturthi (tentative)
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 11, 19),  # Gurunanak Jayanti (tentative)
    date(2026, 12, 25),  # Christmas
])


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in NSE_HOLIDAYS_2025_2026


def prev_trading_day(d: date) -> date:
    """Walk back to the nearest trading day."""
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def _last_thursday_of_month(year: int, month: int) -> date:
    """Last calendar Thursday of a given month."""
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last_day.weekday() - 3) % 7   # 3 = Thursday
    return last_day - timedelta(days=offset)


@lru_cache(maxsize=512)
def monthly_expiry(year: int, month: int) -> date:
    """Last Thursday of the month, adjusted back for holidays."""
    thursday = _last_thursday_of_month(year, month)
    return prev_trading_day(thursday)


@lru_cache(maxsize=512)
def weekly_expiry(ref: date) -> date:
    """Next weekly expiry Thursday on or after ref."""
    days_ahead = (3 - ref.weekday()) % 7   # 3 = Thursday
    if days_ahead == 0 and not is_trading_day(ref):
        days_ahead = 7
    thursday = ref + timedelta(days=days_ahead)
    return prev_trading_day(thursday)


def next_weekly_expiries(from_date: date, count: int = 4) -> list[date]:
    """Return the next `count` weekly expiry dates."""
    results: list[date] = []
    d = from_date
    while len(results) < count:
        exp = weekly_expiry(d)
        if exp not in results and exp >= from_date:
            results.append(exp)
        d = exp + timedelta(days=1)
    return sorted(set(results))


def next_monthly_expiries(from_date: date, count: int = 3) -> list[date]:
    """Return the next `count` monthly expiry dates."""
    results: list[date] = []
    year, month = from_date.year, from_date.month
    while len(results) < count:
        exp = monthly_expiry(year, month)
        if exp >= from_date:
            results.append(exp)
        month += 1
        if month > 12:
            month = 1
            year += 1
    return sorted(results)


def expiry_details(exp: date, from_date: date, series: str) -> dict:
    dte = (exp - from_date).days
    return {
        "date":       exp.isoformat(),              # "2026-07-03"
        "display":    exp.strftime("%d %b %Y (%a)"), # "03 Jul 2026 (Thu)"
        "short":      exp.strftime("%d%b%y").upper(),# "03JUL26"
        "nse_symbol": exp.strftime("%d%b%y").upper(),
        "dte":        dte,
        "series":     series,                        # "weekly" | "monthly"
        "dte_label":  f"{dte}d to expiry",
    }


def available_expiries(underlying: str, from_date: date | None = None) -> list[dict]:
    """
    Return all available expiry series for an underlying, sorted by date.
    Weekly-expiry underlyings (indices) get weekly + monthly options.
    Monthly-expiry underlyings (stocks) get monthly only.
    """
    from app.core.instruments import INSTRUMENT_MAP
    from_date = from_date or date.today()

    inst = INSTRUMENT_MAP.get(underlying.upper())
    is_weekly = inst is not None and inst.get("expiry_type") == "weekly"

    results: list[dict] = []

    if is_weekly:
        for exp in next_weekly_expiries(from_date, count=4):
            results.append(expiry_details(exp, from_date, "weekly"))

    for exp in next_monthly_expiries(from_date, count=3):
        # Avoid duplicate if monthly falls on same date as a weekly
        if not any(r["date"] == exp.isoformat() for r in results):
            results.append(expiry_details(exp, from_date, "monthly"))

    return sorted(results, key=lambda x: x["date"])


def select_expiry(underlying: str, dte_preference: int, from_date: date | None = None) -> dict:
    """
    Pick the closest expiry with at least dte_preference days remaining.
    Falls back to the nearest available if none qualify.
    """
    from_date = from_date or date.today()
    expiries = available_expiries(underlying, from_date)
    for exp in expiries:
        if exp["dte"] >= max(1, dte_preference):
            return exp
    return expiries[-1] if expiries else expiry_details(
        prev_trading_day(from_date + timedelta(days=dte_preference)),
        from_date, "monthly"
    )
