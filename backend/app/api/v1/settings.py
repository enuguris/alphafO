"""Settings API — mode switching, Kite credentials, access token management."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, AppMode
from app.database import get_db
from app.models.kite_config import KiteConfig
from app.core.encryption import encrypt, decrypt

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_or_create_config(db: AsyncSession) -> KiteConfig:
    result = await db.execute(select(KiteConfig).where(KiteConfig.id == 1))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        cfg = KiteConfig(id=1)
        db.add(cfg)
        await db.flush()
    return cfg


# ── Schemas ───────────────────────────────────────────────────────────────────

class ModeUpdate(BaseModel):
    mode: AppMode


class KiteCredentialsIn(BaseModel):
    api_key: str
    api_secret: str


class RequestTokenIn(BaseModel):
    request_token: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.put("/mode")
async def set_mode(update: ModeUpdate):
    if update.mode == AppMode.LIVE:
        return {
            "error": "Live mode can only be enabled after paper trading criteria are met.",
            "use": "POST /api/v1/portfolio/promote-to-live",
        }
    settings.app_mode = update.mode
    return {"mode": settings.app_mode, "message": f"Switched to {update.mode} mode"}


@router.get("/kite-credentials")
async def get_kite_credentials(db: AsyncSession = Depends(get_db)):
    """Return api_key and token status — never expose secrets."""
    cfg = await _get_or_create_config(db)
    today = date.today()
    token_valid = bool(cfg.access_token_enc) and cfg.token_date == today
    return {
        "api_key":     cfg.api_key,
        "has_secret":  bool(cfg.api_secret_enc),
        "token_valid": token_valid,
        "token_date":  cfg.token_date.isoformat() if cfg.token_date else None,
    }


@router.post("/kite-credentials")
async def save_kite_credentials(
    creds: KiteCredentialsIn,
    db: AsyncSession = Depends(get_db),
):
    """Save api_key (plain) and api_secret (encrypted) to DB."""
    cfg = await _get_or_create_config(db)
    cfg.api_key        = creds.api_key.strip()
    cfg.api_secret_enc = encrypt(creds.api_secret.strip())
    # Clear stale token when credentials change
    cfg.access_token_enc = ""
    cfg.token_date = None
    await db.commit()

    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={cfg.api_key}"
    return {
        "message":   "Credentials saved. Click 'Generate Login URL' to authenticate.",
        "login_url": login_url,
    }


@router.get("/kite-login-url")
async def get_kite_login_url(db: AsyncSession = Depends(get_db)):
    """Return the Kite OAuth URL for today's login flow."""
    cfg = await _get_or_create_config(db)
    if not cfg.api_key:
        raise HTTPException(status_code=400, detail="API key not configured. Save credentials first.")
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={cfg.api_key}"
    return {"login_url": login_url}


@router.post("/kite-token")
async def generate_access_token(
    body: RequestTokenIn,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a request_token for an access_token via Kite and store it encrypted."""
    from kiteconnect import KiteConnect  # imported here to avoid hard dep at startup

    cfg = await _get_or_create_config(db)
    if not cfg.api_key or not cfg.api_secret_enc:
        raise HTTPException(status_code=400, detail="Kite credentials not saved yet.")

    api_secret = decrypt(cfg.api_secret_enc)

    try:
        kite = KiteConnect(api_key=cfg.api_key)
        data = kite.generate_session(body.request_token.strip(), api_secret=api_secret)
        access_token = data["access_token"]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Kite token exchange failed: {exc}")

    cfg.access_token_enc = encrypt(access_token)
    cfg.token_date       = date.today()
    await db.commit()

    # Also update the in-memory settings so the current process uses it immediately
    settings.kite_access_token = access_token
    settings.kite_api_key      = cfg.api_key

    return {
        "message":    "Access token generated and stored.",
        "token_date": cfg.token_date.isoformat(),
        "valid_until": "End of today (Kite tokens expire at midnight).",
    }


@router.get("/kite-test")
async def test_kite_connection(db: AsyncSession = Depends(get_db)):
    """
    Test Kite Connect end-to-end:
      1. Credentials present in DB
      2. Access token valid (not expired)
      3. profile() API call succeeds
      4. Fetch last 5 NIFTY daily candles — proves historical data works
      5. Fetch live quote for NIFTY — proves quote API works
    Returns a structured result per check so the UI can show exactly what passed/failed.
    """
    from datetime import timedelta
    from kiteconnect import KiteConnect
    from app.core.encryption import decrypt

    results: list[dict] = []

    def step(name: str, ok: bool, detail: str) -> dict:
        r = {"check": name, "ok": ok, "detail": detail}
        results.append(r)
        return r

    # 1. Credentials
    cfg = await _get_or_create_config(db)
    if not cfg.api_key or not cfg.api_secret_enc:
        step("Credentials", False, "API key / secret not saved. Complete Step 1 first.")
        return {"passed": False, "results": results}
    step("Credentials", True, f"API key {cfg.api_key[:6]}… found in database")

    # 2. Access token present and dated today
    today = date.today()
    if not cfg.access_token_enc or cfg.token_date != today:
        step("Access Token", False,
             f"Token missing or expired (dated {cfg.token_date}). Complete Step 2 to regenerate.")
        return {"passed": False, "results": results}
    step("Access Token", True, f"Token dated {cfg.token_date} — valid for today")

    # 3. Profile API call
    try:
        access_token = decrypt(cfg.access_token_enc)
        kite = KiteConnect(api_key=cfg.api_key)
        kite.set_access_token(access_token)
        profile = kite.profile()
        step("Profile API", True,
             f"Connected as {profile.get('user_name', '?')} ({profile.get('user_id', '?')}) "
             f"— broker: {profile.get('broker', '?')}")
    except Exception as exc:
        step("Profile API", False, f"API call failed: {exc}")
        return {"passed": False, "results": results}

    # 4. Historical OHLCV — last 5 NIFTY daily candles
    try:
        from_date = today - timedelta(days=10)
        candles = kite.historical_data(256265, from_date, today, "day")  # 256265 = NIFTY 50 index token
        if not candles:
            raise ValueError("Empty response")
        last = candles[-1]
        step("Historical Data", True,
             f"NIFTY last close: ₹{last['close']:,.2f} on {str(last['date'])[:10]} "
             f"({len(candles)} candles fetched)")
    except Exception as exc:
        step("Historical Data", False, f"historical_data() failed: {exc}")

    # 5. Live quote
    try:
        quote = kite.quote(["NSE:NIFTY 50"])
        nifty = quote.get("NSE:NIFTY 50", {})
        ltp = nifty.get("last_price", 0)
        step("Live Quote", True, f"NIFTY LTP: ₹{ltp:,.2f}")
    except Exception as exc:
        step("Live Quote", False, f"quote() failed: {exc}")

    all_ok = all(r["ok"] for r in results)
    return {
        "passed": all_ok,
        "results": results,
        "summary": "All checks passed — Kite Connect is fully operational." if all_ok
                   else "Some checks failed. See details above.",
    }
