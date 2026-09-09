"""HTTP gateway — the ONE gateway for the demo, decoupled from any SDK.

It drives the workflow by **string names**, so it imports no worker code and
works against whichever worker is running — Python or TypeScript. `web/` owns
the frontend and this API; the SDK folders stay pure Temporal (worker +
workflow + activities).

    cd web && uv run uvicorn gateway:app --port 8000

Each endpoint is one Temporal client call. Stateless — workflow ID =
conversation ID, so any replica can serve any conversation.
"""

import asyncio
import json
import os
import re
import secrets
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel
from temporalio.client import Client, TLSConfig, WorkflowUpdateFailedError
from temporalio.envconfig import ClientConfig
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import RPCError, RPCStatusCode

# Load repo-root .env (shared demoer quick-switch), then local overrides.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
load_dotenv(override=True)

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE") or os.getenv("TASK_QUEUE", "travel-agent")
WORKFLOW_TYPE = os.getenv("WORKFLOW_TYPE", "TravelAgentWorkflow")
DEFAULT_TRAVELLER_EMAIL = os.getenv("DEFAULT_TRAVELLER_EMAIL", "sa@temporal.io")
WEB_DIR = os.getenv("WEB_DIR", str(Path(__file__).resolve().parent))

# Deploy context. "local" (default) → the drawer shows the `make` commands that
# control local infra. "cloud" → the drawer hides them and shows a "Crash
# workers" button that reaches the registry's crashable-workspace controller.
DEMO_HOSTING = os.getenv("DEMO_HOSTING", "local").strip().lower()
# The registry project name (the `demo` key the catalog's crash endpoint keys on)
# and the catalog origin we proxy the crash request to. Both default safely so a
# cloud deploy only has to set DEMO_HOSTING=cloud.
DEMO_NAME = os.getenv("DEMO_NAME", "canonical-ai-demo")
CATALOG_BASE_URL = os.getenv("CATALOG_BASE_URL", "https://catalog.tmprl-demo.cloud").rstrip("/")
# The auth cookie the platform sets on *.tmprl-demo.cloud; the catalog reads the
# signed email claim from it to scope the crash to the caller's own workspace.
AUTH_SESSION_COOKIE = "temporal_demo_auth"


def temporal_ui_base() -> str:
    if explicit := os.getenv("TEMPORAL_UI_BASE"):
        return explicit
    if "tmprl.cloud" in TEMPORAL_ADDRESS:  # <ns>.<acct>.tmprl.cloud:7233
        host = TEMPORAL_ADDRESS.split(":")[0].split(".")
        ns = ".".join(host[:2]) if len(host) >= 2 else TEMPORAL_NAMESPACE
        return f"https://cloud.temporal.io/namespaces/{ns}"
    return f"http://localhost:8233/namespaces/{TEMPORAL_NAMESPACE}"


