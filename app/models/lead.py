from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SqlEnum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeadSource(str, Enum):
    WEBSITE_FORM = "website_form"
    TYPEFORM_WEBHOOK = "typeform_webhook"
    META_ADS_WEBHOOK = "meta_ads_webhook"
    LINKEDIN_ADS_WEBHOOK = "linkedin_ads_webhook"
    HUBSPOT_WEBHOOK = "hubspot_webhook"
    CSV_IMPORT = "csv_import"
    API_DIRECT = "api_direct"


class PipelineStage(str, Enum):
    NEW = "new"
    QUALIFYING = "qualifying"
    QUALIFIED = "qualified"
    CONTACTED = "contacted"
    MEETING_SCHEDULED = "meeting_scheduled"
    PROPOSAL_SENT = "proposal_sent"
    WON = "won"
    LOST = "lost"
    NURTURE = "nurture"


class QualificationTier(str, Enum):
    UNSCORED = "unscored"
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    DISQUALIFIED = "disqualified"


class InteractionType(str, Enum):
    LEAD_CAPTURED = "lead_captured"
    LEAD_UPDATED = "lead_updated"
    AI_QUALIFIED = "ai_qualified"
    STAGE_CHANGED = "stage_changed"
    EMAIL_SENT = "email_sent"
    WHATSAPP_SENT = "whatsapp_sent"
    LINKEDIN_SENT = "linkedin_sent"
    LEAD_REPLIED = "lead_replied"
    NOTE_ADDED = "note_added"
    WEBHOOK_DISPATCHED = "webhook_dispatched"


class FollowUpStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    REPLIED = "replied"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class FollowUpChannel(str, Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    LINKEDIN = "linkedin"
    CALL = "call"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    # Contact & Company Identity
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(140), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    company_size: Mapped[str | None] = mapped_column(String(60), nullable=True)  # e.g. "1-10", "11-50", "51-200", "201-1000", "1000+"
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    company_website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Raw BANT Discovery Inputs (Budget, Authority, Need, Timeline)
    estimated_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_range: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decision_maker_role: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g., "C-Level / Founder", "VP / Director", "Manager", "Individual Contributor"
    primary_need: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pain_points: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeline_urgency: Mapped[str | None] = mapped_column(String(80), nullable=True)  # e.g., "immediate", "1_3_months", "3_6_months", "exploring"
    current_solution: Mapped[str | None] = mapped_column(String(160), nullable=True)
    raw_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # AI Qualification Output (BANT Breakdown 0-25 each = 0-100 total)
    bant_total_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    budget_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    authority_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    need_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    timeline_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    qualification_tier: Mapped[QualificationTier] = mapped_column(
        SqlEnum(QualificationTier),
        default=QualificationTier.UNSCORED,
        nullable=False,
        index=True,
    )
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_reasoning: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    detected_intent: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recommended_next_action: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suggested_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scoring_engine: Mapped[str | None] = mapped_column(String(80), nullable=True)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # CRM Pipeline & Attribution
    stage: Mapped[PipelineStage] = mapped_column(
        SqlEnum(PipelineStage),
        default=PipelineStage.NEW,
        nullable=False,
        index=True,
    )
    source: Mapped[LeadSource] = mapped_column(
        SqlEnum(LeadSource),
        default=LeadSource.API_DIRECT,
        nullable=False,
        index=True,
    )
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    utm_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(120), nullable=True)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    interactions: Mapped[list["LeadInteraction"]] = relationship(
        "LeadInteraction",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="desc(LeadInteraction.created_at)",
    )
    follow_up_tasks: Mapped[list["FollowUpTask"]] = relationship(
        "FollowUpTask",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="FollowUpTask.step_number",
    )


class LeadInteraction(Base):
    __tablename__ = "lead_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    lead_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    interaction_type: Mapped[InteractionType] = mapped_column(
        SqlEnum(InteractionType), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(60), default="system", nullable=False)
    direction: Mapped[str] = mapped_column(String(30), default="system", nullable=False)  # inbound, outbound, system
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    actor: Mapped[str] = mapped_column(String(100), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    lead: Mapped["Lead"] = relationship("Lead", back_populates="interactions")


class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    lead_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    channel: Mapped[FollowUpChannel] = mapped_column(
        SqlEnum(FollowUpChannel), default=FollowUpChannel.EMAIL, nullable=False
    )
    status: Mapped[FollowUpStatus] = mapped_column(
        SqlEnum(FollowUpStatus), default=FollowUpStatus.PENDING, nullable=False, index=True
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    ai_personalization_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    lead: Mapped["Lead"] = relationship("Lead", back_populates="follow_up_tasks")


class WebhookEventLog(Base):
    __tablename__ = "webhook_event_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    direction: Mapped[str] = mapped_column(String(30), default="inbound", nullable=False)  # inbound, outbound
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)  # typeform, meta_ads, linkedin_ads, hubspot, website
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="processed", nullable=False)
    lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
