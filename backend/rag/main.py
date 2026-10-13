import json, time, uuid, hmac, hashlib, logging, threading
from contextlib import asynccontextmanager
from typing import Annotated, Literal
import mlflow
from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Request,
    Response,
    BackgroundTasks,
    Header,
)
from pydantic import BaseModel, Field, ConfigDict
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Gauge
from .config import DEMO_MODE, POLICY, EMBEDDING_BACKEND
from .db import db, sql, state, set_state, audit
from .security import (
    principal,
    administrator,
    issue_session,
    password_hash,
    acl_clause,
    authorized,
)
from .ingest import create_document, process_document
from .objects import get
from .pipeline import run, configure_tracking
from .releases import (
    configuration,
    configurations,
    register,
    latest_evaluation,
    release_gate,
    bootstrap,
    route,
    rollouts,
    checks,
    abort,
    finish,
    corpus_fingerprint,
)
from .evaluation import evaluate, fixture_user


@asynccontextmanager
async def lifespan(app):
    configure_tracking()
    if EMBEDDING_BACKEND == "sentence-transformers":
        from .embeddings import encode
        from starlette.concurrency import run_in_threadpool

        await run_in_threadpool(encode, ["Embedding model readiness check"])
    yield
    mlflow.flush_trace_async_logging()


app = FastAPI(title="Aperture · Enterprise RAG", version="0.1.0", lifespan=lifespan)
REFUSALS = Gauge("rag_recorded_refusals", "Persisted refused requests")
BLOCKED = Gauge(
    "rag_recorded_hostile_contexts", "Persisted requests with hostile context detected"
)
ROLLOUTS = Gauge("rag_recorded_rollbacks", "Persisted aborted configuration rollouts")
_evaluation_lock = threading.Lock()
_job = {"status": "idle", "error": None}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Strict):
    email: str = Field(max_length=160)
    password: str = Field(max_length=256)


class Demo(Strict):
    identity: Literal["analyst", "director", "administrator"] = "analyst"


class Query(Strict):
    question: str = Field(min_length=3, max_length=2000)
    document_ids: list[str] = Field(default_factory=list, max_length=30)


class Permission(Strict):
    groups: list[Literal["employees", "leadership"]] = Field(min_length=1, max_length=2)


class Candidate(Strict):
    config_id: str
    mode: Literal["shadow", "canary"] = "canary"


class ConfigInput(Strict):
    name: str = Field(max_length=100)
    retrieval: Literal["keyword", "vector", "hybrid"] = "hybrid"
    generation: Literal["extractive", "openai-compatible"] = "extractive"
    model: str = Field(default="source-quotes-v1", max_length=100)
    prompt_version: Literal["grounded-v1", "grounded-v2"] = "grounded-v2"
    top_k: int = Field(default=4, ge=1, le=8)
    candidate_pool: int = Field(default=20, ge=1, le=50)
    max_context_words: int = Field(default=1200, ge=100, le=2500)
    minimum_similarity: float = Field(default=0.35, ge=0.1, le=0.9)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "demo_mode": DEMO_MODE,
        "embedding_backend": EMBEDDING_BACKEND,
        "storage": "postgresql/pgvector"
        if __import__("rag.db", fromlist=["PG"]).PG
        else "sqlite",
        "champion": state("champion") or None,
        "evaluation_job": _job,
    }


@app.post("/api/auth/login")
def login(body: Login):
    with db() as c:
        row = sql(
            c, "SELECT id,password FROM users WHERE email=?", (body.email.lower(),)
        ).fetchone()
    if not row or not hmac.compare_digest(
        password_hash(body.password, row[1].split(":")[0]), row[1]
    ):
        raise HTTPException(401, "Invalid credentials")
    return {"token": issue_session(row[0])}


@app.post("/api/auth/demo")
def demo(body: Demo):
    if not DEMO_MODE:
        raise HTTPException(404, "Demo identities are disabled")
    user = fixture_user(body.identity)
    return {"token": issue_session(user["id"]), "user": user, "development_only": True}


