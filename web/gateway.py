"""HTTP gateway — the ONE gateway for the demo, decoupled from any SDK.

It drives the workflow by **string names**, so it imports
no worker code and works against whichever worker is running — Python or
TypeScript. `web/` owns the frontend and this API; the SDK folders stay pure
Temporal (worker + workflow + activities).

    cd web && uv run uvicorn gateway:app --port 8000

Each endpoint is one Temporal client call. Stateless — workflow ID =
conversation ID, so any replica can serve any conversation.
"""

import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from temporalio.client import Client, TLSConfig, WorkflowUpdateFailedError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import RPCError, RPCStatusCode

# ── config (env only; the gateway's own — it doesn't import the SDK folders) ──
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_API_KEY = os.getenv("TEMPORAL_API_KEY")
TEMPORAL_TLS_CERT = os.getenv("TEMPORAL_TLS_CERT")
TEMPORAL_TLS_KEY = os.getenv("TEMPORAL_TLS_KEY")
TASK_QUEUE = os.getenv("TASK_QUEUE", "support-agent")
WORKFLOW_TYPE = os.getenv("WORKFLOW_TYPE", "SupportAgentWorkflow")
DEFAULT_CUSTOMER_EMAIL = os.getenv("DEFAULT_CUSTOMER_EMAIL", "sa@temporal.io")
WEB_DIR = os.getenv("WEB_DIR", str(Path(__file__).resolve().parent))


def temporal_ui_base() -> str:
    if explicit := os.getenv("TEMPORAL_UI_BASE"):
        return explicit
    if "tmprl.cloud" in TEMPORAL_ADDRESS:  # <ns>.<acct>.tmprl.cloud:7233
        host = TEMPORAL_ADDRESS.split(":")[0].split(".")
        ns = ".".join(host[:2]) if len(host) >= 2 else TEMPORAL_NAMESPACE
        return f"https://cloud.temporal.io/namespaces/{ns}"
    return f"http://localhost:8233/namespaces/{TEMPORAL_NAMESPACE}"


async def _connect() -> Client:
    common = {"namespace": TEMPORAL_NAMESPACE, "data_converter": pydantic_data_converter}
    if TEMPORAL_API_KEY:
        return await Client.connect(TEMPORAL_ADDRESS, api_key=TEMPORAL_API_KEY, tls=True, **common)
    if TEMPORAL_TLS_CERT and TEMPORAL_TLS_KEY:
        tls = TLSConfig(
            client_cert=Path(TEMPORAL_TLS_CERT).read_bytes(),
            client_private_key=Path(TEMPORAL_TLS_KEY).read_bytes(),
        )
        return await Client.connect(TEMPORAL_ADDRESS, tls=tls, **common)
    return await Client.connect(TEMPORAL_ADDRESS, **common)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.temporal = await _connect()
    yield


app = FastAPI(title="support-agent gateway", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(HTTPException)
async def error_shape(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


class SendMessage(BaseModel):
    text: str


class Approve(BaseModel):
    approved: bool
    reason: str | None = None


class LLMStatus(BaseModel):
    down: bool


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
LLM_MODEL = (
    os.getenv("OPENAI_MODEL", "gpt-4o") if LLM_PROVIDER == "openai"
    else os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
)


def _handle(conversation_id: str):
    return app.state.temporal.get_workflow_handle(conversation_id)


def _not_found(e: RPCError):
    if e.status == RPCStatusCode.NOT_FOUND:
        raise HTTPException(status_code=404, detail="unknown conversation") from e
    raise e


@app.post("/conversations", status_code=201)
async def create_conversation(request: Request):
    # Identity: the auth gate's verified email (cloud) → local default. The
    # X-Temporal-Auth-Email header is trustworthy (the platform strips any
    # client-supplied copy before the gate).
    email = request.headers.get("X-Temporal-Auth-Email") or DEFAULT_CUSTOMER_EMAIL
    slug = re.sub(r"[^a-z0-9]+", "-", email.lower()).strip("-")
    conversation_id = f"support-{slug}-{secrets.token_hex(2)}"
    await app.state.temporal.start_workflow(
        WORKFLOW_TYPE, email, id=conversation_id, task_queue=TASK_QUEUE
    )
    return {"conversationId": conversation_id}


@app.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, body: SendMessage):
    try:
        result = await _handle(conversation_id).execute_update("send_message", body.text)
    except WorkflowUpdateFailedError as e:
        detail = getattr(e.cause, "message", None) or str(e.cause)
        raise HTTPException(status_code=409, detail=detail) from e
    except RPCError as e:
        _not_found(e)
    return {"status": result["status"], "reply": result["reply"]}


@app.get("/conversations/{conversation_id}/transcript")
async def transcript(conversation_id: str):
    try:
        messages = await _handle(conversation_id).query("transcript")
    except RPCError as e:
        _not_found(e)
    return {"messages": [{"role": m["role"], "content": m["content"]} for m in messages]}


@app.get("/conversations/{conversation_id}/pending-approval")
async def pending_approval(conversation_id: str):
    try:
        pending = await _handle(conversation_id).query("pending_approval")
    except RPCError as e:
        _not_found(e)
    if pending is None:
        return {"pending": None}
    return {"pending": {"trackIds": pending["track_ids"], "description": pending["description"]}}


@app.post("/conversations/{conversation_id}/approve", status_code=202)
async def approve(conversation_id: str, body: Approve):
    handle = _handle(conversation_id)
    try:
        if await handle.query("pending_approval") is None:
            raise HTTPException(status_code=409, detail="nothing pending")
        await handle.signal("approve_purchase", {"approved": body.approved, "reason": body.reason})
    except RPCError as e:
        _not_found(e)
    return {}


# ── LLM "API status" panel: per-conversation kill-switch (scoped to one workflow) ─
@app.get("/conversations/{conversation_id}/llm-status")
async def get_llm_status(conversation_id: str):
    try:
        down = await _handle(conversation_id).query("is_llm_down")
    except RPCError as e:
        _not_found(e)
    return {"down": down}


@app.post("/conversations/{conversation_id}/llm-status")
async def set_llm_status(conversation_id: str, body: LLMStatus):
    try:
        await _handle(conversation_id).signal("set_llm_status", body.down)
    except RPCError as e:
        _not_found(e)
    return {"down": body.down}


# ── serve the web UI same-origin (BACKEND_URL="" in the browser) ─────────────
@app.get("/config.js")
async def config_js():
    js = (
        'window.BACKEND_URL = "";\n'
        f'window.TEMPORAL_UI_BASE = "{temporal_ui_base()}";\n'
        f'window.LLM_PROVIDER = "{LLM_PROVIDER}";\n'
        f'window.LLM_MODEL = "{LLM_MODEL}";\n'
    )
    # no-store: this is generated per-deploy and must never be cached by the
    # browser or the CDN (Cloudflare) — a stale copy re-introduces the static
    # config.js localhost defaults, which break the deployed app as mixed content.
    return Response(
        content=js,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
