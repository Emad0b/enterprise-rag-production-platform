import json, re, os, httpx
from .config import ROOT, LLM_BASE_URL, LLM_API_KEY
from .ingest import hostile
from .chunker import tokens
from .retrieval import STOPWORDS, query_vector
from .embeddings import model_id

PROMPTS = json.loads((ROOT / "configs/prompts.json").read_text(encoding="utf-8"))
REFUSAL = (
    "I cannot establish an answer from the documents you are authorised to access."
)


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def safe_sentences(source):
    return [s for s in sentences(source["text"]) if not hostile(s) and len(s) >= 15]


def candidates(question, sources, semantic=True):
    query = set(tokens(question)) - STOPWORDS
    qv = query_vector(question, model_id()) if semantic else None
    scored = []
    for i, source in enumerate(sources, 1):
        for sentence in safe_sentences(source):
            overlap = len(query & set(tokens(sentence)))
            lexical = overlap / max(1, len(query))
            vector = next(
                (
                    s["vector"]
                    for s in source.get("_sentences", [])
                    if s["text"] == sentence
                ),
                None,
            )
            similarity = sum(a * b for a, b in zip(qv, vector)) if qv and vector else 0
            if overlap >= 2 or (overlap >= 1 and lexical >= 0.45) or similarity >= 0.45:
                scored.append(
                    (
                        0.05 * lexical + 0.95 * similarity if semantic else lexical,
                        i,
                        sentence,
                    )
                )
    return sorted(scored, reverse=True)


def validate_claims(output, sources):
    if not isinstance(output, dict) or not isinstance(
        output.get("insufficient_evidence"), bool
    ):
        return []
    claims = output.get("claims")
    if (
        output["insufficient_evidence"]
        or not isinstance(claims, list)
        or not 1 <= len(claims) <= 5
    ):
        return []
    accepted = []
    for claim in claims:
        if not isinstance(claim, dict):
            return []
        citation = claim.get("citation")
        quote = claim.get("quote")
        if (
            type(citation) != int
            or not 1 <= citation <= len(sources)
            or not isinstance(quote, str)
        ):
            return []
        if quote not in safe_sentences(sources[citation - 1]):
            return []
        # Only validated exact evidence is rendered; model free prose is never displayed.
        accepted.append({"citation": citation, "quote": quote})
    return accepted


def generate(question, sources, config):
    validation_failed = False
    selected = candidates(question, sources, config["retrieval"] != "keyword")
    blocked = any(s["hostile"] for s in sources)
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "token_measurement": "no-provider-call",
        "estimated_cost": 0.0,
        "provider_called": False,
    }
    if not selected:
        return {
            "answer": REFUSAL,
            "refused": True,
            "claims": [],
            "sources": sources,
            "injection_blocked": blocked,
            "mode": config["generation"],
            **usage,
        }
    if config["generation"] == "extractive":
        claims = [{"citation": selected[0][1], "quote": selected[0][2]}]
    else:
        payload = {
            "question": question,
            "evidence": [
                {
                    "citation": i,
                    "title": s["title"],
                    "page": s["page"],
                    "passage": s["text"],
                }
                for i, s in enumerate(sources, 1)
            ],
        }
        messages = [
            {"role": "system", "content": PROMPTS[config["prompt_version"]]},
            {"role": "user", "content": json.dumps(payload)},
        ]
        headers = {"Authorization": "Bearer " + LLM_API_KEY} if LLM_API_KEY else {}
        with httpx.Client(timeout=45) as client:
            response = client.post(
                LLM_BASE_URL + "/chat/completions",
                headers=headers,
                json={
                    "model": config["model"],
                    "messages": messages,
                    "temperature": 0,
                    "max_tokens": 500,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            data = response.json()
        try:
            output = json.loads(data["choices"][0]["message"]["content"])
            claims = validate_claims(output, sources)
            validation_failed = not claims and not (
                isinstance(output, dict) and output.get("insufficient_evidence") is True
            )
        except (ValueError, KeyError, IndexError, TypeError):
            claims = []
            validation_failed = True
        raw = data.get("usage", {})
        inp = raw.get("prompt_tokens")
        out = raw.get("completion_tokens")
        inp = inp if type(inp) == int and inp >= 0 else None
        out = out if type(out) == int and out >= 0 else None
        usage = {
            "input_tokens": inp,
            "output_tokens": out,
            "token_measurement": "provider-reported"
            if inp is not None and out is not None
            else "unavailable",
            "estimated_cost": None,
            "provider_called": True,
        }
        inrate = os.getenv("INPUT_COST_PER_MILLION")
        outrate = os.getenv("OUTPUT_COST_PER_MILLION")
        if inrate and outrate and inp is not None and out is not None:
            usage["estimated_cost"] = (inp * float(inrate) + out * float(outrate)) / 1e6
    if claims:
        # Relevant exact quotations are required even from the configured provider.
        allowed = {(i, quote) for _, i, quote in selected}
        claims = [c for c in claims if (c["citation"], c["quote"]) in allowed]
        if not claims:
            validation_failed = True
    return {
        "answer": "\n\n".join(c["quote"] + f" [{c['citation']}]" for c in claims)
        if claims
        else REFUSAL,
        "refused": not claims,
        "claims": claims,
        "sources": sources,
        "injection_blocked": blocked,
        "mode": config["generation"],
        "validation_failed": validation_failed,
        **usage,
    }