@app.post("/api/auth/logout")
def logout(user=Depends(principal), authorization: str = Header()):
    with db() as c:
        sql(
            c,
            "DELETE FROM sessions WHERE token=?",
            (hashlib.sha256(authorization[7:].encode()).hexdigest(),),
        )
    return {"signed_out": True}


@app.get("/api/me")
def me(user=Depends(principal)):
    return user


@app.get("/api/documents")
def documents(user=Depends(principal)):
    clause, args = acl_clause(user)
    with db() as c:
        rows = sql(
            c,
            "SELECT d.id,d.title,d.media_type,d.status,d.error,d.created FROM documents d WHERE "
            + clause
            + " ORDER BY d.created",
            args,
        ).fetchall()
        result = []
        for r in rows:
            groups = [
                g[0]
                for g in sql(
                    c, "SELECT group_name FROM acl WHERE document_id=?", (r[0],)
                ).fetchall()
            ]
            result.append(
                dict(
                    id=r[0],
                    title=r[1],
                    media_type=r[2],
                    status=r[3],
                    error=r[4],
                    created=r[5],
                    groups=groups,
                )
            )
    return result


@app.get("/api/documents/{did}/content")
def content(did: str, user=Depends(principal)):
    authorized(user, [did])
    with db() as c:
        row = sql(
            c, "SELECT object_key,media_type FROM documents WHERE id=?", (did,)
        ).fetchone()
    return Response(
        get(row[0]),
        media_type=row[1],
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )


@app.post("/api/documents", status_code=202)
async def upload(
    request: Request,
    background: BackgroundTasks,
    user=Depends(administrator),
    x_document_title: Annotated[str, Header()] = "Uploaded document",
    x_permission_groups: Annotated[str, Header()] = "employees",
):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 10_000_000:
            raise HTTPException(413, "Document exceeds 10 MB")
    try:
        did = create_document(
            x_document_title,
            bytes(raw),
            request.headers.get("content-type", "").split(";")[0],
            x_permission_groups.split(","),
            user["id"],
        )
    except ValueError as error:
        raise HTTPException(422, str(error))
    background.add_task(process_document, did)
    return {"id": did, "status": "queued"}


@app.put("/api/documents/{did}/permissions")
def permissions(did: str, body: Permission, user=Depends(administrator)):
    with db() as c:
        if not sql(c, "SELECT id FROM documents WHERE id=?", (did,)).fetchone():
            raise HTTPException(404, "Document unavailable")
        sql(c, "DELETE FROM acl WHERE document_id=?", (did,))
        for group in set(body.groups):
            sql(c, "INSERT INTO acl VALUES (?,?)", (did, group))
        set_state("corpus_epoch", int(state("corpus_epoch")) + 1, c)
        audit(
            user["id"],
            "permissions_changed",
            {"document_id": did, "groups": body.groups},
            c,
        )
    return {"updated": did, "evaluations_invalidated": True}


def run_shadow(question, user, config, ids, request_id, rid):
    try:
        run(question, user, config, ids, kind="shadow", request_id=request_id)
    except Exception:
        logging.exception("Shadow request failed")
    result = checks(rid)
    if result["reasons"]:
        abort(rid, result["reasons"])


@app.post("/api/query")
def query(
    body: Query,
    background: BackgroundTasks,
    user=Depends(principal),
    x_request_id: Annotated[str | None, Header()] = None,
):
    authorized(user, body.document_ids)
    request_id = (x_request_id or str(uuid.uuid4()))[:128]
    cid, shadow, rid = route(request_id)
    if not cid:
        raise HTTPException(503, "No evaluated, approved configuration is deployed")
    try:
        result = run(
            body.question,
            user,
            configuration(cid),
            body.document_ids,
            request_id=request_id,
        )
    except HTTPException:
        raise
    except Exception:
        logging.exception("RAG request failed")
        if rid:
            result = checks(rid)
            if result["reasons"]:
                abort(rid, result["reasons"])
        raise HTTPException(
            503, "Generation failed; the request was logged for rollout review"
        )
    if rid:
        decision = checks(rid)
        if decision["reasons"]:
            abort(rid, decision["reasons"])
    if shadow:
        background.add_task(
            run_shadow,
            body.question,
            user,
            configuration(shadow),
            body.document_ids,
            request_id,
            rid,
        )
    return {
        **result,
        "rollout_id": rid,
        "shadow_scheduled": bool(shadow),
        "request_id": request_id,
    }


