from fastapi.testclient import TestClient


def test_dashboard_static_serving_and_seed(client: TestClient):
    res_html = client.get("/")
    assert res_html.status_code == 200
    assert "NexusLead AI" in res_html.text

    res_css = client.get("/static/styles.css")
    assert res_css.status_code == 200

    res_js = client.get("/static/app.js")
    assert res_js.status_code == 200

    seed_res = client.post("/api/v1/demo/seed?force_reset=true")
    assert seed_res.status_code == 200
    assert seed_res.json()["seeded"] is True
    assert seed_res.json()["created_leads"] == 6

    stats = client.get("/api/v1/leads/stats").json()
    assert stats["total_leads"] == 6
    assert stats["hot_leads_count"] >= 2
    assert stats["by_stage"]["meeting_scheduled"] >= 1
    assert stats["by_stage"]["proposal_sent"] >= 1


def test_recruiter_one_click_scenarios(client: TestClient):
    scenarios = [
        ("enterprise_hot", "hot"),
        ("typeform_webhook", "hot"),
        ("meta_ads_webhook", "hot"),
        ("cold_nurture", "cold"),
        ("disqualified_student", "disqualified"),
    ]
    for key, expected_tier in scenarios:
        res = client.post(f"/api/v1/demo/scenario/{key}")
        assert res.status_code == 201
        body = res.json()
        assert body["scenario"] == key
        assert body["lead"]["qualification_tier"] == expected_tier
