import random
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.lead import Lead, LeadSource, PipelineStage
from app.schemas.lead import LeadCreate, LeadOut
from app.services.automation_service import execute_follow_up_task, handle_inbound_lead_reply
from app.schemas.automation import InboundReplyRequest
from app.services.crm_service import create_or_merge_lead, transition_lead_stage
from app.services.webhook_ingestor import ingest_webhook_event


INITIAL_SEED_LEADS: list[dict[str, Any]] = [
    {
        "full_name": "Valeria Soto",
        "email": "valeria.soto@fintechlatam.io",
        "phone": "+56 9 8412 3901",
        "job_title": "CTO & Co-Founder",
        "company_name": "FintechLatam",
        "company_size": "201-1000",
        "industry": "Fintech & Pagos",
        "estimated_budget_usd": 42000,
        "decision_maker_role": "C-Level / Founder",
        "primary_need": "Automatizar cualificación de leads B2B con agentes IA y sincronizar pipeline CRM",
        "pain_points": "Recibimos 600 leads mensuales y los SDRs tardan 18 horas en responder.",
        "timeline_urgency": "immediate",
        "current_solution": "HubSpot + Hojas de cálculo",
        "source": LeadSource.WEBSITE_FORM,
        "tags": ["enterprise", "fintech", "inbound"],
    },
    {
        "full_name": "Carlos Mendoza",
        "email": "cmendoza@logistica-andina.cl",
        "phone": "+56 9 7210 4412",
        "job_title": "VP de Operaciones Comerciales",
        "company_name": "Logística Andina SA",
        "company_size": "51-200",
        "industry": "Logística & Supply Chain",
        "estimated_budget_usd": 26500,
        "decision_maker_role": "VP / Director",
        "primary_need": "Integrar webhooks de formularios y seguimiento automático por WhatsApp y Email",
        "pain_points": "Fuga del 40% de prospectos corporativos por falta de seguimiento estructurado.",
        "timeline_urgency": "immediate",
        "current_solution": "Pipedrive",
        "source": LeadSource.TYPEFORM_WEBHOOK,
        "tags": ["logistica", "fast-track"],
    },
    {
        "full_name": "Mariana Silva",
        "email": "msilva@medicloud.mx",
        "phone": "+52 55 4190 8821",
        "job_title": "Head of Growth",
        "company_name": "MediCloud Health",
        "company_size": "51-200",
        "industry": "HealthTech",
        "estimated_budget_usd": 14000,
        "decision_maker_role": "VP / Director",
        "primary_need": "Agente IA para clasificar clínicas entrantes y agendar demos",
        "pain_points": "El equipo comercial invierte demasiado tiempo en prospectos sin presupuesto.",
        "timeline_urgency": "1_3_months",
        "current_solution": "Zoho CRM",
        "source": LeadSource.LINKEDIN_ADS_WEBHOOK,
        "tags": ["healthtech", "mid-market"],
    },
    {
        "full_name": "Fernando Ríos",
        "email": "frios@constructora-pacifico.co",
        "phone": "+57 310 552 9102",
        "job_title": "Gerente Comercial",
        "company_name": "Constructora Pacífico",
        "company_size": "11-50",
        "industry": "Construcción & Inmobiliaria B2B",
        "estimated_budget_usd": 7500,
        "decision_maker_role": "Manager",
        "primary_need": "Automatizar respuestas iniciales y seguimiento de cotizaciones B2B",
        "pain_points": "Seguimiento manual en Excel sin trazabilidad de correos.",
        "timeline_urgency": "1_3_months",
        "current_solution": "Excel / Correo manual",
        "source": LeadSource.META_ADS_WEBHOOK,
        "tags": ["construccion", "smb"],
    },
    {
        "full_name": "Gabriela Paz",
        "email": "gpaz@agencia-creativa.es",
        "phone": "+34 612 889 104",
        "job_title": "Project Manager",
        "company_name": "Agencia Creativa Madrid",
        "company_size": "11-50",
        "industry": "Marketing Digital",
        "estimated_budget_usd": 2800,
        "decision_maker_role": "Manager",
        "primary_need": "Explorar herramientas de automatización comercial con IA para el próximo semestre",
        "pain_points": "Queremos conocer casos de uso antes de definir presupuesto anual.",
        "timeline_urgency": "3_6_months",
        "current_solution": "Notion",
        "source": LeadSource.CSV_IMPORT,
        "tags": ["nurturing", "marketing"],
    },
    {
        "full_name": "Tomás Curioso",
        "email": "tomas.universidad99@gmail.com",
        "phone": None,
        "job_title": "Estudiante Practicante",
        "company_name": "Proyecto Universitario",
        "company_size": "1-10",
        "industry": "Educación",
        "estimated_budget_usd": 0,
        "decision_maker_role": "Individual Contributor",
        "primary_need": "Solo mirando ejemplos para una tarea universitaria sobre IA",
        "pain_points": "Sin dolor comercial ni presupuesto.",
        "timeline_urgency": "exploring",
        "current_solution": "Ninguna",
        "source": LeadSource.WEBSITE_FORM,
        "tags": ["non-icp"],
    },
]


