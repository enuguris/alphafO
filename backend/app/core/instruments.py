"""
NSE F&O instrument universe — all actively traded stocks + indices.
Source: NSE F&O ban list + SEBI approved F&O stocks (as of 2025).
"""
from typing import TypedDict


class Instrument(TypedDict):
    sym: str
    name: str
    sector: str
    lot_size: int
    base_price: float   # approximate spot (used for synthetic data)
    expiry_type: str    # weekly | monthly


INDICES: list[Instrument] = [
    {"sym": "NIFTY",      "name": "Nifty 50",        "sector": "Index",   "lot_size": 25,  "base_price": 24300,  "expiry_type": "weekly"},
    {"sym": "BANKNIFTY",  "name": "Bank Nifty",       "sector": "Index",   "lot_size": 15,  "base_price": 52700,  "expiry_type": "weekly"},
    {"sym": "FINNIFTY",   "name": "Fin Nifty",        "sector": "Index",   "lot_size": 40,  "base_price": 23400,  "expiry_type": "weekly"},
    {"sym": "MIDCPNIFTY", "name": "Midcap Nifty",     "sector": "Index",   "lot_size": 50,  "base_price": 12640,  "expiry_type": "weekly"},
    {"sym": "SENSEX",     "name": "BSE Sensex",       "sector": "Index",   "lot_size": 10,  "base_price": 79500,  "expiry_type": "weekly"},
]

