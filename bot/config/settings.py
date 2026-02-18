"""Bot configuration using Pydantic for validation.

Loads settings from:
1. Environment variables (highest priority, for secrets)
2. TOML config file (bot/config/default.toml or custom path)
3. Pydantic defaults (lowest priority)
"""

import os
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class StrategyConfig(BaseModel):
    """Configuration for a single ticker's strategy."""
    file: str                           # Path to strategy .py file
    timeframe: str = "5m"               # Bar timeframe (1m, 2m, 5m, 10m, etc.)
    params: dict = Field(default_factory=dict)  # Strategy param overrides
    enabled: bool = True


class RiskConfig(BaseModel):
    """Risk management settings."""
    max_daily_loss: float = 3000.0      # Pause trading if daily loss exceeds this ($)
    max_drawdown_pct: float = 15.0      # Circuit breaker: pause if drawdown exceeds (%)
    max_position_value_pct: float = 0.90  # Max position as fraction of equity
    max_positions: int = 1              # Max concurrent positions per ticker
    cooldown_after_stop: int = 0        # Bars to wait after a stop-out before re-entry


class BotConfig(BaseModel):
    """Top-level bot configuration."""

    # Alpaca credentials (load from env vars)
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    paper_trading: bool = True          # True = paper, False = live

    # Strategies: ticker -> config
    strategies: dict[str, StrategyConfig] = Field(default_factory=dict)

    # Position sizing
    position_sizing: str = "percent"    # "fixed", "percent", "risk_based"
    pct_equity: float = 0.90            # 90% of equity per trade
    fixed_size: float = 10_000.0        # $ per trade (for fixed sizing)
    risk_pct: float = 0.02              # 2% risk per trade (for risk_based)

    # Risk management
    risk: RiskConfig = Field(default_factory=RiskConfig)

    # Email notifications (Gmail SMTP)
    email_enabled: bool = True
    email_smtp_server: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_from: str = ""                # Your Gmail address
    email_to: str = ""                  # Recipient (can be same as from)
    email_password: str = ""            # Gmail App Password (NOT your login password)

    # Storage
    db_path: str = "bot/data/trading.db"

    # Logging
    log_level: str = "INFO"
    log_file: str = "bot/data/bot.log"

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "BotConfig":
        """Load config from TOML file + environment variables.

        Environment variables override TOML values:
            ALPACA_API_KEY, ALPACA_SECRET_KEY, DISCORD_WEBHOOK_URL,
            WEBHOOK_PASSPHRASE, BOT_PAPER_TRADING
        """
        data = {}

        # Load from TOML if provided
        if config_path and Path(config_path).exists():
            data = _load_toml(config_path)

        # Environment variable overrides (secrets should always come from env)
        env_overrides = {
            "alpaca_api_key": os.getenv("ALPACA_API_KEY"),
            "alpaca_secret_key": os.getenv("ALPACA_SECRET_KEY"),
            "email_from": os.getenv("EMAIL_FROM"),
            "email_to": os.getenv("EMAIL_TO"),
            "email_password": os.getenv("EMAIL_PASSWORD"),
        }

        paper_env = os.getenv("BOT_PAPER_TRADING")
        if paper_env is not None:
            env_overrides["paper_trading"] = paper_env.lower() in ("true", "1", "yes")

        for key, val in env_overrides.items():
            if val is not None:
                data[key] = val

        return cls(**data)


def _load_toml(path: str) -> dict:
    """Load a TOML file, using tomllib (3.11+) or tomli."""
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomli as tomllib
        except ImportError:
            raise ImportError("Install 'tomli' for Python < 3.11: pip install tomli")

    with open(path, "rb") as f:
        return tomllib.load(f)
