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
