import hashlib, math, threading
from collections import Counter
from .config import EMBEDDING_BACKEND, EMBEDDING_MODEL, EMBEDDING_REVISION, DIMENSIONS
from .chunker import tokens

_model = None
_lock = threading.Lock()


def model_id():
    return (
        EMBEDDING_MODEL + "@" + EMBEDDING_REVISION
        if EMBEDDING_BACKEND == "sentence-transformers"
        else "lexical-hash-v2"
    )


def encode(texts):
    global _model
    if EMBEDDING_BACKEND == "sentence-transformers":
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(
                    EMBEDDING_MODEL, revision=EMBEDDING_REVISION
                )
                if _model.get_sentence_embedding_dimension() != DIMENSIONS:
                    raise ValueError("Model must output 384 dimensions")
            return _model.encode(texts, normalize_embeddings=True).tolist()
    if EMBEDDING_BACKEND != "lexical":
        raise ValueError("Unsupported embedding backend")
    results = []
    for text in texts:
        values = [0.0] * DIMENSIONS
        for token, count in Counter(tokens(text)).items():
            h = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16)
            values[h % DIMENSIONS] += count * (1 if h & 512 else -1)
        norm = math.sqrt(sum(v * v for v in values)) or 1
        results.append([v / norm for v in values])
    return results
