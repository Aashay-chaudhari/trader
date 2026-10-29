from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Evidence(Strict):
    title: str = Field(min_length=3, max_length=250)
    url: str = Field(pattern=r"^https://", max_length=1000)
    published_at: str | None
    observed_at: datetime
    takeaway: str = Field(max_length=900)


class MarketEvent(Strict):
    title: str
    when: str
    timing_known: bool
    symbols: list[str]
    importance: Literal["high", "medium", "low"]
    source_url: str = Field(pattern=r"^https://")
    implication: str


class Plan(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{4,70}$")
    branch: Literal["intraday", "swing", "options"]
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.]{0,20}$")
    strategy: str = Field(min_length=3, max_length=80)
    version: str = Field(min_length=1, max_length=30)
    thesis: str = Field(min_length=15, max_length=1600)
    entry_low: float = Field(gt=0)
    entry_high: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float = Field(gt=0)
    expires_at: datetime
    invalidation: str = Field(min_length=8, max_length=700)
    event_check: str = Field(min_length=8, max_length=700)
    event_risk_known: bool
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def levels(self):
        if not self.stop < self.entry_low <= self.entry_high < self.target:
            raise ValueError("Long plans require stop < entry_low <= entry_high < target")
        if self.expires_at.tzinfo is None:
            raise ValueError("Expiry needs a timezone")
        return self


class Brief(Strict):
    summary: str = Field(max_length=2500)
    regime: Literal["risk_on", "mixed", "risk_off", "unknown"]
    rates_bonds: str
    fed_macro: str
    earnings: str
    market_conditions: str
    cross_market: str
    narratives: str
    unknowns: list[str]
    events: list[MarketEvent] = Field(max_length=25)
    sources: list[Evidence] = Field(max_length=20)
    plans: list[Plan] = Field(max_length=8)


class Decision(Strict):
    plan_id: str
    action: Literal["approve", "wait", "invalidate"]
    reason: str = Field(min_length=10, max_length=1200)
    contradictions: list[str]
    evidence_fresh: bool


class ExperimentContract(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{4,70}$")
    branch: Literal["intraday", "swing", "options"]
    hypothesis: str
    exact_change: str
    parent_version: str
    minimum_sessions: int = Field(ge=20)
    minimum_samples: int = Field(ge=30)
    cost_model: str
    metrics: list[str]


class ImprovementRequest(Strict):
    problem: str
    hypothesis: str
    requested_change: str
    validation_plan: str


class Review(Strict):
    summary: str
    observations: list[str]
    proposed_lessons: list[str]
    experiments: list[ExperimentContract] = Field(max_length=12)
    code_changes: list[ImprovementRequest] = Field(max_length=3)
    no_change_reason: str | None


class Pulse(Strict):
    summary: str
    material_change: bool
    affected_symbols: list[str]
    events: list[MarketEvent] = Field(max_length=10)
    sources: list[Evidence] = Field(max_length=6)
    unknowns: list[str]


class SourceChange(Strict):
    path: str
    content: str = Field(max_length=20000)


class MaintenanceProposal(Strict):
    summary: str
    hypothesis: str
    validation_plan: str
    changes: list[SourceChange] = Field(max_length=3)
    no_change_reason: str | None


class PositionDecision(Strict):
    symbol: str
    action: Literal["hold", "exit"]
    reason: str = Field(min_length=10, max_length=1200)
    evidence_fresh: bool
    invalidation_observed: bool


class PortfolioReview(Strict):
    decisions: list[PositionDecision] = Field(max_length=10)


class ResearchHypothesis(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{4,70}$")
    branch: Literal["intraday", "swing", "options"]
    family: str = Field(max_length=100)
    claim: str = Field(min_length=15, max_length=1000)
    mechanism: str = Field(min_length=15, max_length=1000)
    falsification: str = Field(min_length=15, max_length=1000)
    free_data_feasibility: Literal["ready", "limited", "unavailable"]
    source_urls: list[str] = Field(min_length=1, max_length=5)
    screen_trial_ids: list[str] = Field(max_length=4)
    experiment_ids: list[str] = Field(max_length=6)


class ExplorationReport(Strict):
    summary: str = Field(max_length=2500)
    hypotheses: list[ResearchHypothesis] = Field(min_length=1, max_length=12)
    experiments: list[ExperimentContract] = Field(max_length=12)
    shadow_plans: list[Plan] = Field(max_length=16)
    sources: list[Evidence] = Field(min_length=2, max_length=16)
    uncertainties: list[str] = Field(max_length=15)


class HypothesisValidation(Strict):
    id: str
    verdict: Literal["accepted_for_testing", "needs_work", "rejected"]
    reason: str = Field(min_length=15, max_length=1000)


class ResearchValidation(Strict):
    summary: str = Field(max_length=2000)
    hypotheses: list[HypothesisValidation] = Field(max_length=12)
