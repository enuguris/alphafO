"""
NSE F&O instrument universe — all actively traded stocks + indices.

IMPORTANT: base_price values are APPROXIMATE reference prices used only for
synthetic data generation in testing mode. They are NOT live prices.
When Kite Connect is configured, real historical OHLCV replaces synthetic data.
Prices updated: June 2026.

LOT SIZE HISTORY (NSE revised lot sizes in 2024-2025 to target ≥₹15L contract value):
  NIFTY     : 25 → 75 (Apr 2024) → 65 (Oct 2024, confirmed user July 2026)
  BANKNIFTY : 25 → 15 (2022)     → 30 (2024 revision, estimated ~₹17.1L at ₹57k spot)
  FINNIFTY  : 40 → 65 (2024 revision, estimated at ₹24k spot)
  MIDCPNIFTY: 50 → 120 (2024 revision, estimated at ₹13.5k spot)
  SENSEX    : 10 → 20 (2024 revision BSE, estimated at ₹82k spot)
  ⚠ Run the `verify-lot-sizes` Celery task to cross-check against live Kite data.
  See: docs/NSE_MARKET_CONVENTIONS.md for full history.
"""
from typing import TypedDict


class Instrument(TypedDict):
    sym: str
    name: str
    sector: str
    lot_size: int
    base_price: float   # approximate NSE spot — for synthetic data only
    expiry_type: str    # weekly | monthly


INDICES: list[Instrument] = [
    # lot_size revised Oct 2024 (SEBI ≥₹15L contract value mandate)
    # NIFTY: 65 confirmed by user Jul 2026. BANKNIFTY: 30 estimated — verify via `verify-lot-sizes` task.
    {"sym": "NIFTY",      "name": "Nifty 50",        "sector": "Index",   "lot_size": 65,  "base_price": 24800,  "expiry_type": "weekly"},
    {"sym": "BANKNIFTY",  "name": "Bank Nifty",       "sector": "Index",   "lot_size": 30,  "base_price": 57000,  "expiry_type": "weekly"},
    {"sym": "FINNIFTY",   "name": "Fin Nifty",        "sector": "Index",   "lot_size": 65,  "base_price": 24100,  "expiry_type": "weekly"},
    {"sym": "MIDCPNIFTY", "name": "Midcap Nifty",     "sector": "Index",   "lot_size": 120, "base_price": 13500,  "expiry_type": "weekly"},
    {"sym": "SENSEX",     "name": "BSE Sensex",       "sector": "Index",   "lot_size": 20,  "base_price": 82000,  "expiry_type": "weekly"},
]

