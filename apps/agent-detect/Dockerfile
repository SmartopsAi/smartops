FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        requests \
        numpy \
        scikit-learn

CMD ["python", "apps/agent-detect/app.py"]
