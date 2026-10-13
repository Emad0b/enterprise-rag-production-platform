import hashlib, json, time, uuid, logging
import mlflow
from prometheus_client import Counter, Histogram
from .config import TRACKING_URI, RUNTIME
from .db import db, sql
from .security import authorized
from .retrieval import retrieve
from .generation import generate

QUERIES = Counter("rag_queries_total", "RAG requests", ["config", "kind", "result"])
LATENCY = Histogram(
    "rag_query_seconds",
    "End-to-end RAG operation",
    ["config", "kind"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1, 2, 5, 15, 45),
)
TOKENS = Counter(
    "rag_tokens_total", "Provider reported tokens", ["config", "direction"]
)
COST = Counter(
    "rag_estimated_cost_dollars_total", "Configured provider cost estimate", ["config"]
)
logger = logging.getLogger("rag.requests")


def configure_tracking():
    mlflow.set_tracking_uri(TRACKING_URI)
    client = mlflow.MlflowClient()
    name = "Enterprise RAG · Evaluated Releases"
    if client.get_experiment_by_name(name) is None:
        client.create_experiment(
            name, artifact_location=(RUNTIME / "mlflow-artifacts").as_uri()
        )
    mlflow.set_experiment("Enterprise RAG · Evaluated Releases")


def run(question, user, config, document_ids=None, kind="live", request_id=None):
    start = time.perf_counter()
    tid = str(uuid.uuid4())
    sources = []
    result = None
    error = None
    try:
        with mlflow.start_span(name="rag.request", span_type="CHAIN") as root:
            root.set_inputs(
                {
                    "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                    "principal_sha256": hashlib.sha256(user["id"].encode()).hexdigest(),
                    "config_id": config["id"],
                    "kind": kind,
                }
            )
            root.set_attributes(
                {
                    "prompt_version": config["prompt_version"],
                    "model": config["model"],
                    "request_id": request_id or tid,
                }
            )
            with mlflow.start_span(
                name="authorized.hybrid.retrieval", span_type="RETRIEVER"
            ) as span:
                sources = retrieve(question, user, config, document_ids)
                span.set_outputs(
                    {
                        "chunk_ids": [s["id"] for s in sources],
                        "count": len(sources),
                        "hostile_chunks": sum(s["hostile"] for s in sources),
                    }
                )
            with mlflow.start_span(
                name="grounded.generation",
                span_type="LLM" if config["generation"] != "extractive" else "PARSER",
            ) as span:
                result = generate(question, sources, config)
                span.set_outputs(
                    {
                        "refused": result["refused"],
                        "claim_count": len(result["claims"]),
                        "provider_called": result["provider_called"],
                    }
                )
                span.set_attributes(
                    {
                        "input_tokens": result["input_tokens"] or 0,
                        "output_tokens": result["output_tokens"] or 0,
                        "estimated_cost": result["estimated_cost"]
                        if result["estimated_cost"] is not None
                        else -1,
                    }
                )
            authorized(user, [s["document_id"] for s in sources])
            root.set_outputs(
                {
                    "refused": result["refused"],
                    "injection_blocked": result["injection_blocked"],
                    "sources": len(sources),
                }
            )
            mlflow_id = root.trace_id
    except Exception as exc:
        error = exc
        mlflow_id = None
    latency = (time.perf_counter() - start) * 1000
    summary = {
        "request_id": request_id or tid,
        "mlflow_trace_id": mlflow_id,
        "latency_ms": latency,
        "retrieval": config["retrieval"],
        "prompt_version": config["prompt_version"],
        "model": config["model"],
        "source_ids": [s["document_id"] for s in sources],
        "source_count": len(sources),
        "hostile_chunks": sum(s["hostile"] for s in sources),
        "error": bool(error),
        "error_type": type(error).__name__ if error else None,
        "refused": result["refused"] if result else True,
        "input_tokens": result["input_tokens"] if result else 0,
        "output_tokens": result["output_tokens"] if result else 0,
        "estimated_cost": result["estimated_cost"] if result else None,
        "citation_valid": not result.get("validation_failed", False)
        if result is not None
        else None,
        "authorization_violation": bool(
            error and getattr(error, "status_code", None) == 404
        ),
    }
    with db() as c:
        sql(
            c,
            "INSERT INTO traces VALUES (?,?,?,?,?,?)",
            (tid, user["id"], config["id"], kind, json.dumps(summary), time.time()),
        )
    QUERIES.labels(
        config=config["id"],
        kind=kind,
        result="error" if error else "refused" if result["refused"] else "answered",
    ).inc()
    LATENCY.labels(config=config["id"], kind=kind).observe(latency / 1000)
    if result:
        for direction in ("input", "output"):
            if result[direction + "_tokens"] is not None:
                TOKENS.labels(config=config["id"], direction=direction).inc(
                    result[direction + "_tokens"]
                )
        if result["estimated_cost"] is not None:
            COST.labels(config=config["id"]).inc(result["estimated_cost"])
    logger.info(
        "rag request=%s principal=%s config=%s kind=%s latency_ms=%.3f error=%s",
        request_id or tid,
        user["id"],
        config["id"],
        kind,
        latency,
        bool(error),
    )
    if error:
        raise error
    result["sources"] = [
        {k: v for k, v in s.items() if not k.startswith("_")} for s in result["sources"]
    ]
    return {
        **result,
        "trace_id": tid,
        "latency_ms": round(latency, 3),
        "config_id": config["id"],
        "prompt_version": config["prompt_version"],
        "model": config["model"],
    }
