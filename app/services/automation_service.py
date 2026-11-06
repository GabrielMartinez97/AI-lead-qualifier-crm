from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.lead import (
    FollowUpChannel,
    FollowUpStatus,
    FollowUpTask,
    InteractionType,
    Lead,
    LeadInteraction,
    PipelineStage,
    QualificationTier,
    WebhookEventLog,
)
from app.schemas.automation import (
    BatchExecuteDueResponse,
    ExecuteTaskResponse,
    InboundReplyAnalysisOut,
    InboundReplyRequest,
    SequenceEnrollmentResponse,
)
from app.schemas.lead import FollowUpTaskOut


def dispatch_outbound_webhook(
    db: Session,
    lead: Lead,
    event_type: str,
    summary_text: str,
    extra_data: dict[str, Any] | None = None,
) -> bool:
    """Dispatches an outbound webhook event (Slack/Discord/External CRM notification)
    and records it in `webhook_event_logs` and the lead's interaction timeline.
    """
    payload = {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lead": {
            "id": lead.id,
            "full_name": lead.full_name,
            "email": lead.email,
            "company_name": lead.company_name,
            "job_title": lead.job_title,
            "bant_total_score": lead.bant_total_score,
            "qualification_tier": lead.qualification_tier.value,
            "stage": lead.stage.value,
            "estimated_budget_usd": lead.estimated_budget_usd,
            "suggested_owner": lead.suggested_owner,
        },
        "summary": summary_text,
        "extra": extra_data or {},
    }

    status_str = "simulated_delivered"
    error_msg = None

    if settings.OUTBOUND_WEBHOOK_URL:
        try:
            resp = httpx.post(settings.OUTBOUND_WEBHOOK_URL, json=payload, timeout=4.0)
            status_str = f"delivered_{resp.status_code}"
        except Exception as exc:
            status_str = "delivery_failed"
            error_msg = str(exc)

    webhook_log = WebhookEventLog(
        direction="outbound",
        provider="slack_crm_alert",
        event_type=event_type,
        signature_valid=True,
        payload_json=payload,
        status=status_str,
        lead_id=lead.id,
        error_message=error_msg,
    )
    db.add(webhook_log)

    interaction = LeadInteraction(
        lead_id=lead.id,
        interaction_type=InteractionType.WEBHOOK_DISPATCHED,
        channel="webhook_outbound",
        direction="outbound",
        subject=f"Webhook saliente disparado: {event_type}",
        content=summary_text,
        metadata_json={"event_type": event_type, "status": status_str},
        actor="automation_engine",
    )
    db.add(interaction)
    return True


