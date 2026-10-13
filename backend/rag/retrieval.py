import json, math
from functools import lru_cache
from collections import Counter
from .db import db, sql, PG
from .security import acl_clause, authorized
from .embeddings import encode, model_id
from .chunker import tokens

STOPWORDS = set(
    "a an the what which who where when how why is are was were be to of for on in at and or does do can my our their it as should must about tell me please document policy much many long quickly i each get have".split()
)


@lru_cache(maxsize=256)
def query_vector(question, embedding_model):
    return encode([question])[0]


def fuse(rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, 1):
            scores[cid] = scores.get(cid, 0) + 1 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True), scores


def retrieve(question, user, config, document_ids=None):
    if document_ids:
        authorized(user, document_ids)
    clause, args = acl_clause(user)
    where = "d.status='ready' AND c.model=? AND " + clause
    params = [model_id(), *args]
    if document_ids:
        where += " AND d.id IN (" + ",".join("?" for _ in document_ids) + ")"
        params += list(document_ids)
    select = (
        "SELECT c.id,c.document_id,c.page,c.text,d.title,c.embedding,c.hostile,c.sentences FROM chunks c JOIN documents d ON d.id=c.document_id WHERE "
        + where
    )
    pool = config["candidate_pool"]
    mode = config["retrieval"]
    qv = query_vector(question, model_id()) if mode != "keyword" else None
    keyword_query = " ".join(t for t in tokens(question) if t not in STOPWORDS)
    with db() as c:
        if PG:
            dense_rows = (
                sql(
                    c,
                    select + " ORDER BY c.embedding <=> ?::vector LIMIT ?",
                    (*params, json.dumps(qv), pool),
                ).fetchall()
                if qv
                else []
            )
            keyword_rows = sql(
                c,
                select
                + " AND c.search @@ websearch_to_tsquery('english',?) ORDER BY ts_rank_cd(c.search,websearch_to_tsquery('english',?)) DESC LIMIT ?",
                (*params, keyword_query, keyword_query, pool),
            ).fetchall()
            rows = {r[0]: r for r in [*dense_rows, *keyword_rows]}
            similarities = {
                r[0]: max(
                    [
                        sum(a * b for a, b in zip(qv, json.loads(str(r[5])))),
                        *[
                            sum(a * b for a, b in zip(qv, s["vector"]))
                            for s in json.loads(r[7] or "[]")
                        ],
                    ]
                )
                for r in dense_rows
            }
            dense = sorted(
                [
                    r[0]
                    for r in dense_rows
                    if similarities[r[0]] >= config["minimum_similarity"]
                ],
                key=similarities.get,
                reverse=True,
            )
            lexical = [r[0] for r in keyword_rows]
        else:
            allrows = sql(c, select, params).fetchall()
            rows = {r[0]: r for r in allrows}
            query = set(tokens(question)) - STOPWORDS
            df = Counter(t for r in allrows for t in set(tokens(r[3])))
            avg = sum(len(tokens(r[3])) for r in allrows) / max(1, len(allrows))
            lex = []
            vec = []
            similarities = {}
            for r in allrows:
                words = tokens(r[3])
                counts = Counter(words)
                bm = sum(
                    math.log(1 + (len(allrows) - df[t] + 0.5) / (df[t] + 0.5))
                    * counts[t]
                    * 2.2
                    / (counts[t] + 1.2 * (0.25 + 0.75 * len(words) / max(avg, 1)))
                    for t in query
                    if counts[t]
                )
                if bm > 0:
                    lex.append((bm, r[0]))
                if qv:
                    sim = max(
                        [
                            sum(a * b for a, b in zip(qv, json.loads(r[5]))),
                            *[
                                sum(a * b for a, b in zip(qv, s["vector"]))
                                for s in json.loads(r[7] or "[]")
                            ],
                        ]
                    )
                    similarities[r[0]] = sim
                    if sim >= config["minimum_similarity"]:
                        vec.append((sim, r[0]))
            lexical = [cid for _, cid in sorted(lex, reverse=True)[:pool]]
            dense = [cid for _, cid in sorted(vec, reverse=True)[:pool]]
    ranked, scores = fuse(
        [lexical]
        if mode == "keyword"
        else [dense]
        if mode == "vector"
        else [dense, lexical]
    )
    results = []
    budget = config["max_context_words"]
    for cid in ranked:
        r = rows[cid]
        words = r[3].split()
        if len(words) > budget:
            continue
        results.append(
            {
                "id": cid,
                "document_id": r[1],
                "page": r[2],
                "text": r[3],
                "title": r[4],
                "score": scores[cid],
                "similarity": similarities.get(cid, 0),
                "hostile": bool(r[6]),
                "_sentences": json.loads(r[7]) if r[7] else [],
            }
        )
        budget -= len(words)
        if len(results) >= config["top_k"]:
            break
    # Re-check permissions after retrieval, including the shadow/canary path.
    authorized(user, [r["document_id"] for r in results])
    return results