def seed_initial_crm_data(db: Session, force_reset: bool = False) -> dict[str, Any]:
    """Seeds realistic B2B leads across all stages and qualification tiers so the portfolio dashboard
    looks alive and rich immediately upon startup.
    """
    existing_count = db.scalar(select(func.count()).select_from(Lead)) or 0
    if existing_count > 0 and not force_reset:
        return {"seeded": False, "existing_leads": existing_count}

    if force_reset:
        all_leads = list(db.scalars(select(Lead)).all())
        for l in all_leads:
            db.delete(l)
        db.commit()

    created_leads: list[Lead] = []
    for item in INITIAL_SEED_LEADS:
        lead_in = LeadCreate(**item)
        lead, _ = create_or_merge_lead(db, lead_in, actor="seed_engine")
        created_leads.append(lead)

    # Simulate realistic pipeline progression on a couple of leads so Kanban shows multiple stages
    if len(created_leads) >= 4:
        # Lead 1 (Valeria Soto - Hot): Execute step 1 and simulate a reply booking a meeting!
        lead_valeria = created_leads[0]
        if lead_valeria.follow_up_tasks:
            execute_follow_up_task(db, lead_valeria.follow_up_tasks[0].id, actor="ai_sdr_agent")
        handle_inbound_lead_reply(
            db,
            lead_valeria,
            InboundReplyRequest(
                channel="whatsapp",
                message="¡Hola! Sí, me interesa mucho ver la arquitectura. Agendemos la demo para mañana jueves a las 11:00 AM.",
                sender_name=lead_valeria.full_name,
            ),
        )

        # Lead 2 (Carlos Mendoza - Hot): Execute step 1 and simulate pricing inquiry -> Proposal Sent
        lead_carlos = created_leads[1]
        if lead_carlos.follow_up_tasks:
            execute_follow_up_task(db, lead_carlos.follow_up_tasks[0].id, actor="ai_sdr_agent")
        handle_inbound_lead_reply(
            db,
            lead_carlos,
            InboundReplyRequest(
                channel="email",
                message="Hola equipo, excelente. ¿Me pueden enviar la cotización y precios del plan Enterprise para 120 usuarios?",
                sender_name=lead_carlos.full_name,
            ),
        )

        # Lead 4 (Fernando Ríos - Warm): Execute first email -> Stage Contacted
        lead_fernando = created_leads[3]
        if lead_fernando.follow_up_tasks:
            execute_follow_up_task(db, lead_fernando.follow_up_tasks[0].id, actor="ai_sdr_agent")

    return {"seeded": True, "created_leads": len(created_leads)}


