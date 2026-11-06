from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.lead import FollowUpChannel, FollowUpStatus, FollowUpTask
from app.schemas.automation import (
    BatchExecuteDueResponse,
    ExecuteTaskResponse,
    InboundReplyAnalysisOut,
    InboundReplyRequest,
    SequenceEnrollmentResponse,
)
from app.schemas.lead import FollowUpTaskOut
from app.services.automation_service import (
    enroll_lead_in_sequence,
    execute_due_follow_up_tasks,
    execute_follow_up_task,
    handle_inbound_lead_reply,
)
from app.services.crm_service import get_lead_detail

router = APIRouter(
    prefix="/automation",
    tags=["Commercial Automation & Multi-Channel Sequences"],
)


@router.post("/leads/{lead_id}/enroll", response_model=SequenceEnrollmentResponse)
def enroll_lead_sequence_endpoint(
    lead_id: int,
    replace_pending: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> SequenceEnrollmentResponse:
    """Inscribe o regenera la secuencia adaptativa de seguimiento multi-canal para un lead según su Tier BANT."""
    lead = get_lead_detail(db, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead con ID {lead_id} no encontrado.",
        )
    return enroll_lead_in_sequence(db=db, lead=lead, replace_pending=replace_pending)


@router.get("/tasks", response_model=list[FollowUpTaskOut])
def list_follow_up_tasks_endpoint(
    lead_id: int | None = Query(default=None),
    task_status: FollowUpStatus | None = Query(default=None, alias="status"),
    channel: FollowUpChannel | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[FollowUpTaskOut]:
    """Lista las tareas de seguimiento comercial programadas en la cola de automatización."""
    stmt = select(FollowUpTask)
    if lead_id is not None:
        stmt = stmt.where(FollowUpTask.lead_id == lead_id)
    if task_status is not None:
        stmt = stmt.where(FollowUpTask.status == task_status)
    if channel is not None:
        stmt = stmt.where(FollowUpTask.channel == channel)

    stmt = stmt.order_by(FollowUpTask.scheduled_at.asc(), FollowUpTask.step_number.asc()).limit(limit)
    tasks = list(db.scalars(stmt).all())
    return [FollowUpTaskOut.model_validate(t) for t in tasks]


@router.post("/tasks/{task_id}/execute", response_model=ExecuteTaskResponse)
def execute_single_task_endpoint(
    task_id: int,
    db: Session = Depends(get_db),
) -> ExecuteTaskResponse:
    """Ejecuta inmediatamente un paso de seguimiento (Email, WhatsApp, LinkedIn o Llamada) y actualiza el CRM."""
    try:
        return execute_follow_up_task(db=db, task_id=task_id, actor="manual_or_agent_trigger")
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/run-due", response_model=BatchExecuteDueResponse)
def run_due_tasks_endpoint(
    force_all_pending: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> BatchExecuteDueResponse:
    """Procesa en lote las tareas de seguimiento cuyo horario programado ya venció (o todas si force_all_pending=true)."""
    return execute_due_follow_up_tasks(
        db=db,
        force_all_pending=force_all_pending,
        limit=limit,
    )


@router.post("/leads/{lead_id}/reply", response_model=InboundReplyAnalysisOut)
def process_inbound_reply_endpoint(
    lead_id: int,
    payload: InboundReplyRequest,
    db: Session = Depends(get_db),
) -> InboundReplyAnalysisOut:
    """Analiza con IA la respuesta entrante de un lead (intención, sentimiento, objeción o agendamiento),
    pausa los seguimientos pendientes, mueve la etapa del pipeline y redacta/envía la respuesta contextual.
    """
    lead = get_lead_detail(db, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead con ID {lead_id} no encontrado.",
        )
    return handle_inbound_lead_reply(db=db, lead=lead, payload=payload)
