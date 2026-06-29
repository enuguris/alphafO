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
        if settings.kite_api_key and settings.kite_access_token:
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

    # ── Live Kite ticker ──────────────────────────────────────────────────

    def _start_kite_ticker(self) -> None:
        try:
            from kiteconnect import KiteTicker
            from app.core.data.kite_adapter import KiteAdapter

            adapter = KiteAdapter()
            kite    = adapter._get_kite()

            # Build token→symbol map from NFO+NSE instruments
            instruments = kite.instruments("NSE") + kite.instruments("NFO")
            syms = set(all_symbols())
            for inst in instruments:
                if inst["tradingsymbol"] in syms:
                    _token_to_sym[inst["instrument_token"]] = inst["tradingsymbol"]

            tokens = list(_token_to_sym.keys())[:500]   # Kite limit is 3000, use priority list

            kt = KiteTicker(settings.kite_api_key, settings.kite_access_token)

            def on_ticks(ws, ticks):
                self._on_kite_ticks(ticks)

            def on_connect(ws, response):
                ws.subscribe(tokens)
                ws.set_mode(ws.MODE_FULL, tokens)
                logger.info(f"KiteTicker connected, subscribed to {len(tokens)} instruments")

            def on_close(ws, code, reason):
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
            prev = float(tick.get("ohlc", {}).get("close", ltp) or ltp)
            chg  = ((ltp - prev) / prev * 100) if prev else 0.0
            oi   = tick.get("oi", 0)
            vol  = tick.get("volume", 0)

            self._live_prices[sym] = {"ltp": ltp, "chg": round(chg, 2)}

            pipe.xadd(STREAM_KEY, {
                "sym": sym,
                "ltp": str(round(ltp, 2)),
                "chg": str(round(chg, 2)),
                "oi":  str(oi),
                "vol": str(vol),
                "ts":  str(int(time.time() * 1000)),
            }, maxlen=STREAM_MAXLEN, approximate=True)

        pipe.execute()

    # ── Simulated tick fallback ───────────────────────────────────────────

    async def _simulate_ticks(self) -> None:
        """Gaussian random walk — only used when Kite is not configured."""
        import random
        logger.info("KiteTickerService: running simulated price ticks")
        while self._running:
            pipe = self._redis.pipeline()
            batch: dict[str, dict] = {}
            for sym, price_data in self._live_prices.items():
                ltp  = price_data["ltp"]
                ltp  = ltp * (1 + random.gauss(0, 0.0003))
                chg  = round((ltp - BASE_PRICES.get(sym, ltp)) / BASE_PRICES.get(sym, ltp) * 100, 2)
                self._live_prices[sym] = {"ltp": round(ltp, 2), "chg": chg}
                batch[sym] = {"ltp": round(ltp, 2), "chg": chg}

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