async def _connect() -> Client:
    # TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE and TEMPORAL_API_KEY or TEMPORAL_TLS_CLIENT_*
    # env vars are loaded directly by envconfig
    config = ClientConfig.load_client_connect_config()
    return await Client.connect(
        **config,
        data_converter=pydantic_data_converter,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.temporal = await _connect()
    yield


app = FastAPI(title="travel-agent gateway", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def no_cache_ui(request: Request, call_next):
    """Force the browser to revalidate the UI assets so an updated index.html /
    app.js is never served stale from cache (a stale app.js can break the page)."""
    resp = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".html") or path.endswith(".js"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


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
    email = request.headers.get("X-Temporal-Auth-Email") or DEFAULT_TRAVELLER_EMAIL
    slug = re.sub(r"[^a-z0-9]+", "-", email.lower()).strip("-")
    conversation_id = f"trip-{slug}-{secrets.token_hex(2)}"
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
    return {"pending": {"action": pending["action"], "title": pending["title"],
                        "detail": pending["detail"], "amount": pending["amount"],
                        "args": pending["args"]}}


@app.post("/conversations/{conversation_id}/approve", status_code=202)
async def approve(conversation_id: str, body: Approve):
    handle = _handle(conversation_id)
    try:
        if await handle.query("pending_approval") is None:
            raise HTTPException(status_code=409, detail="nothing pending")
        await handle.signal("confirm_action", {"approved": body.approved, "reason": body.reason})
    except RPCError as e:
        _not_found(e)
    return {}


# ── research_destination: live fan-out progress ──────────────────────────────
@app.get("/conversations/{conversation_id}/research-status")
async def research_status(conversation_id: str):
    try:
        s = await _handle(conversation_id).query("research_status")
    except RPCError as e:
        _not_found(e)
    return {
        "phase": s["phase"],
        "searchesTotal": s["searches_total"],
        "searchesDone": s["searches_done"],
        "plan": [{"query": p["query"], "reason": p["reason"]} for p in s["plan"]],
    }


@app.get("/conversations/{conversation_id}/itinerary")
async def itinerary(conversation_id: str):
    try:
        items = await _handle(conversation_id).query("itinerary_view")
    except RPCError as e:
        _not_found(e)
    total = round(sum(i["price"] for i in items), 2)
    return {
        "items": [{"itemId": f"{i['kind']}-{i['ref_id']}", "kind": i["kind"],
                   "title": i["title"], "subtitle": i["subtitle"], "price": i["price"]}
                  for i in items],
        "total": total,
    }


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


# ── crash workers (cloud): proxy the Demo-controls button to the catalog ─────
# The crashable-workspace controller lives on the OPERATOR's Temporal, not the
# demo's own namespace — so we don't reach it directly. Instead we forward the
# caller's signed auth cookie to the catalog's existing crash endpoint, which
# verifies identity, checks the demo is crashable, and sends the `crash` Update.
# Server-side proxy → no CORS, no operator creds or JWT signing key in this pod.
def _post_catalog_crash(cookie: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{CATALOG_BASE_URL}/api/crashable-workspace/crash",
        data=json.dumps({"demo": DEMO_NAME}).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Cookie": f"{AUTH_SESSION_COOKIE}={cookie}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read() or b"{}"
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"message": body.decode("utf-8", "replace")}


@app.post("/demo-controls/crash-worker")
async def crash_worker(request: Request):
    if DEMO_HOSTING != "cloud":
        raise HTTPException(status_code=400,
                            detail="Worker crash is only available in cloud-hosted mode.")
    cookie = request.cookies.get(AUTH_SESSION_COOKIE)
    if not cookie:
        raise HTTPException(status_code=401,
                            detail="No auth session — sign in through the demo catalog to crash workers.")
    try:
        status, payload = await asyncio.to_thread(_post_catalog_crash, cookie)
    except (urllib.error.URLError, TimeoutError) as e:
        raise HTTPException(status_code=503,
                            detail=f"Could not reach the crash controller: {e}") from e
    if status >= 400:
        detail = payload.get("message") or payload.get("error") or "crash request failed"
        raise HTTPException(status_code=status, detail=detail)
    # The catalog sends the flat WorkspaceStatus; tolerate the raw update
    # envelope ({"success": {"payloads": [status]}}) too, just in case.
    try:
        payload = payload["success"]["payloads"][0]
    except (KeyError, IndexError, TypeError):
        pass
    # Surface the fields the drawer shows: phase/step (Crashing/Ready) + host.
    return {
        "phase": payload.get("phase"),
        "step": payload.get("step"),
        "host": payload.get("host"),
        "appUrl": payload.get("app_url"),
        "workspaceId": payload.get("workspace_id"),
    }


# ── serve the web UI same-origin (BACKEND_URL="" in the browser) ─────────────
@app.get("/config.js")
async def config_js():
    js = (
        'window.BACKEND_URL = "";\n'
        f'window.TEMPORAL_UI_BASE = "{temporal_ui_base()}";\n'
        f'window.LLM_PROVIDER = "{LLM_PROVIDER}";\n'
        f'window.LLM_MODEL = "{LLM_MODEL}";\n'
        f'window.DEMO_HOSTING = "{DEMO_HOSTING}";\n'
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
