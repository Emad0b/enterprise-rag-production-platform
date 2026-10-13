import json, time, uuid, hashlib, threading, math
from .db import db, sql, state, set_state, audit
from .config import POLICY, ROOT
from .generation import PROMPTS

LOCK = threading.RLock()


def configuration(cid):
    with db() as c:
        row = sql(c, "SELECT payload FROM configs WHERE id=?", (cid,)).fetchone()
    if not row:
        raise ValueError("Configuration not found")
    return {"id": cid, **json.loads(row[0])}


def configurations():
    with db() as c:
        rows = c.execute("SELECT id FROM configs ORDER BY created").fetchall()
    return [configuration(r[0]) for r in rows]


def register(payload, actor):
    if payload["prompt_version"] not in PROMPTS:
        raise ValueError("Unknown versioned prompt")
    if payload["retrieval"] not in ("keyword", "vector", "hybrid"):
        raise ValueError("Unknown retrieval mode")
    if payload["generation"] not in ("extractive", "openai-compatible"):
        raise ValueError("Unknown generation backend")
    if (
        not 1 <= payload["top_k"] <= 8
        or not payload["top_k"] <= payload["candidate_pool"] <= 50
    ):
        raise ValueError("Invalid retrieval bounds")
    if (
        not 100 <= payload["max_context_words"] <= 2500
        or not 0.1 <= payload["minimum_similarity"] <= 0.9
    ):
        raise ValueError("Invalid context limits")
    cid = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    with db() as c:
        sql(
            c,
            "INSERT INTO configs VALUES (?,?,?) ON CONFLICT (id) DO NOTHING",
            (cid, json.dumps(payload), time.time()),
        )
        audit(
            actor,
            "configuration_registered",
            {
                "config_id": cid,
                "prompt_version": payload["prompt_version"],
                "model": payload["model"],
            },
            c,
        )
    return configuration(cid)


def corpus_fingerprint():
    with db() as c:
        docs = c.execute(
            "SELECT d.id,d.digest,d.status,a.group_name FROM documents d JOIN acl a ON a.document_id=d.id ORDER BY d.id,a.group_name"
        ).fetchall()
    return hashlib.sha256(json.dumps(docs).encode()).hexdigest()


def pipeline_fingerprint():
    paths = sorted((ROOT / "backend/rag").glob("*.py"))
    return hashlib.sha256(
        b"".join(p.read_bytes().replace(b"\r\n", b"\n") for p in paths)
    ).hexdigest()


def latest_evaluation(cid):
    with db() as c:
        row = sql(
            c,
            "SELECT payload,created FROM evaluations WHERE config_id=? ORDER BY created DESC LIMIT 1",
            (cid,),
        ).fetchone()
    return {**json.loads(row[0]), "created": row[1]} if row else None