FNO_STOCKS: list[Instrument] = [
    # Banking & Finance
    {"sym": "HDFCBANK",    "name": "HDFC Bank",        "sector": "Banking", "lot_size": 550, "base_price": 1840,   "expiry_type": "monthly"},
    {"sym": "ICICIBANK",   "name": "ICICI Bank",       "sector": "Banking", "lot_size": 700, "base_price": 1375,   "expiry_type": "monthly"},
    {"sym": "AXISBANK",    "name": "Axis Bank",        "sector": "Banking", "lot_size": 625, "base_price": 1200,   "expiry_type": "monthly"},
    {"sym": "SBIN",        "name": "SBI",              "sector": "Banking", "lot_size": 1500,"base_price": 856,    "expiry_type": "monthly"},
    {"sym": "KOTAKBANK",   "name": "Kotak Bank",       "sector": "Banking", "lot_size": 400, "base_price": 2134,   "expiry_type": "monthly"},
    {"sym": "INDUSINDBK",  "name": "IndusInd Bank",    "sector": "Banking", "lot_size": 500, "base_price": 950,    "expiry_type": "monthly"},
    {"sym": "BANKBARODA",  "name": "Bank of Baroda",   "sector": "Banking", "lot_size": 3000,"base_price": 240,    "expiry_type": "monthly"},
    {"sym": "PNB",         "name": "Punjab Natl Bank", "sector": "Banking", "lot_size": 5000,"base_price": 110,    "expiry_type": "monthly"},
    {"sym": "CANBK",       "name": "Canara Bank",      "sector": "Banking", "lot_size": 3000,"base_price": 108,    "expiry_type": "monthly"},
    {"sym": "FEDERALBNK",  "name": "Federal Bank",     "sector": "Banking", "lot_size": 5000,"base_price": 195,    "expiry_type": "monthly"},
    {"sym": "IDFCFIRSTB",  "name": "IDFC First Bank",  "sector": "Banking", "lot_size": 5000,"base_price": 78,     "expiry_type": "monthly"},
    {"sym": "BAJFINANCE",  "name": "Bajaj Finance",    "sector": "Finance", "lot_size": 125, "base_price": 7800,   "expiry_type": "monthly"},
    {"sym": "BAJAJFINSV",  "name": "Bajaj Finserv",    "sector": "Finance", "lot_size": 500, "base_price": 1920,   "expiry_type": "monthly"},
    {"sym": "CHOLAFIN",    "name": "Chola Finance",    "sector": "Finance", "lot_size": 500, "base_price": 1290,   "expiry_type": "monthly"},
    {"sym": "MUTHOOTFIN",  "name": "Muthoot Finance",  "sector": "Finance", "lot_size": 500, "base_price": 1820,   "expiry_type": "monthly"},
    {"sym": "LICHSGFIN",   "name": "LIC Housing Fin",  "sector": "Finance", "lot_size": 2000,"base_price": 645,    "expiry_type": "monthly"},
    {"sym": "SBICARD",     "name": "SBI Card",         "sector": "Finance", "lot_size": 2000,"base_price": 720,    "expiry_type": "monthly"},
    {"sym": "HDFCLIFE",    "name": "HDFC Life",        "sector": "Finance", "lot_size": 1100,"base_price": 690,    "expiry_type": "monthly"},
    {"sym": "SBILIFE",     "name": "SBI Life",         "sector": "Finance", "lot_size": 750, "base_price": 1530,   "expiry_type": "monthly"},
    {"sym": "ICICIGI",     "name": "ICICI Lombard",    "sector": "Finance", "lot_size": 200, "base_price": 1890,   "expiry_type": "monthly"},
    # IT
    {"sym": "TCS",         "name": "TCS",              "sector": "IT",      "lot_size": 175, "base_price": 4286,   "expiry_type": "monthly"},
    {"sym": "INFY",        "name": "Infosys",          "sector": "IT",      "lot_size": 400, "base_price": 1923,   "expiry_type": "monthly"},
    {"sym": "WIPRO",       "name": "Wipro",            "sector": "IT",      "lot_size": 1500,"base_price": 615,    "expiry_type": "monthly"},
    {"sym": "HCLTECH",     "name": "HCL Tech",         "sector": "IT",      "lot_size": 350, "base_price": 1887,   "expiry_type": "monthly"},
    {"sym": "TECHM",       "name": "Tech Mahindra",    "sector": "IT",      "lot_size": 600, "base_price": 1640,   "expiry_type": "monthly"},
    {"sym": "LTIM",        "name": "LTIMindtree",      "sector": "IT",      "lot_size": 150, "base_price": 5200,   "expiry_type": "monthly"},
    {"sym": "MPHASIS",     "name": "Mphasis",          "sector": "IT",      "lot_size": 300, "base_price": 2750,   "expiry_type": "monthly"},
    {"sym": "PERSISTENT",  "name": "Persistent Sys",   "sector": "IT",      "lot_size": 125, "base_price": 5800,   "expiry_type": "monthly"},
    {"sym": "COFORGE",     "name": "Coforge",          "sector": "IT",      "lot_size": 150, "base_price": 6800,   "expiry_type": "monthly"},
    # Energy & Oil
    {"sym": "RELIANCE",    "name": "Reliance",         "sector": "Energy",  "lot_size": 250, "base_price": 2975,   "expiry_type": "monthly"},
    {"sym": "ONGC",        "name": "ONGC",             "sector": "Energy",  "lot_size": 3750,"base_price": 268,    "expiry_type": "monthly"},
    {"sym": "NTPC",        "name": "NTPC",             "sector": "Energy",  "lot_size": 3000,"base_price": 384,    "expiry_type": "monthly"},
    {"sym": "POWERGRID",   "name": "Power Grid",       "sector": "Energy",  "lot_size": 3250,"base_price": 325,    "expiry_type": "monthly"},
    {"sym": "ADANIPOWER",  "name": "Adani Power",      "sector": "Energy",  "lot_size": 1250,"base_price": 560,    "expiry_type": "monthly"},
    {"sym": "ADANIGREEN",  "name": "Adani Green",      "sector": "Energy",  "lot_size": 400, "base_price": 1900,   "expiry_type": "monthly"},
    {"sym": "TATAPOWER",   "name": "Tata Power",       "sector": "Energy",  "lot_size": 3000,"base_price": 420,    "expiry_type": "monthly"},
    {"sym": "BPCL",        "name": "BPCL",             "sector": "Energy",  "lot_size": 1800,"base_price": 310,    "expiry_type": "monthly"},
    {"sym": "IOC",         "name": "IOC",              "sector": "Energy",  "lot_size": 5500,"base_price": 163,    "expiry_type": "monthly"},
    {"sym": "GAIL",        "name": "GAIL",             "sector": "Energy",  "lot_size": 4000,"base_price": 215,    "expiry_type": "monthly"},
    # Automobile
    {"sym": "TATAMOTORS",  "name": "Tata Motors",      "sector": "Auto",    "lot_size": 1425,"base_price": 978,    "expiry_type": "monthly"},
    {"sym": "MARUTI",      "name": "Maruti",           "sector": "Auto",    "lot_size": 100, "base_price": 12834,  "expiry_type": "monthly"},
    {"sym": "BAJAJ-AUTO",  "name": "Bajaj Auto",       "sector": "Auto",    "lot_size": 125, "base_price": 10247,  "expiry_type": "monthly"},
    {"sym": "HEROMOTOCO",  "name": "Hero MotoCorp",    "sector": "Auto",    "lot_size": 300, "base_price": 5480,   "expiry_type": "monthly"},
    {"sym": "EICHERMOT",   "name": "Eicher Motors",    "sector": "Auto",    "lot_size": 175, "base_price": 4960,   "expiry_type": "monthly"},
    {"sym": "TVSMOTOR",    "name": "TVS Motor",        "sector": "Auto",    "lot_size": 350, "base_price": 2380,   "expiry_type": "monthly"},
    {"sym": "M&M",         "name": "M&M",              "sector": "Auto",    "lot_size": 700, "base_price": 2950,   "expiry_type": "monthly"},
    {"sym": "ASHOKLEY",    "name": "Ashok Leyland",    "sector": "Auto",    "lot_size": 4000,"base_price": 228,    "expiry_type": "monthly"},
    # Pharma & Healthcare
    {"sym": "SUNPHARMA",   "name": "Sun Pharma",       "sector": "Pharma",  "lot_size": 700, "base_price": 1834,   "expiry_type": "monthly"},
    {"sym": "DRREDDY",     "name": "Dr Reddys",        "sector": "Pharma",  "lot_size": 125, "base_price": 6482,   "expiry_type": "monthly"},
    {"sym": "CIPLA",       "name": "Cipla",            "sector": "Pharma",  "lot_size": 650, "base_price": 1675,   "expiry_type": "monthly"},
    {"sym": "DIVISLAB",    "name": "Divi's Lab",       "sector": "Pharma",  "lot_size": 200, "base_price": 5120,   "expiry_type": "monthly"},
    {"sym": "APOLLOHOSP",  "name": "Apollo Hospitals", "sector": "Pharma",  "lot_size": 175, "base_price": 6800,   "expiry_type": "monthly"},
    {"sym": "AUROPHARMA",  "name": "Aurobindo Pharma", "sector": "Pharma",  "lot_size": 650, "base_price": 1240,   "expiry_type": "monthly"},
    {"sym": "LUPIN",       "name": "Lupin",            "sector": "Pharma",  "lot_size": 850, "base_price": 2080,   "expiry_type": "monthly"},
    {"sym": "BIOCON",      "name": "Biocon",           "sector": "Pharma",  "lot_size": 2900,"base_price": 368,    "expiry_type": "monthly"},
    # Metals & Mining
    {"sym": "TATASTEEL",   "name": "Tata Steel",       "sector": "Metals",  "lot_size": 5500,"base_price": 162,    "expiry_type": "monthly"},
    {"sym": "HINDALCO",    "name": "Hindalco",         "sector": "Metals",  "lot_size": 2150,"base_price": 672,    "expiry_type": "monthly"},
    {"sym": "JSWSTEEL",    "name": "JSW Steel",        "sector": "Metals",  "lot_size": 1350,"base_price": 870,    "expiry_type": "monthly"},
    {"sym": "SAIL",        "name": "SAIL",             "sector": "Metals",  "lot_size": 7500,"base_price": 132,    "expiry_type": "monthly"},
    {"sym": "NMDC",        "name": "NMDC",             "sector": "Metals",  "lot_size": 4500,"base_price": 226,    "expiry_type": "monthly"},
    {"sym": "VEDL",        "name": "Vedanta",          "sector": "Metals",  "lot_size": 2750,"base_price": 458,    "expiry_type": "monthly"},
    {"sym": "COALINDIA",   "name": "Coal India",       "sector": "Metals",  "lot_size": 4200,"base_price": 445,    "expiry_type": "monthly"},
    # FMCG
    {"sym": "HINDUNILVR",  "name": "Hindustan Unilever","sector": "FMCG",   "lot_size": 300, "base_price": 2450,   "expiry_type": "monthly"},
    {"sym": "ITC",         "name": "ITC",              "sector": "FMCG",    "lot_size": 3200,"base_price": 462,    "expiry_type": "monthly"},
    {"sym": "NESTLEIND",   "name": "Nestle India",     "sector": "FMCG",    "lot_size": 50,  "base_price": 24800,  "expiry_type": "monthly"},
    {"sym": "BRITANNIA",   "name": "Britannia",        "sector": "FMCG",    "lot_size": 200, "base_price": 5340,   "expiry_type": "monthly"},
    {"sym": "DABUR",       "name": "Dabur",            "sector": "FMCG",    "lot_size": 2750,"base_price": 538,    "expiry_type": "monthly"},
    {"sym": "MARICO",      "name": "Marico",           "sector": "FMCG",    "lot_size": 1800,"base_price": 628,    "expiry_type": "monthly"},
    {"sym": "COLPAL",      "name": "Colgate-Palmolive","sector": "FMCG",    "lot_size": 1100,"base_price": 2850,   "expiry_type": "monthly"},
    # Cement & Construction
    {"sym": "ULTRACEMCO",  "name": "UltraTech Cement", "sector": "Cement",  "lot_size": 100, "base_price": 10480,  "expiry_type": "monthly"},
    {"sym": "SHREECEM",    "name": "Shree Cement",     "sector": "Cement",  "lot_size": 25,  "base_price": 26800,  "expiry_type": "monthly"},
    {"sym": "ACC",         "name": "ACC",              "sector": "Cement",  "lot_size": 500, "base_price": 1870,   "expiry_type": "monthly"},
    {"sym": "AMBUJACEM",   "name": "Ambuja Cement",    "sector": "Cement",  "lot_size": 2000,"base_price": 620,    "expiry_type": "monthly"},
    {"sym": "LT",          "name": "L&T",              "sector": "Infra",   "lot_size": 175, "base_price": 3860,   "expiry_type": "monthly"},
    {"sym": "DLF",         "name": "DLF",              "sector": "Realty",  "lot_size": 1650,"base_price": 820,    "expiry_type": "monthly"},
    {"sym": "GODREJPROP",  "name": "Godrej Properties","sector": "Realty",  "lot_size": 325, "base_price": 2720,   "expiry_type": "monthly"},
    {"sym": "PRESTIGE",    "name": "Prestige Estates",  "sector": "Realty", "lot_size": 625, "base_price": 1745,   "expiry_type": "monthly"},
    # Telecom & Media
    {"sym": "BHARTIARTL",  "name": "Bharti Airtel",    "sector": "Telecom", "lot_size": 475, "base_price": 1780,   "expiry_type": "monthly"},
    {"sym": "IDEA",        "name": "Vodafone Idea",    "sector": "Telecom", "lot_size": 70000,"base_price": 15,    "expiry_type": "monthly"},
    # Consumer Discretionary
    {"sym": "TITAN",       "name": "Titan",            "sector": "Consumer","lot_size": 375, "base_price": 3420,   "expiry_type": "monthly"},
    {"sym": "PIDILITIND",  "name": "Pidilite",         "sector": "Consumer","lot_size": 375, "base_price": 2980,   "expiry_type": "monthly"},
    {"sym": "HAVELLS",     "name": "Havells",          "sector": "Consumer","lot_size": 1000,"base_price": 1640,   "expiry_type": "monthly"},
    {"sym": "VOLTAS",      "name": "Voltas",           "sector": "Consumer","lot_size": 1500,"base_price": 1560,   "expiry_type": "monthly"},
    {"sym": "VGUARD",      "name": "V-Guard",          "sector": "Consumer","lot_size": 2500,"base_price": 448,    "expiry_type": "monthly"},
    # Conglomerates & Diversified
    {"sym": "ADANIENT",    "name": "Adani Enterprises","sector": "Diversified","lot_size": 250,"base_price": 2780, "expiry_type": "monthly"},
    {"sym": "ADANIPORTS",  "name": "Adani Ports",      "sector": "Diversified","lot_size": 625,"base_price": 1380, "expiry_type": "monthly"},
    {"sym": "TATACONSUM",  "name": "Tata Consumer",    "sector": "FMCG",    "lot_size": 900, "base_price": 1100,   "expiry_type": "monthly"},
    {"sym": "TATACHEM",    "name": "Tata Chemicals",   "sector": "Chemicals","lot_size": 875,"base_price": 1040,   "expiry_type": "monthly"},
    # Aviation, Hotels, Retail
    {"sym": "INDIGO",      "name": "IndiGo",           "sector": "Aviation","lot_size": 300, "base_price": 4820,   "expiry_type": "monthly"},
    {"sym": "IRCTC",       "name": "IRCTC",            "sector": "Services","lot_size": 875, "base_price": 835,    "expiry_type": "monthly"},
    {"sym": "DMART",       "name": "DMart",            "sector": "Retail",  "lot_size": 275, "base_price": 4640,   "expiry_type": "monthly"},
    {"sym": "NYKAA",       "name": "Nykaa",            "sector": "Retail",  "lot_size": 5600,"base_price": 178,    "expiry_type": "monthly"},
    {"sym": "ZOMATO",      "name": "Zomato",           "sector": "Tech",    "lot_size": 4500,"base_price": 238,    "expiry_type": "monthly"},
    {"sym": "PAYTM",       "name": "Paytm",            "sector": "Tech",    "lot_size": 6250,"base_price": 985,    "expiry_type": "monthly"},
    # Chemicals
    {"sym": "PIIND",       "name": "PI Industries",    "sector": "Chemicals","lot_size": 250,"base_price": 3980,   "expiry_type": "monthly"},
    {"sym": "AARTIIND",    "name": "Aarti Industries", "sector": "Chemicals","lot_size": 1050,"base_price": 480,   "expiry_type": "monthly"},
    {"sym": "ATUL",        "name": "Atul Ltd",         "sector": "Chemicals","lot_size": 75, "base_price": 7240,   "expiry_type": "monthly"},
]

