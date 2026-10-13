# Access and release boundaries

The trusted principal comes from an opaque session resolved against the server's user table. Clients cannot submit roles, groups, generation settings, or a configuration override with a query. All source text is untrusted.

## Request path

1. Resolve the bearer session, expiry, and current server-side groups.
2. For an explicit document scope, check access before retrieval. Unknown and restricted identifiers both return `404 Document unavailable`.
3. Run both vector and full-text queries with the same SQL ACL predicate. PostgreSQL/pgvector pools up to 20 authorised chunks and reranks by precomputed sentence similarity; SQLite is a small-corpus local profile.
4. Fuse keyword and semantic ranks and apply top-k/context bounds.
5. Apply the same permission check to retrieved IDs before generation.
6. Treat the document body as data. Exact supporting quotations must be complete permitted source sentences. Suspicious instruction patterns are detected and excluded from selectable evidence; this heuristic is not complete.
7. Recheck document access before returning the answer. A permission change during a provider call prevents delivery of the previously authorised response.
8. Record metadata spans and per-user traces. Shadow execution receives the same principal and document scope. Candidate outputs never replace the live response in shadow mode.

There is no shared answer cache. Only query embeddings are cached, independently of document content; every retrieval still queries the current ACL. Permission revocation is covered by an API regression test.

## Grounding contract

Evidence mode chooses a relevant source sentence. Model API mode asks an OpenAI-compatible endpoint for structured citation/quote claims, then renders only validated quotations. Provider free prose is never shown. This deliberately constrains synthesis to make the grounding boundary inspectable. Citation validation and exact quotations do not prove that the chosen sentence answers every arbitrary question; relevance must be evaluated separately.

The provider adapter can use an API or a vLLM server. The repeatable no-key demo exercises real semantic retrieval and the same output validators, but is not a live-LLM jailbreak benchmark. Contract tests separately inject forged citations, unsupported text, and malicious provider prose.

## Release path

Configurations are immutable hashes of prompt version, model ID, retrieval strategy, candidate pool, top-k, context limit and similarity threshold. Release evaluation records the corpus/ACL fingerprint, evaluation dataset SHA, pinned embedding revision, prompt SHA, and backend code SHA. Any mismatch blocks release until reevaluation.

An administrator explicitly bootstraps a qualified initial champion. Subsequent candidate traffic needs a passing regression report and approval. A shadow review never promotes the candidate. A canary routes 20% of requests deterministically and checks minimum observations, errors, latency, cost and validation failures. Failed checks disable candidate traffic. Full rollout requires another approval and reruns the release gate. These application approvals do not deploy external infrastructure.

## Operational limits

The sample runs one API process. Shared process locks are insufficient for multiple replicas: add distributed locking, transactional deployment state, reconciliation, durable job queues and a real identity provider before enterprise deployment. Background ingestion/evaluation tasks are not durable across process crashes. MLflow, Grafana and object-store consoles are local development interfaces, not production identity boundaries.

Known attack-pattern filtering has evasion risks. No tools or arbitrary URL fetches are available to the assistant. A malicious document can still contain misleading factual statements, and valid citations can cite false source facts. Add reviewed documents, larger adversarial suites, human relevance labels and provider-specific red-team evaluations for a real rollout.

The development MinIO image is pinned for reproducibility. Its community repository is archived; use a supported S3 implementation for real deployment. See the [MinIO repository and release status](https://github.com/minio/minio/releases/tag/RELEASE.2025-04-22T22-12-26Z).

Prometheus rules fire alert states; notifications require an Alertmanager receiver. Configure retention, redaction, tenant isolation, TLS and network policies for a real organisation. This project demonstrates production engineering patterns; its fictional corpus and development authentication do not constitute a production deployment.
