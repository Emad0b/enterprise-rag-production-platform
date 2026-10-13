"""Real HTTP demonstration of SQL ACLs, shadow traffic and an approved canary.

Requires the bootstrapped running API with development demo identities enabled.
No fake model responses or synthetic metric substitutions are used here.
"""

import os, json, time, urllib.request, urllib.error
from pathlib import Path

BASE = os.getenv("RAG_API_URL", "http://127.0.0.1:8300")
ROOT = Path(__file__).resolve().parents[1]


def call(path, body=None, token=None, request_id=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if request_id:
        headers["X-Request-Id"] = request_id
    request = urllib.request.Request(
        BASE + "/api" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


if __name__ == "__main__":
    _, a = call("/auth/demo", {"identity": "administrator"})
    admin = a["token"]
    _, a = call("/auth/demo", {"identity": "analyst"})
    staff = a["token"]
    _, configurations = call("/configurations", token=admin)
    champion = configurations["champion"]
    candidate = next(
        c
        for c in configurations["configs"]
        if c["name"] == "Hybrid · compact challenger"
    )
    _, documents = call("/documents", token=admin)
    restricted = next(
        d["id"] for d in documents if d["title"] == "Leadership Acquisition Memo"
    )
    public = next(d["id"] for d in documents if d["title"] == "Employee Leave Handbook")
    request = urllib.request.Request(
        BASE + f"/api/documents/{public}/content",
        headers={"Authorization": "Bearer " + staff},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.status == 200 and b"24 days" in response.read()
    denied_status, _ = call(
        "/query",
        {
            "question": "What is the Project Cedarbank acquisition budget?",
            "document_ids": [restricted],
        },
        staff,
    )
    assert denied_status == 404, (
        "Restricted explicit-ID requests must fail before retrieval"
    )
    questions = [
        "How many days of annual leave do employees receive?",
        "What is the vendor outage reporting deadline?",
        "What is the Project Cedarbank acquisition budget?",
        "How much can I spend on lunch each day?",
    ]
    events = []
    for mode in ("shadow", "canary"):
        status, started = call(
            "/releases/start", {"config_id": candidate["id"], "mode": mode}, admin
        )
        assert status == 200, (status, started)
        rid = started["rollout"]
        sent = 0
        replies = []
        for i in range(300):
            status, result = call(
                "/query",
                {"question": questions[i % len(questions)]},
                staff,
                f"{mode}-demo-{i}",
            )
            assert status == 200, (status, result)
            replies.append(
                {
                    "config_id": result["config_id"],
                    "refused": result["refused"],
                    "latency_ms": result["latency_ms"],
                    "shadow_scheduled": result["shadow_scheduled"],
                }
            )
            sent += 1
            if i % 5 == 4:
                _, snapshot = call("/configurations", token=admin)
                rollout = next(r for r in snapshot["rollouts"] if r["id"] == rid)
                if rollout["status"] != "active" or rollout["checks"]["requests"] >= 25:
                    break
        # Background shadow work is not on the live response's critical path.
        for _ in range(30):
            _, snapshot = call("/configurations", token=admin)
            rollout = next(r for r in snapshot["rollouts"] if r["id"] == rid)
            if rollout["checks"]["requests"] >= 20:
                break
            time.sleep(0.5)
        assert rollout["checks"]["passed"], rollout
        status, finished = call(f"/releases/{rid}/finish", {}, admin)
        assert status == 200 and finished["passed"], finished
        _, after = call("/configurations", token=admin)
        if mode == "shadow":
            assert after["champion"] == champion and all(
                r["config_id"] == champion for r in replies
            )
        else:
            assert after["champion"] == candidate["id"]
        events.append(
            {
                "mode": mode,
                "requests_sent": sent,
                "checks": rollout["checks"],
                "completion": finished,
                "observed_routing": {
                    cid: sum(r["config_id"] == cid for r in replies)
                    for cid in {r["config_id"] for r in replies}
                },
            }
        )
    report = {
        "fictional_corpus": True,
        "generation": "extractive",
        "traffic": "Actual HTTP requests to the running API",
        "restricted_explicit_id_status": denied_status,
        "authorised_object_download": True,
        "initial_champion": champion,
        "candidate": candidate["id"],
        "events": events,
        "note": "Each stage is explicitly approved by this local demonstration script; shadow completion does not deploy the candidate.",
    }
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/rollout-results.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "restricted_request": denied_status,
                "rollouts": [
                    (e["mode"], e["checks"]["requests"], e["checks"]["p95_ms"])
                    for e in events
                ],
            },
            indent=2,
        )
    )
