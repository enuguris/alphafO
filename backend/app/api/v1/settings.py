"""Settings API — mode switching and Kite credentials."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.config import settings, AppMode

router = APIRouter()


class ModeUpdate(BaseModel):
    mode: AppMode


class KiteCredentials(BaseModel):
    api_key: str
    api_secret: str


@router.put("/mode")
async def set_mode(update: ModeUpdate):
    if update.mode == AppMode.LIVE:
        return {"error": "Live mode can only be enabled after paper trading criteria are met.",
                "use": "POST /api/v1/portfolio/promote-to-live"}
    settings.app_mode = update.mode
    return {"mode": settings.app_mode, "message": f"Switched to {update.mode} mode"}


@router.post("/kite-credentials")
async def save_kite_credentials(creds: KiteCredentials):
    """Store Kite credentials (in production: encrypt and save to DB)."""
    settings.kite_api_key = creds.api_key
    settings.kite_api_secret = creds.api_secret
    return {"message": "Kite credentials saved. Visit the Kite login URL to get access token.",
            "login_url": f"https://kite.zerodha.com/connect/login?v=3&api_key={creds.api_key}"}
