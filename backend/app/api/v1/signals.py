"""Signal API endpoints."""
from datetime import datetime, timedelta, date

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, AppMode
from app.database import get_db
from app.models.signals import Signal, SignalStatus
from app.core.signals.generator import SignalGenerator
from app.core.options.regime import RegimeDetector
from app.core.options.chain_service import ChainService
from app.core.options.iv_rank import IVRankService
from app.core.options.event_calendar import EventCalendar
from app.core.options.strike_selector import StrikeSelector
from app.core.options.max_pain import compute_max_pain
from app.core.options.greeks import compute_greeks, RISK_FREE_RATE

router = APIRouter()


# ── Synthetic data for testing mode ──────────────────────────────────────────

def _synthetic_ohlcv(underlying: str, rows: int = 120) -> pd.DataFrame:
    """
    Generate realistic OHLCV that reliably triggers several patterns:
    - Last candle has a 1.0–1.5% gap up (gap_fill)
    - Last 10 rows have tight range (BB squeeze → mean_reversion)
    - OI and price trend consistently for the last 5 rows (oi_buildup, vwap_oi)
    """
    from app.core.instruments import BASE_PRICES
    rng = np.random.default_rng(abs(hash(underlying)) % (2**31))
    base = BASE_PRICES.get(underlying.upper(), 1500)

    # Body: normal random walk for first (rows-10) candles
    body_len = rows - 10
    close_body = base + np.cumsum(rng.normal(0, base * 0.006, body_len))

    # Squeeze zone: last 10 candles with very tight range (triggers BB squeeze)
    squeeze_base = close_body[-1]
    squeeze_drift = np.linspace(0, squeeze_base * 0.005, 10)  # tiny upward drift
    close_squeeze = squeeze_base + squeeze_drift + rng.normal(0, squeeze_base * 0.0005, 10)

    close_arr = np.concatenate([close_body, close_squeeze])

    # Build open/high/low for full series
    open_arr  = close_arr * (1 + rng.normal(0, 0.003, rows))
    high_arr  = np.maximum(open_arr, close_arr) * (1 + rng.uniform(0.001, 0.008, rows))
    low_arr   = np.minimum(open_arr, close_arr) * (1 - rng.uniform(0.001, 0.008, rows))

    # Inject 1.2% gap UP on last candle (triggers gap_fill)
    open_arr[-1] = close_arr[-2] * 1.012

    # OI: rising in last 5 rows with rising price (triggers oi_buildup)
    oi_base = rng.integers(5_000_000, 15_000_000)
    oi_arr  = np.full(rows, float(oi_base))
    for i in range(rows - 5, rows):
        oi_arr[i] = oi_arr[i-1] * rng.uniform(1.02, 1.06)

    dates = pd.date_range(end=datetime.today(), periods=rows, freq="D")
    return pd.DataFrame({
        "timestamp": dates,
        "open":      np.round(open_arr, 2),
        "high":      np.round(high_arr, 2),
        "low":       np.round(low_arr, 2),
        "close":     np.round(close_arr, 2),
        "volume":    rng.integers(500_000, 5_000_000, rows).astype(float),
        "oi":        np.round(oi_arr, 0),
        "iv":        np.round(rng.uniform(12, 28, rows), 2),
    })


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _safe_dict(obj) -> dict:
    """Convert SQLAlchemy model to dict, replacing nan/inf with None for JSON safety."""
    import math
    d = {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    for k, v in d.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            d[k] = None
    return d


@router.get("/")
async def list_signals(
    pattern: str | None = None,
    underlying: str | None = None,
    status: str = "active",
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    from app.core.instruments import TESTING_FOCUS
    q = select(Signal).where(Signal.status == status)
    if pattern:
        q = q.where(Signal.pattern_name == pattern)
    if underlying:
        q = q.where(Signal.underlying == underlying)
    elif TESTING_FOCUS:
        q = q.where(Signal.underlying.in_(TESTING_FOCUS))
    q = q.order_by(Signal.created_at.desc()).limit(limit)
    result = await db.execute(q)
    signals = result.scalars().all()
    return {"signals": [_safe_dict(s) for s in signals], "count": len(signals)}


@router.post("/scan-all")
async def scan_all(
    timeframes: list[str] | None = None,
    symbols: list[str] | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Run multi-timeframe scan across all (or specified) instruments. Broadcasts via WebSocket."""
    from app.core.scanner import run_full_scan
    from app.api.websocket import manager
    from app.core.instruments import priority_scan_list, all_symbols, TESTING_FOCUS

    scan_symbols = symbols or priority_scan_list()
    # Enforce testing focus — never scan outside the configured focus set
    if TESTING_FOCUS:
        scan_symbols = [s for s in scan_symbols if s in TESTING_FOCUS] or list(TESTING_FOCUS)
    scan_tfs = timeframes or ["15m", "1h", "4h", "daily"]

    result = await run_full_scan(
        symbols=scan_symbols,
        timeframes=scan_tfs,
        broadcast_fn=manager.broadcast,
        db=db,
    )

    # Persist signals
    from app.models.signals import Signal, SignalStatus
    from datetime import timedelta
    from sqlalchemy import and_

    created = []
    valid_until = datetime.utcnow() + timedelta(hours=24)
    for s in result["signals"]:
        # Expire any active signal for the same pattern+underlying with a different direction
        # (e.g. max_pain flipped from long to short) before inserting the new one.
        await db.execute(
            __import__("sqlalchemy", fromlist=["update"]).update(Signal)
            .where(and_(
                Signal.underlying == s["underlying"],
                Signal.pattern_name == s["pattern_name"],
                Signal.direction != s["direction"],
                Signal.status == SignalStatus.ACTIVE,
            ))
            .values(status=SignalStatus.EXPIRED)
        )
        # Skip if an ACTIVE signal with the same key already exists (no time limit).
        dup_q = select(Signal).where(and_(
            Signal.underlying == s["underlying"],
            Signal.pattern_name == s["pattern_name"],
            Signal.direction == s["direction"],
            Signal.status == SignalStatus.ACTIVE,
        ))
        dup = (await db.execute(dup_q)).scalars().first()
        if dup:
            continue
        sig = Signal(
            pattern_name=s["pattern_name"], pattern_version=s.get("pattern_version", "1.0"),
            symbol=s.get("symbol", s["underlying"]), underlying=s["underlying"],
            instrument=s.get("instrument", s["underlying"]), direction=s["direction"],
            entry_price=s["entry_price"], target_price=s["target_price"], stop_loss=s["stop_loss"],
            expected_return_pct=s["expected_return_pct"], confidence_score=s["confidence_score"],
            explanation=s.get("explanation", ""), trading_style=s.get("trading_style", "intraday"),
            status=SignalStatus.ACTIVE, created_at=datetime.utcnow(), valid_until=valid_until,
            option_type=s.get("option_type"), strike=s.get("strike"),
            expiry_date_str=s.get("expiry_date_str"),
            expiry_date_iso=s.get("expiry_date_iso"),
            expiry_display=s.get("expiry_display"),
            expiry_dte=s.get("expiry_dte"),
            expiry_series=s.get("expiry_series"),
            option_strategy=s.get("option_strategy"),
            lot_size=s.get("lot_size"), delta=s.get("delta"), gamma=s.get("gamma"),
            theta=s.get("theta"), vega=s.get("vega"), iv_at_signal=s.get("iv_at_signal"),
            iv_rank=s.get("iv_rank"), regime_trend=s.get("regime_trend"),
            regime_volatility=s.get("regime_volatility"), estimated_premium=s.get("estimated_premium"),
            max_loss=s.get("max_loss"), timeframe=s.get("timeframe"),
        )
        db.add(sig)
        created.append(sig)

    if created:
        await db.commit()
        for sig in created:
            await db.refresh(sig)
        # Auto-execute paper trades for high-confidence signals
        from app.workers.tasks import _auto_paper_trade
        await _auto_paper_trade(created, db)

    return {
        "symbols_scanned": result["symbols_scanned"],
        "timeframes": result["timeframes"],
        "signals_found": result["signals_found"],
        "signals_new": len(created),
        "duration_ms": result["duration_ms"],
    }


@router.get("/{signal_id}")
async def get_signal(signal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(404, "Signal not found")
    return _safe_dict(signal)


@router.post("/run")
async def run_signals(
    underlying: str,
    patterns: list[str] | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Run pattern detection with regime and options enrichment, persist signals to DB."""
    from app.core.instruments import TESTING_FOCUS
    if TESTING_FOCUS and underlying not in TESTING_FOCUS:
        raise HTTPException(400, f"Testing focus active: only {TESTING_FOCUS} allowed")

    # ── 1. Fetch OHLCV ────────────────────────────────────────────────────────
    ohlcv: pd.DataFrame
    data_source: str

    use_kite = (
        settings.app_mode != AppMode.TESTING
        and settings.kite_api_key
        and settings.kite_access_token
    )

    if use_kite:
        try:
            from app.core.data.kite_adapter import KiteAdapter
            adapter = KiteAdapter()
            instruments_df = adapter.get_instruments("NFO")
            fut = instruments_df[
                instruments_df["name"].str.upper() == underlying.upper()
            ].sort_values("expiry").head(1)
            if fut.empty:
                raise ValueError(f"No NFO instrument found for {underlying}")
            token = int(fut.iloc[0]["instrument_token"])
            from datetime import timedelta as td
            ohlcv = adapter.get_historical(token, date.today() - td(days=180), date.today())
            data_source = "kite"
        except Exception as exc:
            ohlcv = _synthetic_ohlcv(underlying)
            data_source = f"synthetic (kite error: {exc})"
    else:
        ohlcv = _synthetic_ohlcv(underlying)
        data_source = "synthetic (testing mode)"

    if ohlcv.empty or len(ohlcv) < 30:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient OHLCV data for {underlying} (source: {data_source})"
        )

    spot_price = float(ohlcv["close"].iloc[-1])

    # ── 2. Detect regime ──────────────────────────────────────────────────────
    try:
        regime = RegimeDetector().detect(ohlcv)
    except Exception as e:
        regime = {"trend": "ranging", "volatility": "normal", "adx": 20.0,
                  "india_vix_proxy": 15.0, "suitable_patterns": []}

    # ── 3. Get options chain ──────────────────────────────────────────────────
    chain_svc = ChainService()
    chain_df = chain_svc.get_chain(underlying)

    # ── 4. Compute IV rank ────────────────────────────────────────────────────
    iv_history = chain_svc.get_iv_history(underlying)
    current_iv = float(ohlcv["iv"].iloc[-1]) if "iv" in ohlcv.columns else 18.0
    iv_rank_val = IVRankService.iv_rank(current_iv, iv_history)
    iv_pct = IVRankService.iv_percentile(current_iv, iv_history)
    iv_regime_str = IVRankService.iv_regime(iv_rank_val)
    strategy_bias = IVRankService.strategy_bias(iv_rank_val)

    # ── 5. Check event calendar ───────────────────────────────────────────────
    cal = EventCalendar()
    today = date.today()
    event_risk = cal.is_event_risk(today)
    upcoming_events = cal.next_events(today, count=3)
    event_warning = ""
    if event_risk:
        event_warning = "⚠️ Event risk: major market event within 2 days — reduce position size."

    # ── 6. Build context for patterns ─────────────────────────────────────────
    context = {
        "iv_rank": iv_rank_val,
        "regime": regime,
    }

    # ── 7. Run signal generator ───────────────────────────────────────────────
    # Use regime-suitable patterns as soft filter (boost confidence), not hard gate
    generator = SignalGenerator()
    raw_signals = generator.run(
        ohlcv,
        options_chain=chain_df,
        underlying=underlying,
        pattern_filter=patterns or None,
        context=context,
    )

    # ── 8. Compute max pain ───────────────────────────────────────────────────
    try:
        max_pain_result = compute_max_pain(chain_df[["strike", "ce_oi", "pe_oi"]])
    except Exception:
        max_pain_result = {"max_pain_strike": None, "pcr": None, "total_oi": None}

    if not raw_signals:
        return {
            "message": f"No patterns detected for {underlying}",
            "underlying": underlying,
            "data_source": data_source,
            "signals_created": 0,
            "regime": regime,
            "iv_rank": round(iv_rank_val, 4),
            "iv_percentile": round(iv_pct, 4),
            "iv_regime": iv_regime_str,
            "strategy_bias": strategy_bias,
            "max_pain": max_pain_result,
            "upcoming_events": upcoming_events,
            "event_warning": event_warning,
        }

    # ── 9. Expire all active signals for the same underlying+pattern (any direction) ──
    # A new scan result supersedes whatever direction was signalled before, so we
    # expire the whole pattern bucket to avoid contradictory signals accumulating.
    new_pattern_names = {s.pattern_name for s in raw_signals}
    if new_pattern_names:
        old_q = select(Signal).where(
            Signal.underlying == underlying,
            Signal.status == SignalStatus.ACTIVE,
            Signal.pattern_name.in_(list(new_pattern_names)),
        )
        old_result = await db.execute(old_q)
        for old_sig in old_result.scalars().all():
            old_sig.status = SignalStatus.EXPIRED

    # ── 10. Persist enriched signals ──────────────────────────────────────────
    selector = StrikeSelector()
    created = []
    valid_until = datetime.utcnow() + timedelta(hours=24)
    dte = 7  # default DTE — weekly expiry

    for s in raw_signals:
        # Pick option contract
        try:
            opt = selector.select(
                underlying=underlying,
                spot_price=spot_price,
                direction=s.direction,
                iv_rank=iv_rank_val,
                dte=dte,
                pattern_name=s.pattern_name,
            )
        except Exception:
            opt = {
                "instrument": s.instrument or f"{underlying}_FUT",
                "option_type": None, "strategy": None,
                "strike": None, "expiry_date_str": None,
                "lot_size": None, "reasoning": "",
            }

        # Compute Greeks for the selected strike
        greeks_data = {}
        if opt.get("strike") and opt.get("option_type"):
            try:
                T = dte / 365.0
                sigma = current_iv / 100.0
                g = compute_greeks(spot_price, opt["strike"], T, sigma, opt["option_type"], RISK_FREE_RATE)
                greeks_data = {
                    "delta": round(g.delta, 4),
                    "gamma": round(g.gamma, 6),
                    "theta": round(g.theta, 4),
                    "vega": round(g.vega, 4),
                }
                estimated_premium = abs(g.delta) * spot_price * 0.02  # rough estimate
                max_loss_val = estimated_premium * (opt.get("lot_size") or 25)
            except Exception:
                greeks_data = {}
                estimated_premium = None
                max_loss_val = None
        else:
            estimated_premium = None
            max_loss_val = None

        # Build explanation with event warning
        explanation = s.explanation
        if event_warning:
            explanation = f"{event_warning}\n\n{explanation}"
        if opt.get("reasoning"):
            explanation = f"{explanation}\n\nOption selection: {opt['reasoning']}"

        sig = Signal(
            pattern_name        = s.pattern_name,
            pattern_version     = s.pattern_version,
            symbol              = s.symbol or underlying,
            underlying          = underlying,
            instrument          = opt.get("instrument") or s.instrument or underlying,
            direction           = s.direction,
            entry_price         = round(s.entry_price, 2),
            target_price        = round(s.target_price, 2),
            stop_loss           = round(s.stop_loss, 2),
            expected_return_pct = round(s.expected_return_pct, 2),
            confidence_score    = round(s.confidence_score, 4),
            explanation         = explanation,
            trading_style       = s.trading_style,
            status              = SignalStatus.ACTIVE,
            created_at          = datetime.utcnow(),
            valid_until         = valid_until,
            # Options fields
            option_type         = opt.get("option_type"),
            strike              = opt.get("strike"),
            expiry_date_str     = opt.get("expiry_date_str") or opt.get("expiry", {}).get("short"),
            expiry_date_iso     = opt.get("expiry_date") or opt.get("expiry", {}).get("date"),
            expiry_display      = opt.get("expiry_display") or opt.get("expiry", {}).get("display"),
            expiry_dte          = opt.get("expiry_dte") or opt.get("expiry", {}).get("dte"),
            expiry_series       = opt.get("expiry_series") or opt.get("expiry", {}).get("series"),
            option_strategy     = opt.get("strategy"),
            lot_size            = opt.get("lot_size"),
            delta               = greeks_data.get("delta"),
            gamma               = greeks_data.get("gamma"),
            theta               = greeks_data.get("theta"),
            vega                = greeks_data.get("vega"),
            iv_at_signal        = round(current_iv, 4),
            iv_rank             = round(iv_rank_val, 4),
            regime_trend        = regime.get("trend"),
            regime_volatility   = regime.get("volatility"),
            estimated_premium   = round(estimated_premium, 2) if estimated_premium else None,
            max_loss            = round(max_loss_val, 2) if max_loss_val else None,
        )
        db.add(sig)
        created.append(sig)

    await db.commit()
    for sig in created:
        await db.refresh(sig)

    return {
        "message": f"Scan complete — {len(created)} signal(s) generated for {underlying}",
        "underlying": underlying,
        "data_source": data_source,
        "signals_created": len(created),
        "regime": regime,
        "iv_rank": round(iv_rank_val, 4),
        "iv_percentile": round(iv_pct, 4),
        "iv_regime": iv_regime_str,
        "strategy_bias": strategy_bias,
        "max_pain": max_pain_result,
        "upcoming_events": upcoming_events,
        "event_warning": event_warning,
        "signals": [s.__dict__ for s in created],
    }
