# App = the HTTP gateway (web/gateway.py) that also serves the web UI same-origin.
# It drives the workflow by string names, so it carries NO worker code — just a
# Temporal client + a web server. Works against any SDK's worker.
# Build context is the repo root (paths are prefixed with web/).
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app/web

# Dependencies first (cached layer).
COPY web/pyproject.toml web/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Gateway + static UI (index.html / app.js / config.js live alongside gateway.py).
COPY web/ ./
ENV WEB_DIR=/app/web

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8000"]
