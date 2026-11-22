# Single-origin image: the React build is served by FastAPI on one port,
# and the accounting ledger lives in PostgreSQL (DATABASE_URL at run time).

# Tailwind 4 ships a native engine that declares Node >= 20, so the build stage
# uses 20 even though the app itself has no Node runtime dependency.
FROM node:20-alpine AS web
WORKDIR /app/services/web
COPY services/web/package.json services/web/package-lock.json ./
RUN npm ci
COPY services/web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/services \
    FLARE_WEB_DIST=/app/static
WORKDIR /app

# Build tools for wheels that lack a binary distribution (psycopg falls back
# to source only if the binary extra is unavailable).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY services/ ./services/
COPY --from=web /app/services/web/dist ./static/

# The knowledge base and session stores write here; mount a volume to keep
# them across restarts. Accounting data itself lives in PostgreSQL.
RUN mkdir -p /app/services/data \
    && useradd --create-home --uid 10001 app \
    && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["python", "-m", "uvicorn", "agent_runtime.main:app", "--host", "0.0.0.0", "--port", "8000"]
