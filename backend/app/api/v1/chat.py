"""AI Chat endpoint — proxies to Claude."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db

router = APIRouter()

SYSTEM_PROMPT = """You are AlphaFO's AI trading assistant, an expert in NSE F&O markets.

## What you help with
- Technical patterns: Gap Fill, Mean Reversion, PCR Divergence, OI Buildup, VWAP+OI, IV Crush, Max Pain, Expiry Week
- Options Greeks (delta, gamma, theta, vega), PCR, OI buildup/unwinding, IV rank, IV/HV relationships
- NIFTY, BANKNIFTY, and F&O stock analysis in Indian market context
- Risk management, position sizing, stop-loss placement, trailing stops
- How to interpret signals, confidence scores, and regime classification in AlphaFO

## AlphaFO internals (answer questions about the system accurately)
- BUY_PATTERNS: gap_fill, oi_buildup, vwap_oi, pcr_divergence, mean_reversion, max_pain — directional, buy CE (long) or PE (short)
- SELL_PATTERNS: iv_crush, expiry_week — premium sellers, sell OTM strangle
- Auto-execution: confidence ≥ 0.82 (synthetic) or ≥ 0.72 (real Kite data), signals < 2h old
- Risk gates: 3% portfolio heat cap, 2% daily loss halt, trailing stop at +30% gain
- Expiry: NIFTY/BANKNIFTY weekly (Tuesday since 2025 NSE change)

## Style
- Concise and actionable. Use ₹ for currency. Reference NSE lot sizes when relevant.
- If asked about live prices/OI, remind that real-time data requires Kite Connect."""


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


async def _resolve_api_key(db: AsyncSession) -> str | None:
    """DB-stored key takes priority over .env so the UI setting wins."""
    try:
        from sqlalchemy import select
        from app.models.kite_config import KiteConfig
        from app.core.encryption import decrypt
        result = await db.execute(select(KiteConfig).where(KiteConfig.id == 1))
        cfg = result.scalar_one_or_none()
        if cfg and cfg.anthropic_api_key_enc:
            return decrypt(cfg.anthropic_api_key_enc)
    except Exception:
        pass
    return settings.anthropic_api_key or None


@router.post("/")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    api_key = await _resolve_api_key(db)
    if not api_key:
        return {
            "role": "assistant",
            "content": (
                "No Anthropic API key configured.\n\n"
                "Go to **Settings → AI Chat** and paste your key (from console.anthropic.com). "
                "It will be stored encrypted in the database."
            ),
        }

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": m.role, "content": m.content} for m in req.messages],
        )
        return {"role": "assistant", "content": resp.content[0].text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
