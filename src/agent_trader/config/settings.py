"""Configuration management — all settings in one place.

Settings are loaded from environment variables (via .env file).
This makes it easy to:
  - Run locally with a .env file
  - Deploy to GitHub Actions with secrets
  - Switch between paper and live trading (eventually)
"""

from functools import lru_cache

from pydantic import Field
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

    # --- Debug Mode ---
    # When True: use deterministic template responses (no CLI/API model calls),
    # fewer stocks, optional web-skip, and reduced context.
    # Keep this enabled by default while validating workflow plumbing.
    debug_mode: bool = True
    debug_max_stocks: int = 3             # Max stocks to analyze in debug mode
    debug_skip_web: bool = True           # Skip live web research in debug mode

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
    dry_run: bool = True               # True = no real orders placed
    paper_portfolio_value: float = 100_000.0  # Starting paper portfolio value

    # --- Risk Limits ---
    max_position_pct: float = 10.0     # Max % of portfolio in one stock
    max_daily_loss_pct: float = 2.0    # Stop trading if daily loss > this %
    min_signal_strength: float = 0.3   # Minimum signal strength to trade
    min_strategies_agree: int = 2      # Min strategies that must agree for a trade
    guarantee_daily_trade: bool = True  # If True, take best available if no strong signal

    # --- Paths ---
    data_dir: str = "data"
    log_dir: str = "logs"
    agent_profile: str = "default"
    agent_label: str = ""

    # --- Schedule ---
    run_frequency: str = "daily"       # "daily", "hourly", "manual"

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
