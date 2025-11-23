# --------------------------------------------------------
# SmartOps ERP Simulator - Production Dockerfile
# Python + FastAPI + Uvicorn
# --------------------------------------------------------

FROM python:3.11-slim AS base

# Set working directory
WORKDIR /app

# Install system packages (needed for build)
RUN apt-get update && apt-get install -y build-essential

# Copy dependency file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose app port
EXPOSE 8000

# Entrypoint for Uvicorn
CMD ["uvicorn", "app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
