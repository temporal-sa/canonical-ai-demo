"""The ONE place that reads environment config. Everything else imports from here."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load repo-root .env (shared demoer quick-switch), then local overrides.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()

TASK_QUEUE = "support-agent"

# Temporal connection — local dev server by default; Temporal Cloud via env.
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_API_KEY = os.getenv("TEMPORAL_API_KEY")
TEMPORAL_TLS_CERT = os.getenv("TEMPORAL_TLS_CERT")
TEMPORAL_TLS_KEY = os.getenv("TEMPORAL_TLS_KEY")

# Database — a full DB_URL (local `docker compose`) OR discrete DB_* parts
# (EKS: the platform injects DB_HOST + a DB_PASSWORD secret, so we compose it —
# a password can't be interpolated into a single URL env var via a secret ref).
def _db_url() -> str:
    if url := os.getenv("DB_URL"):
        return url
    if host := os.getenv("DB_HOST"):
        user = os.getenv("DB_USER", "demo")
        pw = os.getenv("DB_PASSWORD", "demo")
        port = os.getenv("DB_PORT", "5432")
        name = os.getenv("DB_NAME", "music")
        return f"postgresql://{user}:{pw}@{host}:{port}/{name}"
    return "postgresql://demo:demo@localhost:5432/music"


DB_URL = _db_url()

# LLM provider
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# (The HTTP gateway + web UI live in web/ — see web/gateway.py. This folder is
#  worker-only: workflow, activities, and the config they need.)


async def temporal_client():
    """Connect to Temporal — local dev server, Cloud (API key), or Cloud (mTLS)."""
    from temporalio.client import Client, TLSConfig
    from temporalio.contrib.pydantic import pydantic_data_converter

    common = {"namespace": TEMPORAL_NAMESPACE, "data_converter": pydantic_data_converter}

    if TEMPORAL_API_KEY:
        return await Client.connect(
            TEMPORAL_ADDRESS, api_key=TEMPORAL_API_KEY, tls=True, **common
        )
    if TEMPORAL_TLS_CERT and TEMPORAL_TLS_KEY:
        tls = TLSConfig(
            client_cert=Path(TEMPORAL_TLS_CERT).read_bytes(),
            client_private_key=Path(TEMPORAL_TLS_KEY).read_bytes(),
        )
        return await Client.connect(TEMPORAL_ADDRESS, tls=tls, **common)
    return await Client.connect(TEMPORAL_ADDRESS, **common)
