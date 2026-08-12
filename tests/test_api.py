from fastapi.testclient import TestClient

from app.main import create_app


def client():
    app = create_app(database_url="sqlite:///:memory:")
    return TestClient(app)


def signup_payload(email="ana.ribeiro@example.com"):
    return {
        "email": email,
        "password": "senha-segura-123",
        "full_name": "Ana Ribeiro",
    }


def auth_headers(api):
    response = api.post("/api/auth/signup", json=signup_payload())
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def sample_resume():
    return {
        "name": "Analista de Operações — mestre",
        "target_role": "Analista de Operações Sênior",
        "language": "pt",
        "personal": {
            "full_name": "Ana Ribeiro",
            "email": "ana.ribeiro@email.com",
            "phone": "+55 11 98812-4400",
            "location": "São Paulo, SP",
        },
        "summary": "Analista de operações com 7 anos em logística e atendimento.",
        "experience": [
            {
                "role": "Analista de Suporte Pleno",
                "company": "Nuvem Serviços",
                "period": "01/2018 — 02/2021",
                "bullets": [
                    "Responsável pelo time de suporte.",
                    "Ajudei na migração de sistema.",
                ],
            }
        ],
        "education": {
            "school": "Universidade Federal de São Paulo",
            "degree": "Bacharelado em Administração",
            "period": "2013 — 2017",
        },
        "skills": ["Excel avançado", "SQL", "Looker Studio"],
    }


def test_health_reports_database_and_cache_ready():
    api = client()

    response = api.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "cache": "ok"}


def test_signup_and_login_issue_bearer_tokens():
    api = client()

    signup = api.post("/api/auth/signup", json=signup_payload())
    login = api.post(
        "/api/auth/login",
        json={"email": "ana.ribeiro@example.com", "password": "senha-segura-123"},
    )

    assert signup.status_code == 201
    assert signup.json()["token_type"] == "bearer"
    assert signup.json()["user"]["email"] == "ana.ribeiro@example.com"
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_resume_crud_is_scoped_to_authenticated_user():
    api = client()
    headers = auth_headers(api)
    other_headers = auth_headers(api, ) if False else None

    created = api.post("/api/resumes", headers=headers, json=sample_resume())
    listed = api.get("/api/resumes", headers=headers)
    resume_id = created.json()["id"]
    updated = api.patch(
        f"/api/resumes/{resume_id}",
        headers=headers,
        json={"summary": "Resumo atualizado", "skills": ["SQL", "Power BI"]},
    )

    assert created.status_code == 201
    assert created.json()["ats_score"] == 62
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [resume_id]
    assert updated.status_code == 200
    assert updated.json()["summary"] == "Resumo atualizado"
    assert updated.json()["skills"] == ["SQL", "Power BI"]


def test_resume_list_is_user_scoped():
    api = client()
    ana_headers = auth_headers(api)
    bruno_signup = api.post("/api/auth/signup", json=signup_payload("bruno@example.com"))
    bruno_headers = {"Authorization": f"Bearer {bruno_signup.json()['access_token']}"}

    created = api.post("/api/resumes", headers=ana_headers, json=sample_resume())
    bruno_list = api.get("/api/resumes", headers=bruno_headers)

    assert created.status_code == 201
    assert bruno_list.status_code == 200
    assert bruno_list.json() == []


def test_ats_analysis_scores_and_one_click_fixes_match_design_behaviour():
    api = client()
    headers = auth_headers(api)
    resume_id = api.post("/api/resumes", headers=headers, json=sample_resume()).json()["id"]

    initial = api.post(f"/api/resumes/{resume_id}/ats/analyze", headers=headers, json={})
    fixed = api.post(
        f"/api/resumes/{resume_id}/ats/fix",
        headers=headers,
        json={"issue_ids": ["i1", "i2", "i3", "i4", "i5"]},
    )

    assert initial.status_code == 200
    assert initial.json()["score"] == 62
    assert [issue["id"] for issue in initial.json()["issues"]] == ["i1", "i2", "i3", "i4", "i5"]
    assert fixed.status_code == 200
    assert fixed.json()["ats_score"] == 92
    assert fixed.json()["fixed_issue_ids"] == ["i1", "i2", "i3", "i4", "i5"]


def test_job_tailoring_returns_keyword_fit_and_cached_repeat_response():
    api = client()
    headers = auth_headers(api)
    resume_id = api.post("/api/resumes", headers=headers, json=sample_resume()).json()["id"]
    payload = {
        "job_description": "Vaga para operação com SQL, Looker, SLA, Power BI, OKR e supply chain."
    }

    first = api.post(f"/api/resumes/{resume_id}/tailor", headers=headers, json=payload)
    second = api.post(f"/api/resumes/{resume_id}/tailor", headers=headers, json=payload)

    assert first.status_code == 200
    assert first.json()["fit"] >= 54
    assert "SQL" in first.json()["keywords_found"]
    assert "Power BI" in first.json()["keywords_missing"]
    assert second.status_code == 200
    assert second.headers["X-Cache"] == "HIT"
    assert second.json() == first.json()


def test_static_frontend_is_responsive_and_cache_controlled():
    api = client()

    response = api.get("/")

    assert response.status_code == 200
    assert "MEU<span>CV</span>.PRO" in response.text
    assert "@media (max-width: 900px)" in response.text
    assert "grid-template-columns: 1fr" in response.text
    assert response.headers["Cache-Control"] == "public, max-age=300"
