"""
External market data enrichment for pattern discovery.

Fetches and caches:
  1. India VIX      — Yahoo Finance (^INDIAVIX)
  2. FII F&O OI     — NSE archives participant data
  3. PCR + max pain — NSE F&O bhavcopy

All fetchers cache to disk (compressed CSV) and fail silently.
enrich_ohlcv() joins all sources to an OHLCV DataFrame by date.
"""
from __future__ import annotations

import csv
import io
import os
import threading
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

CACHE_DIR = Path(os.environ.get("MARKET_DATA_CACHE", "/app/market_data"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
(CACHE_DIR / "bhav").mkdir(parents=True, exist_ok=True)

_MON_MAP = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def _read_csv(path: Path) -> Optional[pd.DataFrame]:
    try:
        return pd.read_csv(path, parse_dates=["date"])
    except Exception:
        return None


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    try:
        df.to_csv(path, index=False)
    except Exception:
        pass


# ─── India VIX ────────────────────────────────────────────────────────────────

def fetch_india_vix(days: int = 1825) -> Optional[pd.DataFrame]:
    """Return DataFrame[date, vix] from Yahoo Finance ^INDIAVIX. Cached 18 h."""
    cache = CACHE_DIR / "india_vix.csv"

    if cache.exists() and (time.time() - cache.stat().st_mtime) < 18 * 3600:
        df = _read_csv(cache)
        if df is not None and len(df) > 10:
            cutoff = pd.Timestamp.today() - pd.Timedelta(days=days)
            return df[df["date"] >= cutoff].copy()

    try:
        import yfinance as yf

        raw = yf.download(
            "^INDIAVIX",
            start=(date.today() - timedelta(days=days)).strftime("%Y-%m-%d"),
            end=date.today().strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
        if raw is None or raw.empty:
            return None

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.droplevel(1)
        raw.columns = [c.lower() for c in raw.columns]

        df = raw[["close"]].rename(columns={"close": "vix"}).copy()
        df.index.name = "date"
        df = df.reset_index()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df = df.dropna(subset=["vix"])

        _write_csv(df, cache)
        logger.info(f"India VIX: {len(df)} bars fetched and cached")
        return df

    except Exception as e:
        logger.warning(f"India VIX fetch failed: {e}")
        if cache.exists():
            return _read_csv(cache)
        return None


# ─── NSE session ──────────────────────────────────────────────────────────────

def _nse_session():
    try:
        import httpx
        client = httpx.Client(headers=_NSE_HEADERS, timeout=15, follow_redirects=True)
        client.get("https://www.nseindia.com/")
        return client
    except Exception:
        return None


# ─── FII F&O Positioning ─────────────────────────────────────────────────────

_FII_URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{date}.csv"


def _parse_fii_csv(text: str) -> Optional[dict]:
    """
    NSE fao_participant_oi CSV has a title row before the actual column headers,
    so we skip the first line before handing the text to DictReader.
    """
    try:
        lines = text.splitlines()
        # Drop the first line (title: "Participant wise Open Interest...") so
        # DictReader sees the real column headers as row 0.
        body = "\n".join(lines[1:])
        reader = csv.DictReader(io.StringIO(body))
        for row in reader:
            client = row.get("Client Type", "").strip().upper()
            if "FII" in client or "FPI" in client or "FOREIGN" in client:
                def _f(k: str) -> float:
                    return float((row.get(k) or "0").replace(",", "") or 0)
                return {
                    "fii_net_idx": _f("Future Index Long")  - _f("Future Index Short"),
                    "fii_net_stk": _f("Future Stock Long")  - _f("Future Stock Short"),
                }
    except Exception:
        pass
    return None


def _load_fii_cache() -> dict[str, dict]:
    cache = CACHE_DIR / "fii_fo.csv"
    existing: dict[str, dict] = {}
    df = _read_csv(cache)
    if df is not None:
        for _, row in df.iterrows():
            existing[str(row["date"])[:10]] = {
                "fii_net_idx": float(row["fii_net_idx"]),
                "fii_net_stk": float(row["fii_net_stk"]),
            }
    return existing


def _save_fii_cache(existing: dict[str, dict]) -> None:
    df = pd.DataFrame([{"date": k, **v} for k, v in sorted(existing.items())])
    _write_csv(df, CACHE_DIR / "fii_fo.csv")


def fetch_fii_fo_data(days: int = 1825) -> Optional[pd.DataFrame]:
    """Return DataFrame[date, fii_net_idx, fii_net_stk]. Background-downloads missing dates."""
    existing = _load_fii_cache()

    def _bg():
        client = _nse_session()
        if client is None:
            return
        cutoff = date.today() - timedelta(days=days)
        d = date.today() - timedelta(days=1)
        fetched = 0
        while d >= cutoff and fetched < 600:
            if d.weekday() < 5:
                key = d.strftime("%Y-%m-%d")
                if key not in existing:
                    try:
                        resp = client.get(_FII_URL.format(date=d.strftime("%d%m%Y")))
                        if resp.status_code == 200 and len(resp.text) > 100:
                            parsed = _parse_fii_csv(resp.text)
                            if parsed:
                                existing[key] = parsed
                                fetched += 1
                    except Exception:
                        pass
            d -= timedelta(days=1)
        if fetched:
            _save_fii_cache(existing)
            logger.info(f"FII F&O: background cached {fetched} new days")

    if len(existing) < 200:
        threading.Thread(target=_bg, daemon=True).start()

    if not existing:
        return None

    df = pd.DataFrame([{"date": pd.Timestamp(k), **v} for k, v in sorted(existing.items())])
    return df


# ─── PCR + Max Pain ───────────────────────────────────────────────────────────

_BHAV_URL = (
    "https://nsearchives.nseindia.com/content/historical/DERIVATIVES"
    "/{year}/{mon}/fo{dd}{mon}{year}bhav.csv.zip"
)


def _fetch_bhav(client, d: date) -> Optional[pd.DataFrame]:
    """Download and cache one day's F&O bhavcopy."""
    mon  = _MON_MAP[d.month]
    year = d.strftime("%Y")
    dd   = d.strftime("%d")
    cache_f = CACHE_DIR / "bhav" / f"fo{dd}{mon}{year}.csv"

    if cache_f.exists():
        try:
            return pd.read_csv(cache_f, low_memory=False)
        except Exception:
            cache_f.unlink(missing_ok=True)

    try:
        url  = _BHAV_URL.format(year=year, mon=mon, dd=dd)
        resp = client.get(url, timeout=25)
        if resp.status_code != 200:
            return None
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_name = next((n for n in zf.namelist() if n.lower().endswith(".csv")), None)
            if csv_name is None:
                return None
            df_bhav = pd.read_csv(zf.open(csv_name), low_memory=False)
        df_bhav.to_csv(cache_f, index=False)
        return df_bhav
    except Exception:
        return None


def _compute_pcr_maxpain(df_bhav: pd.DataFrame, underlying: str) -> Optional[dict]:
    try:
        sym  = underlying.upper()
        opts = df_bhav[
            (df_bhav["SYMBOL"] == sym) &
            (df_bhav["INSTRUMENT"].isin(["OPTIDX", "OPTSTK"]))
        ].copy()
        if opts.empty:
            return None

        opts["EXPIRY_DT"] = pd.to_datetime(opts["EXPIRY_DT"], dayfirst=True, errors="coerce")
        nearest_exp = opts["EXPIRY_DT"].min()
        opts = opts[opts["EXPIRY_DT"] == nearest_exp].copy()

        opts["STRIKE_PR"] = pd.to_numeric(opts["STRIKE_PR"], errors="coerce")
        opts["OPEN_INT"]  = pd.to_numeric(opts["OPEN_INT"],  errors="coerce").fillna(0)

        ce = opts[opts["OPTION_TYP"] == "CE"]
        pe = opts[opts["OPTION_TYP"] == "PE"]

        total_ce_oi = float(ce["OPEN_INT"].sum())
        total_pe_oi = float(pe["OPEN_INT"].sum())
        if total_ce_oi == 0:
            return None

        pcr = round(total_pe_oi / total_ce_oi, 4)

        # Max pain
        strikes  = sorted(opts["STRIKE_PR"].dropna().unique())
        ce_oi    = ce.groupby("STRIKE_PR")["OPEN_INT"].sum().to_dict()
        pe_oi    = pe.groupby("STRIKE_PR")["OPEN_INT"].sum().to_dict()
        min_pay  = float("inf")
        max_pain = strikes[len(strikes) // 2] if strikes else 0.0

        for s in strikes:
            pay = (sum((s - k) * v for k, v in ce_oi.items() if k < s) +
                   sum((k - s) * v for k, v in pe_oi.items() if k > s))
            if pay < min_pay:
                min_pay  = pay
                max_pain = s

        return {"pcr": pcr, "max_pain": float(max_pain)}
    except Exception as e:
        logger.debug(f"PCR/MaxPain error: {e}")
        return None


def _load_pcr_cache(underlying: str) -> dict[str, dict]:
    cache = CACHE_DIR / f"pcr_{underlying.upper()}.csv"
    existing: dict[str, dict] = {}
    df = _read_csv(cache)
    if df is not None:
        for _, row in df.iterrows():
            existing[str(row["date"])[:10]] = {
                "pcr":      float(row["pcr"]),
                "max_pain": float(row["max_pain"]),
            }
    return existing


def _save_pcr_cache(underlying: str, existing: dict[str, dict]) -> None:
    df = pd.DataFrame([{"date": k, **v} for k, v in sorted(existing.items())])
    _write_csv(df, CACHE_DIR / f"pcr_{underlying.upper()}.csv")


def build_pcr_from_cached_bhav(underlying: str) -> int:
    """
    Process all already-downloaded bhav CSV files in CACHE_DIR/bhav/ into the PCR cache.
    This is a one-time bootstrap — subsequent calls only add missing dates.
    Returns number of dates processed.
    """
    existing = _load_pcr_cache(underlying)
    bhav_dir = CACHE_DIR / "bhav"
    added = 0
    for csv_f in sorted(bhav_dir.glob("fo*.csv")):
        # Filename format: fo01APR2024.csv
        name = csv_f.stem  # fo01APR2024
        try:
            dd   = name[2:4]
            mon  = name[4:7]
            year = name[7:11]
            mon_n = {v: k for k, v in _MON_MAP.items()}.get(mon, 0)
            if not mon_n:
                continue
            d = date(int(year), mon_n, int(dd))
            key = d.strftime("%Y-%m-%d")
            if key in existing:
                continue
            bhav_df = pd.read_csv(csv_f, low_memory=False)
            res = _compute_pcr_maxpain(bhav_df, underlying)
            if res:
                existing[key] = res
                added += 1
        except Exception:
            continue

    if added:
        _save_pcr_cache(underlying, existing)
        logger.info(f"PCR bootstrap {underlying}: processed {added} bhav files into cache")
    return added


def fetch_pcr_maxpain(underlying: str, days: int = 1825) -> Optional[pd.DataFrame]:
    """Return DataFrame[date, pcr, max_pain]. Background-downloads missing bhav files."""
    existing = _load_pcr_cache(underlying)

    # Bootstrap from already-cached bhav files if PCR cache is empty
    if not existing:
        build_pcr_from_cached_bhav(underlying)
        existing = _load_pcr_cache(underlying)

    def _bg():
        client = _nse_session()
        if client is None:
            return
        cutoff  = date.today() - timedelta(days=days)
        d       = date.today() - timedelta(days=1)
        fetched = 0
        while d >= cutoff and fetched < 400:
            if d.weekday() < 5:
                key = d.strftime("%Y-%m-%d")
                if key not in existing:
                    bhav = _fetch_bhav(client, d)
                    if bhav is not None:
                        res = _compute_pcr_maxpain(bhav, underlying)
                        if res:
                            existing[key] = res
                            fetched += 1
            d -= timedelta(days=1)
        if fetched:
            _save_pcr_cache(underlying, existing)
            logger.info(f"PCR/MaxPain {underlying}: cached {fetched} new days")

    if len(existing) < 200:
        threading.Thread(target=_bg, daemon=True).start()

    if not existing:
        return None

    df = pd.DataFrame([
        {"date": pd.Timestamp(k), **v}
        for k, v in sorted(existing.items())
    ])
    return df


# ─── DTE helper ──────────────────────────────────────────────────────────────

def _days_to_expiry(ts: pd.Timestamp) -> int:
    """Days to next Thursday (NSE expiry day). Thursday = 0."""
    return int((3 - ts.date().weekday()) % 7)


# ─── Main enrichment entry point ─────────────────────────────────────────────

def enrich_ohlcv(df: pd.DataFrame, underlying: str) -> pd.DataFrame:
    """
    Join VIX, FII, PCR/max-pain to an OHLCV DataFrame by date.
    Also adds 'dte' column. All joins are left-joins — NaN if data missing.
    """
    df = df.copy()

    if "timestamp" in df.columns:
        date_key = pd.to_datetime(df["timestamp"]).dt.normalize()
    else:
        date_key = pd.to_datetime(df.index).normalize()
    df["_date"] = date_key

    # DTE — always computed
    df["dte"] = df["_date"].apply(_days_to_expiry)

    def _merge(ext_df: pd.DataFrame, col_rename: str) -> pd.DataFrame:
        ext = ext_df.copy()
        ext["date"] = pd.to_datetime(ext["date"]).dt.normalize()
        merged = df.merge(ext, left_on="_date", right_on="date", how="left")
        merged = merged.drop(columns=["date"], errors="ignore")
        return merged

    # India VIX
    vix_df = fetch_india_vix()
    if vix_df is not None and len(vix_df) > 10:
        df = _merge(vix_df, "vix")
        df["vix"] = df["vix"].ffill()

    # FII positioning
    fii_df = fetch_fii_fo_data()
    if fii_df is not None and len(fii_df) > 10:
        df = _merge(fii_df, "fii_net_idx")
        df["fii_net_idx"] = df["fii_net_idx"].ffill()
        df["fii_net_stk"] = df["fii_net_stk"].ffill()

    # PCR + max pain (index underlyings only)
    if underlying.upper() in {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}:
        pcr_df = fetch_pcr_maxpain(underlying)
        if pcr_df is not None and len(pcr_df) > 10:
            df = _merge(pcr_df, "pcr")
            df["pcr"]      = df["pcr"].ffill()
            df["max_pain"] = df["max_pain"].ffill()

    df = df.drop(columns=["_date"], errors="ignore")

    n_vix = df["vix"].notna().sum() if "vix" in df.columns else 0
    n_fii = df["fii_net_idx"].notna().sum() if "fii_net_idx" in df.columns else 0
    n_pcr = df["pcr"].notna().sum() if "pcr" in df.columns else 0
    logger.info(
        f"enrich_ohlcv {underlying}: VIX={n_vix}/{len(df)} "
        f"FII={n_fii}/{len(df)} PCR={n_pcr}/{len(df)} DTE=✓"
    )
    return df


def build_ohlcv_from_bhav(underlying: str, rows: int = 120) -> Optional[pd.DataFrame]:
    """
    Build a real OHLCV DataFrame from cached bhav files (FUTIDX near-month contract).
    Returns None if insufficient bhav data.
    Used by regime detection as a higher-quality alternative to synthetic random walks.
    """
    sym = underlying.upper()
    bhav_dir = CACHE_DIR / "bhav"
    records: list[dict] = []

    for csv_f in sorted(bhav_dir.glob("fo*.csv")):
        try:
            df_b = pd.read_csv(csv_f, low_memory=False)
            # Filter to near-month FUTIDX for this symbol
            fut = df_b[
                (df_b["INSTRUMENT"] == "FUTIDX") &
                (df_b["SYMBOL"] == sym)
            ].copy()
            if fut.empty:
                continue
            # Nearest expiry = first expiry date
            fut["EXPIRY_DT"] = pd.to_datetime(fut["EXPIRY_DT"], dayfirst=True)
            nearest = fut.sort_values("EXPIRY_DT").iloc[0]
            ts = str(nearest.get("TIMESTAMP", "")).strip()
            if not ts:
                continue
            trade_date = pd.to_datetime(ts, dayfirst=True)
            records.append({
                "timestamp": trade_date,
                "open":  float(nearest.get("OPEN", 0) or 0),
                "high":  float(nearest.get("HIGH", 0) or 0),
                "low":   float(nearest.get("LOW", 0) or 0),
                "close": float(nearest.get("CLOSE", 0) or 0),
                "volume": float(nearest.get("CONTRACTS", 0) or 0),
                "oi":    float(nearest.get("OPEN_INT", 0) or 0),
            })
        except Exception:
            continue

    if not records:
        return None

    result = pd.DataFrame(records).sort_values("timestamp").drop_duplicates("timestamp")
    result = result[result["close"] > 0].tail(rows).reset_index(drop=True)
    # Synthetic IV column (ATM IV not available from bhav)
    result["iv"] = 18.0
    return result if len(result) >= 20 else None
