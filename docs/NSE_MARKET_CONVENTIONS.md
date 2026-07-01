# NSE F&O Market Conventions

Tracks all NSE/SEBI rules that affect AlphaFO signal generation, symbol formatting, and trade sizing.
Update this file whenever you discover a change. The `verify-lot-sizes` Celery task cross-checks lot
sizes against Kite instrument data daily and logs warnings if they drift.

---

## Lot Sizes (NSE revision — target ≥₹15L contract value)

SEBI mandated minimum contract value of ₹15 lakhs effective from contracts maturing after Oct 2024.
Lot sizes were revised upward across all index F&O.

| Underlying  | Old lot | New lot | Effective    | Source / Status             |
|-------------|---------|---------|------------- |-----------------------------|
| NIFTY 50    | 25      | **65**  | Oct 2024     | ✅ Confirmed by user Jul 2026 |
| BANKNIFTY   | 15      | **30**  | Oct 2024     | ⚠️ Estimated (57000×30=₹17.1L) — verify |
| FINNIFTY    | 40      | **65**  | Oct 2024     | ⚠️ Estimated — verify        |
| MIDCPNIFTY  | 50      | **120** | Oct 2024     | ⚠️ Estimated — verify        |
| SENSEX(BSE) | 10      | **20**  | Oct 2024     | ⚠️ Estimated — verify        |

**How to verify**: Run `POST /api/v1/system/run-task/verify-lot-sizes` — it fetches the Kite NFO
instrument master and compares lot sizes. Or check NSE's contract specification page directly.

**Formula**: `lot_size = ceil(15_00_000 / current_spot)` rounded to a round number NSE picks.

---

## Expiry Schedule (effective 1 September 2025 — SEBI circular)

NSE moved all index option expiries to **Tuesday**. BSE moved to **Thursday**.

| Underlying  | Expiry day | Weekly? | Monthly series        |
|-------------|------------|---------|-----------------------|
| NIFTY 50    | Tuesday    | ✅ Yes  | Last Tuesday of month |
| FINNIFTY    | Tuesday    | ✅ Yes  | Last Tuesday of month |
| MIDCPNIFTY  | Tuesday    | ✅ Yes  | Last Tuesday of month |
| BANKNIFTY   | Tuesday    | ❌ No   | Last Tuesday of month only |
| SENSEX(BSE) | Thursday   | ✅ Yes  | Last Thursday of month |
| BANKEX(BSE) | Thursday   | ❌ No   | Last Thursday of month only |

**Before Sep 2025**: NIFTY expired Thursday, BANKNIFTY Wednesday, FINNIFTY Tuesday.

---

## Kite / Upstox Symbol Format

Both Kite and Upstox use the **same NSE tradingsymbol format**. No conversion needed when switching
between providers — only the API prefix differs.

```
Monthly (last Tuesday of month):   {UL}{YY}{MON3}{strike}{type}
  e.g. BANKNIFTY26JUL57900PE   → BANKNIFTY monthly Jul 2026

Weekly (any other Tuesday):        {UL}{YY}{M}{DD:02d}{strike}{type}
  e.g. NIFTY2671424000PE       → NIFTY weekly 14 Jul 2026 (YY=26, M=7 no-zero, DD=14)
```

**Critical rule**: month digit has NO leading zero (7 not 07). Day has leading zero (07, 14).

| API     | Prefix   | Full example                      |
|---------|----------|-----------------------------------|
| Kite    | `NFO:`   | `NFO:NIFTY2671424000PE`           |
| Upstox  | `NSE_FO|`| `NSE_FO\|NIFTY2671424000PE`       |

---

## Historical Changes Log

| Date       | Change                                               | Impact in code                           |
|------------|------------------------------------------------------|------------------------------------------|
| Nov 2024   | BANKNIFTY weekly options discontinued by NSE         | `NO_WEEKLY_OPTIONS` set in `expiry.py`   |
| Sep 2025   | NSE moved all index expiries from Thu→Tue            | `WEEKLY_EXPIRY_WEEKDAY` in `expiry.py`; `_last_tuesday()` in `upstox_ltp.py` and `tasks.py` |
| Oct 2024   | SEBI lot size revision (≥₹15L contract value)        | `INDICES` lot sizes in `instruments.py`  |
| Jul 2026   | User confirmed NIFTY lot=65, BANKNIFTY lot≠15        | Updated `instruments.py` NIFTY→65        |

---

## Daily Verification Checklist (run by `verify-lot-sizes` Celery task)

1. Fetch Kite NFO instrument master (rate-limited: 1/day, cached in Redis `kite:instrument_tokens`)
2. For each index in `TESTING_FOCUS`, compare `inst["lot_size"]` vs `LOT_SIZES[sym]`
3. Log `WARNING` if any mismatch found — shows in SystemHealth page
4. Store last-verified timestamp in Redis key `task_last_run:verify-lot-sizes`

**What it does NOT auto-fix**: lot size mismatches require a code change + redeploy since they affect
risk gate calculations, position sizing, and P&L. Manual review required before updating.
