"""
Backfill NSE F&O bhav files from Jul 2024 to today using the UDiFF format
(NSE discontinued the old fo{DD}{MON}{YYYY}bhav.csv.zip URL in July 2024).

Downloads BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip, converts columns
to the legacy schema (SYMBOL, INSTRUMENT, EXPIRY_DT, TIMESTAMP, OPEN, HIGH,
LOW, CLOSE, CONTRACTS, OPEN_INT, CHG_IN_OI, STRIKE_PR, OPTION_TYP, SETTLE_PR)
and saves as fo{DD}{MON}{YYYY}.csv in the existing cache dir, so
build_ohlcv_from_bhav / PCR builders work unchanged.
"""
import io
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

CACHE = Path("/app/market_data/bhav")
CACHE.mkdir(parents=True, exist_ok=True)

URL = ("https://nsearchives.nseindia.com/content/fo/"
       "BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip")

MON = {1:"JAN",2:"FEB",3:"MAR",4:"APR",5:"MAY",6:"JUN",
       7:"JUL",8:"AUG",9:"SEP",10:"OCT",11:"NOV",12:"DEC"}

INSTR_MAP = {"IDF": "FUTIDX", "IDO": "OPTIDX", "STF": "FUTSTK", "STO": "OPTSTK"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
}


def legacy_name(d: date) -> Path:
    return CACHE / f"fo{d.strftime('%d')}{MON[d.month]}{d.year}.csv"


def convert(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "INSTRUMENT": df["FinInstrmTp"].map(INSTR_MAP).fillna(df["FinInstrmTp"]),
        "SYMBOL":     df["TckrSymb"],
        "EXPIRY_DT":  pd.to_datetime(df["XpryDt"]).dt.strftime("%d-%b-%Y"),
        "STRIKE_PR":  pd.to_numeric(df["StrkPric"], errors="coerce").fillna(0),
        "OPTION_TYP": df["OptnTp"].fillna("XX"),
        "OPEN":       df["OpnPric"], "HIGH": df["HghPric"],
        "LOW":        df["LwPric"],  "CLOSE": df["ClsPric"],
        "SETTLE_PR":  df["SttlmPric"],
        "CONTRACTS":  df["TtlTradgVol"],
        "OPEN_INT":   df["OpnIntrst"],
        "CHG_IN_OI":  df["ChngInOpnIntrst"],
        "TIMESTAMP":  pd.to_datetime(df["TradDt"]).dt.strftime("%d-%b-%Y"),
    })
    # Keep only F&O rows the app uses (halves file size)
    return out[out["INSTRUMENT"].isin(["FUTIDX", "OPTIDX", "FUTSTK", "OPTSTK"])]


def main():
    start = date(2016, 7, 1)
    end_cap = date(2021, 6, 29)   # first day after old-format cache ends
    end   = end_cap
    got = skipped = failed = 0

    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        d = start
        while d <= end:
            if d.weekday() >= 5:            # weekend
                d += timedelta(days=1)
                continue
            target = legacy_name(d)
            if target.exists():
                skipped += 1
                d += timedelta(days=1)
                continue
            url = URL.format(ymd=d.strftime("%Y%m%d"))
            try:
                r = client.get(url)
                if r.status_code == 200:
                    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
                        raw = pd.read_csv(zf.open(name), low_memory=False)
                    convert(raw).to_csv(target, index=False)
                    got += 1
                    if got % 25 == 0:
                        print(f"[{d}] downloaded={got} skipped={skipped} failed={failed}", flush=True)
                else:
                    failed += 1   # holiday or missing — fine
            except Exception as e:
                failed += 1
                print(f"[{d}] error: {e}", flush=True)
            time.sleep(0.4)       # be polite to NSE archives
            d += timedelta(days=1)

    print(f"DONE downloaded={got} skipped={skipped} failed(holidays)={failed}", flush=True)


if __name__ == "__main__":
    main()
