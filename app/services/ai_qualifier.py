import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.lead import (
    InteractionType,
    Lead,
    LeadInteraction,
    PipelineStage,
    QualificationTier,
)
from app.schemas.ai_qualification import (
    AIQualificationResult,
    BANTBreakdownSchema,
    BatchQualifyResponse,
    DomainIntelligenceSchema,
)

FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "yahoo.com",
    "yahoo.es",
    "icloud.com",
    "me.com",
    "proton.me",
    "protonmail.com",
    "aol.com",
    "zoho.com",
    "gmx.com",
    "mail.com",
}

TLD_COUNTRY_MAP = {
    "cl": "Chile",
    "mx": "México",
    "co": "Colombia",
    "ar": "Argentina",
    "pe": "Perú",
    "es": "España",
    "uy": "Uruguay",
    "br": "Brasil",
    "us": "Estados Unidos",
}


def analyze_email_domain(email: str) -> DomainIntelligenceSchema:
    parts = email.strip().lower().split("@")
    domain = parts[1] if len(parts) == 2 else "unknown.local"
    is_corporate = domain not in FREE_EMAIL_DOMAINS and not domain.endswith(".edu")

    tld = domain.split(".")[-1] if "." in domain else ""
    inferred_country = TLD_COUNTRY_MAP.get(tld)

    if is_corporate:
        inferred_website = f"https://{domain}"
        if tld in ("io", "ai", "tech", "cloud", "dev", "app"):
            trust_signal = f"Dominio tecnológico B2B verificado ({domain}) — alta afinidad digital"
        else:
            trust_signal = f"Dominio corporativo verificado ({domain})"
    else:
        inferred_website = None
        trust_signal = f"Correo personal/gratuito ({domain}) — menor señal de madurez corporativa"

    return DomainIntelligenceSchema(
        email_domain=domain,
        is_corporate_domain=is_corporate,
        inferred_website=inferred_website,
        inferred_country=inferred_country,
        trust_signal=trust_signal,
    )


def _parse_budget_hint(budget_usd: float | None, budget_range: str | None, raw_msg: str | None) -> float | None:
    if budget_usd is not None and budget_usd > 0:
        return float(budget_usd)

    combined = f"{budget_range or ''} {raw_msg or ''}".lower()
    # Look for patterns like $15,000, 20k, 15000 usd
    match_k = re.search(r"\$?\s*(\d+(?:[.,]\d+)?)\s*k\b", combined)
    if match_k:
        return float(match_k.group(1).replace(",", ".")) * 1000.0

    match_usd = re.search(r"\$\s*(\d{1,3}(?:[.,]\d{3})+|\d{4,7})", combined)
    if match_usd:
        cleaned = match_usd.group(1).replace(",", "").replace(".", "")
        try:
            return float(cleaned)
        except ValueError:
            pass

    return None


