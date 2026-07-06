"""
Kite Ticker — real-time NSE tick data via Zerodha WebSocket.

Architecture:
  KiteTickerService.start()  →  KiteTicker WebSocket
     on_ticks()              →  Redis Stream "ticks"  (XADD)

Consumers (WebSocket relay, pattern engine) read from the stream
via XREAD with consumer groups so each gets its own copy.

Stream key:  ticks
Stream format per message:
  {sym: "NIFTY", ltp: "24756.50", chg: "0.42", oi: "12345678",
   vol: "98765", ts: "1719651234567"}
"""
import asyncio
import json
import os
import threading
import time
from datetime import datetime
from typing import Callable

import redis
from loguru import logger

from app.core.instruments import BASE_PRICES, all_symbols
from app.config import settings


STREAM_KEY   = "ticks"
STREAM_MAXLEN = 10_000   # keep last 10k ticks per trim

# Instrument token → symbol lookup (populated at start)
_token_to_sym: dict[int, str] = {}

# Kite NSE tradingsymbol → our internal symbol (indices use different names in Kite master)
_KITE_ALIAS: dict[str, str] = {
    "NIFTY 50":          "NIFTY",
    "NIFTY BANK":        "BANKNIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY",
    "NIFTY MID SELECT":  "MIDCPNIFTY",
    "INDIA VIX":         "INDIAVIX",
    "SENSEX":            "SENSEX",      # BSE:SENSEX
}

# BSE indices need exchange prefix "BSE:" in kite.quote() calls
_BSE_SYMBOLS: set[str] = {"SENSEX"}

# Hardcoded Kite instrument tokens for indices — avoids calling kite.instruments()
# for the most important symbols on every startup (instruments() is rate-limited to ~1/day).
_HARDCODED_TOKENS: dict[int, str] = {
    256265:  "NIFTY",
    260105:  "BANKNIFTY",
    257801:  "FINNIFTY",
    288009:  "MIDCPNIFTY",
    264969:  "INDIAVIX",
    265:     "SENSEX",     # BSE:SENSEX
}

# Redis key for cached instrument token→symbol map (TTL 23h so it refreshes daily)
_INSTRUMENTS_CACHE_KEY = "kite:instrument_tokens"
_INSTRUMENTS_CACHE_TTL = 23 * 3600


def _redis_client() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