def release_gate(cid):
    config = configuration(cid)
    report = latest_evaluation(cid)
    reasons = []
    if not report:
        return {"passed": False, "reasons": ["Run the regression evaluation first"]}
    metrics = report["metrics"]
    required = (
        "recall",
        "faithfulness",
        "citation_correctness",
        "relevance",
        "refusal_accuracy",
        "p95_ms",
        "security_failures",
    )
    if any(
        type(metrics.get(k)) not in (int, float)
        or not math.isfinite(metrics[k])
        or metrics[k] < 0
        for k in required
    ):
        return {
            "passed": False,
            "reasons": ["Evaluation metrics must be finite and non-negative"],
        }
    if metrics.get("cost_per_query") is not None and (
        type(metrics["cost_per_query"]) not in (int, float)
        or not math.isfinite(metrics["cost_per_query"])
        or metrics["cost_per_query"] < 0
    ):
        return {"passed": False, "reasons": ["Cost must be finite and non-negative"]}
    if report.get("pipeline_sha256") != pipeline_fingerprint():
        reasons.append("Pipeline code changed; repeat evaluation")
    if (
        report["dataset_sha256"]
        != hashlib.sha256((ROOT / "evaluations/cases.json").read_bytes()).hexdigest()
    ):
        reasons.append("Evaluation dataset changed")
    from .embeddings import model_id

    if report["embedding_model"] != model_id():
        reasons.append("Embedding model changed")
    if report["corpus_fingerprint"] != corpus_fingerprint():
        reasons.append("Corpus or permissions changed; repeat evaluation")
    if time.time() - report["created"] > POLICY["evaluation_max_age_seconds"]:
        reasons.append("Evaluation is stale")
    prompt_hash = hashlib.sha256(PROMPTS[config["prompt_version"]].encode()).hexdigest()
    if report["prompt_sha256"] != prompt_hash:
        reasons.append("Prompt changed since evaluation")
    for metric in (
        "recall",
        "faithfulness",
        "citation_correctness",
        "relevance",
        "refusal_accuracy",
    ):
        if metrics[metric] < POLICY["minimum_" + metric]:
            reasons.append(metric + " below release threshold")
    if metrics["security_failures"] > POLICY["maximum_security_failures"]:
        reasons.append("Security regression detected")
    if metrics["p95_ms"] > POLICY["maximum_p95_ms"]:
        reasons.append("p95 latency exceeds budget")
    if metrics["cost_per_query"] is None:
        reasons.append("Configure provider token rates and usage before release")
    elif metrics["cost_per_query"] > POLICY["maximum_cost_per_query"]:
        reasons.append("Cost exceeds query budget")
    champion = state("champion")
    baseline = latest_evaluation(champion) if champion else None
    if baseline and baseline["corpus_fingerprint"] == report["corpus_fingerprint"]:
        if (
            metrics["recall"]
            < baseline["metrics"]["recall"] - POLICY["maximum_recall_regression"]
        ):
            reasons.append("Retrieval recall regressed")
        if (
            metrics["p95_ms"]
            > max(10, baseline["metrics"]["p95_ms"]) * POLICY["maximum_p95_ratio"]
        ):
            reasons.append("p95 regressed against champion")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "policy": POLICY,
        "evaluation_id": report["id"],
    }


def bootstrap(cid, actor):
    with LOCK:
        if state("champion"):
            raise ValueError("Use a monitored rollout after initial deployment")
        gate = release_gate(cid)
        if not gate["passed"]:
            return gate
        with db() as c:
            set_state("champion", cid, c)
            audit(actor, "initial_champion_approved", {"config_id": cid}, c)
        return {**gate, "champion": cid}


def rollouts():
    with db() as c:
        rows = c.execute("SELECT * FROM rollouts ORDER BY created DESC").fetchall()
    return [
        dict(
            id=r[0],
            candidate=r[1],
            champion=r[2],
            status=r[3],
            mode=r[4],
            created=r[5],
            decision=json.loads(r[6]) if r[6] else None,
        )
        for r in rows
    ]


def start(cid, mode, actor):
    with LOCK:
        if mode not in ("shadow", "canary"):
            raise ValueError("Select shadow or canary")
        if not state("champion") or cid == state("champion"):
            raise ValueError("A distinct candidate and existing champion are required")
        if state("active_rollout"):
            raise ValueError("A rollout is already active")
        gate = release_gate(cid)
        if not gate["passed"]:
            audit(actor, "release_rejected", {"candidate": cid, **gate})
            return gate
        rid = str(uuid.uuid4())
        with db() as c:
            sql(
                c,
                "INSERT INTO rollouts VALUES (?,?,?,?,?,?,?)",
                (rid, cid, state("champion"), "active", mode, time.time(), None),
            )
            set_state("active_rollout", rid, c)
            audit(
                actor,
                "rollout_approved",
                {"rollout": rid, "mode": mode, "candidate": cid},
                c,
            )
        return {"passed": True, "rollout": rid}


def route(request_id):
    champion = state("champion")
    rid = state("active_rollout")
    if not rid:
        return champion, None, None
    current = next(r for r in rollouts() if r["id"] == rid)
    if current["mode"] == "shadow":
        return champion, current["candidate"], rid
    bucket = int(hashlib.sha256(request_id.encode()).hexdigest()[:16], 16) / 2**64
    return (
        (current["candidate"] if bucket < POLICY["canary_fraction"] else champion),
        None,
        rid,
    )


