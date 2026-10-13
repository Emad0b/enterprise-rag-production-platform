import os, json
from pathlib import Path

ROOT = Path(os.getenv("RAG_ROOT", str(Path(__file__).resolve().parents[2]))).resolve()
RUNTIME = Path(os.getenv("RAG_HOME", str(ROOT / "runtime"))).resolve()
RUNTIME.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", "")
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "sentence-transformers")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_REVISION = os.getenv(
    "EMBEDDING_REVISION", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
)
DIMENSIONS = 384
CHUNK_SIZE, CHUNK_OVERLAP = 160, 30
DEMO_MODE = os.getenv("RAG_DEMO_MODE", "false").lower() == "true"
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8001/v1").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "configured-model")
TRACKING_URI = os.getenv(
    "MLFLOW_TRACKING_URI", "sqlite:///" + str(RUNTIME / "mlflow.db").replace("\\", "/")
)
POLICY = json.loads((ROOT / "configs/release-policy.json").read_text())