def _evaluate_heuristic_bant(
    lead: Lead,
    domain_info: DomainIntelligenceSchema,
) -> AIQualificationResult:
    now = datetime.now(timezone.utc)

    # 1. BUDGET SCORE (0 - 25)
    inferred_budget = _parse_budget_hint(
        lead.estimated_budget_usd, lead.budget_range, lead.raw_message
    )
    company_size_str = (lead.company_size or "").strip()

    if inferred_budget is not None:
        if inferred_budget >= 25000:
            budget_score = 25
            budget_rationale = f"Presupuesto Enterprise confirmado (${inferred_budget:,.0f} USD), supera ampliamente el ticket objetivo B2B."
        elif inferred_budget >= 10000:
            budget_score = 21
            budget_rationale = f"Presupuesto Mid-Market sólido (${inferred_budget:,.0f} USD), ideal para despliegue completo de agentes IA."
        elif inferred_budget >= 4000:
            budget_score = 15
            budget_rationale = f"Presupuesto moderado (${inferred_budget:,.0f} USD), apto para plan inicial o piloto acotado."
        elif inferred_budget >= 1500:
            budget_score = 9
            budget_rationale = f"Presupuesto ajustado (${inferred_budget:,.0f} USD), requiere paquete estandarizado Self-Serve."
        else:
            budget_score = 4
            budget_rationale = f"Presupuesto muy bajo (${inferred_budget:,.0f} USD) frente al costo de implementación B2B."
    else:
        if company_size_str in ("201-1000", "1000+", "51-200"):
            budget_score = 16
            budget_rationale = f"Sin presupuesto explícito, pero tamaño de empresa ({company_size_str} empleados) sugiere capacidad financiera media-alta."
        elif company_size_str == "11-50":
            budget_score = 12
            budget_rationale = "Presupuesto por descubrir en llamada; empresa en crecimiento (11-50 empleados)."
        else:
            budget_score = 7
            budget_rationale = "Sin presupuesto declarado ni señales de escala corporativa."

    # 2. AUTHORITY SCORE (0 - 25)
    role_text = f"{lead.job_title or ''} {lead.decision_maker_role or ''}".lower()
    if any(k in role_text for k in ("ceo", "cto", "coo", "cfo", "founder", "co-founder", "fundador", "director general", "presidente", "owner", "c-level")):
        authority_score = 24
        authority_rationale = f"Tomador de decisión final C-Level/Founder ({lead.job_title or lead.decision_maker_role})."
    elif any(k in role_text for k in ("vp", "vice president", "director", "head of", "gerente general", "gerente comercial", "cro")):
        authority_score = 20
        authority_rationale = f"Ejecutivo con alta influencia presupuestaria ({lead.job_title or lead.decision_maker_role})."
    elif any(k in role_text for k in ("manager", "gerente", "líder", "lead", "jefe", "product owner", "operations")):
        authority_score = 15
        authority_rationale = f"Mando medio / Champion operativo ({lead.job_title or lead.decision_maker_role}); puede requerir aprobación de dirección."
    elif any(k in role_text for k in ("estudiante", "student", "practicante", "intern", "becario")):
        authority_score = 3
        authority_rationale = f"Perfil académico/sin autoridad de compra comercial ({lead.job_title or 'Estudiante/Practicante'})."
    elif role_text.strip():
        authority_score = 10
        authority_rationale = f"Rol individual o evaluador técnico ({lead.job_title or lead.decision_maker_role}); validar quién firma el contrato."
    else:
        authority_score = 8
        authority_rationale = "Cargo no especificado en el registro inicial."

    if domain_info.is_corporate_domain and authority_score < 25:
        authority_score = min(25, authority_score + 1)
    elif not domain_info.is_corporate_domain:
        authority_score = max(2, authority_score - 3)
        authority_rationale += f" Penalizado (-3 pts) por uso de correo gratuito ({domain_info.email_domain})."

    # 3. NEED SCORE (0 - 25)
    need_text = f"{lead.primary_need or ''} {lead.pain_points or ''} {lead.raw_message or ''}".lower()
    high_value_keywords = (
        "automatizar", "agente", "ia", "crm", "leads", "cualificar", "seguimiento",
        "ventas", "pipeline", "webhook", "api", "integrar", "hubspot", "salesforce",
        "conversión", "sdr", "erp", "atención", "b2b", "escala",
    )
    matched_keywords = [kw for kw in high_value_keywords if kw in need_text]

    if len(matched_keywords) >= 3 or len(need_text.strip()) >= 75:
        need_score = 23
        need_rationale = (
            f"Dolor de negocio altamente alineado con nuestra solución ({', '.join(matched_keywords[:4]) or 'caso de uso detallado'})."
        )
    elif len(matched_keywords) >= 1 or len(need_text.strip()) >= 25:
        need_score = 16
        need_rationale = (
            f"Necesidad comercial identificada ({lead.primary_need or 'automatización'}), requiere profundizar métricas de impacto."
        )
    elif any(k in need_text for k in ("curiosidad", "solo mirando", "tarea", "universidad", "prueba gratis sin presupuesto")):
        need_score = 4
        need_rationale = "Intención exploratoria o no comercial sin dolor operativo urgente."
    else:
        need_score = 9
        need_rationale = "Contexto de necesidad escaso; se requiere discovery para confirmar encaje técnico."

    # 4. TIMELINE SCORE (0 - 25)
    timeline_text = f"{lead.timeline_urgency or ''} {lead.raw_message or ''}".lower()
    if any(k in timeline_text for k in ("immediate", "inmediato", "urgente", "esta semana", "este mes", "asap", "ya", "q4", "15 días", "30 días")):
        timeline_score = 24
        timeline_rationale = "Urgencia inmediata de implementación (< 30 días)."
    elif any(k in timeline_text for k in ("1_3_months", "1-3", "trimestre", "próximo mes", "2 meses", "3 meses")):
        timeline_score = 18
        timeline_rationale = "Horizonte de decisión a corto-mediano plazo (1 a 3 meses)."
    elif any(k in timeline_text for k in ("3_6_months", "3-6", "semestre", "mitad de año", "6 meses")):
        timeline_score = 11
        timeline_rationale = "Proyecto planificado a mediano plazo (3 a 6 meses)."
    elif any(k in timeline_text for k in ("exploring", "explorando", "sin fecha", "futuro", "viendo opciones")):
        timeline_score = 5
        timeline_rationale = "Fase de exploración temprana sin fecha de compra definida."
    else:
        timeline_score = 11
        timeline_rationale = "Plazo de implementación no declarado explícitamente."

    total_score = budget_score + authority_score + need_score + timeline_score

    # Determine Qualification Tier & Recommended Stage & Executive Routing
    if total_score >= 75:
        tier = QualificationTier.HOT
        recommended_stage = PipelineStage.QUALIFIED
        icp_fit = "Alto (Ideal Customer Profile)"
        detected_intent = "Compra Inmediata / Agendar Demo Ejecutiva"
        suggested_owner = "AE Senior Enterprise (Sofía Morales)"
        recommended_next_action = (
            "Contactar en < 15 minutos vía WhatsApp + Email ejecutivo con link directo a Calendly para Demo de Arquitectura."
        )
    elif total_score >= 50:
        tier = QualificationTier.WARM
        recommended_stage = PipelineStage.QUALIFIED
        icp_fit = "Medio-Alto (Mid-Market / Crecimiento)"
        detected_intent = "Evaluación Técnica y Comparativa de ROI"
        suggested_owner = "SDR Mid-Market (Diego Valdés)"
        recommended_next_action = (
            "Iniciar secuencia consultiva de 3 pasos (Email + LinkedIn) enfocada en caso de éxito y llamada de Discovery de 20 min."
        )
    elif total_score >= 30:
        tier = QualificationTier.COLD
        recommended_stage = PipelineStage.NURTURE
        icp_fit = "Bajo-Medio (Requiere Maduración)"
        detected_intent = "Exploración Inicial / Educación"
        suggested_owner = "Automatización Marketing / Nurture Bot"
        recommended_next_action = (
            "Inscribir en cadencia educativa automatizada (Calculadora ROI + Demo grabada) sin consumir horas de AE."
        )
    else:
        tier = QualificationTier.DISQUALIFIED
        recommended_stage = PipelineStage.LOST
        icp_fit = "Fuera de ICP (Descartado)"
        detected_intent = "Sin Intención Comercial B2B"
        suggested_owner = "Self-Serve / Sin Asignación"
        recommended_next_action = (
            "Enviar recursos gratuitos automatizados y archivar del pipeline activo."
        )

    # Objections & Talking Points tailored to the lead's weak/strong spots
    objections: list[str] = []
    if budget_score < 16:
        objections.append("Sensibilidad al precio o necesidad de demostrar ROI en menos de 60 días.")
    if authority_score < 18:
        objections.append("Requiere involucrar al decisor económico (CEO/VP) antes de aprobar propuesta.")
    if lead.current_solution:
        objections.append(f"Costo de migración o coexistencia con su herramienta actual ({lead.current_solution}).")
    else:
        objections.append("Escepticismo sobre la precisión del agente IA y tiempos de integración con su CRM.")

    talking_points = [
        f"Personalizar demo para el sector {lead.industry or 'B2B'} de {lead.company_name or 'su empresa'}.",
        "Mostrar cómo la cualificación BANT instantánea reduce el tiempo de respuesta de horas a menos de 30 segundos.",
        "Presentar arquitectura de Webhooks bidireccionales y control humano (Human-in-the-loop) en el pipeline.",
    ]

    summary = (
        f"Lead {tier.value.upper()} ({total_score}/100 BANT) de {lead.company_name or 'empresa no especificada'}. "
        f"{authority_rationale.split('.')[0]}. {budget_rationale.split('.')[0]}. "
        f"Ruta recomendada: {suggested_owner}."
    )

    breakdown = BANTBreakdownSchema(
        budget_score=budget_score,
        budget_rationale=budget_rationale,
        authority_score=authority_score,
        authority_rationale=authority_rationale,
        need_score=need_score,
        need_rationale=need_rationale,
        timeline_score=timeline_score,
        timeline_rationale=timeline_rationale,
    )

    return AIQualificationResult(
        bant_total_score=total_score,
        qualification_tier=tier,
        recommended_stage=recommended_stage,
        bant_breakdown=breakdown,
        domain_intelligence=domain_info,
        icp_fit_level=icp_fit,
        detected_intent=detected_intent,
        ai_summary=summary,
        potential_objections=objections[:3],
        talking_points=talking_points,
        recommended_next_action=recommended_next_action,
        suggested_owner=suggested_owner,
        scoring_engine="bant-heuristic-engine-v2",
        qualified_at=now,
    )


