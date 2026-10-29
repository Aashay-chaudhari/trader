from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
ET = ZoneInfo("America/New_York")
BRANCHES = ("intraday", "swing", "options")


def now_et():
    return datetime.now(ET)


@dataclass(frozen=True)
class Config:
    root: Path = ROOT
    start_date: str = "2026-10-30"
    execution: bool = False
    publish: bool = True
    poll_seconds: int = 30
    research_model: str = "gpt-6.1-sol"
    decision_model: str = "gpt-6.1-sol"
    light_model: str = "gpt-6-luna"
    maintenance_model: str = "gpt-6.1-sol"
    codex_bin: str = ""
    max_agent_seconds: int = 600
    max_agent_calls_day: int = 16
    max_input_chars: int = 28000
    api_key: str = ""
    secret_key: str = ""
    ntfy_topic: str = ""
    dashboard_url: str = "https://aashay-chaudhari.github.io/trader/"

    @property
    def state_dir(self):
        return self.root / ".runtime"

    @classmethod
    def load(cls, root=ROOT):
        from dotenv import dotenv_values

        values = {**dotenv_values(root / ".env"), **os.environ}
        return cls(
            root=root,
            start_date=values.get("TRADER_START_DATE", "2026-10-30"),
            execution=values.get("TRADER_EXECUTION", "false").lower() == "true",
            publish=values.get("TRADER_PUBLISH", "true").lower() == "true",
            codex_bin=values.get("TRADER_CODEX_BIN", ""),
            research_model=values.get("TRADER_RESEARCH_MODEL", "gpt-6.1-sol"),
            decision_model=values.get("TRADER_DECISION_MODEL", "gpt-6.1-sol"),
            light_model=values.get("TRADER_LIGHT_MODEL", "gpt-6-luna"),
            maintenance_model=values.get("TRADER_MAINTENANCE_MODEL", "gpt-6.1-sol"),
            api_key=values.get("ALPACA_API_KEY", ""),
            secret_key=values.get("ALPACA_SECRET_KEY", ""),
            ntfy_topic=values.get("NTFY_TOPIC", ""),
        )
