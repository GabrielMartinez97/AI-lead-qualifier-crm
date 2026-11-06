import csv
import io
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.lead import (
    InteractionType,
    Lead,
    LeadInteraction,
    LeadSource,
    PipelineStage,
    QualificationTier,
)
from app.schemas.lead import (
    BulkImportResponse,
    LeadCreate,
    LeadUpdate,
    PipelineStatsOut,
)
from app.services.ai_qualifier import qualify_lead_in_db


def create_or_merge_lead(
    db: Session, payload: LeadCreate, actor: str = "ingestion_engine"
) -> tuple[Lead, bool]:
    """Create a new lead or merge into an existing lead by normalized email (idempotency)."""
    normalized_email = payload.email.strip().lower()
    existing = db.scalar(select(Lead).where(func.lower(Lead.email) == normalized_email))

    if existing:
        existing.duplicate_count += 1
        merged_fields: list[str] = []

        update_candidates = {
            "full_name": payload.full_name,
            "phone": payload.phone,
            "job_title": payload.job_title,
            "company_name": payload.company_name,
            "company_size": payload.company_size,
            "industry": payload.industry,
            "company_website": payload.company_website,
            "country": payload.country,
            "estimated_budget_usd": payload.estimated_budget_usd,
            "budget_range": payload.budget_range,
            "decision_maker_role": payload.decision_maker_role,
            "primary_need": payload.primary_need,
            "pain_points": payload.pain_points,
            "timeline_urgency": payload.timeline_urgency,
            "current_solution": payload.current_solution,
            "raw_message": payload.raw_message,
            "utm_source": payload.utm_source,
            "utm_campaign": payload.utm_campaign,
        }

        for field_name, new_val in update_candidates.items():
            if new_val is not None and new_val != "":
                current_val = getattr(existing, field_name)
                if current_val != new_val:
                    setattr(existing, field_name, new_val)
                    merged_fields.append(field_name)

        if payload.tags:
            combined_tags = list(dict.fromkeys([*(existing.tags or []), *payload.tags]))
            existing.tags = combined_tags

        interaction = LeadInteraction(
            lead_id=existing.id,
            interaction_type=InteractionType.LEAD_UPDATED,
            channel=payload.source.value,
            direction="inbound",
            subject=f"Re-ingreso de lead detectado ({payload.source.value})",
            content=(
                f"El contacto volvió a interactuar desde '{payload.source.value}'. "
                f"Campos actualizados/enriquecidos: {', '.join(merged_fields) if merged_fields else 'ninguno'}."
            ),
            metadata_json={
                "duplicate_count": existing.duplicate_count,
                "merged_fields": merged_fields,
                "source": payload.source.value,
            },
            actor=actor,
        )
        db.add(interaction)
        db.commit()
        db.refresh(existing)
        if settings.AUTO_QUALIFY_ON_INGEST and merged_fields:
            existing, _ = qualify_lead_in_db(db, existing, actor="ai_auto_requalifier")
        return existing, True

    lead = Lead(
        external_id=payload.external_id,
        full_name=payload.full_name.strip(),
        email=normalized_email,
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
        stage=PipelineStage.NEW,
        qualification_tier=QualificationTier.UNSCORED,
        tags=payload.tags or [],
        utm_source=payload.utm_source,
        utm_campaign=payload.utm_campaign,
    )
    db.add(lead)
    db.flush()

    capture_interaction = LeadInteraction(
        lead_id=lead.id,
        interaction_type=InteractionType.LEAD_CAPTURED,
        channel=payload.source.value,
        direction="inbound",
        subject=f"Lead capturado vía {payload.source.value}",
        content=(
            f"Nuevo lead registrado: {lead.full_name} ({lead.company_name or 'Sin empresa'}) — "
            f"Cargo: {lead.job_title or 'N/A'}. "
            f"Necesidad principal: {lead.primary_need or lead.raw_message or 'No especificada'}."
        ),
        metadata_json={
            "source": payload.source.value,
            "estimated_budget_usd": lead.estimated_budget_usd,
            "timeline_urgency": lead.timeline_urgency,
            "utm_source": lead.utm_source,
            "utm_campaign": lead.utm_campaign,
        },
        actor=actor,
    )
    db.add(capture_interaction)
    db.commit()
    db.refresh(lead)
    if settings.AUTO_QUALIFY_ON_INGEST:
        lead, _ = qualify_lead_in_db(db, lead, actor="ai_auto_qualifier")
    return lead, False