FNO_STOCKS: list[Instrument] = [
    # Banking
    {"sym": "HDFCBANK",    "name": "HDFC Bank",        "sector": "Banking", "lot_size": 550, "base_price": 1820,   "expiry_type": "monthly"},
    {"sym": "ICICIBANK",   "name": "ICICI Bank",       "sector": "Banking", "lot_size": 700, "base_price": 1450,   "expiry_type": "monthly"},
    {"sym": "AXISBANK",    "name": "Axis Bank",        "sector": "Banking", "lot_size": 625, "base_price": 1200,   "expiry_type": "monthly"},
    {"sym": "SBIN",        "name": "SBI",              "sector": "Banking", "lot_size": 1500,"base_price": 830,    "expiry_type": "monthly"},
    {"sym": "KOTAKBANK",   "name": "Kotak Bank",       "sector": "Banking", "lot_size": 400, "base_price": 2100,   "expiry_type": "monthly"},
    {"sym": "INDUSINDBK",  "name": "IndusInd Bank",    "sector": "Banking", "lot_size": 500, "base_price": 780,    "expiry_type": "monthly"},
    {"sym": "BANKBARODA",  "name": "Bank of Baroda",   "sector": "Banking", "lot_size": 3000,"base_price": 230,    "expiry_type": "monthly"},
    {"sym": "PNB",         "name": "Punjab Natl Bank", "sector": "Banking", "lot_size": 5000,"base_price": 100,    "expiry_type": "monthly"},
    {"sym": "CANBK",       "name": "Canara Bank",      "sector": "Banking", "lot_size": 3000,"base_price": 102,    "expiry_type": "monthly"},
    {"sym": "FEDERALBNK",  "name": "Federal Bank",     "sector": "Banking", "lot_size": 5000,"base_price": 185,    "expiry_type": "monthly"},
    {"sym": "IDFCFIRSTB",  "name": "IDFC First Bank",  "sector": "Banking", "lot_size": 5000,"base_price": 68,     "expiry_type": "monthly"},
    # Finance
    {"sym": "BAJFINANCE",  "name": "Bajaj Finance",    "sector": "Finance", "lot_size": 125, "base_price": 9200,   "expiry_type": "monthly"},
    {"sym": "BAJAJFINSV",  "name": "Bajaj Finserv",    "sector": "Finance", "lot_size": 500, "base_price": 2150,   "expiry_type": "monthly"},
    {"sym": "CHOLAFIN",    "name": "Chola Finance",    "sector": "Finance", "lot_size": 500, "base_price": 1700,   "expiry_type": "monthly"},
    {"sym": "MUTHOOTFIN",  "name": "Muthoot Finance",  "sector": "Finance", "lot_size": 500, "base_price": 2400,   "expiry_type": "monthly"},
    {"sym": "LICHSGFIN",   "name": "LIC Housing Fin",  "sector": "Finance", "lot_size": 2000,"base_price": 620,    "expiry_type": "monthly"},
    {"sym": "SBICARD",     "name": "SBI Card",         "sector": "Finance", "lot_size": 2000,"base_price": 700,    "expiry_type": "monthly"},
    {"sym": "HDFCLIFE",    "name": "HDFC Life",        "sector": "Finance", "lot_size": 1100,"base_price": 730,    "expiry_type": "monthly"},
    {"sym": "SBILIFE",     "name": "SBI Life",         "sector": "Finance", "lot_size": 750, "base_price": 1700,   "expiry_type": "monthly"},
    {"sym": "ICICIGI",     "name": "ICICI Lombard",    "sector": "Finance", "lot_size": 200, "base_price": 2000,   "expiry_type": "monthly"},
    # IT
    {"sym": "TCS",         "name": "TCS",              "sector": "IT",      "lot_size": 175, "base_price": 3600,   "expiry_type": "monthly"},
    {"sym": "INFY",        "name": "Infosys",          "sector": "IT",      "lot_size": 400, "base_price": 1670,   "expiry_type": "monthly"},
    {"sym": "WIPRO",       "name": "Wipro",            "sector": "IT",      "lot_size": 1500,"base_price": 270,    "expiry_type": "monthly"},
    {"sym": "HCLTECH",     "name": "HCL Tech",         "sector": "IT",      "lot_size": 350, "base_price": 1680,   "expiry_type": "monthly"},
    {"sym": "TECHM",       "name": "Tech Mahindra",    "sector": "IT",      "lot_size": 600, "base_price": 1780,   "expiry_type": "monthly"},
    {"sym": "LTIM",        "name": "LTIMindtree",      "sector": "IT",      "lot_size": 150, "base_price": 5600,   "expiry_type": "monthly"},
    {"sym": "MPHASIS",     "name": "Mphasis",          "sector": "IT",      "lot_size": 300, "base_price": 3100,   "expiry_type": "monthly"},
    {"sym": "PERSISTENT",  "name": "Persistent Sys",   "sector": "IT",      "lot_size": 125, "base_price": 6500,   "expiry_type": "monthly"},
    {"sym": "COFORGE",     "name": "Coforge",          "sector": "IT",      "lot_size": 150, "base_price": 9200,   "expiry_type": "monthly"},
    # Energy & Oil
    {"sym": "RELIANCE",    "name": "Reliance",         "sector": "Energy",  "lot_size": 250, "base_price": 1310,   "expiry_type": "monthly"},
    {"sym": "ONGC",        "name": "ONGC",             "sector": "Energy",  "lot_size": 3750,"base_price": 240,    "expiry_type": "monthly"},
    {"sym": "NTPC",        "name": "NTPC",             "sector": "Energy",  "lot_size": 3000,"base_price": 330,    "expiry_type": "monthly"},
    {"sym": "POWERGRID",   "name": "Power Grid",       "sector": "Energy",  "lot_size": 3250,"base_price": 290,    "expiry_type": "monthly"},
    {"sym": "ADANIPOWER",  "name": "Adani Power",      "sector": "Energy",  "lot_size": 1250,"base_price": 570,    "expiry_type": "monthly"},
    {"sym": "ADANIGREEN",  "name": "Adani Green",      "sector": "Energy",  "lot_size": 400, "base_price": 1000,   "expiry_type": "monthly"},
    {"sym": "TATAPOWER",   "name": "Tata Power",       "sector": "Energy",  "lot_size": 3000,"base_price": 390,    "expiry_type": "monthly"},
    {"sym": "BPCL",        "name": "BPCL",             "sector": "Energy",  "lot_size": 1800,"base_price": 280,    "expiry_type": "monthly"},
    {"sym": "IOC",         "name": "IOC",              "sector": "Energy",  "lot_size": 5500,"base_price": 135,    "expiry_type": "monthly"},
    {"sym": "GAIL",        "name": "GAIL",             "sector": "Energy",  "lot_size": 4000,"base_price": 175,    "expiry_type": "monthly"},
    # Automobile
    {"sym": "TATAMOTORS",  "name": "Tata Motors",      "sector": "Auto",    "lot_size": 1425,"base_price": 432,    "expiry_type": "monthly"},
    {"sym": "MARUTI",      "name": "Maruti",           "sector": "Auto",    "lot_size": 100, "base_price": 12500,  "expiry_type": "monthly"},
    {"sym": "BAJAJ-AUTO",  "name": "Bajaj Auto",       "sector": "Auto",    "lot_size": 125, "base_price": 9000,   "expiry_type": "monthly"},
    {"sym": "HEROMOTOCO",  "name": "Hero MotoCorp",    "sector": "Auto",    "lot_size": 300, "base_price": 4400,   "expiry_type": "monthly"},
    {"sym": "EICHERMOT",   "name": "Eicher Motors",    "sector": "Auto",    "lot_size": 175, "base_price": 5200,   "expiry_type": "monthly"},
    {"sym": "TVSMOTOR",    "name": "TVS Motor",        "sector": "Auto",    "lot_size": 350, "base_price": 2600,   "expiry_type": "monthly"},
    {"sym": "M&M",         "name": "M&M",              "sector": "Auto",    "lot_size": 700, "base_price": 3150,   "expiry_type": "monthly"},
    {"sym": "ASHOKLEY",    "name": "Ashok Leyland",    "sector": "Auto",    "lot_size": 4000,"base_price": 220,    "expiry_type": "monthly"},
    # Pharma & Healthcare
    {"sym": "SUNPHARMA",   "name": "Sun Pharma",       "sector": "Pharma",  "lot_size": 700, "base_price": 1800,   "expiry_type": "monthly"},
    {"sym": "DRREDDY",     "name": "Dr Reddys",        "sector": "Pharma",  "lot_size": 125, "base_price": 6800,   "expiry_type": "monthly"},
    {"sym": "CIPLA",       "name": "Cipla",            "sector": "Pharma",  "lot_size": 650, "base_price": 1600,   "expiry_type": "monthly"},
    {"sym": "DIVISLAB",    "name": "Divi's Lab",       "sector": "Pharma",  "lot_size": 200, "base_price": 4800,   "expiry_type": "monthly"},
    {"sym": "APOLLOHOSP",  "name": "Apollo Hospitals", "sector": "Pharma",  "lot_size": 175, "base_price": 7500,   "expiry_type": "monthly"},
    {"sym": "AUROPHARMA",  "name": "Aurobindo Pharma", "sector": "Pharma",  "lot_size": 650, "base_price": 1350,   "expiry_type": "monthly"},
    {"sym": "LUPIN",       "name": "Lupin",            "sector": "Pharma",  "lot_size": 850, "base_price": 2300,   "expiry_type": "monthly"},
    {"sym": "BIOCON",      "name": "Biocon",           "sector": "Pharma",  "lot_size": 2900,"base_price": 350,    "expiry_type": "monthly"},
    # Metals & Mining
    {"sym": "TATASTEEL",   "name": "Tata Steel",       "sector": "Metals",  "lot_size": 5500,"base_price": 145,    "expiry_type": "monthly"},
    {"sym": "HINDALCO",    "name": "Hindalco",         "sector": "Metals",  "lot_size": 2150,"base_price": 680,    "expiry_type": "monthly"},
    {"sym": "JSWSTEEL",    "name": "JSW Steel",        "sector": "Metals",  "lot_size": 1350,"base_price": 980,    "expiry_type": "monthly"},
    {"sym": "SAIL",        "name": "SAIL",             "sector": "Metals",  "lot_size": 7500,"base_price": 115,    "expiry_type": "monthly"},
    {"sym": "NMDC",        "name": "NMDC",             "sector": "Metals",  "lot_size": 4500,"base_price": 215,    "expiry_type": "monthly"},
    {"sym": "VEDL",        "name": "Vedanta",          "sector": "Metals",  "lot_size": 2750,"base_price": 490,    "expiry_type": "monthly"},
    {"sym": "COALINDIA",   "name": "Coal India",       "sector": "Metals",  "lot_size": 4200,"base_price": 430,    "expiry_type": "monthly"},
    # FMCG
    {"sym": "HINDUNILVR",  "name": "Hindustan Unilever","sector": "FMCG",   "lot_size": 300, "base_price": 2350,   "expiry_type": "monthly"},
    {"sym": "ITC",         "name": "ITC",              "sector": "FMCG",    "lot_size": 3200,"base_price": 435,    "expiry_type": "monthly"},
    # NESTLEIND: 10:1 stock split Sep 2023 — price is now ~₹2,400 not ₹24,800
    {"sym": "NESTLEIND",   "name": "Nestle India",     "sector": "FMCG",    "lot_size": 50,  "base_price": 2400,   "expiry_type": "monthly"},
    {"sym": "BRITANNIA",   "name": "Britannia",        "sector": "FMCG",    "lot_size": 200, "base_price": 5500,   "expiry_type": "monthly"},
    {"sym": "DABUR",       "name": "Dabur",            "sector": "FMCG",    "lot_size": 2750,"base_price": 550,    "expiry_type": "monthly"},
    {"sym": "MARICO",      "name": "Marico",           "sector": "FMCG",    "lot_size": 1800,"base_price": 660,    "expiry_type": "monthly"},
    {"sym": "COLPAL",      "name": "Colgate-Palmolive","sector": "FMCG",    "lot_size": 1100,"base_price": 3100,   "expiry_type": "monthly"},
    # Cement & Infrastructure
    {"sym": "ULTRACEMCO",  "name": "UltraTech Cement", "sector": "Cement",  "lot_size": 100, "base_price": 11500,  "expiry_type": "monthly"},
    {"sym": "SHREECEM",    "name": "Shree Cement",     "sector": "Cement",  "lot_size": 25,  "base_price": 27000,  "expiry_type": "monthly"},
    {"sym": "ACC",         "name": "ACC",              "sector": "Cement",  "lot_size": 500, "base_price": 1900,   "expiry_type": "monthly"},
    {"sym": "AMBUJACEM",   "name": "Ambuja Cement",    "sector": "Cement",  "lot_size": 2000,"base_price": 590,    "expiry_type": "monthly"},
    {"sym": "LT",          "name": "L&T",              "sector": "Infra",   "lot_size": 175, "base_price": 3900,   "expiry_type": "monthly"},
    {"sym": "DLF",         "name": "DLF",              "sector": "Realty",  "lot_size": 1650,"base_price": 900,    "expiry_type": "monthly"},
    {"sym": "GODREJPROP",  "name": "Godrej Properties","sector": "Realty",  "lot_size": 325, "base_price": 2700,   "expiry_type": "monthly"},
    {"sym": "PRESTIGE",    "name": "Prestige Estates",  "sector": "Realty", "lot_size": 625, "base_price": 1900,   "expiry_type": "monthly"},
    # Telecom
    {"sym": "BHARTIARTL",  "name": "Bharti Airtel",    "sector": "Telecom", "lot_size": 475, "base_price": 1940,   "expiry_type": "monthly"},
    {"sym": "IDEA",        "name": "Vodafone Idea",    "sector": "Telecom", "lot_size": 70000,"base_price": 8,     "expiry_type": "monthly"},
    # Consumer Discretionary
    {"sym": "TITAN",       "name": "Titan",            "sector": "Consumer","lot_size": 375, "base_price": 3350,   "expiry_type": "monthly"},
    {"sym": "PIDILITIND",  "name": "Pidilite",         "sector": "Consumer","lot_size": 375, "base_price": 3200,   "expiry_type": "monthly"},
    {"sym": "HAVELLS",     "name": "Havells",          "sector": "Consumer","lot_size": 1000,"base_price": 1680,   "expiry_type": "monthly"},
    {"sym": "VOLTAS",      "name": "Voltas",           "sector": "Consumer","lot_size": 1500,"base_price": 1680,   "expiry_type": "monthly"},
    {"sym": "VGUARD",      "name": "V-Guard",          "sector": "Consumer","lot_size": 2500,"base_price": 440,    "expiry_type": "monthly"},
    # Diversified / Conglomerates
    {"sym": "ADANIENT",    "name": "Adani Enterprises","sector": "Diversified","lot_size": 250,"base_price": 2500, "expiry_type": "monthly"},
    {"sym": "ADANIPORTS",  "name": "Adani Ports",      "sector": "Diversified","lot_size": 625,"base_price": 1450, "expiry_type": "monthly"},
    {"sym": "TATACONSUM",  "name": "Tata Consumer",    "sector": "FMCG",    "lot_size": 900, "base_price": 1050,   "expiry_type": "monthly"},
    {"sym": "TATACHEM",    "name": "Tata Chemicals",   "sector": "Chemicals","lot_size": 875,"base_price": 980,    "expiry_type": "monthly"},
    # Aviation & Services
    {"sym": "INDIGO",      "name": "IndiGo",           "sector": "Aviation","lot_size": 300, "base_price": 4700,   "expiry_type": "monthly"},
    {"sym": "IRCTC",       "name": "IRCTC",            "sector": "Services","lot_size": 875, "base_price": 820,    "expiry_type": "monthly"},
    {"sym": "DMART",       "name": "DMart",            "sector": "Retail",  "lot_size": 275, "base_price": 4400,   "expiry_type": "monthly"},
    {"sym": "NYKAA",       "name": "Nykaa",            "sector": "Retail",  "lot_size": 5600,"base_price": 175,    "expiry_type": "monthly"},
    {"sym": "ZOMATO",      "name": "Zomato",           "sector": "Tech",    "lot_size": 4500,"base_price": 265,    "expiry_type": "monthly"},
    {"sym": "PAYTM",       "name": "Paytm",            "sector": "Tech",    "lot_size": 6250,"base_price": 900,    "expiry_type": "monthly"},
    # Chemicals
    {"sym": "PIIND",       "name": "PI Industries",    "sector": "Chemicals","lot_size": 250,"base_price": 4200,   "expiry_type": "monthly"},
    {"sym": "AARTIIND",    "name": "Aarti Industries", "sector": "Chemicals","lot_size": 1050,"base_price": 490,   "expiry_type": "monthly"},
    {"sym": "ATUL",        "name": "Atul Ltd",         "sector": "Chemicals","lot_size": 75, "base_price": 6900,   "expiry_type": "monthly"},
]

