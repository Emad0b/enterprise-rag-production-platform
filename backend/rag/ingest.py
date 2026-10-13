import hashlib, uuid, time, json, re, unicodedata
from .db import db, sql, set_state, state, audit
from .objects import put, get
from .parser import parse_pdf
from .chunker import split_page
from .embeddings import encode, model_id

INJECTION = re.compile(
    r"ignore\s+(all\s+)?(previous|prior|system)|system\s*(prompt|override)|reveal\s+(the\s+)?(secret|password|token)|send\s+.*(secret|token)|bypass\s+.*(permission|access)|you\s+are\s+now|assistant\s*:\s*|<\|?(system|im_start)|override\s+.*rules|exfiltrat|print\s+.*(secret|canary)",
    re.I,
)


def hostile(text):
    return bool(INJECTION.search(unicodedata.normalize("NFKC", text)))


def create_document(title, raw, media_type, groups, actor):
    if not groups or not set(groups) <= {"employees", "leadership"}:
        raise ValueError("Use a non-empty set of known permission groups")
    if len(raw) > 10_000_000:
        raise ValueError("Document exceeds 10 MB")
    if media_type not in ("application/pdf", "text/plain", "text/markdown"):
        raise ValueError("Upload a text-based PDF, TXT or Markdown document")
    did = str(uuid.uuid4())
    key = did + (".pdf" if media_type == "application/pdf" else ".txt")
    put(key, raw, media_type)
    with db() as c:
        sql(
            c,
            "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
            (
                did,
                title[:160],
                key,
                media_type,
                hashlib.sha256(raw).hexdigest(),
                "queued",
                None,
                time.time(),
            ),
        )
        for group in set(groups):
            sql(c, "INSERT INTO acl VALUES (?,?)", (did, group))
        set_state("corpus_epoch", int(state("corpus_epoch")) + 1, c)
        audit(actor, "document_ingested", {"document_id": did, "groups": groups}, c)
    return did


def process_document(did):
    try:
        with db() as c:
            row = sql(
                c, "SELECT object_key,media_type FROM documents WHERE id=?", (did,)
            ).fetchone()
            sql(c, "UPDATE documents SET status='processing' WHERE id=?", (did,))
        raw = get(row[0])
        pages = parse_pdf(raw) if row[1] == "application/pdf" else [raw.decode("utf-8")]
        chunks = [
            (page + 1, pos, text)
            for page, body in enumerate(pages)
            for pos, text in enumerate(split_page(body))
            if text.strip()
        ]
        if not chunks or len(chunks) > 2500:
            raise ValueError("Document has no text or exceeds 2,500 chunks")
        vectors = encode([chunk[2] for chunk in chunks])
        sentence_lists = [
            [
                s.strip()
                for s in re.split(r"(?<=[.!?])\s+|\n+", text)
                if s.strip() and not hostile(s) and len(s.strip()) >= 15
            ]
            for _, _, text in chunks
        ]
        flat = [s for group in sentence_lists for s in group]
        sentence_vectors = iter(encode(flat)) if flat else iter([])
        with db() as c:
            sql(c, "DELETE FROM chunks WHERE document_id=?", (did,))
            for (page, pos, text), vector, sentences in zip(
                chunks, vectors, sentence_lists
            ):
                cid = hashlib.sha256(f"{did}:{page}:{pos}:{text}".encode()).hexdigest()
                sentence_data = [
                    {"text": sentence, "vector": next(sentence_vectors)}
                    for sentence in sentences
                ]
                sql(
                    c,
                    "INSERT INTO chunks(id,document_id,page,position,text,embedding,model,hostile,sentences) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        cid,
                        did,
                        page,
                        pos,
                        text,
                        json.dumps(vector),
                        model_id(),
                        int(hostile(text)),
                        json.dumps(sentence_data),
                    ),
                )
            sql(c, "UPDATE documents SET status='ready',error=NULL WHERE id=?", (did,))
            set_state("corpus_epoch", int(state("corpus_epoch")) + 1, c)
    except Exception as error:
        with db() as c:
            sql(
                c,
                "UPDATE documents SET status='failed',error=? WHERE id=?",
                (type(error).__name__, did),
            )
        raise
