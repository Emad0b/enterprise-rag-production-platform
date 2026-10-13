"""Small HTTP latency and response-quality smoke measurement."""

import json, time, sys, urllib.request
from pathlib import Path
from demo_rollouts import call, ROOT

if __name__ == "__main__":
    _, identity = call("/auth/demo", {"identity": "analyst"})
    token = identity["token"]
    # Warm request separates readiness and network warmup from the timed sample.
    call(
        "/query",
        {"question": "How many days of annual leave do employees receive?"},
        token,
    )
    times = []
    operations = []
    costs = []
    errors = 0
    for i in range(100):
        start = time.perf_counter()
        status, result = call(
            "/query",
            {"question": "How many days of annual leave do employees receive?"},
            token,
            f"benchmark-{i}",
        )
        times.append((time.perf_counter() - start) * 1000)
        if status != 200:
            errors += 1
            continue
        operations.append(result["latency_ms"])
        costs.append(result["estimated_cost"])
    times.sort()
    operations.sort()
    report = {
        "requests": 100,
        "concurrency": 1,
        "errors": errors,
        "p50_http_ms": times[49],
        "p95_http_ms": times[94],
        "p95_operation_ms": operations[int((len(operations) - 1) * 0.95)]
        if operations
        else None,
        "estimated_provider_cost_per_query": sum(costs) / len(costs)
        if costs and all(c is not None for c in costs)
        else None,
        "generation_backend": "extractive",
        "query_embedding_cache": "warm; repeated query",
        "note": "Small sequential local HTTP smoke benchmark; not a capacity guarantee or an LLM benchmark.",
    }
    (ROOT / "reports/http-benchmark.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
