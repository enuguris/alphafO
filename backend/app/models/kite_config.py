"""KiteConfig — persists Zerodha + Upstox credentials and daily access tokens."""
from datetime import date
from sqlalchemy import Column, String, Date, Integer
from app.database import Base


class KiteConfig(Base):
    __tablename__ = "kite_config"

    id             = Column(Integer, primary_key=True, default=1)
    # Zerodha Kite credentials (stored encrypted via app.core.encryption)
    api_key              = Column(String, nullable=False, default="")
    api_secret_enc       = Column(String, nullable=False, default="")
    access_token_enc     = Column(String, nullable=False, default="")
    token_date           = Column(Date, nullable=True)
    # Upstox credentials
    upstox_api_key           = Column(String, nullable=False, default="")
    upstox_api_secret_enc    = Column(String, nullable=False, default="")
    upstox_access_token_enc  = Column(String, nullable=False, default="")
    upstox_token_date        = Column(Date, nullable=True)
    # Anthropic API key — stored encrypted
    anthropic_api_key_enc = Column(String, nullable=False, default="")