def checks(rid):
    current = next((r for r in rollouts() if r["id"] == rid), None)
    if not current:
        raise ValueError("Rollout not found")
    if (
        current["status"] != "active"
        and current["decision"]
        and "requests" in current["decision"]
    ):
        return current["decision"]
    with db() as c:
        rows = sql(
            c,
            "SELECT payload FROM traces WHERE config_id=? AND created>=? AND kind IN ('live','shadow')",
            (current["candidate"], current["created"]),
        ).fetchall()
    data = [json.loads(r[0]) for r in rows]
    n = len(data)
    reasons = []
    errors = sum(d["error"] for d in data) / n if n else 0
    times = sorted(d["latency_ms"] for d in data)
    p95 = times[int((n - 1) * 0.95)] if n else None
    costs = [d.get("estimated_cost") for d in data]
    avg_cost = sum(costs) / n if n and all(c is not None for c in costs) else None
    violations = sum(
        d.get("citation_valid") is False or d.get("authorization_violation", False)
        for d in data
    )
    if violations:
        reasons.append("Security or citation validation failure")
    if n >= POLICY["minimum_canary_requests"]:
        if errors > POLICY["maximum_canary_error_rate"]:
            reasons.append("Candidate error rate exceeds budget")
        if p95 > POLICY["maximum_p95_ms"]:
            reasons.append("Candidate p95 exceeds budget")
        if avg_cost is None:
            reasons.append("Candidate cost is unknown")
        elif avg_cost > POLICY["maximum_cost_per_query"]:
            reasons.append("Candidate cost exceeds budget")
    return {
        "passed": n >= POLICY["minimum_canary_requests"] and not reasons,
        "requests": n,
        "error_rate": errors,
        "p95_ms": p95,
        "cost_per_query": avg_cost,
        "reasons": reasons,
    }


def abort(rid, reasons, actor="automatic-policy"):
    with LOCK:
        current = next((r for r in rollouts() if r["id"] == rid), None)
        if not current:
            raise ValueError("Rollout not found")
        if current["status"] != "active":
            return {"aborted": rid, "champion": state("champion")}
        decision = {**checks(rid), "passed": False, "reasons": reasons}
        with db() as c:
            sql(
                c,
                "UPDATE rollouts SET status='aborted',decision=? WHERE id=? AND status='active'",
                (json.dumps(decision), rid),
            )
            if state("active_rollout") == rid:
                set_state("active_rollout", "", c)
            audit(actor, "canary_rolled_back", {"rollout": rid, "reasons": reasons}, c)
    return {"aborted": rid, "champion": state("champion")}


def finish(rid, actor):
    with LOCK:
        current = next((r for r in rollouts() if r["id"] == rid), None)
        if not current or current["status"] != "active":
            raise ValueError("Active rollout required")
        result = checks(rid)
        gate = release_gate(current["candidate"])
        if not result["passed"] or not gate["passed"]:
            return {
                "passed": False,
                "reasons": [*result["reasons"], *gate["reasons"]]
                or ["More candidate observations are required"],
            }
        if current["mode"] == "shadow":
            with db() as c:
                set_state("active_rollout", "", c)
                sql(
                    c,
                    "UPDATE rollouts SET status='shadow_completed',decision=? WHERE id=?",
                    (json.dumps(result), rid),
                )
                audit(
                    actor,
                    "shadow_review_completed",
                    {"rollout": rid, "champion_unchanged": True},
                    c,
                )
            return {
                "passed": True,
                "champion": state("champion"),
                "shadow_completed": rid,
            }
        with db() as c:
            set_state("previous", current["champion"], c)
            set_state("champion", current["candidate"], c)
            set_state("active_rollout", "", c)
            sql(
                c,
                "UPDATE rollouts SET status='completed',decision=? WHERE id=?",
                (json.dumps(result), rid),
            )
            audit(
                actor,
                "full_rollout_approved",
                {"rollout": rid, "champion": current["candidate"]},
                c,
            )
        return {"passed": True, "champion": current["candidate"]}
