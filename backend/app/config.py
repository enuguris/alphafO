"""
AlphaFO — Application Configuration
Loaded from environment variables / .env file.
"""
from enum import Enum
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(str, Enum):
    TESTING = "testing"
    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "AlphaFO"
    app_version: str = "1.0.0"
    debug: bool = False
    secret_key: str = "change-me"
    app_mode: AppMode = AppMode.TESTING

    # Database
    database_url: str = "postgresql+asyncpg://alphafO:password@localhost:5432/alphafO"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Kite Connect
    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""

    # Risk Parameters
    max_capital_risk_per_trade: float = 0.01   # 1%
    max_portfolio_heat: float = 0.03            # 3%
    daily_loss_limit: float = 0.02             # 2%
    weekly_loss_limit: float = 0.03            # 3%

    # Paper Trading Promotion Thresholds
    paper_min_trades: int = 60
    paper_min_win_rate: float = 0.55
    paper_max_drawdown: float = 0.10

    # Data
    nse_data_dir: str = "./data/nse"
    initial_capital: float = 500_000.0         # ₹5,00,000

    # AI Chat
    anthropic_api_key: str = ""


settings = Settings()
