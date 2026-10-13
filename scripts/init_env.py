import secrets
from pathlib import Path

path = Path(".env")
if path.exists():
    raise SystemExit(".env exists; existing settings preserved.")
settings = {
    "RAG_DEMO_MODE": "true",
    "S3_ACCESS_KEY": "aperture-local",
    **{
        k: secrets.token_urlsafe(32)
        for k in ("POSTGRES_PASSWORD", "S3_SECRET_KEY", "GRAFANA_ADMIN_PASSWORD")
    },
}
path.write_text(
    "\n".join(f"{k}={v}" for k, v in settings.items()) + "\n", encoding="utf-8"
)
print("Development settings saved to .env; secrets are not printed.")
