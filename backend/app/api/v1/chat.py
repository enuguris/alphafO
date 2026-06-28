"""AI Chat endpoint — proxies to Claude."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.config import settings

router = APIRouter()

SYSTEM_PROMPT = """You are AlphaFO's AI trading assistant, an expert in NSE F&O markets.
You help traders understand:
- Technical patterns: Gap Fill, Mean Reversion, PCR Divergence, OI Buildup, VWAP+OI, IV Crush, Max Pain, Expiry Week
- Options Greeks, PCR, OI analysis, IV/HV relationships
- NIFTY, BANKNIFTY, and individual F&O stock analysis
- Risk management, position sizing, stop-loss strategies
- How to interpret signals shown in the AlphaFO dashboard

Keep answers concise, specific to Indian markets (NSE/NFO), and actionable.
Use ₹ for currency. Reference lot sizes, margin requirements when relevant.
If asked about live prices or current OI, note that real-time data needs Kite Connect configured."""


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


@router.post("/")
async def chat(req: ChatRequest):
    if not settings.anthropic_api_key:
        # Return a helpful fallback when no API key is set
        return {
            "role": "assistant",
            "content": (
                "The Anthropic API key is not configured. To enable AI chat:\n\n"
                "1. Add `ANTHROPIC_API_KEY=your-key` to your `.env` file\n"
                "2. Restart the backend container\n\n"
                "Until then, I can still help you understand the dashboard — "
                "what would you like to know about AlphaFO's patterns or signals?"
            ),
        }

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": m.role, "content": m.content} for m in req.messages],
        )
        return {"role": "assistant", "content": resp.content[0].text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