def _build_adaptive_cadence_steps(lead: Lead) -> tuple[str, list[dict[str, Any]]]:
    now = datetime.now(timezone.utc)
    first_name = lead.full_name.split()[0] if lead.full_name else "Hola"
    company = lead.company_name or "tu empresa"
    need = lead.primary_need or "automatizar procesos comerciales con IA"
    owner = lead.suggested_owner or "Equipo Comercial NexusLead"

    if lead.qualification_tier == QualificationTier.HOT:
        cadence_name = "Cadencia Fast-Track Enterprise (Hot Lead: WhatsApp + Email + Llamada 24h)"
        steps = [
            {
                "step_number": 1,
                "channel": FollowUpChannel.WHATSAPP,
                "scheduled_at": now,
                "subject": f"Contacto inmediato WhatsApp — {company}",
                "body": (
                    f"¡Hola {first_name}! Soy del equipo de {owner}. Recibimos tu solicitud en {company} "
                    f"sobre '{need}'. Por el alcance de su operación, preparé una demo personalizada de nuestra "
                    f"arquitectura de agentes IA. ¿Te queda bien hoy a las 16:00 o mañana por la mañana para una sesión de 15 min?"
                ),
                "notes": "Disparo inmediato (< 15 min) por alta puntuación BANT y urgencia.",
            },
            {
                "step_number": 2,
                "channel": FollowUpChannel.EMAIL,
                "scheduled_at": now + timedelta(hours=2),
                "subject": f"Arquitectura de Agentes IA & Automatización Comercial para {company}",
                "body": (
                    f"Hola {first_name},\n\n"
                    f"Analizamos el caso de {company} ({lead.job_title or 'Dirección'}) respecto a: {need}.\n\n"
                    f"Preparamos un esquema técnico mostrando cómo conectamos la ingesta de leads por Webhooks, "
                    f"cualificación BANT en tiempo real y seguimiento automático sin fricción para tu equipo.\n\n"
                    f"Puedes elegir el horario directo en nuestra agenda ejecutiva o responder este correo con tu disponibilidad.\n\n"
                    f"Saludos cordiales,\n{owner}"
                ),
                "notes": "Correo ejecutivo +2h con propuesta de valor adaptada al cargo e industria.",
            },
            {
                "step_number": 3,
                "channel": FollowUpChannel.CALL,
                "scheduled_at": now + timedelta(hours=24),
                "subject": f"Llamada Ejecutiva de Descubrimiento y ROI — {company}",
                "body": (
                    f"Guion de llamada para {owner}:\n"
                    f"1. Validar impacto actual de '{need}' en {company}.\n"
                    f"2. Confirmar presupuesto estimado (${lead.estimated_budget_usd or 'por definir'}) y tiempos de despliegue.\n"
                    f"3. Resolver objeciones detectadas por IA y cerrar fecha de PoC/Propuesta."
                ),
                "notes": "Seguimiento telefónico +24h asignado a AE Senior.",
            },
        ]
    elif lead.qualification_tier == QualificationTier.WARM:
        cadence_name = "Cadencia Consultiva Mid-Market (Warm Lead: Email + LinkedIn 48h + Caso de Éxito 5d)"
        steps = [
            {
                "step_number": 1,
                "channel": FollowUpChannel.EMAIL,
                "scheduled_at": now,
                "subject": f"Ideas para optimizar '{need[:45]}' en {company}",
                "body": (
                    f"Hola {first_name},\n\n"
                    f"Gracias por contactarnos desde {company}. Vi que están evaluando soluciones para {need}.\n\n"
                    f"En empresas de tamaño similar ({lead.company_size or 'en crecimiento'}), implementar un agente "
                    f"cualificador BANT reduce en un 70% el tiempo operativo de filtrado y triplica la tasa de reunión.\n\n"
                    f"¿Te gustaría que revisemos en 20 minutos cómo se integraría con su flujo actual?\n\n"
                    f"Un saludo,\n{owner}"
                ),
                "notes": "Email consultivo inicial centrado en diagnóstico y ahorro de tiempo.",
            },
            {
                "step_number": 2,
                "channel": FollowUpChannel.LINKEDIN,
                "scheduled_at": now + timedelta(hours=48),
                "subject": f"Touchpoint LinkedIn (+48h) — Caso de éxito sector {lead.industry or 'B2B'}",
                "body": (
                    f"Hola {first_name}, te envié un correo hace un par de días sobre la automatización en {company}. "
                    f"Te comparto por aquí cómo otro equipo de {lead.industry or 'servicios B2B'} automatizó el 100% "
                    f"de su seguimiento comercial con IA. ¡Encantado de conectar!"
                ),
                "notes": "Mensaje social +48h por LinkedIn para reforzar confianza.",
            },
            {
                "step_number": 3,
                "channel": FollowUpChannel.EMAIL,
                "scheduled_at": now + timedelta(days=5),
                "subject": f"¿Seguimos en contacto para el proyecto de IA en {company}?",
                "body": (
                    f"Hola {first_name},\n\n"
                    f"Sé que como {lead.job_title or 'líder de área'} la agenda suele estar a tope. "
                    f"Si todavía tienen como prioridad resolver '{need}' este trimestre, dime qué día de la próxima "
                    f"semana te viene bien para una llamada rápida de evaluación técnica.\n\n"
                    f"Saludos,\n{owner}"
                ),
                "notes": "Cierre de cadencia consultiva al día 5.",
            },
        ]
    elif lead.qualification_tier == QualificationTier.COLD:
        cadence_name = "Cadencia Automatizada de Nurturing Educativo (Cold Lead: 24h + 7d)"
        steps = [
            {
                "step_number": 1,
                "channel": FollowUpChannel.EMAIL,
                "scheduled_at": now + timedelta(hours=24),
                "subject": f"Recurso práctico: Calculadora de ROI en Automatización IA para {company}",
                "body": (
                    f"Hola {first_name},\n\n"
                    f"Gracias por tu interés en nuestras soluciones de IA comercial. Mientras exploran opciones en {company}, "
                    f"te comparto nuestra guía interactiva y una demo grabada de 3 minutos sobre cómo estructurar "
                    f"un embudo autónomo de captación y cualificación de leads.\n\n"
                    f"Si en algún momento el proyecto cobra urgencia, responde a este correo y lo revisamos juntos.\n\n"
                    f"Saludos,\n{owner}"
                ),
                "notes": "Nutrición sin costo de horas de ejecutivo (+24h).",
            },
            {
                "step_number": 2,
                "channel": FollowUpChannel.EMAIL,
                "scheduled_at": now + timedelta(days=7),
                "subject": f"3 plantillas de automatización B2B para implementar en {company}",
                "body": (
                    f"Hola {first_name},\n\n"
                    f"Te comparto 3 arquitecturas reales de integración entre formularios web, agentes IA y CRM "
                    f"para cuando decidan dar el siguiente paso en {company}.\n\n"
                    f"Un cordial saludo,\n{owner}"
                ),
                "notes": "Segundo toque educativo (+7 días).",
            },
        ]
    else:
        cadence_name = "Sin secuencia activa (Lead Disqualified / Fuera de ICP)"
        steps = []

    return cadence_name, steps


