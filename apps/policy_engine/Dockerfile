FROM python:3.11-slim

# -----------------------------
# System setup
# -----------------------------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# -----------------------------
# Install Python dependencies
# -----------------------------
COPY apps/policy_engine/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

# -----------------------------
# Copy Policy Engine source
# -----------------------------
COPY apps /app/apps

# -----------------------------
# Runtime configuration
# -----------------------------
ENV PYTHONPATH=/app
ENV POLICY_ENGINE_PORT=8002

EXPOSE 8002

# -----------------------------
# Start Policy Engine
# -----------------------------
CMD ["uvicorn", "apps.policy_engine.app:app", "--host", "0.0.0.0", "--port", "8002"]