ALL_INSTRUMENTS: list[Instrument] = INDICES + FNO_STOCKS

# Quick lookup maps
INSTRUMENT_MAP: dict[str, Instrument] = {i["sym"]: i for i in ALL_INSTRUMENTS}
SECTOR_MAP: dict[str, list[Instrument]] = {}
for _inst in ALL_INSTRUMENTS:
    SECTOR_MAP.setdefault(_inst["sector"], []).append(_inst)

LOT_SIZES: dict[str, int] = {i["sym"]: i["lot_size"] for i in ALL_INSTRUMENTS}
BASE_PRICES: dict[str, float] = {i["sym"]: i["base_price"] for i in ALL_INSTRUMENTS}


def get_instrument(sym: str) -> Instrument | None:
    return INSTRUMENT_MAP.get(sym.upper())


def get_by_sector(sector: str) -> list[Instrument]:
    return SECTOR_MAP.get(sector, [])


def all_symbols() -> list[str]:
    return list(INSTRUMENT_MAP.keys())


def index_symbols() -> list[str]:
    return [i["sym"] for i in INDICES]


def priority_scan_list() -> list[str]:
    """High-liquidity instruments scanned on every cycle."""
    return [
        "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
        "RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY",
        "TATAMOTORS", "BAJFINANCE", "SBIN", "AXISBANK", "ITC",
        "BHARTIARTL", "WIPRO", "HCLTECH", "SUNPHARMA", "TITAN",
        "LT", "ADANIENT", "ADANIPORTS", "HINDUNILVR", "ULTRACEMCO",
    ]
