import hashlib
import hmac
from typing import Any
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.lead import LeadSource, WebhookEventLog
from app.schemas.lead import LeadCreate, LeadOut, WebhookIngestResponse
from app.services.crm_service import create_or_merge_lead

PROVIDER_SOURCE_MAP: dict[str, LeadSource] = {
    "typeform": LeadSource.TYPEFORM_WEBHOOK,
    "meta_ads": LeadSource.META_ADS_WEBHOOK,
    "linkedin_ads": LeadSource.LINKEDIN_ADS_WEBHOOK,
    "hubspot": LeadSource.HUBSPOT_WEBHOOK,
    "website": LeadSource.WEBSITE_FORM,
}


def verify_webhook_signature(
    raw_body: bytes,
    signature_header: str | None,
    secret_header: str | None,
) -> bool:
    """Verify either X-Webhook-Secret token or X-Webhook-Signature HMAC-SHA256.
    If neither header is provided, returns True for open demo testing unless strict header is passed.
    """
    if secret_header is not None:
        return hmac.compare_digest(secret_header.strip(), settings.WEBHOOK_SECRET)

    if signature_header is not None:
        sig = signature_header.strip()
        if sig.startswith("sha256="):
            sig = sig.removeprefix("sha256=")
        expected = hmac.new(
            settings.WEBHOOK_SECRET.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(sig, expected)

    return True


def _extract_from_typeform(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize Typeform webhook (`form_response.answers` or flat answers dict)."""
    form_response = payload.get("form_response", {})
    answers = form_response.get("answers", [])
    extracted: dict[str, Any] = {
        "external_id": form_response.get("token") or payload.get("event_id"),
    }

    for ans in answers:
        field_ref = (ans.get("field", {}).get("ref") or "").lower()
        ans_type = ans.get("type")
        val = ans.get(ans_type)
        if isinstance(val, dict) and "label" in val:
            val = val["label"]

        if "email" in field_ref or ans_type == "email":
            extracted["email"] = val
        elif "name" in field_ref or "nombre" in field_ref:
            extracted["full_name"] = val
        elif "company" in field_ref or "empresa" in field_ref:
            extracted["company_name"] = val
        elif "role" in field_ref or "cargo" in field_ref or "title" in field_ref:
            extracted["job_title"] = val
        elif "budget" in field_ref or "presupuesto" in field_ref:
            if isinstance(val, (int, float)):
                extracted["estimated_budget_usd"] = float(val)
            else:
                extracted["budget_range"] = str(val)
        elif "size" in field_ref or "empleados" in field_ref:
            extracted["company_size"] = str(val)
        elif "timeline" in field_ref or "urgencia" in field_ref:
            extracted["timeline_urgency"] = str(val)
        elif "need" in field_ref or "necesidad" in field_ref or "message" in field_ref:
            extracted["primary_need"] = str(val)

    # Also merge top-level convenience keys if present
    for k in (
        "full_name",
        "email",
        "phone",
        "job_title",
        "company_name",
        "company_size",
        "industry",
        "estimated_budget_usd",
        "budget_range",
        "decision_maker_role",
        "primary_need",
        "pain_points",
        "timeline_urgency",
        "raw_message",
    ):
        if k in payload and payload[k] is not None:
            extracted[k] = payload[k]

    return extracted


def _extract_from_meta_ads(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize Meta Lead Ads (`field_data` array or flat payload)."""
    field_data = payload.get("field_data", [])
    extracted: dict[str, Any] = {
        "external_id": payload.get("leadgen_id") or payload.get("id"),
        "utm_source": "meta_ads",
        "utm_campaign": payload.get("campaign_name") or payload.get("ad_name"),
    }

    for item in field_data:
        name = (item.get("name") or "").lower()
        values = item.get("values") or []
        first_val = values[0] if values else None
        if not first_val:
            continue
        if name in ("email", "work_email"):
            extracted["email"] = first_val
        elif name in ("full_name", "name"):
            extracted["full_name"] = first_val
        elif name in ("phone_number", "phone"):
            extracted["phone"] = first_val
        elif name in ("company_name", "company"):
            extracted["company_name"] = first_val
        elif name in ("job_title", "role"):
            extracted["job_title"] = first_val
        elif "budget" in name:
            try:
                extracted["estimated_budget_usd"] = float(str(first_val).replace("$", "").replace(",", ""))
            except ValueError:
                extracted["budget_range"] = str(first_val)
        elif "timeline" in name or "urgency" in name:
            extracted["timeline_urgency"] = str(first_val)
        elif "need" in name or "challenge" in name:
            extracted["primary_need"] = str(first_val)

    for k, v in payload.items():
        if k not in ("field_data",) and v is not None and k not in extracted:
            extracted[k] = v

    return extracted


def normalize_webhook_payload(provider: str, payload: dict[str, Any]) -> LeadCreate:
    provider_key = provider.strip().lower()
    source_enum = PROVIDER_SOURCE_MAP.get(provider_key, LeadSource.API_DIRECT)

    if provider_key == "typeform":
        data = _extract_from_typeform(payload)
    elif provider_key == "meta_ads":
        data = _extract_from_meta_ads(payload)
    elif provider_key == "hubspot":
        props = payload.get("properties", payload)
        first_name = props.get("firstname", "")
        last_name = props.get("lastname", "")
        combined_name = f"{first_name} {last_name}".strip() if (first_name or last_name) else props.get("full_name")
        data = {
            "external_id": str(payload.get("objectId") or props.get("hs_object_id") or ""),
            "full_name": combined_name or props.get("name"),
            "email": props.get("email"),
            "phone": props.get("phone"),
            "job_title": props.get("jobtitle") or props.get("job_title"),
            "company_name": props.get("company") or props.get("company_name"),
            "company_size": props.get("numemployees") or props.get("company_size"),
            "industry": props.get("industry"),
            "company_website": props.get("website"),
            "estimated_budget_usd": props.get("estimated_budget_usd") or props.get("budget"),
            "primary_need": props.get("primary_need") or props.get("hs_content_membership_notes"),
            "timeline_urgency": props.get("timeline_urgency") or props.get("timeline"),
            "raw_message": props.get("message") or props.get("raw_message"),
            "utm_source": "hubspot",
        }
    else:
        data = dict(payload)

    full_name = (
        data.get("full_name")
        or data.get("name")
        or data.get("nombre")
        or "Contacto Entrante"
    )
    email = data.get("email") or data.get("correo")
    if not email:
        raise ValueError(f"El payload del webhook '{provider}' no contiene un campo 'email' válido.")

    raw_budget = data.get("estimated_budget_usd") or data.get("budget")
    budget_usd: float | None = None
    budget_range = data.get("budget_range")
    if raw_budget is not None:
        try:
            budget_usd = float(str(raw_budget).replace("$", "").replace(",", "").strip())
        except ValueError:
            budget_range = str(raw_budget)

    tags = list(data.get("tags") or [])
    if f"webhook:{provider_key}" not in tags:
        tags.append(f"webhook:{provider_key}")

    return LeadCreate(
        external_id=str(data["external_id"]) if data.get("external_id") else None,
        full_name=str(full_name),
        email=str(email),
        phone=data.get("phone") or data.get("telefono"),
        job_title=data.get("job_title") or data.get("cargo") or data.get("role"),
        company_name=data.get("company_name") or data.get("company") or data.get("empresa"),
        company_size=str(data["company_size"]) if data.get("company_size") else None,
        industry=data.get("industry") or data.get("industria"),
        company_website=data.get("company_website") or data.get("website"),
        country=data.get("country") or data.get("pais"),
        estimated_budget_usd=budget_usd,
        budget_range=budget_range,
        decision_maker_role=data.get("decision_maker_role"),
        primary_need=data.get("primary_need") or data.get("need") or data.get("necesidad"),
        pain_points=data.get("pain_points") or data.get("dolores"),
        timeline_urgency=data.get("timeline_urgency") or data.get("timeline") or data.get("urgencia"),
        current_solution=data.get("current_solution"),
        raw_message=data.get("raw_message") or data.get("message") or data.get("mensaje"),
        source=source_enum,
        tags=tags,
        utm_source=data.get("utm_source") or provider_key,
        utm_campaign=data.get("utm_campaign"),
    )


def ingest_webhook_event(
    db: Session,
    provider: str,
    payload: dict[str, Any],
    signature_valid: bool = True,
) -> WebhookIngestResponse:
    provider_key = provider.strip().lower()
    event_log = WebhookEventLog(
        direction="inbound",
        provider=provider_key,
        event_type=payload.get("event_type") or f"{provider_key}.lead.submitted",
        signature_valid=signature_valid,
        payload_json=payload,
        status="received",
    )
    db.add(event_log)
    db.flush()

    if not signature_valid:
        event_log.status = "rejected_signature"
        event_log.error_message = "Invalid webhook signature or secret header."
        db.commit()
        raise PermissionError("Firma o secreto del webhook inválido.")

    try:
        lead_in = normalize_webhook_payload(provider_key, payload)
        lead, was_dedup = create_or_merge_lead(
            db, lead_in, actor=f"webhook:{provider_key}"
        )
        event_log.lead_id = lead.id
        event_log.status = "deduplicated" if was_dedup else "processed"
        db.commit()
        db.refresh(lead)

        return WebhookIngestResponse(
            status=event_log.status,
            provider=provider_key,
            event_id=event_log.id,
            deduplicated=was_dedup,
            lead=LeadOut.model_validate(lead),
        )
    except Exception as exc:
        event_log.status = "failed"
        event_log.error_message = str(exc)
        db.commit()
        raise
