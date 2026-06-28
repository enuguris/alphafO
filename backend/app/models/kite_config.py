"""KiteConfig — persists Zerodha credentials and daily access token."""
from datetime import date
from sqlalchemy import Column, String, Date, Integer
from app.database import Base


class KiteConfig(Base):
    __tablename__ = "kite_config"

    id             = Column(Integer, primary_key=True, default=1)
    api_key        = Column(String, nullable=False, default="")
    # Stored encrypted via app.core.encryption
    api_secret_enc = Column(String, nullable=False, default="")
    access_token_enc = Column(String, nullable=False, default="")
    token_date     = Column(Date, nullable=True)   # date the access_token was generated