def trigger_demo_scenario(db: Session, scenario_key: str) -> dict[str, Any]:
    """Executes a 1-click recruiter simulation scenario (injecting a realistic lead or webhook
    and running the full AI BANT qualification + sequence enrollment pipeline).
    """
    suffix = random.randint(100, 999)
    key = scenario_key.strip().lower()

    if key == "enterprise_hot":
        payload = LeadCreate(
            full_name="Sofía Alarcón",
            email=f"s.alarcon.{suffix}@andinacloud.ai",
            phone="+56 9 9102 4480",
            job_title="Chief Technology Officer (CTO)",
            company_name="AndinaCloud Enterprise",
            company_size="201-1000",
            industry="Cloud & AI Infrastructure",
            estimated_budget_usd=48000,
            decision_maker_role="C-Level / Founder",
            primary_need="Automatizar cualificación BANT con IA, webhooks bidireccionales y ruteo de ejecutivos",
            pain_points="Volumen alto de leads B2B sin filtrar; necesitamos respuesta automática en menos de 60 segundos.",
            timeline_urgency="immediate",
            current_solution="Salesforce Enterprise",
            source=LeadSource.WEBSITE_FORM,
            tags=["simulador-1-clic", "enterprise", "q4-urgent"],
        )
        lead, dedup = create_or_merge_lead(db, payload, actor="recruiter_simulator")
        return {
            "scenario": key,
            "title": "Lead Enterprise HOT ($48,000 USD) inyectado y cualificado por IA",
            "deduplicated": dedup,
            "lead": LeadOut.model_validate(lead),
        }

    if key == "typeform_webhook":
        tf_payload = {
            "event_id": f"tf_sim_{suffix}",
            "form_response": {
                "token": f"tok_{suffix}",
                "answers": [
                    {"field": {"ref": "full_name"}, "type": "text", "text": "Martín Vega"},
                    {"field": {"ref": "work_email"}, "type": "email", "email": f"mvega.{suffix}@logismart.cl"},
                    {"field": {"ref": "company_name"}, "type": "text", "text": "LogiSmart Fleet"},
                    {"field": {"ref": "job_title"}, "type": "text", "text": "Director de Operaciones"},
                    {"field": {"ref": "budget"}, "type": "number", "number": 16500},
                    {"field": {"ref": "size"}, "type": "text", "text": "51-200"},
                    {"field": {"ref": "timeline"}, "type": "choice", "choice": {"label": "1_3_months"}},
                    {
                        "field": {"ref": "primary_need"},
                        "type": "text",
                        "text": "Conectar formularios Typeform con agente IA cualificador y seguimiento por WhatsApp",
                    },
                ],
            },
        }
        res = ingest_webhook_event(db, provider="typeform", payload=tf_payload, signature_valid=True)
        return {
            "scenario": key,
            "title": "Webhook de Typeform procesado, normalizado y cualificado con BANT",
            "deduplicated": res.deduplicated,
            "lead": res.lead,
        }

    if key == "meta_ads_webhook":
        meta_payload = {
            "leadgen_id": f"meta_lg_{suffix}",
            "campaign_name": "B2B_AI_Automation_Q4",
            "field_data": [
                {"name": "full_name", "values": ["Carolina Pizarro"]},
                {"name": "work_email", "values": [f"cpizarro.{suffix}@agrotech-latam.com"]},
                {"name": "phone_number", "values": ["+56 9 6331 9012"]},
                {"name": "company_name", "values": ["AgroTech Latam"]},
                {"name": "job_title", "values": ["CEO & Founder"]},
                {"name": "budget", "values": ["28000"]},
                {"name": "timeline", "values": ["immediate"]},
                {"name": "need", "values": ["Automatizar embudo comercial B2B y seguimiento de leads de campañas Meta Ads"]},
            ],
        }
        res = ingest_webhook_event(db, provider="meta_ads", payload=meta_payload, signature_valid=True)
        return {
            "scenario": key,
            "title": "Webhook de Meta Lead Ads procesado y cualificado como HOT",
            "deduplicated": res.deduplicated,
            "lead": res.lead,
        }

    if key == "cold_nurture":
        payload = LeadCreate(
            full_name="Lucas Mora",
            email=f"lmora.{suffix}@studiodigital.pe",
            job_title="Coordinador de Marketing",
            company_name="StudioDigital Lima",
            company_size="11-50",
            industry="Agencia Digital",
            estimated_budget_usd=3200,
            decision_maker_role="Individual Contributor",
            primary_need="Evaluando opciones de automatización para el próximo año",
            timeline_urgency="exploring",
            source=LeadSource.LINKEDIN_ADS_WEBHOOK,
            tags=["simulador-1-clic", "nurture"],
        )
        lead, dedup = create_or_merge_lead(db, payload, actor="recruiter_simulator")
        return {
            "scenario": key,
            "title": "Lead COLD (Exploración temprana) asignado a Nurturing Educativo",
            "deduplicated": dedup,
            "lead": LeadOut.model_validate(lead),
        }

    if key == "disqualified_student":
        payload = LeadCreate(
            full_name="Pedro Gómez",
            email=f"pedro.estudiante.{suffix}@gmail.com",
            job_title="Estudiante Universitario",
            company_name="Sin Empresa",
            company_size="1-10",
            industry="Educación",
            estimated_budget_usd=100,
            decision_maker_role="Student",
            primary_need="Curiosidad sobre agentes de IA para un trabajo práctico",
            timeline_urgency="exploring",
            source=LeadSource.WEBSITE_FORM,
            tags=["simulador-1-clic", "filtered-out"],
        )
        lead, dedup = create_or_merge_lead(db, payload, actor="recruiter_simulator")
        return {
            "scenario": key,
            "title": "Lead No Cualificado (Gmail + Sin Presupuesto) filtrado automáticamente por IA",
            "deduplicated": dedup,
            "lead": LeadOut.model_validate(lead),
        }

    raise ValueError(f"Escenario '{scenario_key}' no reconocido.")
