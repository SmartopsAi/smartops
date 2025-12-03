# --------------------------------------------------------
# SmartOps ERP Simulator - Production Dockerfile
# Python + FastAPI + Uvicorn
# --------------------------------------------------------

FROM python:3.11-slim AS base

# OCI labels → required to auto-link package to SmartopsAi/smartops repo
LABEL org.opencontainers.image.source="https://github.com/SmartopsAi/smartops"
LABEL org.opencontainers.image.description="SmartOps ERP Simulator"
LABEL org.opencontainers.image.licenses="MIT"

# Set working directory
WORKDIR /app

# Install system packages (needed for building wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Gunicorn/Uvicorn entrypoint
CMD ["uvicorn", "app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
