from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.lead import Lead
from app.schemas.ai_qualification import (
    AIQualificationResult,
    BatchQualifyRequest,
    BatchQualifyResponse,
)
from app.schemas.lead import LeadCreate, LeadOut
from app.services.ai_qualifier import (
    evaluate_lead_ai,
    qualify_lead_in_db,
    qualify_leads_batch,
)
from app.services.crm_service import get_lead_detail

router = APIRouter(prefix="/ai", tags=["AI Lead Qualifier Agent (BANT + Domain Intel)"])


@router.post("/qualify/{lead_id}")
def qualify_single_lead_endpoint(
    lead_id: int,
    force_heuristic: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Ejecuta el Agente IA Cualificador (BANT + Inteligencia de Dominio) sobre un lead existente."""
    lead = get_lead_detail(db, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead con ID {lead_id} no encontrado.",
        )

    updated_lead, qualification = qualify_lead_in_db(
        db=db,
        lead=lead,
        force_heuristic=force_heuristic,
        actor="ai_qualifier_manual",
    )
    return {
        "lead": LeadOut.model_validate(updated_lead),
        "qualification": qualification,
    }


@router.post("/qualify-batch", response_model=BatchQualifyResponse)
def qualify_batch_endpoint(
    payload: BatchQualifyRequest,
    db: Session = Depends(get_db),
) -> BatchQualifyResponse:
    """Cualifica en lote leads pendientes o un subconjunto de IDs mediante el Agente IA."""
    return qualify_leads_batch(
        db=db,
        lead_ids=payload.lead_ids,
        only_unscored=payload.only_unscored,
        limit=payload.limit,
        force_heuristic=payload.force_heuristic,
    )


@router.post("/analyze-preview", response_model=AIQualificationResult)
def analyze_lead_preview_endpoint(
    payload: LeadCreate,
    force_heuristic: bool = Query(default=False),
) -> AIQualificationResult:
    """Simula en vivo el análisis BANT + Inteligencia de Dominio de un lead sin guardarlo en la base de datos."""
    temp_lead = Lead(
        full_name=payload.full_name,
        email=payload.email.strip().lower(),
        phone=payload.phone,
        job_title=payload.job_title,
        company_name=payload.company_name,
        company_size=payload.company_size,
        industry=payload.industry,
        company_website=payload.company_website,
        country=payload.country,
        estimated_budget_usd=payload.estimated_budget_usd,
        budget_range=payload.budget_range,
        decision_maker_role=payload.decision_maker_role,
        primary_need=payload.primary_need,
        pain_points=payload.pain_points,
        timeline_urgency=payload.timeline_urgency,
        current_solution=payload.current_solution,
        raw_message=payload.raw_message,
        source=payload.source,
    )
    return evaluate_lead_ai(temp_lead, force_heuristic=force_heuristic)