def enroll_lead_in_sequence(
    db: Session,
    lead: Lead,
    replace_pending: bool = True,
) -> SequenceEnrollmentResponse:
    """Enrolls a qualified lead into the adaptive multi-channel follow-up sequence matching its BANT tier."""
    if replace_pending:
        existing_pending = list(
            db.scalars(
                select(FollowUpTask).where(
                    FollowUpTask.lead_id == lead.id,
                    FollowUpTask.status == FollowUpStatus.PENDING,
                )
            ).all()
        )
        for task in existing_pending:
            db.delete(task)
        db.flush()

    cadence_name, steps = _build_adaptive_cadence_steps(lead)
    created_tasks: list[FollowUpTask] = []

    for step in steps:
        task = FollowUpTask(
            lead_id=lead.id,
            step_number=step["step_number"],
            channel=step["channel"],
            status=FollowUpStatus.PENDING,
            scheduled_at=step["scheduled_at"],
            subject=step["subject"],
            body=step["body"],
            ai_personalization_notes=step["notes"],
        )
        db.add(task)
        created_tasks.append(task)

    webhook_sent = False
    if lead.qualification_tier == QualificationTier.HOT:
        webhook_sent = dispatch_outbound_webhook(
            db=db,
            lead=lead,
            event_type="lead.hot_qualified_alert",
            summary_text=(
                f"🔥 Lead HOT detectado ({lead.bant_total_score}/100 BANT): {lead.full_name} "
                f"de {lead.company_name or 'N/A'}. Asignado a {lead.suggested_owner}. "
                f"Secuencia Fast-Track de 3 pasos activada."
            ),
            extra_data={"cadence_name": cadence_name, "steps_count": len(created_tasks)},
        )

    db.commit()
    for t in created_tasks:
        db.refresh(t)

    return SequenceEnrollmentResponse(
        lead_id=lead.id,
        qualification_tier=lead.qualification_tier.value,
        cadence_name=cadence_name,
        tasks_created=len(created_tasks),
        outbound_webhook_dispatched=webhook_sent,
        tasks=[FollowUpTaskOut.model_validate(t) for t in created_tasks],
    )


