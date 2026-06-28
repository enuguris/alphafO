"""
Live Trading Broker — places real orders via Zerodha Kite Connect.
GATED: Only accessible after paper trading promotion criteria are met.
All operations are logged and guardrailed.
"""
from datetime import datetime
from loguru import logger
from app.config import settings, AppMode
from app.core.risk.guardrails import pre_trade_check
from app.core.patterns.base import PatternSignal


class LiveBroker:
    """Places real F&O orders via Kite Connect with full guardrails."""

    def __init__(self):
        self._kite = None

    def _get_kite(self):
        if self._kite is None:
            from kiteconnect import KiteConnect
            self._kite = KiteConnect(api_key=settings.kite_api_key)
            self._kite.set_access_token(settings.kite_access_token)
        return self._kite

    def place_order(self, signal: PatternSignal, quantity: int, paper_stats: dict,
                    portfolio_heat: float, daily_pnl_pct: float) -> dict:
        """Place a real order. Runs ALL guardrails first."""
        allowed, reason = pre_trade_check(
            mode=AppMode.LIVE,
            signal_confidence=signal.confidence_score,
            capital_at_risk_pct=settings.max_capital_risk_per_trade,
            portfolio_heat=portfolio_heat,
            daily_pnl_pct=daily_pnl_pct,
            paper_stats=paper_stats,
        )
        if not allowed:
            logger.error(f"LIVE order BLOCKED by guardrail: {reason}")
            return {"success": False, "reason": reason}

        kite = self._get_kite()
        transaction = "BUY" if signal.direction == "long" else "SELL"

        try:
            order_id = kite.place_order(
                tradingsymbol=signal.instrument,
                exchange="NFO",
                transaction_type=transaction,
                quantity=quantity,
                order_type="MARKET",
                product="MIS",         # intraday; use NRML for positional
                variety="regular",
            )
            logger.info(f"LIVE ORDER PLACED: {signal.instrument} {transaction} x{quantity} — order_id={order_id}")
            return {"success": True, "order_id": order_id, "trade": {
                "symbol": signal.instrument, "direction": signal.direction,
                "quantity": quantity, "order_id": order_id,
                "placed_at": datetime.utcnow().isoformat(),
            }}
        except Exception as e:
            logger.error(f"LIVE order failed: {e}")
            return {"success": False, "reason": str(e)}

    def place_stop_order(self, instrument: str, quantity: int, stop_price: float,
                         direction: str) -> dict:
        """Place a stop-loss order immediately after entry."""
        kite = self._get_kite()
        # Cover order: if long, stop is a sell; if short, stop is a buy
        transaction = "SELL" if direction == "long" else "BUY"
        try:
            order_id = kite.place_order(
                tradingsymbol=instrument, exchange="NFO",
                transaction_type=transaction, quantity=quantity,
                order_type="SL-M", trigger_price=stop_price,
                product="MIS", variety="regular",
            )
            logger.info(f"Stop order placed: {instrument} {transaction} SL-M @ {stop_price}")
            return {"success": True, "order_id": order_id}
        except Exception as e:
            logger.error(f"Stop order failed: {e}")
            return {"success": False, "reason": str(e)}
