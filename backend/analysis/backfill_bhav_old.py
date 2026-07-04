"""Backfill 2016-2021 NSE F&O bhav files (old format URL, no conversion needed)."""
import io, time, zipfile
from datetime import date, timedelta
from pathlib import Path
import httpx

CACHE = Path("/app/market_data/bhav")
MON = {1:"JAN",2:"FEB",3:"MAR",4:"APR",5:"MAY",6:"JUN",7:"JUL",8:"AUG",9:"SEP",10:"OCT",11:"NOV",12:"DEC"}
URL = "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{y}/{m}/fo{dd}{m}{y}bhav.csv.zip"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

got = failed = skipped = 0
with httpx.Client(headers=H, timeout=30, follow_redirects=True) as c:
    d = date(2021, 6, 30)
    while d <= date(2024, 7, 7):
        if d.weekday() >= 5:
            d += timedelta(days=1); continue
        target = CACHE / f"fo{d.strftime('%d')}{MON[d.month]}{d.year}.csv"
        if target.exists():
            skipped += 1; d += timedelta(days=1); continue
        try:
            r = c.get(URL.format(y=d.year, m=MON[d.month], dd=d.strftime("%d")))
            if r.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                    name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
                    target.write_bytes(zf.read(name))
                got += 1
                if got % 100 == 0:
                    print(f"[{d}] got={got} failed={failed}", flush=True)
            else:
                failed += 1
        except Exception as e:
            failed += 1
        time.sleep(0.35)
        d += timedelta(days=1)
print(f"DONE got={got} skipped={skipped} failed={failed}", flush=True)
