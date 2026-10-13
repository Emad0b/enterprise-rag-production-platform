"""Register and evaluate an explicitly configured model API without deployment."""

import sys, os, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from rag.config import LLM_MODEL
from rag.pipeline import configure_tracking
from rag.releases import register, release_gate
from rag.evaluation import evaluate

if __name__ == "__main__":
    configure_tracking()
    config = register(
        {
            "name": "Configured provider · " + LLM_MODEL,
            "retrieval": "hybrid",
            "generation": "openai-compatible",
            "model": LLM_MODEL,
            "prompt_version": "grounded-v2",
            "top_k": 4,
            "candidate_pool": 20,
            "max_context_words": 1200,
            "minimum_similarity": 0.35,
        },
        "explicit-local-provider-evaluation",
    )
    report = evaluate(config["id"])
    (ROOT / "reports/provider-evaluation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "configuration": config["id"],
                "metrics": report["metrics"],
                "gate": release_gate(config["id"]),
                "auto_deployed": False,
            },
            indent=2,
        )
    )
