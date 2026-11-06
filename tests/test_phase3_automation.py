from fastapi.testclient import TestClient


def test_adaptive_cadence_enrollment_and_task_execution(client: TestClient):
    # 1. Create a HOT lead -> should auto-enroll in 3-step Fast-Track (WhatsApp, Email, Call) + dispatch outbound webhook
    hot_res = client.post(
        "/api/v1/leads",
        json={
            "full_name": "Camila Navarro",
            "email": "cnavarro@enterprise-bank.cl",
            "job_title": "CTO",
            "company_name": "Enterprise Bank",
            "company_size": "1000+",
            "industry": "Banking",
            "estimated_budget_usd": 55000,
            "primary_need": "Automatizar cualificación de leads y CRM con agentes IA",
            "timeline_urgency": "immediate",
        },
    )
    assert hot_res.status_code == 201
    lead_id = hot_res.json()["id"]
    assert hot_res.json()["qualification_tier"] == "hot"

    detail = client.get(f"/api/v1/leads/{lead_id}").json()
    tasks = detail["follow_up_tasks"]
    assert len(tasks) == 3
    assert [t["channel"] for t in tasks] == ["whatsapp", "email", "call"]
    assert all(t["status"] == "pending" for t in tasks)

    # Check outbound webhook was logged for Hot lead
    wh_logs = client.get("/api/v1/webhooks/logs?provider=slack_crm_alert").json()
    assert any(log["event_type"] == "lead.hot_qualified_alert" and log["lead_id"] == lead_id for log in wh_logs)

    # Execute Step 1 (WhatsApp)
    first_task_id = tasks[0]["id"]
    exec_res = client.post(f"/api/v1/automation/tasks/{first_task_id}/execute")
    assert exec_res.status_code == 200
    exec_body = exec_res.json()
    assert exec_body["task"]["status"] == "sent"
    assert exec_body["lead_stage"] == "contacted"


def test_ai_inbound_reply_handler_meeting_pricing_and_unsubscribe(client: TestClient):
    # Create a Warm lead
    warm_res = client.post(
        "/api/v1/leads",
        json={
            "full_name": "Diego Herrera",
            "email": "dherrera@retailcloud.co",
            "job_title": "VP of Sales",
            "company_name": "RetailCloud",
            "company_size": "51-200",
            "industry": "Retail Tech",
            "estimated_budget_usd": 12000,
            "primary_need": "Integrar webhooks de leads y automatizar seguimiento",
            "timeline_urgency": "1_3_months",
        },
    )
    lead_id = warm_res.json()["id"]

    # 1. Lead replies asking to book a demo meeting
    reply_res = client.post(
        f"/api/v1/automation/leads/{lead_id}/reply",
        json={
            "channel": "email",
            "message": "Hola equipo, me interesa mucho. ¿Podemos agendar una demo mañana jueves a las 15:00?",
        },
    )
    assert reply_res.status_code == 200
    analysis = reply_res.json()
    assert analysis["detected_reply_intent"] == "book_meeting"
    assert analysis["sentiment"] == "positive"
    assert analysis["new_stage"] == "meeting_scheduled"
    assert analysis["cancelled_Pending_tasks"] == 3
    assert analysis["outbound_webhook_dispatched"] is True

    # Verify no tasks remain pending
    remaining_pending = client.get(f"/api/v1/automation/tasks?lead_id={lead_id}&status=pending").json()
    assert len(remaining_pending) == 0

    # 2. Lead later asks for a formal pricing proposal
    pricing_res = client.post(
        f"/api/v1/automation/leads/{lead_id}/reply",
        json={
            "channel": "whatsapp",
            "message": "Por cierto, ¿me pueden enviar la cotización y precios de los planes antes de la llamada?",
        },
    )
    assert pricing_res.status_code == 200
    assert pricing_res.json()["detected_reply_intent"] == "pricing_inquiry"
    assert pricing_res.json()["new_stage"] == "proposal_sent"

    # 3. Unsubscribe scenario moves stage to lost
    unsub_res = client.post(
        f"/api/v1/automation/leads/{lead_id}/reply",
        json={
            "channel": "email",
            "message": "No me interesa por ahora, por favor dar de baja mi correo.",
        },
    )
    assert unsub_res.status_code == 200
    assert unsub_res.json()["detected_reply_intent"] == "unsubscribe"
    assert unsub_res.json()["new_stage"] == "lost"
