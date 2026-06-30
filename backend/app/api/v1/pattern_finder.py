"""Pattern Finder API — backtest management and live pattern alerts."""
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from app.database import get_db
from app.models.pattern_backtest import PatternBacktest, PatternTrade, BacktestStatus
from datetime import date, timedelta
from loguru import logger

router = APIRouter()

# ── In-memory discovery progress (single-process — one job at a time) ─────────
_disc_progress: dict = {
    "running":     False,
    "pct":         0,
    "step":        "",
    "done_steps":  0,
    "total_steps": 0,
    "found":       0,
    "with_edge":   0,
    "started_at":  None,
    "finished_at": None,
}

def _prog(**kw):
    _disc_progress.update(kw)


def _bt_dict(b: PatternBacktest) -> dict:
    return {
        "id":             b.id,
        "created_at":     b.created_at.isoformat() if b.created_at else None,
        "completed_at":   b.completed_at.isoformat() if b.completed_at else None,
        "underlying":     b.underlying,
        "pattern_name":   b.pattern_name,
        "timeframe":      b.timeframe,
        "date_from":      b.date_from,
        "date_to":        b.date_to,
        "bars_tested":    b.bars_tested,
        "total_signals":  b.total_signals,
        "trades_taken":   b.trades_taken,
        "winning_trades": b.winning_trades,
        "losing_trades":  b.losing_trades,
        "win_rate":       b.win_rate,
        "profit_factor":  b.profit_factor,
        "avg_winner":     b.avg_winner,
        "avg_loser":      b.avg_loser,
        "total_net_pnl":  b.total_net_pnl,
        "max_drawdown_pct": b.max_drawdown_pct,
        "sharpe_ratio":   b.sharpe_ratio,
        "avg_holding_bars": b.avg_holding_bars,
        "status":         b.status,
        "data_source":    b.data_source,
        "error_message":  b.error_message,
        "has_edge":       (
            (b.win_rate or 0) >= 0.52 and
            (b.profit_factor or 0) >= 1.3 and
            (b.trades_taken or 0) >= 10
        ),
    }


@router.post("/run")
async def run_backtest(
    underlyings: list[str] | None = None,
    patterns:    list[str] | None = None,
    timeframes:  list[str] | None = None,
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
):
    """Kick off a backtest. Runs in background, returns run IDs immediately."""
    from app.core.patterns.registry import PatternRegistry
    from app.core.instruments import priority_scan_list

    syms = [s.upper() for s in (underlyings or priority_scan_list()[:5])]
    pats = patterns or [p.name for p in PatternRegistry.get().all()]
    tfs  = timeframes or ["daily", "1h"]

    created_ids = []
    today = date.today().isoformat()
    year_ago = (date.today() - timedelta(days=365)).isoformat()

    for sym in syms:
        for pat in pats:
            for tf in tfs:
                # Don't re-run if a recent completed run exists (< 7 days old)
                existing = await db.execute(
                    select(PatternBacktest).where(
                        PatternBacktest.underlying   == sym,
                        PatternBacktest.pattern_name == pat,
                        PatternBacktest.timeframe    == tf,
                        PatternBacktest.status       == BacktestStatus.COMPLETE,
                    ).order_by(desc(PatternBacktest.created_at)).limit(1)
                )
                ex = existing.scalar_one_or_none()
                if ex and ex.created_at and (date.today() - ex.created_at.date()).days < 7:
                    created_ids.append(ex.id)
                    continue

                bt = PatternBacktest(
                    underlying=sym, pattern_name=pat, timeframe=tf,
                    date_from=year_ago, date_to=today,
                    status=BacktestStatus.PENDING,
                )
                db.add(bt)
                await db.flush()
                created_ids.append(bt.id)

    await db.commit()

    # Run in background
    if background_tasks:
        background_tasks.add_task(_run_backtests_bg, created_ids)

    return {"run_ids": created_ids, "count": len(created_ids), "message": "Backtests queued"}


