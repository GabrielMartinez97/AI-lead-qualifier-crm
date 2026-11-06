from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field

from app.models.lead import PipelineStage, QualificationTier


class BANTBreakdownSchema(BaseModel):
    budget_score: int = Field(..., ge=0, le=25)
    budget_rationale: str
    authority_score: int = Field(..., ge=0, le=25)
    authority_rationale: str
    need_score: int = Field(..., ge=0, le=25)
    need_rationale: str
    timeline_score: int = Field(..., ge=0, le=25)
    timeline_rationale: str


class DomainIntelligenceSchema(BaseModel):
    email_domain: str
    is_corporate_domain: bool
    inferred_website: str | None = None
    inferred_country: str | None = None
    trust_signal: str


class AIQualificationResult(BaseModel):
    bant_total_score: int = Field(..., ge=0, le=100)
    qualification_tier: QualificationTier
    recommended_stage: PipelineStage
    bant_breakdown: BANTBreakdownSchema
    domain_intelligence: DomainIntelligenceSchema
    icp_fit_level: str
    detected_intent: str
    ai_summary: str
    potential_objections: list[str] = Field(default_factory=list)
    talking_points: list[str] = Field(default_factory=list)
    recommended_next_action: str
    suggested_owner: str
    scoring_engine: str
    qualified_at: datetime


class BatchQualifyRequest(BaseModel):
    lead_ids: list[int] | None = Field(
        default=None,
        description="IDs de leads a cualificar. Si es null, cualifica todos los leads unscored o indicados por limit.",
    )
    only_unscored: bool = Field(default=True)
    limit: int = Field(default=25, ge=1, le=100)
    force_heuristic: bool = Field(default=False)


class BatchQualifyResponse(BaseModel):
    processed: int
    hot_count: int
    warm_count: int
    cold_count: int
    disqualified_count: int
    results: list[dict[str, Any]]
