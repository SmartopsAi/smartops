FROM python:3.11-slim

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (minimal)
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dashboard code
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir \
    flask \
    requests

# Expose dashboard port
EXPOSE 5050

# Start dashboard
CMD ["python", "app.py"]
