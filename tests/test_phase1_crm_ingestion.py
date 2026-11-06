import hashlib
import hmac
import json
from fastapi.testclient import TestClient

from app.core.config import settings


def test_create_and_deduplicate_lead(client: TestClient):
    payload = {
        "full_name": "Valeria Soto",
        "email": "Valeria.Soto@FintechLatam.io",
        "job_title": "VP of Operations",
        "company_name": "FintechLatam",
        "company_size": "51-200",
        "industry": "Fintech",
        "estimated_budget_usd": 18000,
        "decision_maker_role": "VP / Director",
        "primary_need": "Automatizar atención y cualificación de prospectos B2B con agentes IA",
        "timeline_urgency": "immediate",
        "source": "website_form",
        "tags": ["fintech", "inbound"],
    }
    res1 = client.post("/api/v1/leads", json=payload)
    assert res1.status_code == 201
    data1 = res1.json()
    assert data1["email"] == "valeria.soto@fintechlatam.io"
    assert data1["duplicate_count"] == 0
    lead_id = data1["id"]

    # Re-ingest same email with updated budget & extra tag
    payload2 = {
        **payload,
        "email": "valeria.soto@fintechlatam.io",
        "estimated_budget_usd": 25000,
        "tags": ["q4-priority"],
    }
    res2 = client.post("/api/v1/leads", json=payload2)
    assert res2.status_code == 201
    data2 = res2.json()
    assert data2["id"] == lead_id
    assert data2["duplicate_count"] == 1
    assert data2["estimated_budget_usd"] == 25000.0
    assert "fintech" in data2["tags"] and "q4-priority" in data2["tags"]

    detail = client.get(f"/api/v1/leads/{lead_id}").json()
    assert len(detail["interactions"]) >= 2


def test_multi_provider_webhooks_and_hmac_security(client: TestClient):
    typeform_payload = {
        "event_id": "tf_evt_001",
        "form_response": {
            "token": "tf_tok_999",
            "answers": [
                {"field": {"ref": "full_name"}, "type": "text", "text": "Carlos Mendoza"},
                {"field": {"ref": "work_email"}, "type": "email", "email": "cmendoza@logistica-global.com"},
                {"field": {"ref": "company_name"}, "type": "text", "text": "Logística Global SA"},
                {"field": {"ref": "job_title"}, "type": "text", "text": "CTO"},
                {"field": {"ref": "budget"}, "type": "number", "number": 32000},
                {"field": {"ref": "timeline"}, "type": "choice", "choice": {"label": "1_3_months"}},
                {"field": {"ref": "primary_need"}, "type": "text", "text": "Integrar agentes IA con ERP y CRM"},
            ],
        },
    }
    raw_bytes = json.dumps(typeform_payload).encode("utf-8")
    valid_sig = hmac.new(
        settings.WEBHOOK_SECRET.encode("utf-8"), raw_bytes, hashlib.sha256
    ).hexdigest()

    res = client.post(
        "/api/v1/webhooks/leads/typeform",
        content=raw_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={valid_sig}",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["provider"] == "typeform"
    assert body["deduplicated"] is False
    assert body["lead"]["email"] == "cmendoza@logistica-global.com"
    assert body["lead"]["estimated_budget_usd"] == 32000.0

    # Invalid signature must return 401
    bad_res = client.post(
        "/api/v1/webhooks/leads/meta_ads",
        json={"email": "hacker@test.com", "full_name": "Bad Actor"},
        headers={"X-Webhook-Secret": "wrong_secret"},
    )
    assert bad_res.status_code == 401


def test_csv_bulk_import_and_stage_transition(client: TestClient):
    csv_content = (
        "full_name,email,company_name,job_title,estimated_budget_usd,company_size,primary_need,timeline_urgency\n"
        "Elena Rojas,elena@cloudscale.io,CloudScale,CEO,45000,51-200,Automatización comercial B2B con IA,immediate\n"
        "Marco Díaz,marco@pyme.cl,Pyme Local,Analista,1200,1-10,Explorando herramientas,exploring\n"
    )
    res = client.post("/api/v1/leads/import/csv", json={"csv_text": csv_content})
    assert res.status_code == 200
    summary = res.json()
    assert summary["processed"] == 2
    assert summary["created"] == 2

    lead_id = summary["lead_ids"][0]
    stage_res = client.post(
        f"/api/v1/leads/{lead_id}/stage",
        json={"stage": "contacted", "reason": "Validado presupuesto de $45k con CEO", "actor": "sales_director"},
    )
    assert stage_res.status_code == 200
    assert stage_res.json()["stage"] == "contacted"

    stats = client.get("/api/v1/leads/stats").json()
    assert stats["total_leads"] == 2
    assert stats["total_estimated_pipeline_usd"] == 45000.0
