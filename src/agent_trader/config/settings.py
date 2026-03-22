"""Configuration management — all settings in one place.

Settings are loaded from environment variables (via .env file).
This makes it easy to:
  - Run locally with a .env file
  - Deploy to GitHub Actions with secrets
  - Switch between paper and live trading (eventually)
"""

import os
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration for the trading system."""

    # --- API Keys ---
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""

    # --- News & Data API Keys ---
    marketaux_api_key: str = ""       # Free tier: 100 req/day, entity-linked news
    fred_api_key: str = ""            # Free: macro data (VIX, yields, spreads)
    sec_edgar_user_agent: str = ""    # Required by SEC: "Name email@example.com"
    finnhub_api_key: str = ""         # Free: 60 req/min, social sentiment, insider trades
    alpha_vantage_api_key: str = ""   # Free: 25 req/day, NLP news sentiment

    # --- LLM Models ---
    # Sonnet for deep morning research (worth the $0.01-0.03)
    # Haiku for periodic monitoring checks ($0.001)
    llm_provider: str = "auto"  # "auto", "anthropic", or "openai"
    research_model: str = "claude-sonnet-4-6"
    monitor_model: str = "claude-haiku-4-5-20251001"
    research_model_openai: str = "gpt-4o-mini"
    llm_max_output_tokens: int = 4000  # Cap output tokens for API calls
    llm_max_prompt_chars: int = 80000  # Soft cap input prompt size before API call

    # --- CLI Agent Mode ---
    # When True, use Claude Code CLI (claude -p) instead of direct API calls.
    # The CLI agent can explore the full repo for historical context.
    # Falls back to direct API call if CLI is not available.
    use_cli_agent: bool = False          # Set to True to enable CLI agent mode
    cli_agent_provider: str = "claude"   # "claude" or "codex"
    cli_agent_max_turns: int = 5         # Max agent iterations (controls cost)
    cli_agent_timeout: int = 300         # Max seconds before timeout

    # --- Run Mode (single control variable) ---
    # "debug"  — template responses, no LLM calls, no orders, 3 stocks, skip web
    # "paper"  — real LLM calls, Alpaca paper orders, full pipeline
    # "live"   — real LLM calls, Alpaca live orders (future)
    run_mode: str = "debug"

    # Legacy fields — still read from .env for backward compatibility.
    # The model_validator below resolves them into run_mode.
    debug_mode: bool = True
    dry_run: bool = True
    debug_max_stocks: int = 3
    debug_skip_web: bool = True

    @model_validator(mode="after")
    def _resolve_run_mode(self) -> "Settings":
        """Derive run_mode from legacy env vars when RUN_MODE is not explicitly set.

        Priority: RUN_MODE env var > PRODUCTION_MODE > DEBUG_MODE/DRY_RUN.
        """
        env_run_mode = os.environ.get("RUN_MODE", "").strip().lower()
        if env_run_mode in ("debug", "paper", "live"):
            self.run_mode = env_run_mode
            # Sync legacy fields to match
            self.debug_mode = (env_run_mode == "debug")
            self.dry_run = (env_run_mode != "live")
            return self

        # PRODUCTION_MODE (GitHub Actions master switch)
        prod = os.environ.get("PRODUCTION_MODE", "").strip().lower()
        if prod == "true":
            self.run_mode = "paper"
            self.debug_mode = False
            self.dry_run = False
            return self

        # Fall back to legacy debug_mode / dry_run fields
        if not self.debug_mode and not self.dry_run:
            self.run_mode = "paper"
        elif not self.debug_mode:
            self.run_mode = "paper"  # real LLM + dry-run = still paper mode
        else:
            self.run_mode = "debug"
        return self

    # --- Computed properties (use these instead of legacy fields) ---

    @property
    def is_debug(self) -> bool:
        """Template mode — no LLM/API calls, deterministic responses."""
        return self.run_mode == "debug"

    @property
    def is_dry_run(self) -> bool:
        """No real orders placed (debug and paper are both dry-run)."""
        return self.run_mode != "live"

    @property
    def max_stocks(self) -> int:
        """Max stocks to analyze (capped in debug mode)."""
        return self.debug_max_stocks if self.is_debug else 0  # 0 = unlimited

    @property
    def skip_web(self) -> bool:
        """Skip live web research."""
        return self.is_debug

    # --- Knowledge Accumulation ---
    enable_knowledge_base: bool = True    # Load accumulated knowledge into prompts
    knowledge_token_budget: int = 1500    # Token budget for knowledge context
    observations_token_budget: int = 500  # Token budget for observations context
    observation_retention_days: int = 90  # Archive daily observations after N days

    # --- Swing Trading ---
    enable_swing_tracking: bool = True    # Track multi-day positions

    # --- Trading Config ---
    watchlist: list[str] = Field(
        default=["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"],
        description="Fallback stocks if screener doesn't run",
    )
    paper_portfolio_value: float = 100_000.0  # Starting paper portfolio value

    # --- Risk Limits ---
    max_position_pct: float = 10.0     # Max % of portfolio in one stock
    max_daily_loss_pct: float = 2.0    # Stop trading if daily loss > this %
    min_signal_strength: float = 0.3   # Minimum signal strength to trade
    min_strategies_agree: int = 2      # Min strategies that must agree for a trade
    guarantee_daily_trade: bool = True  # If True, take best available if no strong signal

    # --- Push Notifications (ntfy.sh — free, no signup) ---
    # Install ntfy app on phone → subscribe to your topic → done.
    ntfy_topic: str = ""               # e.g., "agent-trader-yourname" (pick anything unique)
    ntfy_server: str = "https://ntfy.sh"  # Self-host or use public server
    # Optional Twilio SMS fallback (paid, requires signup)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    alert_phone_number: str = ""
    # Alert toggles
    enable_trade_alerts: bool = True   # Notify on trade execution
    enable_daily_summary: bool = True  # End-of-day P&L notification
    enable_error_alerts: bool = True   # Notify on pipeline errors

    # --- Paths ---
    data_dir: str = "data"
    log_dir: str = "logs"
    agent_profile: str = "default"
    agent_label: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance. Call once at startup."""
    return Settings()


def reset_settings() -> None:
    """Clear the settings cache (useful for testing)."""
    get_settings.cache_clear()
