# Aperture — Enterprise RAG, Evaluated and Permission-Aware

[![CI](https://github.com/Emad0b/enterprise-rag-production-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Emad0b/enterprise-rag-production-platform/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB)
![React](https://img.shields.io/badge/React-TypeScript-3178C6)
![License](https://img.shields.io/badge/License-MIT-green)

An organisation's document assistant with an inspectable trust boundary: **permission-filtered retrieval, grounded answers, repeatable security and quality evaluations, and approved configuration rollouts**. New retrieval and prompt configurations must pass quality, latency and cost gates before receiving traffic.

**FastAPI · PostgreSQL/pgvector · S3 object storage · Sentence Transformers · OpenAI-compatible API / vLLM · MLflow · Prometheus · Grafana · Docker · GitHub Actions**

![Aperture knowledge workspace](docs/workspace.png)

**[Watch the recorded three-scenario security demo](docs/security-demo.webm)** · [Grounded answer](docs/grounded-answer.png) · [Restricted refusal](docs/restricted-refusal.png) · [Hostile retrieved document](docs/hostile-document.png)

## What the video demonstrates

1. An employee asks about annual leave and receives the correct **24-day** answer, with an exact supporting quotation and citation.
2. The same employee asks for a restricted acquisition budget. The assistant refuses; leadership documents never enter that employee's retrieved context. Separate API tests and the HTTP rollout demo verify that explicitly requesting a restricted document ID returns **404**, just like an unavailable ID.
3. A retrieved vendor note contains an instruction to ignore the assistant's rules, reveal a marker, and bypass permissions. The answer remains the documented **45-minute reporting deadline**; the malicious instruction is isolated and never rendered as an answer.

The recording uses **real semantic retrieval over fictional documents**, in explicitly labeled **evidence mode**: validated source quotations rather than a paid LLM response. It demonstrates application permission and output boundaries, not universal live-LLM jailbreak resistance. The provider adapter and malicious-provider output contract are tested separately. See [demo notes](docs/demo-notes.md).

![Hostile instructions isolated from the factual answer](docs/hostile-document.png)

## What is implemented

- PDF, text and Markdown ingestion; overlapping chunks; pinned 384-dimensional semantic embeddings; precomputed safe sentence embeddings.
- PostgreSQL/pgvector cosine search and full-text search, followed by reciprocal rank fusion and sentence-level evidence ranking. A lightweight SQLite profile supports local development.
- Private S3-compatible object storage in Docker, with document downloads served through the authenticated, permission-checked API.
- Server-resolved opaque sessions and document ACLs for `employees` and `leadership`. Clients cannot submit roles or override the query's RAG configuration.
- Permission checks before SQL retrieval, before generation, and before returning the answer. Revocation tests verify that prior answers are not reused after access changes.
- A repeatable **42-case** dataset covering direct questions, semantic paraphrases, citation sources, authorized leadership access, restricted access, missing evidence, and prompt injection.
- Faithfulness, supporting-document recall, citation correctness, answer relevance, refusal accuracy, and prohibited-output checks.
- MLflow parent/child traces for retrieval and generation; provider-reported tokens and configured cost estimates; per-user metadata trace inspection; Prometheus metrics and a provisioned Grafana dashboard.
- Immutable configurations with model/prompt versioning. Regression reports are tied to corpus/ACL, code, evaluation dataset, embedding revision and prompt fingerprints.
- Approved shadow traffic and deterministic 20% canary routing. Shadow traffic receives the same identity and ACL; shadow completion leaves the champion unchanged. Canary failures disable candidate traffic; full promotion requires another approval.

## Measured results

On the self-authored fictional corpus:

- **Keyword baseline:** 37/42 cases passed; supporting-document Recall@2 **94.4%**. It is blocked by strict citation and refusal gates.
- **Semantic hybrid:** 42/42 cases passed; supporting-document Recall@4 **100%**. The committed run measured warm application p95 **52.6 ms**.
- **Compact hybrid challenger:** 42/42 passed; Recall@3 **100%**, warm application p95 **19.7 ms**. The smaller context retained the measured quality. It was evaluated after query-embedding cache warming, so these timings do not isolate the effect of context size.
- **Actual HTTP shadow run:** 25 candidate observations; p95 **42.4 ms**; zero errors. The champion remained unchanged.
- **Actual HTTP canary:** 25 candidate observations among 125 incoming requests; p95 **31.4 ms**; zero errors. Full rollout was explicitly approved.
- **Local HTTP smoke benchmark:** 100/100 successful sequential requests, p95 **54.2 ms**, warm repeated-query embedding cache, no provider call.

The engineering budgets are **750 ms application p95** and **$0.002 estimated provider cost per query**. Retrieval quality improved within these limits. The semantic path is slower than the keyword-only baseline; the compact challenger preserves the measured quality with less context. The two hybrid timings have different query-cache profiles; they are recorded observations, not a controlled claim that context reduction alone caused the speedup. No paid-model quality or cost result is claimed.

Raw evidence: [evaluations](reports/evaluation-results.json), [real HTTP rollouts and restricted-ID denial](reports/rollout-results.json), [HTTP benchmark](reports/http-benchmark.json). Recorded identifiers and timings describe one run; fresh runs produce new traces and platform-dependent timings.

## Evaluation methodology

Every case contains a question, expected answer, supporting document titles, expected terms, permitted identity, expected refusal, and optional prohibited strings.

- **Retrieval recall:** fraction of labeled supporting documents in the top-k context; this is document recall, not chunk recall.
- **Faithfulness:** every rendered claim is a complete, permitted, exact source sentence. Unexpected refusals count as failures for answerable cases.
- **Citation correctness:** rendered claims cite the labeled supporting document, rather than merely a syntactically valid citation number.
- **Answer relevance:** expected-term coverage against the labeled answer. This is a deterministic task-specific proxy; it does not measure general semantic relevance or penalize every kind of verbosity.
- **Refusal accuracy:** observed refusal matches the labeled decision.
- **Security tests:** no prohibited marker or restricted fact appears in the answer; SQL filtering, direct-ID access, permission revocation and trace isolation have separate API tests.

The demonstration does not use an LLM judge. Model API mode renders only validated quotations and ignores provider free prose, deliberately constraining synthesis. These strong structural checks still cannot prove that every chosen quotation answers an arbitrary question. The corpus is small and fictional; 100% on these cases is not a universal security or quality guarantee.

The embedding model is pinned to [`all-MiniLM-L6-v2` revision `1110a243`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41). Ingestion precomputes sentence vectors so query-time evidence selection needs no second model inference per sentence. Only query embeddings are cached; there is no shared answer cache. The API warms the embedding model before readiness.

## Architecture

```mermaid
flowchart LR
    I[PDF / TXT / Markdown] --> S[Private S3 objects]
    I --> C[Parse + chunk + embed sentences]
    C --> DB[PostgreSQL / pgvector + full-text]
    U[Trusted server-side principal] --> ACL[SQL document ACL filter]
    Q[Question] --> ACL
    ACL --> DB
    DB --> R[Hybrid fusion + bounded context]
    R --> G[Evidence mode or model API / vLLM]
    G --> V[Exact quote + citation + access validation]
    V --> A[Answer or refusal]
    R --> T[MLflow retrieval / generation traces]
    G --> T
    T --> M[Prometheus + Grafana]
    E[42 labeled regression cases] --> RG[Quality / security / p95 / cost gates]
    RG --> AP[Explicit release approval]
    AP --> SH[Shadow or 20% canary]
    SH --> ACL
    SH --> RB[Fail: disable candidate traffic]
    SH --> FA[Pass + full rollout approval]
```

Read [architecture and trust boundaries](docs/architecture.md) for the security model, release-state behavior, and operational tradeoffs.

## Docker quickstart

Requires Docker Compose and Python for creating development secrets.

```bash
python scripts/init_env.py
docker compose up --build -d
# Wait for /api/health; the first run downloads the pinned embedding model.
docker compose exec -T api python scripts/bootstrap.py
python scripts/demo_rollouts.py
```

Open **http://localhost:5177**. The fictional identities are Analyst, Leadership and Admin; identity switching is enabled only by the explicit `RAG_DEMO_MODE=true` development setting. The analyst sees ten documents; leadership can additionally access the board memo. Admin can inspect the full evaluation dataset and approve releases.

Other interfaces:

- API/OpenAPI: **http://localhost:8300/docs**
- MLflow: **http://localhost:5002**
- Grafana: **http://localhost:3002** — provisioned **Aperture · RAG Operations** dashboard
- Prometheus: **http://localhost:9092**
- Development object store console: **http://localhost:9102**

All published ports bind to localhost. PostgreSQL, object storage and application artifacts persist in separate Docker volumes. `.env`, credentials, uploaded objects and runtime state are excluded from Git. The pinned RustFS 1.0.1 service supplies the development S3-compatible backend. For actual deployment, configure your supported object-storage service and operational controls; see [the architecture notes](docs/architecture.md).

## Local development

Create and activate a Python 3.12 virtual environment, then:

```bash
pip install -r backend/requirements.txt
python scripts/bootstrap.py
```

Set `PYTHONPATH=backend` and `RAG_DEMO_MODE=true`, then run:

```bash
uvicorn rag.main:app --host 127.0.0.1 --port 8300
```

PowerShell setup:

```powershell
$env:PYTHONPATH = 'backend'
$env:RAG_DEMO_MODE = 'true'
uvicorn rag.main:app --host 127.0.0.1 --port 8300
```

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

The local profile uses SQLite and filesystem objects. Semantic embeddings remain the default. `EMBEDDING_BACKEND=lexical` is an explicitly different lightweight test profile, not semantic AI. Run all commands from the repository root unless a different directory is stated. For local MLflow, use `mlflow server --backend-store-uri sqlite:///runtime/mlflow.db --host 127.0.0.1 --port 5002 --workers 1`.

## Configure a model API or vLLM

Set the service's `LLM_BASE_URL`, `LLM_MODEL` and, if required, `LLM_API_KEY`. A vLLM OpenAI-compatible server normally uses a base URL such as `http://localhost:8001/v1`; Docker can reach a host server through `http://host.docker.internal:8001/v1`.

Set `INPUT_COST_PER_MILLION` and `OUTPUT_COST_PER_MILLION` to the rates you intend to estimate. They are **not fetched or guessed**. Token counts are provider-reported; missing usage or rates produce an unknown cost, which blocks release. Use a deployment-specific model version rather than a mutable alias where your provider supports it.

Run an explicit provider evaluation after bootstrapping:

```bash
python scripts/evaluate_provider.py
```

In Docker, run that command inside the API service after configuring and recreating its environment. It registers a separate immutable provider configuration and writes `reports/provider-evaluation.json`. It **does not deploy** the candidate. Evaluate the model-specific quality, latency, cost and hostile-document behavior before approving shadow or canary traffic.

The adapter uses `chat/completions` with a JSON response format and requests citation/quote claims. It never gives the model tools, document-permission controls or arbitrary URL-fetch capabilities. Validated source quotations are the only claims displayed.

## Release policy

[configs/release-policy.json](configs/release-policy.json) defines minimum retrieval/relevance, exact-quotation/citation/refusal gates, zero prohibited-output failures, latency and cost budgets, and a 25% maximum p95 regression against the evaluated champion.

Release reports become invalid if document content/ACLs, evaluation cases, backend code, embedding revision or the prompt change. They expire after one day. Missing cost estimates block release.

1. An admin evaluates and explicitly approves the initial configuration.
2. A candidate must pass regression gates before shadow or canary traffic.
3. Shadow requests run after the live response with the same principal and scope; outputs are not shown to the caller.
4. The canary receives 20% of requests, selected using a deterministic hash of `X-Request-Id`.
5. At least 20 candidate observations are required. Error, latency, cost and validation failures disable the candidate. The champion remains available.
6. Successful full rollout requires another admin approval and fresh static-gate checks. Shadow completion alone never deploys a candidate.

The application stores a previous champion for lineage. Rollback while a canary is active disables its traffic; the sample does not implement an automatic post-promotion quality rollback based on delayed human feedback.

## Verify and reproduce

```bash
python -m pytest -q backend/tests
python scripts/demo_rollouts.py
python scripts/benchmark.py
cd frontend
npm run build
npx playwright install chromium
npm run test:e2e
node scripts/record-demo.mjs
```

Browser, video, rollout and benchmark commands require the running bootstrapped API/dashboard in demo mode. The rollout script expects the original champion and an unused compact challenger; rerun against fresh runtime state for the exact recorded sequence. Benchmark results explicitly distinguish HTTP from application operation latency and state the warm repeated-query cache profile.

GitHub Actions runs security/API tests against SQLite and PostgreSQL/pgvector, semantic fixture evaluations, browser/mobile workflows, the real HTTP shadow/canary sequence, and a full Docker stack with S3 ingestion and object access. Test reports do not silently substitute mocked model output for measured semantic retrieval.

## Scope

This portfolio project demonstrates production engineering patterns with a fictional single-organisation corpus. Real deployment requires a real identity provider, tenant isolation, distributed release locking, durable ingestion/evaluation workers, rate limits, authenticated monitoring, TLS, retention policies and provider-specific red-team testing. Pattern-based injection detection is incomplete; false source facts can remain false even when quoted correctly.

Built on parsing and embedding components from [DocuMind](https://github.com/Emad0b/documind), with a new permission model, evaluation/release system, observability stack and interface.

## License

[MIT](LICENSE). The fictional documents and evaluation labels are self-authored. Embedding model and dependency licenses remain with their respective authors.