def _evaluate_with_gemini(
    lead: Lead,
    domain_info: DomainIntelligenceSchema,
    heuristic_baseline: AIQualificationResult,
) -> AIQualificationResult:
    """Calls Google Gemini API (`gemini-3.8-flash`) using the official `google-genai` Interactions API
    to produce structured JSON BANT analysis. Falls back cleanly to heuristic_baseline on any error.
    """
    from google import genai

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    prompt = f"""Analiza y cualifica el siguiente Lead B2B utilizando la metodología BANT (Budget, Authority, Need, Timeline).
Devuelve EXCLUSIVAMENTE un objeto JSON válido con la siguiente estructura exacta:
{{
  "budget_score": <int 0-25>,
  "budget_rationale": "<explicación en español>",
  "authority_score": <int 0-25>,
  "authority_rationale": "<explicación en español>",
  "need_score": <int 0-25>,
  "need_rationale": "<explicación en español>",
  "timeline_score": <int 0-25>,
  "timeline_rationale": "<explicación en español>",
  "icp_fit_level": "<Alto | Medio-Alto | Bajo-Medio | Fuera de ICP>",
  "detected_intent": "<intención comercial principal>",
  "ai_summary": "<resumen ejecutivo de 2-3 oraciones en español>",
  "potential_objections": ["<objeción 1>", "<objeción 2>"],
  "talking_points": ["<punto clave 1>", "<punto clave 2>", "<punto clave 3>"],
  "recommended_next_action": "<acción comercial concreta>",
  "suggested_owner": "<AE Senior Enterprise | SDR Mid-Market | Automatización Marketing | Self-Serve>"
}}

Datos del Lead:
- Nombre: {lead.full_name}
- Email: {lead.email} (Dominio corporativo: {domain_info.is_corporate_domain}, {domain_info.trust_signal})
- Cargo: {lead.job_title or 'No especificado'} (Rol decisor: {lead.decision_maker_role or 'No especificado'})
- Empresa: {lead.company_name or 'No especificada'} (Tamaño: {lead.company_size or 'N/A'}, Industria: {lead.industry or 'N/A'})
- Presupuesto estimado USD: {lead.estimated_budget_usd} (Rango: {lead.budget_range or 'N/A'})
- Necesidad principal: {lead.primary_need or 'N/A'}
- Dolores / Pain points: {lead.pain_points or 'N/A'}
- Urgencia / Timeline: {lead.timeline_urgency or 'N/A'}
- Solución actual: {lead.current_solution or 'N/A'}
- Mensaje original: {lead.raw_message or 'N/A'}
"""

    interaction = client.interactions.create(
        model=settings.GEMINI_MODEL,
        system_instruction=(
            "Eres un Director de Operaciones de Ingresos (RevOps) experto en cualificación de leads B2B "
            "para una agencia/SaaS de Automatización e Inteligencia Artificial. Responde únicamente con JSON válido."
        ),
        input=prompt,
        generation_config={"response_mime_type": "application/json"},
    )

    raw_text = (interaction.output_text or "").strip()
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.DOTALL).strip()

    parsed: dict[str, Any] = json.loads(raw_text)

    b_score = max(0, min(25, int(parsed.get("budget_score", heuristic_baseline.bant_breakdown.budget_score))))
    a_score = max(0, min(25, int(parsed.get("authority_score", heuristic_baseline.bant_breakdown.authority_score))))
    n_score = max(0, min(25, int(parsed.get("need_score", heuristic_baseline.bant_breakdown.need_score))))
    t_score = max(0, min(25, int(parsed.get("timeline_score", heuristic_baseline.bant_breakdown.timeline_score))))
    total = b_score + a_score + n_score + t_score

    if total >= 75:
        tier = QualificationTier.HOT
        rec_stage = PipelineStage.QUALIFIED
    elif total >= 50:
        tier = QualificationTier.WARM
        rec_stage = PipelineStage.QUALIFIED
    elif total >= 30:
        tier = QualificationTier.COLD
        rec_stage = PipelineStage.NURTURE
    else:
        tier = QualificationTier.DISQUALIFIED
        rec_stage = PipelineStage.LOST

    breakdown = BANTBreakdownSchema(
        budget_score=b_score,
        budget_rationale=str(parsed.get("budget_rationale") or heuristic_baseline.bant_breakdown.budget_rationale),
        authority_score=a_score,
        authority_rationale=str(parsed.get("authority_rationale") or heuristic_baseline.bant_breakdown.authority_rationale),
        need_score=n_score,
        need_rationale=str(parsed.get("need_rationale") or heuristic_baseline.bant_breakdown.need_rationale),
        timeline_score=t_score,
        timeline_rationale=str(parsed.get("timeline_rationale") or heuristic_baseline.bant_breakdown.timeline_rationale),
    )

    return AIQualificationResult(
        bant_total_score=total,
        qualification_tier=tier,
        recommended_stage=rec_stage,
        bant_breakdown=breakdown,
        domain_intelligence=domain_info,
        icp_fit_level=str(parsed.get("icp_fit_level") or heuristic_baseline.icp_fit_level),
        detected_intent=str(parsed.get("detected_intent") or heuristic_baseline.detected_intent),
        ai_summary=str(parsed.get("ai_summary") or heuristic_baseline.ai_summary),
        potential_objections=list(parsed.get("potential_objections") or heuristic_baseline.potential_objections),
        talking_points=list(parsed.get("talking_points") or heuristic_baseline.talking_points),
        recommended_next_action=str(
            parsed.get("recommended_next_action") or heuristic_baseline.recommended_next_action
        ),
        suggested_owner=str(parsed.get("suggested_owner") or heuristic_baseline.suggested_owner),
        scoring_engine=f"gemini:{settings.GEMINI_MODEL}",
        qualified_at=datetime.now(timezone.utc),
    )


