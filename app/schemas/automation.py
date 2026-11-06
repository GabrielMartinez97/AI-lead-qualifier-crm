from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field

from app.models.lead import FollowUpChannel, FollowUpStatus, PipelineStage
from app.schemas.lead import FollowUpTaskOut


class SequenceEnrollmentResponse(BaseModel):
    lead_id: int
    qualification_tier: str
    cadence_name: str
    tasks_created: int
    outbound_webhook_dispatched: bool
    tasks: list[FollowUpTaskOut]


class ExecuteTaskResponse(BaseModel):
    task: FollowUpTaskOut
    lead_id: int
    lead_stage: PipelineStage
    interaction_id: int
    message: str


class InboundReplyRequest(BaseModel):
    channel: FollowUpChannel = Field(default=FollowUpChannel.EMAIL)
    message: str = Field(..., min_length=2, max_length=4000)
    sender_name: str | None = Field(default=None, max_length=160)


class InboundReplyAnalysisOut(BaseModel):
    lead_id: int
    detected_reply_intent: str  # book_meeting, pricing_inquiry, objection, unsubscribe, general_question
    sentiment: str  # positive, neutral, negative
    confidence: float
    previous_stage: PipelineStage
    new_stage: PipelineStage
    cancelled_Pending_tasks: int
    ai_suggested_response_subject: str
    ai_suggested_response_body: str
    internal_sales_alert: str
    outbound_webhook_dispatched: bool
    analyzed_at: datetime


class BatchExecuteDueResponse(BaseModel):
    executed_count: int
    task_ids: list[int]
    details: list[dict[str, Any]]
