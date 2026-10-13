import json, time, uuid, hashlib
from conftest import auth
from rag.db import db, sql, state
from rag.releases import (
    register,
    corpus_fingerprint,
    pipeline_fingerprint,
    release_gate,
    start,
    checks,
    route,
    finish,
    abort,
)
from rag.generation import PROMPTS
from rag.embeddings import model_id
from rag.config import ROOT


def qualified(config):
    report = {
        "id": str(uuid.uuid4()),
        "metrics": {
            "recall": 1,
            "faithfulness": 1,
            "citation_correctness": 1,
            "relevance": 1,
            "refusal_accuracy": 1,
            "security_failures": 0,
            "p95_ms": 100,
            "cost_per_query": 0,
        },
        "corpus_fingerprint": corpus_fingerprint(),
        "pipeline_sha256": pipeline_fingerprint(),
        "prompt_sha256": hashlib.sha256(
            PROMPTS[config["prompt_version"]].encode()
        ).hexdigest(),
        "dataset_sha256": hashlib.sha256(
            (ROOT / "evaluations/cases.json").read_bytes()
        ).hexdigest(),
        "embedding_model": model_id(),
    }
    with db() as c:
        sql(
            c,
            "INSERT INTO evaluations VALUES (?,?,?,?)",
            (report["id"], config["id"], json.dumps(report), time.time()),
        )
    return report


def test_regression_gates_and_approval_on_canary(workspace):
    client, *_, champion, tokens = workspace
    candidate = register(
        {**{k: v for k, v in champion.items() if k != "id"}, "name": "Canary test"},
        "test",
    )
    assert not release_gate(candidate["id"])["passed"]
    assert (
        client.post(
            "/api/releases/start",
            headers=auth(tokens["analyst"]),
            json={"config_id": candidate["id"]},
        ).status_code
        == 403
    )
    qualified(champion)
    report = qualified(candidate)
    assert release_gate(candidate["id"])["passed"]
    rid = start(candidate["id"], "canary", "explicit-test-approval")["rollout"]
    counts = sum(route(str(i))[0] == candidate["id"] for i in range(1000))
    assert 150 < counts < 250
    assert route("stable") == route("stable")
    assert not finish(rid, "explicit-test-approval")["passed"]
    with db() as c:
        for i in range(20):
            payload = {
                "error": i == 0,
                "latency_ms": 15,
                "estimated_cost": 0,
                "citation_valid": True,
                "refused": False,
                "hostile_chunks": 0,
            }
            sql(
                c,
                "INSERT INTO traces VALUES (?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    "test",
                    candidate["id"],
                    "live",
                    json.dumps(payload),
                    time.time(),
                ),
            )
    assert checks(rid)["reasons"] == ["Candidate error rate exceeds budget"]
    abort(rid, checks(rid)["reasons"])
    assert state("champion") == champion["id"] and not state("active_rollout")
    # Same config must be reevaluated when the corpus or ACL changes.
    report["corpus_fingerprint"] = "changed"
    with db() as c:
        sql(
            c,
            "INSERT INTO evaluations VALUES (?,?,?,?)",
            (str(uuid.uuid4()), candidate["id"], json.dumps(report), time.time() + 1),
        )
    assert (
        "Corpus or permissions changed; repeat evaluation"
        in release_gate(candidate["id"])["reasons"]
    )


def test_shadow_completion_keeps_champion(workspace):
    _, *_, champion, tokens = workspace
    candidate = register(
        {**{k: v for k, v in champion.items() if k != "id"}, "name": "Shadow test"},
        "test",
    )
    qualified(candidate)
    qualified(champion)
    rid = start(candidate["id"], "shadow", "explicit-test-approval")["rollout"]
    assert route("shadow-client") == (champion["id"], candidate["id"], rid)
    with db() as c:
        for i in range(20):
            sql(
                c,
                "INSERT INTO traces VALUES (?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    "test",
                    candidate["id"],
                    "shadow",
                    json.dumps(
                        {
                            "error": False,
                            "latency_ms": 10,
                            "estimated_cost": 0,
                            "citation_valid": True,
                            "refused": False,
                            "hostile_chunks": 0,
                        }
                    ),
                    time.time(),
                ),
            )
    assert finish(rid, "explicit-test-approval")["passed"]
    assert state("champion") == champion["id"]


def test_api_automatically_removes_failing_candidate(workspace, monkeypatch):
    client, *_, champion, tokens = workspace
    candidate = register(
        {
            **{k: v for k, v in champion.items() if k != "id"},
            "name": "Injected failure canary",
        },
        "test",
    )
    qualified(candidate)
    qualified(champion)
    rid = start(candidate["id"], "canary", "explicit-test-approval")["rollout"]
    import rag.pipeline

    original = rag.pipeline.generate

    def failing(question, sources, config):
        if config["id"] == candidate["id"]:
            raise RuntimeError("Injected model failure")
        return original(question, sources, config)

    monkeypatch.setattr(rag.pipeline, "generate", failing)
    ids = [str(i) for i in range(1000) if route(str(i))[0] == candidate["id"]][:20]
    for request_id in ids:
        response = client.post(
            "/api/query",
            headers={**auth(tokens["analyst"]), "X-Request-Id": request_id},
            json={"question": "How many days of annual leave do employees receive?"},
        )
        assert response.status_code == 503
    assert not state("active_rollout") and state("champion") == champion["id"]
    assert "Candidate error rate exceeds budget" in checks(rid)["reasons"]
