import re
from .config import CHUNK_SIZE, CHUNK_OVERLAP


def tokens(text):
    return re.findall(r"\b\w+\b", text.lower())


def split_page(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    if not 0 <= overlap < size:
        raise ValueError("Invalid chunk overlap")
    words = text.split()
    return [" ".join(words[i : i + size]) for i in range(0, len(words), size - overlap)]
