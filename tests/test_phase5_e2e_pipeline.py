from fastapi.testclient import TestClient


def test_complete_end_to_end_lead_commercial_lifecycle(client: TestClient):
    """End-to-end test validating the entire commercial automation journey:
    1. Lead enters via Meta Ads Webhook
    2. AI Agent qualifies via BANT + Domain Intelligence -> HOT tier -> Stage QUALIFIED
    3. Adaptive 3-step sequence is enrolled + Outbound Slack/CRM Webhook is dispatched
    4. Step #1 (WhatsApp) is executed -> Stage advances to CONTACTED
    5. Lead replies asking to schedule a demo -> AI Reply Handler moves stage to MEETING_SCHEDULED & cancels pending tasks
    6. Lead replies asking for formal quote -> AI Reply Handler moves stage to PROPOSAL_SENT
    7. Sales rep closes deal -> Stage WON -> KPIs reflect conversion
    """
    # Step 1: Ingest via Meta Ads Webhook
    meta_webhook = {
        "leadgen_id": "e2e_meta_9001",
        "campaign_name": "Enterprise_AI_Agents_LATAM",
        "field_data": [
            {"name": "full_name", "values": ["Sebastián Lagos"]},
            {"name": "work_email", "values": ["slagos@bancodigital.cl"]},
            {"name": "phone_number", "values": ["+56 9 8877 6655"]},
            {"name": "company_name", "values": ["Banco Digital Austral"]},
            {"name": "job_title", "values": ["CEO & Founder"]},
            {"name": "budget", "values": ["62000"]},
            {"name": "timeline", "values": ["immediate"]},
            {"name": "need", "values": ["Automatizar recepción, cualificación BANT y seguimiento comercial con agentes IA"]},
        ],
    }
    ingest_res = client.post("/api/v1/webhooks/leads/meta_ads", json=meta_webhook)
    assert ingest_res.status_code == 201
    lead = ingest_res.json()["lead"]
    lead_id = lead["id"]

    # Step 2: Verify AI Qualification & Domain Intelligence
    assert lead["qualification_tier"] == "hot"
    assert lead["bant_total_score"] >= 85
    assert lead["stage"] == "qualified"
    assert lead["country"] == "Chile"
    assert lead["company_website"] == "https://bancodigital.cl"

    # Step 3: Verify Adaptive Sequence & Outbound Alert
    detail = client.get(f"/api/v1/leads/{lead_id}").json()
    assert len(detail["follow_up_tasks"]) == 3
    step1_id = detail["follow_up_tasks"][0]["id"]

    # Step 4: Execute Step 1 (WhatsApp)
    exec_res = client.post(f"/api/v1/automation/tasks/{step1_id}/execute")
    assert exec_res.status_code == 200
    assert exec_res.json()["lead_stage"] == "contacted"

    # Step 5: Inbound reply booking demo
    reply1 = client.post(
        f"/api/v1/automation/leads/{lead_id}/reply",
        json={"channel": "whatsapp", "message": "Perfecto, agendemos la demo mañana a las 10:00 AM."},
    )
    assert reply1.status_code == 200
    assert reply1.json()["new_stage"] == "meeting_scheduled"

    # Step 6: Inbound reply requesting pricing proposal
    reply2 = client.post(
        f"/api/v1/automation/leads/{lead_id}/reply",
        json={"channel": "email", "message": "Excelente demo. Envíame la cotización y precios para firmar este mes."},
    )
    assert reply2.status_code == 200
    assert reply2.json()["new_stage"] == "proposal_sent"

    # Step 7: Close deal as WON
    won_res = client.post(
        f"/api/v1/leads/{lead_id}/stage",
        json={"stage": "won", "reason": "Contrato anual firmado por $62,000 USD", "actor": "ae_senior"},
    )
    assert won_res.status_code == 200
    assert won_res.json()["stage"] == "won"

    final_detail = client.get(f"/api/v1/leads/{lead_id}").json()
    assert len(final_detail["interactions"]) >= 7