async def _run_backtests_bg(run_ids: list[int]):
    """Background worker: runs each backtest and saves results."""
    from app.core.backtest.engine import run_backtest as _engine
    from app.database import AsyncSessionLocal
    from datetime import datetime

    async with AsyncSessionLocal() as db:
        for bt_id in run_ids:
            result_q = await db.execute(select(PatternBacktest).where(PatternBacktest.id == bt_id))
            bt = result_q.scalar_one_or_none()
            if not bt or bt.status == BacktestStatus.COMPLETE:
                continue

            bt.status = BacktestStatus.RUNNING
            await db.commit()

            try:
                result = await _engine(bt.underlying, bt.pattern_name, bt.timeframe)

                bt.bars_tested      = result.bars_tested
                bt.total_signals    = result.total_signals
                bt.trades_taken     = result.trades_taken
                bt.winning_trades   = result.winning_trades
                bt.losing_trades    = result.losing_trades
                bt.win_rate         = result.win_rate
                bt.profit_factor    = result.profit_factor
                bt.avg_winner       = result.avg_winner
                bt.avg_loser        = result.avg_loser
                bt.total_net_pnl    = result.total_net_pnl
                bt.max_drawdown_pct = result.max_drawdown_pct
                bt.sharpe_ratio     = result.sharpe_ratio
                bt.avg_holding_bars = result.avg_holding_bars
                bt.data_source      = result.data_source
                bt.status           = BacktestStatus.COMPLETE
                bt.completed_at     = datetime.utcnow()

                # Save individual trades
                for t in result.trades:
                    pt = PatternTrade(
                        backtest_id   = bt.id,
                        underlying    = bt.underlying,
                        pattern_name  = bt.pattern_name,
                        timeframe     = bt.timeframe,
                        signal_date   = t["signal_date"],
                        direction     = t["direction"],
                        option_type   = t["option_type"],
                        strike        = t["strike"],
                        expiry_dte    = t["expiry_dte"],
                        spot_at_entry = t["spot_at_entry"],
                        entry_price   = t["entry_price"],
                        exit_price    = t["exit_price"],
                        exit_reason   = t["exit_reason"],
                        holding_bars  = t["holding_bars"],
                        gross_pnl     = t["gross_pnl"],
                        charges       = t["charges"],
                        net_pnl       = t["net_pnl"],
                        pnl_pct       = t["pnl_pct"],
                        iv_at_entry   = t["iv_at_entry"],
                        confidence    = t["confidence"],
                    )
                    db.add(pt)

                await db.commit()

            except Exception as e:
                bt.status = BacktestStatus.FAILED
                bt.error_message = str(e)
                await db.commit()


