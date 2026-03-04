FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

# Copy whole repo into /app (repo-root build context)
WORKDIR /app
COPY . /app

# Run agent-detect from its folder (so app.py is found)
WORKDIR /app/apps/agent-detect

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        requests \
        numpy \
        scikit-learn

CMD ["python", "app.py"]