def evaluate_lead_ai(lead: Lead, force_heuristic: bool = False) -> AIQualificationResult:
    """Runs Domain Intelligence + BANT Qualification using Gemini API if configured,
    with automatic fallback to the deterministic BANT engine.
    """
    domain_info = analyze_email_domain(lead.email)
    baseline = _evaluate_heuristic_bant(lead, domain_info)

    if settings.GEMINI_API_KEY and not force_heuristic:
        try:
            return _evaluate_with_gemini(lead, domain_info, baseline)
        except Exception:
            return baseline

    return baseline


def qualify_lead_in_db(
    db: Session,
    lead: Lead,
    force_heuristic: bool = False,
    actor: str = "ai_qualifier_agent",
) -> tuple[Lead, AIQualificationResult]:
    """Qualifies a lead, enriches its corporate domain/country if missing, updates its BANT fields & stage,
    and records an AI_QUALIFIED interaction in the CRM timeline.
    """
    result = evaluate_lead_ai(lead, force_heuristic=force_heuristic)

    # Enrich missing company website / country from domain intelligence
    if not lead.company_website and result.domain_intelligence.inferred_website:
        lead.company_website = result.domain_intelligence.inferred_website
    if not lead.country and result.domain_intelligence.inferred_country:
        lead.country = result.domain_intelligence.inferred_country

    # Persist BANT scores and AI insights
    lead.bant_total_score = result.bant_total_score
    lead.budget_score = result.bant_breakdown.budget_score
    lead.authority_score = result.bant_breakdown.authority_score
    lead.need_score = result.bant_breakdown.need_score
    lead.timeline_score = result.bant_breakdown.timeline_score
    lead.qualification_tier = result.qualification_tier
    lead.ai_summary = result.ai_summary
    lead.detected_intent = result.detected_intent
    lead.recommended_next_action = result.recommended_next_action
    lead.suggested_owner = result.suggested_owner
    lead.scoring_engine = result.scoring_engine
    lead.qualified_at = result.qualified_at

    lead.ai_reasoning = {
        "bant_breakdown": result.bant_breakdown.model_dump(),
        "domain_intelligence": result.domain_intelligence.model_dump(),
        "icp_fit_level": result.icp_fit_level,
        "potential_objections": result.potential_objections,
        "talking_points": result.talking_points,
        "recommended_stage": result.recommended_stage.value,
    }

    # Automatically advance stage if lead was NEW or QUALIFYING
    if lead.stage in (PipelineStage.NEW, PipelineStage.QUALIFYING):
        lead.stage = result.recommended_stage

    # Add tag for tier
    existing_tags = [t for t in (lead.tags or []) if not t.startswith("tier:")]
    existing_tags.append(f"tier:{result.qualification_tier.value}")
    if result.domain_intelligence.is_corporate_domain and "corporate-email" not in existing_tags:
        existing_tags.append("corporate-email")
    lead.tags = existing_tags

    interaction = LeadInteraction(
        lead_id=lead.id,
        interaction_type=InteractionType.AI_QUALIFIED,
        channel="ai_agent",
        direction="system",
        subject=(
            f"Agente IA cualificó el lead: {result.qualification_tier.value.upper()} "
            f"({result.bant_total_score}/100 pts BANT)"
        ),
        content=(
            f"{result.ai_summary}\n"
            f"• Desglose BANT: Budget {result.bant_breakdown.budget_score}/25 | "
            f"Authority {result.bant_breakdown.authority_score}/25 | "
            f"Need {result.bant_breakdown.need_score}/25 | "
            f"Timeline {result.bant_breakdown.timeline_score}/25\n"
            f"• ICP Fit: {result.icp_fit_level} | Intención: {result.detected_intent}\n"
            f"• Siguiente acción: {result.recommended_next_action}"
        ),
        metadata_json={
            "bant_total_score": result.bant_total_score,
            "tier": result.qualification_tier.value,
            "scoring_engine": result.scoring_engine,
            "suggested_owner": result.suggested_owner,
            "is_corporate_domain": result.domain_intelligence.is_corporate_domain,
        },
        actor=actor,
    )
    db.add(interaction)
    db.commit()
    db.refresh(lead)
    return lead, result