@router.get("/runs")
async def list_runs(
    underlying: str | None = None,
    pattern_name: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    q = select(PatternBacktest).order_by(desc(PatternBacktest.created_at)).limit(limit)
    if underlying:
        q = q.where(PatternBacktest.underlying == underlying.upper())
    if pattern_name:
        q = q.where(PatternBacktest.pattern_name == pattern_name)
    rows = (await db.execute(q)).scalars().all()
    return {"runs": [_bt_dict(r) for r in rows], "count": len(rows)}


@router.get("/performance")
async def pattern_performance(db: AsyncSession = Depends(get_db)):
    """
    Summary table: best pattern × timeframe combos ranked by profit factor.
    Only includes runs with ≥10 trades and COMPLETE status.
    """
    q = (
        select(PatternBacktest)
        .where(
            PatternBacktest.status      == BacktestStatus.COMPLETE,
            PatternBacktest.trades_taken >= 10,
        )
        .order_by(desc(PatternBacktest.profit_factor))
        .limit(200)
    )
    rows = (await db.execute(q)).scalars().all()

    # Deduplicate: keep best run per (underlying, pattern, timeframe)
    seen: dict[tuple, PatternBacktest] = {}
    for r in rows:
        key = (r.underlying, r.pattern_name, r.timeframe)
        if key not in seen or (r.profit_factor or 0) > (seen[key].profit_factor or 0):
            seen[key] = r

    results = sorted(seen.values(), key=lambda x: (x.profit_factor or 0), reverse=True)
    return {
        "patterns": [_bt_dict(r) for r in results],
        "count": len(results),
        "proven_count": sum(1 for r in results if (r.win_rate or 0) >= 0.52 and (r.profit_factor or 0) >= 1.3),
    }


@router.get("/trades/{backtest_id}")
async def backtest_trades(backtest_id: int, db: AsyncSession = Depends(get_db)):
    """Return all simulated trades for a backtest run."""
    bt_q = await db.execute(select(PatternBacktest).where(PatternBacktest.id == backtest_id))
    bt = bt_q.scalar_one_or_none()
    if not bt:
        raise HTTPException(404, "Backtest not found")

    trades_q = await db.execute(
        select(PatternTrade)
        .where(PatternTrade.backtest_id == backtest_id)
        .order_by(PatternTrade.signal_date)
    )
    trades = trades_q.scalars().all()

    def _t(t: PatternTrade) -> dict:
        return {
            "id": t.id, "signal_date": t.signal_date, "direction": t.direction,
            "option_type": t.option_type, "strike": t.strike, "expiry_dte": t.expiry_dte,
            "spot_at_entry": t.spot_at_entry, "entry_price": t.entry_price,
            "exit_price": t.exit_price, "exit_reason": t.exit_reason,
            "holding_bars": t.holding_bars, "gross_pnl": t.gross_pnl,
            "charges": t.charges, "net_pnl": t.net_pnl, "pnl_pct": t.pnl_pct,
            "iv_at_entry": t.iv_at_entry, "confidence": t.confidence,
        }

    return {"backtest": _bt_dict(bt), "trades": [_t(t) for t in trades]}


@router.get("/live-alerts")
async def live_alerts(db: AsyncSession = Depends(get_db)):
    """
    Patterns that are firing TODAY on live data AND have proven historical edge.
    Returns signals tagged with backtest stats so the UI can show confidence.
    """
    from app.models.signals import Signal, SignalStatus
    from sqlalchemy import and_
    from datetime import datetime, timedelta as _td

    cutoff = datetime.utcnow() - _td(hours=6)

    # Fresh signals from last 6 hours
    sigs_q = await db.execute(
        select(Signal).where(
            Signal.status    == SignalStatus.ACTIVE,
            Signal.created_at >= cutoff,
        ).order_by(desc(Signal.confidence_score)).limit(50)
    )
    signals = sigs_q.scalars().all()

    # Look up backtest performance for each signal's (underlying, pattern, timeframe)
    alerts = []
    for sig in signals:
        tf = sig.timeframe or "daily"
        bt_q = await db.execute(
            select(PatternBacktest).where(
                PatternBacktest.underlying   == sig.underlying,
                PatternBacktest.pattern_name == sig.pattern_name,
                PatternBacktest.timeframe    == tf,
                PatternBacktest.status       == BacktestStatus.COMPLETE,
                PatternBacktest.trades_taken >= 10,
            ).order_by(desc(PatternBacktest.created_at)).limit(1)
        )
        bt = bt_q.scalar_one_or_none()

        has_edge = bt and (bt.win_rate or 0) >= 0.52 and (bt.profit_factor or 0) >= 1.3
        alerts.append({
            "signal_id":      sig.id,
            "underlying":     sig.underlying,
            "pattern_name":   sig.pattern_name,
            "direction":      sig.direction,
            "option_type":    sig.option_type,
            "strike":         sig.strike,
            "expiry_display": sig.expiry_display,
            "confidence":     sig.confidence_score,
            "estimated_premium": sig.estimated_premium,
            "explanation":    sig.explanation,
            "created_at":     sig.created_at.isoformat(),
            "has_edge":       has_edge,
            "backtest": {
                "win_rate":      bt.win_rate,
                "profit_factor": bt.profit_factor,
                "trades_taken":  bt.trades_taken,
                "total_net_pnl": bt.total_net_pnl,
                "sharpe_ratio":  bt.sharpe_ratio,
                "data_source":   bt.data_source,
            } if bt else None,
        })

    return {
        "alerts": alerts,
        "proven_count": sum(1 for a in alerts if a["has_edge"]),
        "total": len(alerts),
    }


@router.delete("/runs/{backtest_id}")
async def delete_run(backtest_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete as _del
    await db.execute(_del(PatternTrade).where(PatternTrade.backtest_id == backtest_id))
    await db.execute(_del(PatternBacktest).where(PatternBacktest.id == backtest_id))
    await db.commit()
    return {"deleted": backtest_id}


# ── Auto-discovery endpoints ──────────────────────────────────────────────────

def _dp_dict(p, backtest_id: int | None = None) -> dict:
    from app.core.patterns.composite import generate_display_name
    display_name = generate_display_name(
        p.features if isinstance(p.features, list) else [],
        p.direction,
        p.underlying,
    )
    return {
        "id":           p.id,
        "created_at":   p.created_at.isoformat() if p.created_at else None,
        "underlying":   p.underlying,
        "timeframe":    p.timeframe,
        "pattern_slug": p.pattern_slug,
        "display_name": display_name,
        "features":     p.features,
        "backtest_id":  backtest_id,
        "direction":    p.direction,
        "option_type":  p.option_type,
        "n_samples":    p.n_samples,
        "win_rate":     p.win_rate,
        "mean_fwd_ret": p.mean_fwd_ret,
        "p_value":      p.p_value,
        "effect_size":  p.effect_size,
        "source":       p.source,
        "explanation":  p.explanation,
        "active":       p.active,
        "has_edge":     p.has_edge,
        "last_backtest_win_rate":      p.last_backtest_win_rate,
        "last_backtest_profit_factor": p.last_backtest_profit_factor,
        "last_backtest_trades":        p.last_backtest_trades,
        "last_backtest_net_pnl":       p.last_backtest_net_pnl,
        "last_backtest_at": p.last_backtest_at.isoformat() if p.last_backtest_at else None,
    }


@router.post("/discover")
async def discover_patterns(
    underlyings: list[str] | None = None,
    timeframes:  list[str] | None = None,
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Kick off automated pattern discovery for the given instruments.
    Runs two algorithms in the background:
      1. Statistical miner   — exhaustive feature-combo significance testing
      2. Decision tree       — train on existing PatternTrade win/loss data
    Discovered patterns are walk-forward backtested and those with edge are
    auto-wired into the live scanner.
    """
    from app.core.instruments import priority_scan_list
    syms = [s.upper() for s in (underlyings or priority_scan_list()[:5])]
    tfs  = timeframes or ["daily", "1h"]

    if background_tasks:
        background_tasks.add_task(_run_discovery_bg, syms, tfs)

    return {
        "message":     "Discovery queued",
        "instruments": syms,
        "timeframes":  tfs,
        "algorithms":  ["statistical", "decision_tree"],
    }


@router.get("/discover/progress")
async def discover_progress():
    """Poll this while discovery is running to get live progress."""
    return _disc_progress


async def _run_discovery_bg(underlyings: list[str], timeframes: list[str]):
    """
    Mine patterns and persist them. DB session is opened only for the
    quick persist step and closed immediately after — never held open
    during slow network I/O or CPU-bound computation.

    Walk-forward backtests run as a separate fire-and-forget task so
    the app stays responsive throughout.
    """
    import asyncio as _asyncio
    from datetime import datetime
    from app.core.backtest.historical_data import fetch_historical_best
    from app.core.backtest.miner import mine_statistical_patterns
    from app.core.backtest.dt_analyzer import run_dt_analysis
    from app.models.discovered_pattern import DiscoveredPattern
    from app.database import AsyncSessionLocal
    from sqlalchemy import select

    combos      = [(u, tf) for u in underlyings for tf in timeframes]
    total_steps = len(combos) * 2   # fetch + mine per combo (backtest is separate)
    done        = 0

    _prog(running=True, pct=0, step="Starting…", done_steps=0,
          total_steps=total_steps, found=0, with_edge=0,
          started_at=datetime.utcnow().isoformat(), finished_at=None)

    for underlying, tf in combos:
        try:
            # ── 1. Fetch data (network I/O — no DB session open) ────────────
            _prog(step=f"{underlying}/{tf} — fetching {tf} data",
                  pct=int(done / total_steps * 100))
            df, data_source = await fetch_historical_best(underlying, tf)
            done += 1
            if df is None or len(df) < 60:
                logger.warning(f"Discovery: not enough data for {underlying}/{tf}")
                done += 1
                _prog(done_steps=done, pct=int(done / total_steps * 100))
                continue
            logger.info(f"Discovery: {underlying}/{tf} — {data_source} ({len(df)} bars)")

            # ── 2. Mine (CPU-bound — runs in thread, event loop free) ────────
            _prog(step=f"{underlying}/{tf} — mining patterns ({len(df)} bars)",
                  done_steps=done, pct=int(done / total_steps * 100))
            stat_rules = await _asyncio.get_event_loop().run_in_executor(
                None, mine_statistical_patterns, df, underlying, tf
            )
            all_rules = list(stat_rules)

            # DT analysis (uses existing trade history) — short DB session
            async with AsyncSessionLocal() as db_dt:
                from app.models.pattern_backtest import PatternTrade as _PT
                tq = await db_dt.execute(select(_PT).where(_PT.underlying == underlying))
                existing_trades = [
                    {"signal_date": t.signal_date, "net_pnl": t.net_pnl,
                     "pnl_pct": t.pnl_pct, "direction": t.direction}
                    for t in tq.scalars().all()
                ]
            if len(existing_trades) >= 20:
                dt_rules = await run_dt_analysis(existing_trades, underlying, tf)
                all_rules.extend(dt_rules)

            done += 1

            # ── 3. Persist — short DB session, then close immediately ────────
            async with AsyncSessionLocal() as db_save:
                for rule in all_rules:
                    from app.core.patterns.composite import composite_from_rule
                    cp   = composite_from_rule(rule)
                    slug = cp.name
                    eq   = await db_save.execute(
                        select(DiscoveredPattern).where(DiscoveredPattern.pattern_slug == slug)
                    )
                    dp_existing = eq.scalar_one_or_none()
                    if dp_existing:
                        dp_existing.win_rate     = rule.win_rate
                        dp_existing.n_samples    = rule.n_samples
                        dp_existing.mean_fwd_ret = rule.mean_fwd_ret
                        dp_existing.p_value      = rule.p_value
                        dp_existing.effect_size  = rule.effect_size
                        dp_existing.explanation  = rule.explanation
                        dp_existing.updated_at   = datetime.utcnow()
                    else:
                        db_save.add(DiscoveredPattern(
                            underlying   = underlying,
                            timeframe    = tf,
                            pattern_slug = slug,
                            features     = rule.features,
                            direction    = rule.direction,
                            option_type  = rule.option_type,
                            n_samples    = rule.n_samples,
                            win_rate     = rule.win_rate,
                            mean_fwd_ret = rule.mean_fwd_ret,
                            p_value      = rule.p_value,
                            effect_size  = rule.effect_size,
                            source       = rule.source,
                            explanation  = rule.explanation,
                        ))
                await db_save.commit()

            _prog(found=_disc_progress["found"] + len(all_rules),
                  done_steps=done, pct=int(done / total_steps * 100))
            logger.info(
                f"Discovery: {underlying}/{tf} — "
                f"{len(stat_rules)} stat + {len(all_rules) - len(stat_rules)} DT rules persisted"
            )

        except Exception as e:
            logger.error(f"Discovery failed {underlying}/{tf}: {e}")
            done = min(done + 1, total_steps)
            _prog(done_steps=done, pct=int(done / total_steps * 100))

        # Yield to event loop between combos
        await _asyncio.sleep(0)

    _prog(running=False, pct=100, step=f"Complete — {_disc_progress['found']} patterns discovered",
          done_steps=total_steps, finished_at=datetime.utcnow().isoformat())


async def _backtest_all_discovered(underlyings: list[str], timeframes: list[str]):
    """
    Walk-forward backtest the top discovered patterns. Runs after discovery
    completes, uses short-lived sessions per pattern so the DB pool stays free.
    """
    import asyncio as _asyncio
    from app.database import AsyncSessionLocal
    from app.models.discovered_pattern import DiscoveredPattern
    from sqlalchemy import select, desc

    for underlying in underlyings:
        for tf in timeframes:
            async with AsyncSessionLocal() as db:
                dp_q = await db.execute(
                    select(DiscoveredPattern).where(
                        DiscoveredPattern.underlying == underlying,
                        DiscoveredPattern.timeframe  == tf,
                        DiscoveredPattern.active     == True,
                    ).order_by(desc(DiscoveredPattern.effect_size)).limit(3)
                )
                patterns = dp_q.scalars().all()

            for dp in patterns:
                try:
                    await _asyncio.sleep(0)   # yield between each backtest
                    await _backtest_one(dp)
                except Exception as e:
                    logger.warning(f"Backtest skipped {dp.pattern_slug}: {e}")

    # Update with_edge count in progress
    async with AsyncSessionLocal() as db:
        from sqlalchemy import func
        eq = await db.execute(
            select(func.count()).where(DiscoveredPattern.has_edge == True)
        )
        edge_n = eq.scalar() or 0
    _prog(with_edge=edge_n, step="Complete")
    logger.info(f"Walk-forward backtests done — {edge_n} patterns with edge")


async def _backtest_one(dp):
    """Backtest a single DiscoveredPattern with its own DB session."""
    from datetime import datetime, date as _date
    from app.database import AsyncSessionLocal
    from app.models.discovered_pattern import DiscoveredPattern
    from app.models.pattern_backtest import PatternBacktest, PatternTrade, BacktestStatus
    from app.core.backtest.engine import run_backtest as _engine
    from app.core.patterns.composite import composite_from_rule
    from app.core.backtest.miner import DiscoveredRule
    from sqlalchemy import select, delete as _del

    rule = DiscoveredRule(
        features    = dp.features,
        direction   = dp.direction,
        underlying  = dp.underlying,
        timeframe   = dp.timeframe,
        n_samples   = dp.n_samples,
        win_rate    = dp.win_rate,
        mean_fwd_ret= dp.mean_fwd_ret,
        p_value     = dp.p_value or 0.0,
        effect_size = dp.effect_size,
        option_type = dp.option_type,
        explanation = dp.explanation,
        source      = dp.source,
    )
    cp     = composite_from_rule(rule)
    result = await _engine(dp.underlying, cp.name, dp.timeframe, pattern_override=cp)

    has_edge = (
        (result.win_rate or 0) >= 0.52 and
        (result.profit_factor or 0) >= 1.3 and
        (result.trades_taken or 0) >= 10
    )

    async with AsyncSessionLocal() as db:
        # Re-fetch the pattern within this session
        q  = await db.execute(select(DiscoveredPattern).where(DiscoveredPattern.id == dp.id))
        dp2 = q.scalar_one_or_none()
        if dp2 is None:
            return

        dp2.last_backtest_win_rate      = result.win_rate
        dp2.last_backtest_profit_factor = result.profit_factor
        dp2.last_backtest_trades        = result.trades_taken
        dp2.last_backtest_net_pnl       = result.total_net_pnl
        dp2.last_backtest_at            = datetime.utcnow()
        dp2.has_edge                    = has_edge

        today = _date.today().isoformat()
        await db.execute(_del(PatternTrade).where(
            PatternTrade.backtest_id.in_(
                select(PatternBacktest.id).where(PatternBacktest.pattern_name == cp.name)
            )
        ))
        await db.execute(_del(PatternBacktest).where(PatternBacktest.pattern_name == cp.name))
        bt = PatternBacktest(
            underlying      = dp.underlying,
            pattern_name    = cp.name,
            timeframe       = dp.timeframe,
            date_from       = today, date_to = today,
            bars_tested     = result.bars_tested,
            total_signals   = result.total_signals,
            trades_taken    = result.trades_taken,
            winning_trades  = result.winning_trades,
            losing_trades   = result.losing_trades,
            win_rate        = result.win_rate,
            profit_factor   = result.profit_factor,
            avg_winner      = result.avg_winner,
            avg_loser       = result.avg_loser,
            total_net_pnl   = result.total_net_pnl,
            max_drawdown_pct= result.max_drawdown_pct,
            sharpe_ratio    = result.sharpe_ratio,
            avg_holding_bars= result.avg_holding_bars,
            status          = BacktestStatus.COMPLETE,
            data_source     = result.data_source,
            completed_at    = datetime.utcnow(),
        )
        db.add(bt)
        await db.flush()
        for t in result.trades:
            db.add(PatternTrade(
                backtest_id    = bt.id,
                underlying     = dp.underlying,
                pattern_name   = cp.name,
                timeframe      = dp.timeframe,
                signal_date    = t["signal_date"],
                direction      = t["direction"],
                option_type    = t["option_type"],
                strike         = t.get("strike"),
                expiry_dte     = t.get("expiry_dte"),
                spot_at_entry  = t.get("spot_at_entry"),
                entry_price    = t["entry_price"],
                exit_price     = t["exit_price"],
                exit_reason    = t["exit_reason"],
                holding_bars   = t.get("holding_bars", 0),
                gross_pnl      = t["gross_pnl"],
                charges        = t["charges"],
                net_pnl        = t["net_pnl"],
                pnl_pct        = t.get("pnl_pct", 0.0),
                iv_at_entry    = t.get("iv_at_entry"),
                confidence     = t.get("confidence"),
            ))
        await db.commit()
    logger.info(f"Backtest {cp.name}: WR={result.win_rate:.0%} PF={result.profit_factor:.1f} edge={has_edge}")




@router.get("/discovered")
async def list_discovered(
    underlying:  str | None = None,
    only_active: bool = True,
    only_edge:   bool = False,
    db: AsyncSession = Depends(get_db),
):
    """List all auto-discovered patterns, optionally filtered."""
    from app.models.discovered_pattern import DiscoveredPattern
    from app.models.pattern_backtest import PatternBacktest
    from sqlalchemy import select, desc

    q = select(DiscoveredPattern).order_by(
        DiscoveredPattern.underlying.asc(),
        DiscoveredPattern.timeframe.asc(),
        desc(DiscoveredPattern.effect_size),
    )
    if underlying:
        q = q.where(DiscoveredPattern.underlying == underlying.upper())
    if only_active:
        q = q.where(DiscoveredPattern.active == True)
    if only_edge:
        q = q.where(DiscoveredPattern.has_edge == True)

    rows = (await db.execute(q)).scalars().all()

    # Fetch backtest_ids for all pattern slugs in one query
    slugs = [r.pattern_slug for r in rows]
    bt_map: dict[str, int] = {}
    if slugs:
        bt_q = await db.execute(
            select(PatternBacktest.pattern_name, PatternBacktest.id)
            .where(PatternBacktest.pattern_name.in_(slugs))
            .order_by(desc(PatternBacktest.id))
        )
        for name, bid in bt_q.all():
            bt_map.setdefault(name, bid)   # keep first (latest) per slug

    return {
        "patterns":     [_dp_dict(r, bt_map.get(r.pattern_slug)) for r in rows],
        "count":        len(rows),
        "with_edge":    sum(1 for r in rows if r.has_edge),
        "statistical":  sum(1 for r in rows if r.source == "statistical"),
        "decision_tree":sum(1 for r in rows if r.source == "decision_tree"),
    }


@router.patch("/discovered/{pattern_id}/toggle")
async def toggle_discovered(pattern_id: int, db: AsyncSession = Depends(get_db)):
    """Enable or disable a discovered pattern from auto-execution."""
    from app.models.discovered_pattern import DiscoveredPattern
    from sqlalchemy import select

    q  = await db.execute(select(DiscoveredPattern).where(DiscoveredPattern.id == pattern_id))
    dp = q.scalar_one_or_none()
    if not dp:
        raise HTTPException(404, "Pattern not found")
    dp.active = not dp.active
    await db.commit()
    return {"id": pattern_id, "active": dp.active}


@router.delete("/discovered/all")
async def delete_all_discovered(db: AsyncSession = Depends(get_db)):
    """Delete all discovered patterns and their backtests in one shot."""
    from app.models.discovered_pattern import DiscoveredPattern
    from app.models.pattern_backtest import PatternBacktest, PatternTrade
    from sqlalchemy import delete as _del, select

    # Collect pattern slugs for cascade delete of backtests/trades
    slugs_q = await db.execute(select(DiscoveredPattern.pattern_slug))
    slugs   = [r[0] for r in slugs_q.all()]

    if slugs:
        # Delete trades → backtests → patterns (FK order)
        bt_ids_q = await db.execute(
            select(PatternBacktest.id).where(PatternBacktest.pattern_name.in_(slugs))
        )
        bt_ids = [r[0] for r in bt_ids_q.all()]
        if bt_ids:
            await db.execute(_del(PatternTrade).where(PatternTrade.backtest_id.in_(bt_ids)))
        await db.execute(_del(PatternBacktest).where(PatternBacktest.pattern_name.in_(slugs)))

    n = await db.execute(select(DiscoveredPattern))
    count = len(n.scalars().all())
    await db.execute(_del(DiscoveredPattern))
    await db.commit()

    # Reset progress state so the UI shows fresh
    _prog(running=False, pct=0, step="", done_steps=0, total_steps=0,
          found=0, with_edge=0, started_at=None, finished_at=None)

    return {"deleted": count}


@router.delete("/discovered/{pattern_id}")
async def delete_discovered(pattern_id: int, db: AsyncSession = Depends(get_db)):
    from app.models.discovered_pattern import DiscoveredPattern
    from sqlalchemy import delete as _del
    await db.execute(_del(DiscoveredPattern).where(DiscoveredPattern.id == pattern_id))
    await db.commit()
    return {"deleted": pattern_id}


@router.get("/discovered/{pattern_id}/chart")
async def discovered_pattern_chart(
    pattern_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Return OHLCV bars + list of dates where this pattern fired.
    Frontend uses this to render a candlestick chart with occurrence markers.
    """
    from app.models.discovered_pattern import DiscoveredPattern
    from app.core.backtest.engine import _fetch_historical, _TF_DAYS
    from app.core.backtest.features import compute_features
    import pandas as pd

    q = await db.execute(select(DiscoveredPattern).where(DiscoveredPattern.id == pattern_id))
    dp = q.scalar_one_or_none()
    if not dp:
        raise HTTPException(404, "Pattern not found")

    days = _TF_DAYS.get(dp.timeframe, 1825)
    df, source = await _fetch_historical(dp.underlying, dp.timeframe, days)
    if df is None or len(df) < 30:
        raise HTTPException(400, "Insufficient historical data")

    # Ensure timestamp column is a string-friendly datetime
    if "timestamp" not in df.columns:
        df = df.reset_index().rename(columns={"index": "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Compute boolean features and find occurrence bars
    feat = compute_features(df)
    required_features: list[str] = dp.features if isinstance(dp.features, list) else []

    mask = pd.Series(True, index=feat.index)
    for f in required_features:
        if f in feat.columns:
            mask = mask & feat[f].astype(bool)

    occ_set = set(df.loc[mask, "timestamp"].dt.strftime("%Y-%m-%d").tolist())

    bars = []
    for _, row in df.iterrows():
        ts = row["timestamp"].strftime("%Y-%m-%d")
        bars.append({
            "timestamp": ts,
            "open":      round(float(row["open"]),   2),
            "high":      round(float(row["high"]),   2),
            "low":       round(float(row["low"]),    2),
            "close":     round(float(row["close"]),  2),
            "volume":    int(row.get("volume", 0) or 0),
            "fired":     ts in occ_set,
        })

    occurrences = sorted(occ_set)

    return {
        "bars":          bars,
        "occurrences":   occurrences,
        "underlying":    dp.underlying,
        "timeframe":     dp.timeframe,
        "data_source":   source,
        "n_bars":        len(bars),
        "n_occurrences": len(occurrences),
        "features":      required_features,
        "explanation":   dp.explanation or "",
        "win_rate_stat": dp.win_rate,
        "effect_size":   dp.effect_size,
        "direction":     dp.direction,
    }
