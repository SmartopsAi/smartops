FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/SmartopsAi/smartops"
LABEL org.opencontainers.image.description="SmartOps Orchestrator"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY apps/orchestrator/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps ./apps

ENV PYTHONPATH=/app

EXPOSE 8001

CMD ["uvicorn", "apps.orchestrator.app:app", "--host", "0.0.0.0", "--port", "8001"]
