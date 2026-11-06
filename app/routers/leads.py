from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.lead import LeadSource, PipelineStage, QualificationTier
from app.schemas.lead import (
    BulkImportResponse,
    LeadCreate,
    LeadDetailOut,
    LeadInteractionOut,
    LeadListResponse,
    LeadOut,
    LeadUpdate,
    NoteCreateRequest,
    PipelineStatsOut,
    StageTransitionRequest,
)
from app.services.crm_service import (
    add_lead_note,
    create_or_merge_lead,
    get_lead_detail,
    get_pipeline_stats,
    import_leads_from_csv,
    list_leads,
    transition_lead_stage,
    update_lead,
)

router = APIRouter(prefix="/leads", tags=["CRM Leads & Ingestion"])


@router.post("", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
def create_lead_endpoint(
    payload: LeadCreate,
    db: Session = Depends(get_db),
) -> LeadOut:
    """Crea un nuevo lead en el CRM o enriquece/deduplica si el email ya existe."""
    lead, _ = create_or_merge_lead(db, payload, actor="api_client")
    return LeadOut.model_validate(lead)


@router.get("", response_model=LeadListResponse)
def list_leads_endpoint(
    stage: PipelineStage | None = Query(default=None),
    tier: QualificationTier | None = Query(default=None),
    source: LeadSource | None = Query(default=None),
    search: str | None = Query(default=None),
    min_score: int | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> LeadListResponse:
    total, items = list_leads(
        db=db,
        stage=stage,
        tier=tier,
        source=source,
        search=search,
        min_score=min_score,
        limit=limit,
        offset=offset,
    )
    return LeadListResponse(
        total=total,
        items=[LeadOut.model_validate(item) for item in items],
    )


@router.get("/stats", response_model=PipelineStatsOut)
def get_pipeline_stats_endpoint(db: Session = Depends(get_db)) -> PipelineStatsOut:
    """Devuelve métricas agregadas del embudo comercial y distribución BANT."""
    return get_pipeline_stats(db)


@router.post("/import/csv", response_model=BulkImportResponse)
async def import_csv_file_endpoint(
    request: Request,
    db: Session = Depends(get_db),
) -> BulkImportResponse:
    """Importa leads masivamente desde un archivo CSV (multipart/form-data), JSON ({'csv_text': ...}) o text/csv."""
    content_type = (request.headers.get("content-type") or "").lower()
    content_str = ""

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        uploaded = form.get("file")
        if uploaded is not None and hasattr(uploaded, "read"):
            raw_bytes = await uploaded.read()
            content_str = raw_bytes.decode("utf-8-sig", errors="replace")
        elif "csv_text" in form:
            content_str = str(form["csv_text"])
    elif "application/json" in content_type:
        body = await request.json()
        if isinstance(body, dict):
            content_str = str(body.get("csv_text") or "")
    else:
        raw_bytes = await request.body()
        content_str = raw_bytes.decode("utf-8-sig", errors="replace")

    if not content_str.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes enviar un archivo CSV ('file') o el campo 'csv_text'.",
        )

    return import_leads_from_csv(db, content_str)


@router.post("/import/batch", response_model=BulkImportResponse)
def import_batch_json_endpoint(
    leads: list[LeadCreate],
    db: Session = Depends(get_db),
) -> BulkImportResponse:
    """Importa un lote de leads en formato JSON con deduplicación por email."""
    created = 0
    deduplicated = 0
    lead_ids: list[int] = []
    for item in leads:
        lead, was_dedup = create_or_merge_lead(db, item, actor="batch_importer")
        lead_ids.append(lead.id)
        if was_dedup:
            deduplicated += 1
        else:
            created += 1

    return BulkImportResponse(
        processed=len(leads),
        created=created,
        deduplicated=deduplicated,
        failed=0,
        errors=[],
        lead_ids=lead_ids,
    )


@router.get("/{lead_id}", response_model=LeadDetailOut)
def get_lead_detail_endpoint(
    lead_id: int,
    db: Session = Depends(get_db),
) -> LeadDetailOut:
    lead = get_lead_detail(db, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead con ID {lead_id} no encontrado.",
        )
    return LeadDetailOut.model_validate(lead)


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead_endpoint(
    lead_id: int,
    payload: LeadUpdate,
    db: Session = Depends(get_db),
) -> LeadOut:
    lead = get_lead_detail(db, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead con ID {lead_id} no encontrado.",
        )
    updated = update_lead(db, lead, payload)
    return LeadOut.model_validate(updated)


@router.post("/{lead_id}/stage", response_model=LeadOut)
def transition_stage_endpoint(
    lead_id: int,
    payload: StageTransitionRequest,
    db: Session = Depends(get_db),
) -> LeadOut:
    lead = get_lead_detail(db, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead con ID {lead_id} no encontrado.",
        )
    updated = transition_lead_stage(
        db=db,
        lead=lead,
        new_stage=payload.stage,
        reason=payload.reason,
        actor=payload.actor,
    )
    return LeadOut.model_validate(updated)


@router.post(
    "/{lead_id}/notes",
    response_model=LeadInteractionOut,
    status_code=status.HTTP_201_CREATED,
)
def add_note_endpoint(
    lead_id: int,
    payload: NoteCreateRequest,
    db: Session = Depends(get_db),
) -> LeadInteractionOut:
    lead = get_lead_detail(db, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead con ID {lead_id} no encontrado.",
        )
    interaction = add_lead_note(
        db=db,
        lead=lead,
        content=payload.content,
        actor=payload.actor,
    )
    return LeadInteractionOut.model_validate(interaction)