ALL_INSTRUMENTS: list[Instrument] = INDICES + FNO_STOCKS

# Quick lookup maps
INSTRUMENT_MAP: dict[str, Instrument] = {i["sym"]: i for i in ALL_INSTRUMENTS}
SECTOR_MAP: dict[str, list[Instrument]] = {}
for _inst in ALL_INSTRUMENTS:
    SECTOR_MAP.setdefault(_inst["sector"], []).append(_inst)

LOT_SIZES: dict[str, int] = {i["sym"]: i["lot_size"] for i in ALL_INSTRUMENTS}
BASE_PRICES: dict[str, float] = {i["sym"]: i["base_price"] for i in ALL_INSTRUMENTS}


def get_lot_size(sym: str) -> int:
    """
    Return lot size for a symbol, preferring live Kite data from Redis cache.
    Cache key `kite:nfo_lot_sizes` is written by KiteTickerService at startup
    and refreshed daily by the `verify-lot-sizes` Celery task.
    Falls back to instruments.py hardcoded values if cache unavailable.
    """
    try:
        import json as _json
        import redis as _redis
        from app.config import settings as _s
        _r = _redis.from_url(_s.redis_url, decode_responses=True, socket_connect_timeout=1)
        raw = _r.get("kite:nfo_lot_sizes")
        if raw:
            live = _json.loads(raw)
            if sym in live:
                return int(live[sym])
    except Exception:
        pass
    return LOT_SIZES.get(sym, 1)


def get_instrument(sym: str) -> Instrument | None:
    return INSTRUMENT_MAP.get(sym.upper())


def get_by_sector(sector: str) -> list[Instrument]:
    return SECTOR_MAP.get(sector, [])


def all_symbols() -> list[str]:
    return list(INSTRUMENT_MAP.keys())


def index_symbols() -> list[str]:
    return [i["sym"] for i in INDICES]


# ── Testing focus ─────────────────────────────────────────────────────────────
# Set to a non-empty list to restrict all scanning/discovery to these symbols.
# Empty list = full universe.
TESTING_FOCUS: list[str] = ["NIFTY", "BANKNIFTY"]


def priority_scan_list() -> list[str]:
    """High-liquidity instruments scanned on every cycle."""
    if TESTING_FOCUS:
        return list(TESTING_FOCUS)
    return [
        "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
        "RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY",
        "TATAMOTORS", "BAJFINANCE", "SBIN", "AXISBANK", "ITC",
        "BHARTIARTL", "WIPRO", "HCLTECH", "SUNPHARMA", "TITAN",
        "LT", "ADANIENT", "ADANIPORTS", "HINDUNILVR", "ULTRACEMCO",
    ]
