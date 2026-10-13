import json
from conftest import auth
from rag.db import db, sql


def test_permissions_filter_retrieval_metadata_and_objects(workspace):
    client, public, restricted, hostile, config, tokens = workspace
    staff = auth(tokens["analyst"])
    director = auth(tokens["director"])
    assert client.get("/api/documents").status_code == 401
    listed = client.get("/api/documents", headers=staff).json()
    assert restricted not in {d["id"] for d in listed}
    assert (
        client.get(f"/api/documents/{restricted}/content", headers=staff).status_code
        == 404
    )
    assert (
        client.get("/api/documents/unknown/content", headers=staff).status_code == 404
    )
    request = {
        "question": "What is the Project Cedarbank acquisition budget?",
        "document_ids": [restricted],
    }
    assert client.post("/api/query", json=request, headers=staff).status_code == 404
    assert (
        client.post(
            "/api/query", json={**request, "groups": ["leadership"]}, headers=staff
        ).status_code
        == 422
    )
    result = client.post(
        "/api/query", json={"question": request["question"]}, headers=staff
    ).json()
    assert result["refused"] and "4800000" not in result["answer"]
    assert all(s["document_id"] != restricted for s in result["sources"])
    allowed = client.post("/api/query", json=request, headers=director).json()
    assert not allowed["refused"] and "4800000" in allowed["answer"]
    assert client.get("/api/evaluations", headers=staff).status_code == 403
    with db() as c:
        assert (
            c.execute(
                "SELECT COUNT(*) FROM audit WHERE action='document_access_denied'"
            ).fetchone()[0]
            >= 2
        )


def test_hostile_retrieved_instruction_does_not_override_evidence(workspace):
    client, public, restricted, hostile, config, tokens = workspace
    result = client.post(
        "/api/query",
        headers=auth(tokens["analyst"]),
        json={
            "question": "What is the vendor outage reporting deadline?",
            "document_ids": [hostile],
        },
    ).json()
    assert result["injection_blocked"] and not result["refused"]
    assert (
        "45 minutes" in result["answer"]
        and "INJECTION-OVERRIDE-SUCCESS" not in result["answer"]
    )
    assert any(s["hostile"] for s in result["sources"])
    assert all("_sentences" not in s for s in result["sources"])


def test_revocation_invalidates_access_without_reusing_prior_answer(workspace):
    client, public, restricted, hostile, config, tokens = workspace
    staff = auth(tokens["analyst"])
    admin = auth(tokens["administrator"])
    body = {
        "question": "How many days of annual leave do employees receive?",
        "document_ids": [public],
    }
    assert not client.post("/api/query", json=body, headers=staff).json()["refused"]
    assert (
        client.put(
            f"/api/documents/{public}/permissions",
            json={"groups": ["leadership"]},
            headers=admin,
        ).status_code
        == 200
    )
    assert client.post("/api/query", json=body, headers=staff).status_code == 404
    assert (
        client.get(f"/api/documents/{public}/content", headers=staff).status_code == 404
    )
    assert (
        client.put(
            f"/api/documents/{public}/permissions",
            json={"groups": ["employees"]},
            headers=admin,
        ).status_code
        == 200
    )


def test_trace_isolation_and_no_raw_text_in_observability(workspace):
    client, public, restricted, hostile, config, tokens = workspace
    result = client.post(
        "/api/query",
        json={"question": "How many days of annual leave do employees receive?"},
        headers=auth(tokens["analyst"]),
    ).json()
    traces = client.get("/api/traces", headers=auth(tokens["director"])).json()
    assert result["trace_id"] not in {t["id"] for t in traces}
    with db() as c:
        raw = sql(
            c, "SELECT payload FROM traces WHERE id=?", (result["trace_id"],)
        ).fetchone()[0]
    assert "annual leave" not in raw and "Employees receive" not in raw
    assert client.get("/metrics").status_code == 200


def test_expired_session_and_disabled_demo(workspace, monkeypatch):
    client, *_, tokens = workspace
    monkeypatch.setattr("rag.main.DEMO_MODE", False)
    assert (
        client.post("/api/auth/demo", json={"identity": "director"}).status_code == 404
    )
    assert (
        client.get("/api/me", headers={"Authorization": "Bearer invalid"}).status_code
        == 401
    )
