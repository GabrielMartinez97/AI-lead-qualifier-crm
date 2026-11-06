from fastapi.testclient import TestClient


def test_auto_bant_qualification_and_domain_intelligence_hot_vs_disqualified(client: TestClient):
    # 1. Enterprise Hot Lead with corporate .cl domain
    hot_payload = {
        "full_name": "Roberto Fuentes",
        "email": "rfuentes@minera-andina.cl",
        "job_title": "CEO & Co-Founder",
        "company_name": "Minera Andina Tech",
        "company_size": "201-1000",
        "industry": "Mining & Logistics",
        "estimated_budget_usd": 38000,
        "decision_maker_role": "C-Level / Founder",
        "primary_need": "Automatizar cualificación de leads B2B, integrar CRM y desplegar agentes IA en ventas",
        "pain_points": "Perdemos oportunidades por demora de 24h en seguimiento de SDRs",
        "timeline_urgency": "immediate",
    }
    res_hot = client.post("/api/v1/leads", json=hot_payload)
    assert res_hot.status_code == 201
    hot_lead = res_hot.json()

    assert hot_lead["bant_total_score"] >= 80
    assert hot_lead["qualification_tier"] == "hot"
    assert hot_lead["stage"] == "qualified"
    assert hot_lead["company_website"] == "https://minera-andina.cl"
    assert hot_lead["country"] == "Chile"
    assert "corporate-email" in hot_lead["tags"]
    assert "AE Senior" in hot_lead["suggested_owner"]
    assert hot_lead["ai_reasoning"]["domain_intelligence"]["is_corporate_domain"] is True
    assert len(hot_lead["ai_reasoning"]["potential_objections"]) >= 1
    assert len(hot_lead["ai_reasoning"]["talking_points"]) == 3

    # 2. Low-fit / Disqualified student lead with free gmail.com domain
    low_payload = {
        "full_name": "Juan Estudiante",
        "email": "juanito123@gmail.com",
        "job_title": "Estudiante Universitario",
        "company_name": "Ninguna",
        "company_size": "1-10",
        "estimated_budget_usd": 100,
        "primary_need": "Curiosidad por tarea de la universidad",
        "timeline_urgency": "exploring",
    }
    res_low = client.post("/api/v1/leads", json=low_payload)
    assert res_low.status_code == 201
    low_lead = res_low.json()

    assert low_lead["bant_total_score"] < 30
    assert low_lead["qualification_tier"] == "disqualified"
    assert low_lead["stage"] == "lost"
    assert low_lead["ai_reasoning"]["domain_intelligence"]["is_corporate_domain"] is False


def test_manual_requalify_and_batch_and_preview_endpoints(client: TestClient):
    preview_res = client.post(
        "/api/v1/ai/analyze-preview",
        json={
            "full_name": "Lucía Méndez",
            "email": "lucia@saasgrowth.io",
            "job_title": "Head of Sales",
            "company_name": "SaaSGrowth",
            "company_size": "51-200",
            "estimated_budget_usd": 14000,
            "primary_need": "Automatizar seguimiento comercial y webhooks con HubSpot",
            "timeline_urgency": "1_3_months",
        },
    )
    assert preview_res.status_code == 200
    preview = preview_res.json()
    assert preview["bant_total_score"] >= 65
    assert preview["domain_intelligence"]["is_corporate_domain"] is True

    create_res = client.post(
        "/api/v1/leads",
        json={
            "full_name": "Andrés Silva",
            "email": "asilva@meditech.mx",
            "job_title": "Sales Manager",
            "company_name": "MediTech",
            "company_size": "11-50",
            "estimated_budget_usd": 6000,
            "primary_need": "Agente IA para seguimiento de leads",
            "timeline_urgency": "1_3_months",
        },
    )
    lead_id = create_res.json()["id"]
    initial_score = create_res.json()["bant_total_score"]

    client.patch(
        f"/api/v1/leads/{lead_id}",
        json={"job_title": "CEO", "estimated_budget_usd": 35000, "timeline_urgency": "immediate"},
    )
    requal_res = client.post(f"/api/v1/ai/qualify/{lead_id}")
    assert requal_res.status_code == 200
    new_score = requal_res.json()["qualification"]["bant_total_score"]
    assert new_score > initial_score
    assert requal_res.json()["lead"]["qualification_tier"] == "hot"

    batch_res = client.post(
        "/api/v1/ai/qualify-batch",
        json={"lead_ids": [lead_id], "only_unscored": False},
    )
    assert batch_res.status_code == 200
    assert batch_res.json()["processed"] == 1
    assert batch_res.json()["hot_count"] == 1