@app.get("/api/traces")
def traces(user=Depends(principal)):
    with db() as c:
        rows = sql(
            c,
            "SELECT id,config_id,kind,payload,created FROM traces WHERE user_id=? AND kind!=? ORDER BY created DESC LIMIT 100",
            (user["id"], "evaluation"),
        ).fetchall()
    return [
        dict(id=r[0], config_id=r[1], kind=r[2], **json.loads(r[3]), created=r[4])
        for r in rows
    ]


@app.get("/api/configurations")
def configs(user=Depends(principal)):
    return {
        "champion": state("champion"),
        "configs": [
            dict(
                **c,
                evaluation=latest_evaluation(c["id"])["metrics"]
                if latest_evaluation(c["id"])
                else None,
                gate=release_gate(c["id"]),
            )
            for c in configurations()
        ],
        "rollouts": [{**r, "checks": checks(r["id"])} for r in rollouts()],
        "policy": POLICY,
        "job": _job,
    }


@app.post("/api/configurations")
def create_config(body: ConfigInput, user=Depends(administrator)):
    try:
        return register(body.model_dump(), user["id"])
    except ValueError as error:
        raise HTTPException(422, str(error))


@app.get("/api/evaluations")
def evaluations(user=Depends(administrator)):
    with db() as c:
        rows = c.execute(
            "SELECT payload FROM evaluations ORDER BY created DESC LIMIT 20"
        ).fetchall()
    return [json.loads(r[0]) for r in rows]


def evaluate_job(cid, actor):
    try:
        _job.update(status="running", error=None)
        evaluate(cid, actor)
        _job.update(status="completed", error=None)
    except Exception as error:
        logging.exception("Evaluation failed")
        _job.update(status="failed", error=str(error))
    finally:
        _evaluation_lock.release()


@app.post("/api/evaluations", status_code=202)
def evaluation(
    body: Candidate, background: BackgroundTasks, user=Depends(administrator)
):
    try:
        configuration(body.config_id)
    except ValueError:
        raise HTTPException(404, "Configuration not found")
    if not _evaluation_lock.acquire(blocking=False):
        raise HTTPException(409, "Evaluation already running")
    _job.update(status="queued", error=None)
    background.add_task(evaluate_job, body.config_id, user["id"])
    return {"status": "queued", "auto_promote": False}


@app.post("/api/releases/bootstrap")
def initial_release(body: Candidate, user=Depends(administrator)):
    try:
        result = bootstrap(body.config_id, user["id"])
    except ValueError as error:
        raise HTTPException(409, str(error))
    if not result["passed"]:
        raise HTTPException(409, result)
    return result


@app.post("/api/releases/start")
def start_release(body: Candidate, user=Depends(administrator)):
    from .releases import start

    try:
        result = start(body.config_id, body.mode, user["id"])
    except ValueError as error:
        raise HTTPException(409, str(error))
    if not result["passed"]:
        raise HTTPException(409, result)
    return result


@app.post("/api/releases/{rid}/finish")
def finish_release(rid: str, user=Depends(administrator)):
    try:
        result = finish(rid, user["id"])
    except ValueError as error:
        raise HTTPException(409, str(error))
    if not result["passed"]:
        raise HTTPException(409, result)
    return result


@app.post("/api/releases/{rid}/abort")
def abort_release(rid: str, user=Depends(administrator)):
    try:
        return abort(rid, ["Operator requested rollback"], user["id"])
    except ValueError as error:
        raise HTTPException(404, str(error))


@app.get("/metrics")
def metrics():
    with db() as c:
        rows = c.execute("SELECT payload FROM traces").fetchall()
        count = c.execute(
            "SELECT COUNT(*) FROM rollouts WHERE status='aborted'"
        ).fetchone()[0]
    items = [json.loads(r[0]) for r in rows]
    REFUSALS.set(sum(d["refused"] for d in items))
    BLOCKED.set(sum(d["hostile_chunks"] > 0 for d in items))
    ROLLOUTS.set(count)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
