"""Create a fictional organisation, versioned RAG configurations, and real evaluations."""

import sys, os, json, secrets, uuid, time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
os.environ.setdefault("RAG_ROOT", str(root))
os.environ.setdefault("RAG_DEMO_MODE", "true")
os.environ.setdefault("DO_NOT_TRACK", "1")
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
from rag.config import RUNTIME, LLM_MODEL
from rag.db import db, sql, state
from rag.security import password_hash
from rag.ingest import create_document, process_document
from rag.embeddings import model_id
from rag.releases import register, bootstrap, release_gate
from rag.evaluation import evaluate
from rag.pipeline import configure_tracking

if __name__ == "__main__":
    (root / "reports").mkdir(exist_ok=True)
    configure_tracking()
    credentials = {}
    for identity, name, groups, admin in [
        ("analyst", "Maya Chen", ["employees"], 0),
        ("director", "Alex Morgan", ["employees", "leadership"], 0),
        ("administrator", "Workspace Admin", ["employees", "leadership"], 1),
    ]:
        with db() as c:
            if not sql(
                c, "SELECT id FROM users WHERE email=?", (identity + "@example.test",)
            ).fetchone():
                password = secrets.token_urlsafe(24)
                credentials[identity] = {
                    "email": identity + "@example.test",
                    "password": password,
                }
                sql(
                    c,
                    "INSERT INTO users VALUES (?,?,?,?,?,?)",
                    (
                        str(uuid.uuid4()),
                        identity + "@example.test",
                        name,
                        password_hash(password),
                        json.dumps(groups),
                        admin,
                    ),
                )
    if credentials:
        (RUNTIME / "credentials.json").write_text(
            json.dumps(credentials, indent=2), encoding="utf-8"
        )
    manifest = json.loads(
        (root / "evaluations/documents.json").read_text(encoding="utf-8")
    )
    for item in manifest:
        with db() as c:
            existing = sql(
                c, "SELECT id FROM documents WHERE title=?", (item["title"],)
            ).fetchone()
        if not existing:
            did = create_document(
                item["title"],
                (root / "evaluations/documents" / item["file"]).read_bytes(),
                "text/plain",
                item["groups"],
                "bootstrap",
            )
            process_document(did)
        else:
            with db() as c:
                missing = sql(
                    c,
                    "SELECT id FROM chunks WHERE document_id=? AND (sentences IS NULL OR model!=?)",
                    (existing[0], model_id()),
                ).fetchone()
            if missing:
                process_document(existing[0])
    reports = []
    configs = []
    for name, retrieval, top_k, prompt in [
        ("Keyword baseline", "keyword", 2, "grounded-v1"),
        ("Hybrid · grounded v2", "hybrid", 4, "grounded-v2"),
        ("Hybrid · compact challenger", "hybrid", 3, "grounded-v2"),
    ]:
        config = register(
            {
                "name": name,
                "retrieval": retrieval,
                "generation": "extractive",
                "model": "source-quotes-v1",
                "prompt_version": prompt,
                "top_k": top_k,
                "candidate_pool": 20,
                "max_context_words": 1200 if top_k == 4 else 900,
                "minimum_similarity": 0.35,
            },
            "bootstrap",
        )
        configs.append(config)
        report = evaluate(config["id"])
        reports.append(report)
        print(
            json.dumps(
                {
                    "name": name,
                    "metrics": report["metrics"],
                    "gate": release_gate(config["id"]),
                }
            )
        )
    champion = next(c for c in configs if c["name"] == "Hybrid · grounded v2")
    if not state("champion"):
        result = bootstrap(champion["id"], "explicit-demo-approval")
        if not result["passed"]:
            raise RuntimeError(
                "Initial configuration failed its fixed release gates: "
                + json.dumps(result)
            )
    mlflow = __import__("mlflow")
    mlflow.flush_trace_async_logging()
    (root / "reports/evaluation-results.json").write_text(
        json.dumps(
            {
                "fictional_documents": True,
                "generation_backend": "extractive",
                "reports": reports,
                "configurations": configs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        "Bootstrap complete. Private credentials are in runtime/credentials.json; no passwords printed."
    )
