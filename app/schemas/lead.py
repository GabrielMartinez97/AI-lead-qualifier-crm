from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.lead import (
    FollowUpChannel,
    FollowUpStatus,
    InteractionType,
    LeadSource,
    PipelineStage,
    QualificationTier,
)


class LeadCreate(BaseModel):
    external_id: str | None = Field(default=None, max_length=120)
    full_name: str = Field(..., min_length=2, max_length=160)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=60)
    job_title: str | None = Field(default=None, max_length=140)
    company_name: str | None = Field(default=None, max_length=180)
    company_size: str | None = Field(
        default=None,
        description="Tamaño de empresa, ej: '1-10', '11-50', '51-200', '201-1000', '1000+'",
    )
    industry: str | None = Field(default=None, max_length=120)
    company_website: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=80)

    # BANT Discovery Inputs
    estimated_budget_usd: float | None = Field(default=None, ge=0)
    budget_range: str | None = Field(default=None, max_length=80)
    decision_maker_role: str | None = Field(default=None, max_length=100)
    primary_need: str | None = Field(default=None, max_length=200)
    pain_points: str | None = Field(default=None)
    timeline_urgency: str | None = Field(default=None, max_length=80)
    current_solution: str | None = Field(default=None, max_length=160)
    raw_message: str | None = Field(default=None)

    source: LeadSource = Field(default=LeadSource.API_DIRECT)
    tags: list[str] = Field(default_factory=list)
    utm_source: str | None = Field(default=None, max_length=100)
    utm_campaign: str | None = Field(default=None, max_length=120)


class LeadUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    phone: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    company_size: str | None = None
    industry: str | None = None
    company_website: str | None = None
    country: str | None = None
    estimated_budget_usd: float | None = Field(default=None, ge=0)
    budget_range: str | None = None
    decision_maker_role: str | None = None
    primary_need: str | None = None
    pain_points: str | None = None
    timeline_urgency: str | None = None
    current_solution: str | None = None
    raw_message: str | None = None
    tags: list[str] | None = None
    suggested_owner: str | None = None


class StageTransitionRequest(BaseModel):
    stage: PipelineStage
    reason: str | None = Field(default=None, max_length=500)
    actor: str = Field(default="sales_rep", max_length=100)


class NoteCreateRequest(BaseModel):
    content: str = Field(..., min_length=2, max_length=4000)
    actor: str = Field(default="sales_rep", max_length=100)


class LeadInteractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    interaction_type: InteractionType
    channel: str
    direction: str
    subject: str | None
    content: str
    metadata_json: dict[str, Any] | None
    actor: str
    created_at: datetime


class FollowUpTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    step_number: int
    channel: FollowUpChannel
    status: FollowUpStatus
    scheduled_at: datetime
    executed_at: datetime | None
    subject: str | None
    body: str
    ai_personalization_notes: str | None
    created_at: datetime


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str | None
    full_name: str
    email: str
    phone: str | None
    job_title: str | None
    company_name: str | None
    company_size: str | None
    industry: str | None
    company_website: str | None
    country: str | None

    estimated_budget_usd: float | None
    budget_range: str | None
    decision_maker_role: str | None
    primary_need: str | None
    pain_points: str | None
    timeline_urgency: str | None
    current_solution: str | None
    raw_message: str | None

    bant_total_score: int
    budget_score: int
    authority_score: int
    need_score: int
    timeline_score: int
    qualification_tier: QualificationTier
    ai_summary: str | None
    ai_reasoning: dict[str, Any] | None
    detected_intent: str | None
    recommended_next_action: str | None
    suggested_owner: str | None
    scoring_engine: str | None
    qualified_at: datetime | None

    stage: PipelineStage
    source: LeadSource
    tags: list[str]
    utm_source: str | None
    utm_campaign: str | None
    duplicate_count: int
    last_contacted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LeadDetailOut(LeadOut):
    interactions: list[LeadInteractionOut] = Field(default_factory=list)
    follow_up_tasks: list[FollowUpTaskOut] = Field(default_factory=list)


class LeadListResponse(BaseModel):
    total: int
    items: list[LeadOut]


class PipelineStatsOut(BaseModel):
    total_leads: int
    by_stage: dict[str, int]
    by_tier: dict[str, int]
    by_source: dict[str, int]
    average_bant_score: float
    hot_leads_count: int
    conversion_ready_rate: float
    total_estimated_pipeline_usd: float


class BulkImportResponse(BaseModel):
    processed: int
    created: int
    deduplicated: int
    failed: int
    errors: list[str] = Field(default_factory=list)
    lead_ids: list[int] = Field(default_factory=list)


class WebhookIngestResponse(BaseModel):
    status: str
    provider: str
    event_id: int
    deduplicated: bool
    lead: LeadOut