def execute_follow_up_task(
    db: Session,
    task_id: int,
    actor: str = "automation_scheduler",
) -> ExecuteTaskResponse:
    task = db.get(FollowUpTask, task_id)
    if not task:
        raise LookupError(f"Tarea de seguimiento con ID {task_id} no encontrada.")

    lead = db.get(Lead, task.lead_id)
    if not lead:
        raise LookupError(f"Lead asociado ({task.lead_id}) no encontrado.")

    now = datetime.now(timezone.utc)
    task.status = FollowUpStatus.SENT
    task.executed_at = now
    lead.last_contacted_at = now

    if lead.stage in (PipelineStage.NEW, PipelineStage.QUALIFYING, PipelineStage.QUALIFIED):
        lead.stage = PipelineStage.CONTACTED

    channel_interaction_map = {
        FollowUpChannel.EMAIL: InteractionType.EMAIL_SENT,
        FollowUpChannel.WHATSAPP: InteractionType.WHATSAPP_SENT,
        FollowUpChannel.LINKEDIN: InteractionType.LINKEDIN_SENT,
        FollowUpChannel.CALL: InteractionType.NOTE_ADDED,
    }
    i_type = channel_interaction_map.get(task.channel, InteractionType.EMAIL_SENT)

    interaction = LeadInteraction(
        lead_id=lead.id,
        interaction_type=i_type,
        channel=task.channel.value,
        direction="outbound",
        subject=task.subject or f"Paso #{task.step_number} enviado ({task.channel.value})",
        content=task.body,
        metadata_json={
            "task_id": task.id,
            "step_number": task.step_number,
            "channel": task.channel.value,
        },
        actor=actor,
    )
    db.add(interaction)
    db.commit()
    db.refresh(task)
    db.refresh(lead)
    db.refresh(interaction)

    return ExecuteTaskResponse(
        task=FollowUpTaskOut.model_validate(task),
        lead_id=lead.id,
        lead_stage=lead.stage,
        interaction_id=interaction.id,
        message=f"Paso #{task.step_number} ({task.channel.value}) ejecutado y registrado en el timeline del lead.",
    )


def execute_due_follow_up_tasks(
    db: Session,
    force_all_pending: bool = False,
    limit: int = 20,
) -> BatchExecuteDueResponse:
    now = datetime.now(timezone.utc)
    stmt = select(FollowUpTask).where(FollowUpTask.status == FollowUpStatus.PENDING)
    if not force_all_pending:
        stmt = stmt.where(FollowUpTask.scheduled_at <= now)

    stmt = stmt.order_by(FollowUpTask.scheduled_at.asc()).limit(limit)
    due_tasks = list(db.scalars(stmt).all())

    executed_ids: list[int] = []
    details: list[dict[str, Any]] = []

    for task in due_tasks:
        res = execute_follow_up_task(db, task.id, actor="automation_cron_runner")
        executed_ids.append(task.id)
        details.append(
            {
                "task_id": task.id,
                "lead_id": res.lead_id,
                "channel": res.task.channel.value,
                "step_number": res.task.step_number,
                "new_stage": res.lead_stage.value,
            }
        )

    return BatchExecuteDueResponse(
        executed_count=len(executed_ids),
        task_ids=executed_ids,
        details=details,
    )


