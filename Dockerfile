# Single-origin image: React build served by FastAPI on one port.
FROM node:20-alpine AS web
WORKDIR /app/services/web
COPY services/web/package.json services/web/package-lock.json ./
RUN npm ci
COPY services/web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/services
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY services/ ./services/
COPY --from=web /app/services/web/dist ./services/web/dist
RUN mkdir -p services/data
EXPOSE 8000
# Real model: set DEEPSEEK_API_KEY or OPENAI_API_KEY at run time.
CMD ["python", "-m", "uvicorn", "agent_runtime.main:app", "--host", "0.0.0.0", "--port", "8000"]