def list_leads(
    db: Session,
    stage: PipelineStage | None = None,
    tier: QualificationTier | None = None,
    source: LeadSource | None = None,
    search: str | None = None,
    min_score: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[Lead]]:
    stmt = select(Lead)

    if stage is not None:
        stmt = stmt.where(Lead.stage == stage)
    if tier is not None:
        stmt = stmt.where(Lead.qualification_tier == tier)
    if source is not None:
        stmt = stmt.where(Lead.source == source)
    if min_score is not None:
        stmt = stmt.where(Lead.bant_total_score >= min_score)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Lead.full_name.ilike(pattern),
                Lead.email.ilike(pattern),
                Lead.company_name.ilike(pattern),
                Lead.job_title.ilike(pattern),
                Lead.primary_need.ilike(pattern),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    items_stmt = (
        stmt.order_by(Lead.bant_total_score.desc(), Lead.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = list(db.scalars(items_stmt).all())
    return total, items


def get_lead_detail(db: Session, lead_id: int) -> Lead | None:
    stmt = (
        select(Lead)
        .where(Lead.id == lead_id)
        .options(
            selectinload(Lead.interactions),
            selectinload(Lead.follow_up_tasks),
        )
    )
    return db.scalar(stmt)


def update_lead(db: Session, lead: Lead, payload: LeadUpdate) -> Lead:
    update_data = payload.model_dump(exclude_unset=True)
    for field_name, val in update_data.items():
        setattr(lead, field_name, val)

    db.commit()
    db.refresh(lead)
    return lead


def transition_lead_stage(
    db: Session,
    lead: Lead,
    new_stage: PipelineStage,
    reason: str | None = None,
    actor: str = "sales_rep",
) -> Lead:
    previous_stage = lead.stage
    lead.stage = new_stage

    interaction = LeadInteraction(
        lead_id=lead.id,
        interaction_type=InteractionType.STAGE_CHANGED,
        channel="crm_pipeline",
        direction="system",
        subject=f"Cambio de etapa: {previous_stage.value} → {new_stage.value}",
        content=reason or f"Etapa comercial actualizada de '{previous_stage.value}' a '{new_stage.value}'.",
        metadata_json={
            "previous_stage": previous_stage.value,
            "new_stage": new_stage.value,
        },
        actor=actor,
    )
    db.add(interaction)
    db.commit()
    db.refresh(lead)
    return lead


def add_lead_note(
    db: Session,
    lead: Lead,
    content: str,
    actor: str = "sales_rep",
) -> LeadInteraction:
    interaction = LeadInteraction(
        lead_id=lead.id,
        interaction_type=InteractionType.NOTE_ADDED,
        channel="crm_note",
        direction="system",
        subject="Nota comercial registrada",
        content=content.strip(),
        actor=actor,
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    return interaction


def get_pipeline_stats(db: Session) -> PipelineStatsOut:
    leads = list(db.scalars(select(Lead)).all())
    total = len(leads)

    by_stage: dict[str, int] = {s.value: 0 for s in PipelineStage}
    by_tier: dict[str, int] = {t.value: 0 for t in QualificationTier}
    by_source: dict[str, int] = {}

    scored_leads = [l for l in leads if l.qualification_tier != QualificationTier.UNSCORED]
    total_score = sum(l.bant_total_score for l in scored_leads)
    avg_score = round(total_score / len(scored_leads), 1) if scored_leads else 0.0

    hot_count = 0
    conversion_ready_count = 0
    total_pipeline_usd = 0.0

    for lead in leads:
        by_stage[lead.stage.value] = by_stage.get(lead.stage.value, 0) + 1
        by_tier[lead.qualification_tier.value] = by_tier.get(lead.qualification_tier.value, 0) + 1
        by_source[lead.source.value] = by_source.get(lead.source.value, 0) + 1

        if lead.qualification_tier == QualificationTier.HOT:
            hot_count += 1
        if lead.qualification_tier in (QualificationTier.HOT, QualificationTier.WARM):
            conversion_ready_count += 1
        if lead.estimated_budget_usd and lead.stage not in (PipelineStage.LOST,):
            total_pipeline_usd += float(lead.estimated_budget_usd)

    conversion_ready_rate = round((conversion_ready_count / total) * 100.0, 1) if total > 0 else 0.0

    return PipelineStatsOut(
        total_leads=total,
        by_stage=by_stage,
        by_tier=by_tier,
        by_source=by_source,
        average_bant_score=avg_score,
        hot_leads_count=hot_count,
        conversion_ready_rate=conversion_ready_rate,
        total_estimated_pipeline_usd=round(total_pipeline_usd, 2),
    )


def import_leads_from_csv(db: Session, csv_text: str) -> BulkImportResponse:
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    processed = 0
    created = 0
    deduplicated = 0
    failed = 0
    errors: list[str] = []
    lead_ids: list[int] = []

    for idx, row in enumerate(reader, start=1):
        processed += 1
        norm_row = {
            (k.strip().lower() if k else ""): (v.strip() if isinstance(v, str) else "")
            for k, v in row.items()
        }

        email = (
            norm_row.get("email")
            or norm_row.get("correo")
            or norm_row.get("work_email")
            or ""
        )
        full_name = (
            norm_row.get("full_name")
            or norm_row.get("name")
            or norm_row.get("nombre")
            or ""
        )

        if not email or not full_name:
            failed += 1
            errors.append(f"Fila {idx}: 'full_name'/'nombre' y 'email'/'correo' son obligatorios.")
            continue

        raw_budget = (
            norm_row.get("estimated_budget_usd")
            or norm_row.get("budget")
            or norm_row.get("presupuesto")
            or ""
        )
        budget_usd: float | None = None
        if raw_budget:
            cleaned = (
                raw_budget.replace("$", "")
                .replace(",", "")
                .replace("USD", "")
                .replace("usd", "")
                .strip()
            )
            try:
                budget_usd = float(cleaned)
            except ValueError:
                budget_usd = None

        raw_tags = norm_row.get("tags") or norm_row.get("etiquetas") or ""
        tags = [t.strip() for t in raw_tags.split(";") if t.strip()] if raw_tags else ["csv-import"]

        try:
            lead_in = LeadCreate(
                full_name=full_name,
                email=email,
                phone=norm_row.get("phone") or norm_row.get("telefono") or None,
                job_title=norm_row.get("job_title") or norm_row.get("cargo") or norm_row.get("role") or None,
                company_name=norm_row.get("company_name") or norm_row.get("company") or norm_row.get("empresa") or None,
                company_size=norm_row.get("company_size") or norm_row.get("tamano_empresa") or norm_row.get("size") or None,
                industry=norm_row.get("industry") or norm_row.get("industria") or norm_row.get("sector") or None,
                company_website=norm_row.get("company_website") or norm_row.get("website") or None,
                country=norm_row.get("country") or norm_row.get("pais") or None,
                estimated_budget_usd=budget_usd,
                budget_range=norm_row.get("budget_range") or (raw_budget if budget_usd is None and raw_budget else None),
                decision_maker_role=norm_row.get("decision_maker_role") or norm_row.get("nivel_decision") or None,
                primary_need=norm_row.get("primary_need") or norm_row.get("need") or norm_row.get("necesidad") or None,
                pain_points=norm_row.get("pain_points") or norm_row.get("dolores") or None,
                timeline_urgency=norm_row.get("timeline_urgency") or norm_row.get("timeline") or norm_row.get("urgencia") or None,
                current_solution=norm_row.get("current_solution") or norm_row.get("solucion_actual") or None,
                raw_message=norm_row.get("raw_message") or norm_row.get("message") or norm_row.get("mensaje") or None,
                source=LeadSource.CSV_IMPORT,
                tags=tags,
            )
            lead, was_dedup = create_or_merge_lead(db, lead_in, actor="csv_importer")
            lead_ids.append(lead.id)
            if was_dedup:
                deduplicated += 1
            else:
                created += 1
        except Exception as exc:
            failed += 1
            errors.append(f"Fila {idx} ({email}): {exc}")

    return BulkImportResponse(
        processed=processed,
        created=created,
        deduplicated=deduplicated,
        failed=failed,
        errors=errors,
        lead_ids=lead_ids,
    )
