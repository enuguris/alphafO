"""
NSE/BSE expiry date calculator — exact dates with holiday awareness.

Effective September 1, 2025 (SEBI circular):
  NSE instruments all expire on TUESDAY (weekly + monthly)
    NIFTY 50    → Tuesday (weekly)
    FINNIFTY    → Tuesday (weekly)
    MIDCPNIFTY  → Tuesday (weekly)
    BANKNIFTY   → Tuesday (monthly/quarterly only — weekly discontinued Nov 2024)

  BSE instruments all expire on THURSDAY (weekly + monthly)
    SENSEX      → Thursday (weekly)
    BANKEX      → Thursday (monthly only — weekly discontinued)

Monthly expiry = last Tuesday of the month (NSE) / last Thursday (BSE).
If expiry day is a market holiday, expiry shifts to the previous trading day.
"""
from datetime import date, timedelta
from functools import lru_cache


# Per-instrument weekly expiry weekday (0=Mon … 4=Fri)
# Effective Sep 1, 2025: NSE moved from Thursday to Tuesday; BSE moved to Thursday
WEEKLY_EXPIRY_WEEKDAY: dict[str, int] = {
    "NIFTY":      1,   # Tuesday  (NSE — changed Sep 2025)
    "NIFTY 50":   1,
    "BANKNIFTY":  1,   # Tuesday  (monthly only, no weekly since Nov 2024)
    "BANK NIFTY": 1,
    "FINNIFTY":   1,   # Tuesday  (NSE)
    "FIN NIFTY":  1,
    "MIDCPNIFTY": 1,   # Tuesday  (NSE)
    "SENSEX":     3,   # Thursday (BSE — changed Sep 2025)
    "BANKEX":     3,   # Thursday (BSE)
}
DEFAULT_WEEKLY_EXPIRY_WEEKDAY = 1  # Tuesday (NSE default)

# Instruments that no longer have weekly options (monthly/quarterly only)
NO_WEEKLY_OPTIONS: frozenset[str] = frozenset(["BANKNIFTY", "BANK NIFTY", "BANKEX"])


# NSE trading holidays 2025-2026
NSE_HOLIDAYS_2025_2026: frozenset[date] = frozenset([
    # 2025
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-ul-Fitr
    date(2025, 4, 10),   # Good Friday
    date(2025, 4, 14),   # Dr. Ambedkar Jayanti
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


def _expiry_weekday(underlying: str) -> int:
    """Return the weekday (0=Mon…4=Fri) on which this underlying expires weekly."""
    return WEEKLY_EXPIRY_WEEKDAY.get(underlying.upper().strip(), DEFAULT_WEEKLY_EXPIRY_WEEKDAY)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in NSE_HOLIDAYS_2025_2026


def prev_trading_day(d: date) -> date:
    """Walk back to the nearest trading day (used when expiry falls on a holiday)."""
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Last calendar occurrence of `weekday` (0=Mon…6=Sun) in the given month."""
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


@lru_cache(maxsize=1024)
def monthly_expiry(year: int, month: int, underlying: str = "NIFTY") -> date:
    """
    Last expiry-weekday of the month for this underlying, holiday-adjusted.
    Effective Sep 1, 2025:
      NSE (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY) → last Tuesday of month
      BSE (SENSEX, BANKEX) → last Thursday of month
    """
    bse = underlying.upper().strip() in ("SENSEX", "BANKEX")
    monthly_weekday = 3 if bse else 1   # Thursday for BSE, Tuesday for NSE
    target = _last_weekday_of_month(year, month, monthly_weekday)
    return prev_trading_day(target)


@lru_cache(maxsize=1024)
def weekly_expiry(ref: date, underlying: str = "NIFTY") -> date:
    """Next weekly expiry for this underlying on or after ref."""
    wd = _expiry_weekday(underlying)
    days_ahead = (wd - ref.weekday()) % 7
    # If today IS the expiry weekday but not a trading day, go to next cycle
    if days_ahead == 0 and not is_trading_day(ref):
        days_ahead = 7
    target = ref + timedelta(days=days_ahead)
    return prev_trading_day(target)


def next_weekly_expiries(from_date: date, count: int = 4, underlying: str = "NIFTY") -> list[date]:
    """Return the next `count` weekly expiry dates for this underlying."""
    results: list[date] = []
    d = from_date
    while len(results) < count:
        exp = weekly_expiry(d, underlying)
        if exp not in results and exp >= from_date:
            results.append(exp)
        d = exp + timedelta(days=1)
    return sorted(set(results))


def next_monthly_expiries(from_date: date, count: int = 3, underlying: str = "NIFTY") -> list[date]:
    """Return the next `count` monthly expiry dates for this underlying."""
    results: list[date] = []
    year, month = from_date.year, from_date.month
    while len(results) < count:
        exp = monthly_expiry(year, month, underlying)
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
        "date":       exp.isoformat(),
        "display":    exp.strftime("%d %b %Y (%a)"),
        "short":      exp.strftime("%d%b%y").upper(),
        "nse_symbol": exp.strftime("%d%b%y").upper(),
        "dte":        dte,
        "series":     series,
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

    if is_weekly and underlying.upper().strip() not in NO_WEEKLY_OPTIONS:
        for exp in next_weekly_expiries(from_date, count=8, underlying=underlying):
            results.append(expiry_details(exp, from_date, "weekly"))

    for exp in next_monthly_expiries(from_date, count=2, underlying=underlying):
        if not any(r["date"] == exp.isoformat() for r in results):
            results.append(expiry_details(exp, from_date, "monthly"))

    return sorted(results, key=lambda x: x["date"])


def select_expiry(underlying: str, dte_preference: int, from_date: date | None = None) -> dict:
    """Pick the closest expiry with at least dte_preference days remaining."""
    from_date = from_date or date.today()
    expiries = available_expiries(underlying, from_date)
    for exp in expiries:
        if exp["dte"] >= max(1, dte_preference):
            return exp
    return expiries[-1] if expiries else expiry_details(
        prev_trading_day(from_date + timedelta(days=dte_preference)),
        from_date, "monthly"
    )