def handle_inbound_lead_reply(
    db: Session,
    lead: Lead,
    payload: InboundReplyRequest,
) -> InboundReplyAnalysisOut:
    """Analyzes an incoming reply from a lead (via Email, WhatsApp, or LinkedIn),
    classifies commercial intent & sentiment, cancels/pauses pending automated follow-ups,
    transitions the pipeline stage automatically, and crafts a contextual AI response.
    """
    now = datetime.now(timezone.utc)
    msg_lower = payload.message.strip().lower()
    first_name = lead.full_name.split()[0] if lead.full_name else "Hola"
    company = lead.company_name or "tu empresa"
    previous_stage = lead.stage

    # Classify intent & sentiment
    if any(
        kw in msg_lower
        for kw in (
            "no me interesa",
            "baja",
            "desuscribir",
            "no contactar",
            "stop",
            "elimina mi correo",
            "ya contratamos otro",
        )
    ):
        intent = "unsubscribe"
        sentiment = "negative"
        confidence = 0.96
        new_stage = PipelineStage.LOST
        subject = f"Confirmación de baja de lista comercial — {company}"
        body = (
            f"Hola {first_name}, entendido perfectamente. Hemos detenido todos los seguimientos automáticos "
            f"para tu contacto. Te agradecemos tu tiempo y quedamos a disposición si en el futuro cambian las prioridades."
        )
        internal_alert = "Lead solicitó baja / descarte. Secuencia cancelada y movido a etapa LOST."
    elif any(
        kw in msg_lower
        for kw in (
            "precio",
            "precios",
            "costo",
            "cuánto cuesta",
            "cuanto cuesta",
            "cotización",
            "cotizacion",
            "propuesta comercial",
            "tarifa",
            "planes",
            "licencia",
        )
    ) and not any(k in msg_lower for k in ("agendar", "calendly")):
        intent = "pricing_inquiry"
        sentiment = "positive"
        confidence = 0.91
        new_stage = PipelineStage.PROPOSAL_SENT
        subject = f"Propuesta de Inversión y Planes de Automatización IA — {company}"
        body = (
            f"Hola {first_name},\n\n"
            f"Con gusto te comparto la estructura de inversión estimada para {company} según su volumen ({lead.company_size or 'B2B'}):\n\n"
            f"• Plan Growth AI CRM: Ingesta multi-canal + Agente Cualificador BANT + Cadencias automatizadas.\n"
            f"• Plan Enterprise Custom: Integración dedicada con su ERP/CRM actual, modelos ajustados y SLA prioritario.\n\n"
            f"Basado en su presupuesto de referencia (${lead.estimated_budget_usd or 'a medida'}), el retorno estimado se logra en el primer trimestre. "
            f"¿Revisamos los números exactos en una llamada de 15 minutos mañana?"
        )
        internal_alert = f"💰 {lead.full_name} solicitó propuesta/precios. Etapa avanzada a PROPOSAL_SENT."
    elif any(
        kw in msg_lower
        for kw in (
            "agendar",
            "reunión",
            "reunion",
            "demo",
            "llamada",
            "mañana",
            "jueves",
            "martes",
            "miércoles",
            "viernes",
            "lunes",
            "calendly",
            "disponible",
            "15 min",
            "conversemos",
            "hablemos",
        )
    ):
        intent = "book_meeting"
        sentiment = "positive"
        confidence = 0.95
        new_stage = PipelineStage.MEETING_SCHEDULED
        subject = f"Confirmación de Demo Ejecutiva: Agentes IA para {company}"
        body = (
            f"¡Excelente {first_name}! Ya bloqueamos el espacio para nuestra sesión de demostración con {company}.\n\n"
            f"Agenda propuesta (20 min):\n"
            f"1. Flujo en vivo del Agente IA cualificando leads y conectando vía Webhooks.\n"
            f"2. Adaptación a su caso de '{lead.primary_need or 'automatización comercial'}'.\n"
            f"3. Plan de implementación y retorno de inversión.\n\n"
            f"Te acabo de enviar la invitación de calendario. ¡Nos vemos ahí!"
        )
        internal_alert = f"🎯 ¡Reunión solicitada por {lead.full_name}! Etapa avanzada a MEETING_SCHEDULED."
    elif any(
        kw in msg_lower
        for kw in (
            "caro",
            "complejo",
            "difícil",
            "dificil",
            "ya tenemos",
            "usamos hubspot",
            "usamos salesforce",
            "más adelante",
            "proximo trimestre",
            "duda",
            "seguridad",
        )
    ):
        intent = "objection"
        sentiment = "neutral"
        confidence = 0.88
        new_stage = PipelineStage.CONTACTED
        subject = f"Sobre la integración sin fricción con tu stack actual en {company}"
        body = (
            f"Hola {first_name},\n\n"
            f"Es una excelente pregunta. De hecho, nuestro agente IA no reemplaza tu infraestructura actual "
            f"({lead.current_solution or 'tu CRM'}), sino que se conecta en horas mediante Webhooks y API REST "
            f"para entregar los leads ya cualificados y con el primer seguimiento hecho.\n\n"
            f"Podemos arrancar con un piloto acotado de 2 semanas sin interrumpir la operación de tu equipo. ¿Te hace sentido?"
        )
        internal_alert = f"⚠️ Objeción comercial detectada de {lead.full_name}. Se generó respuesta de manejo de objeciones."
    else:
        intent = "general_question"
        sentiment = "neutral"
        confidence = 0.82
        new_stage = PipelineStage.CONTACTED
        subject = f"Re: Consulta sobre Automatización Comercial con IA — {company}"
        body = (
            f"Hola {first_name},\n\n"
            f"Gracias por tu respuesta. Respecto a tu consulta, nuestra plataforma centraliza todos los canales de entrada, "
            f"evalúa cada prospecto con IA bajo matriz BANT y automatiza el seguimiento personalizado.\n\n"
            f"¿Te parece bien si coordinamos una breve llamada esta semana para mostrarte un ejemplo real aplicado a {company}?"
        )
        internal_alert = f"Respuesta general recibida de {lead.full_name}. Secuencia pausada para atención personalizada."

    # Record inbound reply interaction
    inbound_interaction = LeadInteraction(
        lead_id=lead.id,
        interaction_type=InteractionType.LEAD_REPLIED,
        channel=payload.channel.value,
        direction="inbound",
        subject=f"Respuesta recibida del lead vía {payload.channel.value} (Intención: {intent})",
        content=payload.message.strip(),
        metadata_json={
            "detected_reply_intent": intent,
            "sentiment": sentiment,
            "confidence": confidence,
        },
        actor=payload.sender_name or lead.full_name,
    )
    db.add(inbound_interaction)

    # Cancel/Pause pending automated tasks so the lead isn't spammed by scheduled emails after replying
    pending_tasks = list(
        db.scalars(
            select(FollowUpTask).where(
                FollowUpTask.lead_id == lead.id,
                FollowUpTask.status == FollowUpStatus.PENDING,
            )
        ).all()
    )
    cancelled_count = 0
    for idx, t in enumerate(pending_tasks):
        if idx == 0 and intent != "unsubscribe":
            t.status = FollowUpStatus.REPLIED
        else:
            t.status = FollowUpStatus.CANCELLED
        cancelled_count += 1

    # Update lead stage & record AI auto-response interaction
    lead.stage = new_stage
    lead.last_contacted_at = now
    lead.recommended_next_action = internal_alert

    outbound_reply_interaction = LeadInteraction(
        lead_id=lead.id,
        interaction_type=InteractionType.EMAIL_SENT
        if payload.channel == FollowUpChannel.EMAIL
        else InteractionType.WHATSAPP_SENT,
        channel=payload.channel.value,
        direction="outbound",
        subject=subject,
        content=body,
        metadata_json={
            "auto_generated_by": "ai_reply_handler",
            "in_response_to_intent": intent,
            "previous_stage": previous_stage.value,
            "new_stage": new_stage.value,
        },
        actor="ai_sales_agent",
    )
    db.add(outbound_reply_interaction)

    webhook_dispatched = False
    if intent in ("book_meeting", "pricing_inquiry"):
        webhook_dispatched = dispatch_outbound_webhook(
            db=db,
            lead=lead,
            event_type=f"lead.reply.{intent}",
            summary_text=internal_alert,
            extra_data={
                "inbound_message": payload.message,
                "new_stage": new_stage.value,
                "sentiment": sentiment,
            },
        )

    db.commit()
    db.refresh(lead)

    return InboundReplyAnalysisOut(
        lead_id=lead.id,
        detected_reply_intent=intent,
        sentiment=sentiment,
        confidence=confidence,
        previous_stage=previous_stage,
        new_stage=new_stage,
        cancelled_Pending_tasks=cancelled_count,
        ai_suggested_response_subject=subject,
        ai_suggested_response_body=body,
        internal_sales_alert=internal_alert,
        outbound_webhook_dispatched=webhook_dispatched,
        analyzed_at=now,
    )