class KiteTickerService:
    """
    Manages a KiteTicker connection and fans ticks out to Redis Streams.
    Falls back to simulated ticks when Kite is not configured.
    """

    def __init__(self):
        self._running  = False
        self._thread: threading.Thread | None = None
        self._sim_task: asyncio.Task | None   = None
        self._redis    = _redis_client()
        self._live_prices: dict[str, dict] = {
            sym: {"ltp": price, "chg": 0.0}
            for sym, price in BASE_PRICES.items()
        }

    # ── Public API ────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._kt = None   # KiteTicker instance (set when live)
        if settings.kite_api_key and settings.kite_access_token:
            self._seed_prices_from_quote()   # correct LTP + chg before first WS tick
            self._thread = threading.Thread(target=self._start_kite_ticker, daemon=True)
            self._thread.start()
            logger.info("KiteTickerService: started live ticker")
        else:
            logger.warning("KiteTickerService: Kite not configured — using simulated ticks")
            asyncio.create_task(self._simulate_ticks())

    def stop(self) -> None:
        self._running = False

    def get_snapshot(self) -> dict[str, dict]:
        """Current in-memory price snapshot (latest known LTP per symbol)."""
        return dict(self._live_prices)

    def subscribe_option_tokens(self, nfo_symbols: list[str]) -> None:
        """
        Subscribe one or more NFO option symbols to the live KiteTicker.
        Called when paper trades are opened so their premiums stream in real-time.
        No-op when running in simulated mode (Kite not configured).
        """
        if not (settings.kite_api_key and settings.kite_access_token):
            return
        if not nfo_symbols:
            return

        try:
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=settings.kite_api_key)
            kite.set_access_token(settings.kite_access_token)

            sym_set = set(nfo_symbols)
            new_tokens: list[int] = []

            # Look up tokens for symbols not yet in our map
            already_known = {s for s in sym_set if s in {v for v in _token_to_sym.values()}}
            to_resolve = sym_set - already_known

            if to_resolve:
                instruments = kite.instruments("NFO")
                for inst in instruments:
                    if inst["tradingsymbol"] in to_resolve:
                        tok = inst["instrument_token"]
                        _token_to_sym[tok] = inst["tradingsymbol"]
                        new_tokens.append(tok)
                        # Seed snapshot with 0 until first tick arrives
                        if inst["tradingsymbol"] not in self._live_prices:
                            self._live_prices[inst["tradingsymbol"]] = {"ltp": 0.0, "chg": 0.0}

            # Add previously resolved tokens that weren't subscribed yet
            for tok, sym in _token_to_sym.items():
                if sym in already_known and tok not in new_tokens:
                    new_tokens.append(tok)

            if new_tokens and self._kt is not None:
                self._kt.subscribe(new_tokens)
                self._kt.set_mode(self._kt.MODE_LTP, new_tokens)
                logger.info(f"Subscribed {len(new_tokens)} option tokens: {nfo_symbols[:5]}...")
            elif new_tokens:
                # Ticker not yet connected — tokens will be subscribed on next on_connect
                self._pending_tokens = getattr(self, "_pending_tokens", []) + new_tokens
                logger.info(f"Queued {len(new_tokens)} option tokens for subscription")
        except Exception as e:
            logger.warning(f"subscribe_option_tokens failed: {e}")

    def _seed_prices_from_quote(self) -> None:
        """
        Fetch current LTP + previous close for all instruments via kite.quote() REST API,
        seed _live_prices with correct change%, and populate _token_to_sym from the
        instrument_token field in each quote response — so the WebSocket subscription
        covers all instruments without needing kite.instruments().
        """
        try:
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=settings.kite_api_key)
            kite.set_access_token(settings.kite_access_token)

            # Build internal symbol → Kite exchange:tradingsymbol map
            _internal_to_kite: dict[str, str] = {}
            for kite_ts, internal in _KITE_ALIAS.items():
                exchange = "BSE" if internal in _BSE_SYMBOLS else "NSE"
                _internal_to_kite[internal] = f"{exchange}:{kite_ts}"
            from app.core.instruments import all_symbols
            for sym in all_symbols():
                if sym not in _internal_to_kite:
                    _internal_to_kite[sym] = f"NSE:{sym}"

            all_kite_syms = list(_internal_to_kite.values())
            seeded = 0
            for i in range(0, len(all_kite_syms), 500):
                batch_kite = all_kite_syms[i:i+500]
                try:
                    quotes = kite.quote(batch_kite)
                    for kite_sym, data in quotes.items():
                        ltp   = float(data.get("last_price") or 0)
                        close = float((data.get("ohlc") or {}).get("close") or ltp)
                        if not ltp:
                            continue
                        chg = round((ltp - close) / close * 100, 2) if close else 0.0
                        raw      = kite_sym.replace("NSE:", "").replace("NFO:", "").replace("BSE:", "")
                        internal = _KITE_ALIAS.get(raw, raw)
                        self._live_prices[internal] = {"ltp": ltp, "chg": chg}

                        # Harvest instrument token from quote response → use for WS subscription
                        token = data.get("instrument_token")
                        if token and internal:
                            _token_to_sym[int(token)] = internal
                        seeded += 1
                except Exception as e:
                    logger.warning(f"Seed quote batch failed: {e}")

            # Persist harvested tokens to Redis so scanner can use them without instruments() call
            if _token_to_sym and self._redis:
                try:
                    tok_json = json.dumps({str(t): s for t, s in _token_to_sym.items()})
                    self._redis.setex(_INSTRUMENTS_CACHE_KEY, _INSTRUMENTS_CACHE_TTL, tok_json)
                    logger.info(f"Saved {len(_token_to_sym)} tokens to Redis cache")
                except Exception as re:
                    logger.warning(f"Redis token save failed: {re}")

            logger.info(
                f"Seeded {seeded} instruments from kite.quote() — "
                f"{len(_token_to_sym)} tokens ready for WebSocket subscription"
            )
        except Exception as e:
            logger.warning(f"Price seed from kite.quote() failed: {e}")

    # ── Live Kite ticker ──────────────────────────────────────────────────

    def _start_kite_ticker(self) -> None:
        try:
            from kiteconnect import KiteTicker
            from app.core.data.kite_adapter import KiteAdapter

            adapter = KiteAdapter()
            kite    = adapter._get_kite()

            # Build token→symbol map — seed hardcoded indices first (no API call needed)
            _token_to_sym.update(_HARDCODED_TOKENS)

            # Try Redis cache before calling kite.instruments() (rate-limited to ~1/day)
            cached = self._redis.get(_INSTRUMENTS_CACHE_KEY)
            if cached:
                import json as _json
                for tok_str, sym in _json.loads(cached).items():
                    _token_to_sym[int(tok_str)] = sym
                logger.info(f"Loaded {len(_token_to_sym)} instrument tokens from Redis cache")
            else:
                try:
                    instruments = kite.instruments("NSE") + kite.instruments("NFO")
                    syms = set(all_symbols())
                    new_map: dict[str, str] = {}
                    lot_size_map: dict[str, int] = {}
                    for inst in instruments:
                        ts = inst["tradingsymbol"]
                        internal_sym = _KITE_ALIAS.get(ts, ts)
                        if internal_sym in syms:
                            tok = inst["instrument_token"]
                            _token_to_sym[tok] = internal_sym
                            new_map[str(tok)] = internal_sym
                        # Capture lot sizes for all NFO instruments by underlying name
                        name = inst.get("name", "")
                        canonical = _KITE_ALIAS.get(name, name)
                        if canonical in syms and inst.get("lot_size"):
                            lot_size_map[canonical] = int(inst["lot_size"])
                    import json as _json
                    self._redis.setex(_INSTRUMENTS_CACHE_KEY, _INSTRUMENTS_CACHE_TTL, _json.dumps(new_map))
                    if lot_size_map:
                        self._redis.setex("kite:nfo_lot_sizes", _INSTRUMENTS_CACHE_TTL, _json.dumps(lot_size_map))
                        logger.info(f"Cached live lot sizes for {len(lot_size_map)} instruments from Kite")
                    logger.info(f"Fetched and cached {len(new_map)} instrument tokens")
                except Exception as e:
                    logger.warning(f"kite.instruments() failed ({e}), using hardcoded tokens only")

            tokens = list(_token_to_sym.keys())[:500]   # Kite limit is 3000, use priority list

            kt = KiteTicker(settings.kite_api_key, settings.kite_access_token)
            self._kt = kt

            def on_ticks(ws, ticks):
                self._on_kite_ticks(ticks)

            def on_connect(ws, response):
                # Use all tokens harvested from quote seed + instruments call + hardcoded
                all_tokens = list(set(
                    list(_token_to_sym.keys()) +
                    getattr(self, "_pending_tokens", [])
                ))[:3000]   # Kite hard limit is 3000 tokens
                ws.subscribe(all_tokens)
                ws.set_mode(ws.MODE_FULL, all_tokens)
                self._pending_tokens = []
                logger.info(f"KiteTicker connected, subscribed to {len(all_tokens)} instruments")

            def on_close(ws, code, reason):
                self._kt = None
                logger.warning(f"KiteTicker closed: {code} {reason}")

            def on_error(ws, code, reason):
                logger.error(f"KiteTicker error: {code} {reason}")

            kt.on_ticks   = on_ticks
            kt.on_connect = on_connect
            kt.on_close   = on_close
            kt.on_error   = on_error

            kt.connect(threaded=False)   # blocks
        except Exception as e:
            logger.error(f"KiteTickerService failed to start: {e}")
            logger.info("Falling back to simulated ticks")
            asyncio.run(self._simulate_ticks())

    def _on_kite_ticks(self, ticks: list) -> None:
        pipe = self._redis.pipeline()
        for tick in ticks:
            sym = _token_to_sym.get(tick.get("instrument_token", 0))
            if not sym:
                continue
            ltp = float(tick.get("last_price", 0))
            # Use Kite's pre-computed change% vs prev close; fall back to ohlc calc
            if "change" in tick and tick["change"] is not None:
                chg = round(float(tick["change"]), 2)
            else:
                prev = float(tick.get("ohlc", {}).get("close", ltp) or ltp)
                chg  = round((ltp - prev) / prev * 100, 2) if prev else 0.0
            oi   = tick.get("oi", 0)
            vol  = tick.get("volume", 0)

            self._live_prices[sym] = {"ltp": ltp, "chg": round(chg, 2)}

            # Write to a simple key so Celery workers (no in-memory snapshot) can read it
            pipe.set(f"spot:{sym}", str(round(ltp, 2)), ex=3600)

            pipe.xadd(STREAM_KEY, {
                "sym": sym,
                "ltp": str(round(ltp, 2)),
                "chg": str(round(chg, 2)),
                "oi":  str(oi),
                "vol": str(vol),
                "ts":  str(int(time.time() * 1000)),
            }, maxlen=STREAM_MAXLEN, approximate=True)

        # Heartbeat: proves REAL Kite ticks are flowing (never set by the
        # synthetic fallback). health-scan flags staleness during market hours
        # — a dead WebSocket otherwise degrades spot: keys to random-walk
        # values silently (bit us 2026-07-03 morning).
        pipe.set("ticker:last_real_tick", str(int(time.time())), ex=600)
        pipe.execute()

    # ── Simulated tick fallback ───────────────────────────────────────────

    async def _simulate_ticks(self) -> None:
        """Gaussian random walk — only used when Kite is not configured."""
        import random
        # Day-open prices: change% is intraday movement, not drift from stale constants
        day_open: dict[str, float] = {
            sym: data["ltp"] for sym, data in self._live_prices.items()
        }
        logger.info("KiteTickerService: running simulated price ticks")
        while self._running:
            # Market closed (weekend / outside 09:15-15:30 IST): FREEZE prices.
            # Random-walking a closed market showed fake "live" moves in the UI
            # (user caught this 2026-07-05). We still rewrite the last value to
            # keep the spot: keys' TTL alive for MTM readers.
            from datetime import datetime as _dtm, timedelta as _tdl, timezone as _tz
            _now_ist = _dtm.now(_tz.utc) + _tdl(hours=5, minutes=30)
            _mkt_open = (_now_ist.weekday() < 5 and
                         (9, 15) <= (_now_ist.hour, _now_ist.minute) <= (15, 30))
            pipe = self._redis.pipeline()
            batch: dict[str, dict] = {}
            if not _mkt_open:
                for sym, price_data in self._live_prices.items():
                    pipe.set(f"spot:{sym}", str(price_data["ltp"]), ex=3600)
                pipe.execute()
                await asyncio.sleep(30)
                continue
            for sym, price_data in self._live_prices.items():
                ltp  = price_data["ltp"]
                ltp  = ltp * (1 + random.gauss(0, 0.0003))
                ltp  = round(ltp, 2)
                open_px = day_open.get(sym, ltp)
                chg  = round((ltp - open_px) / open_px * 100, 2) if open_px else 0.0
                self._live_prices[sym] = {"ltp": ltp, "chg": chg}
                batch[sym] = {"ltp": ltp, "chg": chg}
                pipe.set(f"spot:{sym}", str(ltp), ex=3600)

                pipe.xadd(STREAM_KEY, {
                    "sym": sym,
                    "ltp": str(round(ltp, 2)),
                    "chg": str(chg),
                    "oi":  "0",
                    "vol": "0",
                    "ts":  str(int(time.time() * 1000)),
                }, maxlen=STREAM_MAXLEN, approximate=True)

            pipe.execute()
            await asyncio.sleep(1)


# Singleton
ticker_service = KiteTickerService()


def ensure_stream_groups() -> None:
    """Create consumer groups for websocket and pattern-engine consumers."""
    r = _redis_client()
    for group in ("ws_relay", "pattern_engine"):
        try:
            r.xgroup_create(STREAM_KEY, group, id="$", mkstream=True)
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
