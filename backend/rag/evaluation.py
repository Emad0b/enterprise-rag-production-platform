import json, time, uuid, hashlib
from pathlib import Path
import mlflow
from .config import ROOT
from .db import db, sql, audit
from .generation import PROMPTS, safe_sentences
from .chunker import tokens
from .pipeline import run
from .releases import configuration, corpus_fingerprint, pipeline_fingerprint


def fixture_user(key):
    with db() as c:
        row = sql(
            c,
            "SELECT id,email,name,groups_json,admin FROM users WHERE email=?",
            (key + "@example.test",),
        ).fetchone()
    if not row:
        raise ValueError("Bootstrap the fictional evaluation users first")
    return {
        "id": row[0],
        "email": row[1],
        "name": row[2],
        "groups": json.loads(row[3]),
        "admin": bool(row[4]),
    }


def evaluate(cid, actor="evaluation-runner"):
    config = configuration(cid)
    cases = json.loads((ROOT / "evaluations/cases.json").read_text(encoding="utf-8"))
    with db() as c:
        documents = dict(c.execute("SELECT title,id FROM documents").fetchall())
    fingerprint = corpus_fingerprint()
    results = []
    for case in cases:
        user = fixture_user(case["user"])
        start = time.perf_counter()
        result = run(case["question"], user, config, kind="evaluation")
        expected_docs = {documents[title] for title in case["supporting_documents"]}
        retrieved = {s["document_id"] for s in result["sources"]}
        recall = (
            len(expected_docs & retrieved) / len(expected_docs)
            if expected_docs
            else None
        )
        faithfulness = (
            all(
                c["quote"] in safe_sentences(result["sources"][c["citation"] - 1])
                for c in result["claims"]
            )
            if result["claims"]
            else case["expected_refusal"] and result["refused"]
        )
        citation_correctness = (
            all(
                result["sources"][c["citation"] - 1]["document_id"] in expected_docs
                for c in result["claims"]
            )
            if result["claims"]
            else case["expected_refusal"] and result["refused"]
        )
        answer_words = set(tokens(result["answer"]))
        expected = set(case["expected_terms"])
        relevance = (
            len(expected & answer_words) / len(expected)
            if expected
            else float(result["refused"])
        )
        forbidden = case.get("forbidden_strings", [])
        leak = any(marker.lower() in result["answer"].lower() for marker in forbidden)
        # SQL-level permissions also apply to every retrieved context item.
        from .security import authorized

        authorized(user, list(retrieved))
        passed = (
            not leak
            and result["refused"] == case["expected_refusal"]
            and relevance >= 0.8
            and (recall is None or recall == 1)
            and faithfulness
            and citation_correctness
        )
        results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "question": case["question"],
                "user": case["user"],
                "expected_answer": case["expected_answer"],
                "answer": result["answer"],
                "supporting_documents": case["supporting_documents"],
                "retrieved_documents": [s["title"] for s in result["sources"]],
                "recall": recall,
                "faithfulness": float(faithfulness),
                "citation_correctness": float(citation_correctness),
                "relevance": relevance,
                "refusal_correct": result["refused"] == case["expected_refusal"],
                "security_failure": leak,
                "injection_blocked": result["injection_blocked"],
                "passed": bool(passed),
                "latency_ms": result["latency_ms"],
                "estimated_cost": result["estimated_cost"],
            }
        )
    recalls = [r["recall"] for r in results if r["recall"] is not None]
    costs = [r["estimated_cost"] for r in results]
    times = sorted(r["latency_ms"] for r in results)
    metrics = {
        "recall": sum(recalls) / len(recalls),
        "faithfulness": sum(r["faithfulness"] for r in results) / len(results),
        "citation_correctness": sum(r["citation_correctness"] for r in results)
        / len(results),
        "relevance": sum(r["relevance"] for r in results) / len(results),
        "refusal_accuracy": sum(r["refusal_correct"] for r in results) / len(results),
        "security_failures": sum(r["security_failure"] for r in results),
        "p95_ms": times[int((len(times) - 1) * 0.95)],
        "cost_per_query": sum(costs) / len(costs)
        if all(c is not None for c in costs)
        else None,
        "passed_cases": sum(r["passed"] for r in results),
        "cases": len(results),
    }
    if fingerprint != corpus_fingerprint():
        raise ValueError("Corpus changed during evaluation; repeat on a stable corpus")
    eid = str(uuid.uuid4())
    report = {
        "id": eid,
        "config_id": cid,
        "metrics": metrics,
        "cases": results,
        "corpus_fingerprint": fingerprint,
        "prompt_sha256": hashlib.sha256(
            PROMPTS[config["prompt_version"]].encode()
        ).hexdigest(),
        "dataset_sha256": hashlib.sha256(
            (ROOT / "evaluations/cases.json").read_bytes()
        ).hexdigest(),
        "generation_backend": config["generation"],
        "embedding_model": __import__(
            "rag.embeddings", fromlist=["model_id"]
        ).model_id(),
        "methodology": "Exact-quotation faithfulness; supporting-document citation correctness; labeled expected-term relevance; labeled refusal and leakage checks. These are deterministic task-specific measures, not an LLM judge or a universal security guarantee.",
        "latency_scope": "Warm embedding model; application operation including MLflow span creation, excluding HTTP transport. Query-embedding cache may be warm on repeat evaluations.",
    }
    report["pipeline_sha256"] = pipeline_fingerprint()
    with mlflow.start_run(run_name="rag-regression-" + cid) as run_info:
        mlflow.log_params(
            {
                **config,
                "evaluation_dataset_sha256": report["dataset_sha256"],
                "corpus_fingerprint": fingerprint,
            }
        )
        mlflow.log_metrics({k: v for k, v in metrics.items() if v is not None})
        mlflow.log_dict(report, "evaluation.json")
        report["mlflow_run_id"] = run_info.info.run_id
    with db() as c:
        sql(
            c,
            "INSERT INTO evaluations VALUES (?,?,?,?)",
            (eid, cid, json.dumps(report), time.time()),
        )
        audit(
            actor,
            "regression_evaluation_completed",
            {"config_id": cid, "evaluation_id": eid, "metrics": metrics},
            c,
        )
    return report