def qualify_leads_batch(
    db: Session,
    lead_ids: list[int] | None = None,
    only_unscored: bool = True,
    limit: int = 25,
    force_heuristic: bool = False,
) -> BatchQualifyResponse:
    stmt = select(Lead)
    if lead_ids:
        stmt = stmt.where(Lead.id.in_(lead_ids))
    elif only_unscored:
        stmt = stmt.where(Lead.qualification_tier == QualificationTier.UNSCORED)

    stmt = stmt.order_by(Lead.created_at.desc()).limit(limit)
    leads = list(db.scalars(stmt).all())

    hot_count = 0
    warm_count = 0
    cold_count = 0
    disqualified_count = 0
    results: list[dict[str, Any]] = []

    for lead in leads:
        updated_lead, qual_res = qualify_lead_in_db(
            db=db,
            lead=lead,
            force_heuristic=force_heuristic,
            actor="ai_batch_qualifier",
        )
        if qual_res.qualification_tier == QualificationTier.HOT:
            hot_count += 1
        elif qual_res.qualification_tier == QualificationTier.WARM:
            warm_count += 1
        elif qual_res.qualification_tier == QualificationTier.COLD:
            cold_count += 1
        else:
            disqualified_count += 1

        results.append(
            {
                "lead_id": updated_lead.id,
                "full_name": updated_lead.full_name,
                "company_name": updated_lead.company_name,
                "bant_total_score": qual_res.bant_total_score,
                "qualification_tier": qual_res.qualification_tier.value,
                "stage": updated_lead.stage.value,
                "suggested_owner": qual_res.suggested_owner,
            }
        )

    return BatchQualifyResponse(
        processed=len(results),
        hot_count=hot_count,
        warm_count=warm_count,
        cold_count=cold_count,
        disqualified_count=disqualified_count,
        results=results,
    )
