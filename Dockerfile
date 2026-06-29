FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt .
RUN pip install -r requirements.txt

# App code.
COPY app/ app/
COPY templates/ templates/
COPY static/ static/
COPY run.py .

# State (sqlite db) lives here; mount a volume so it survives restarts.
RUN mkdir -p /app/data
ENV PGDUTY_DATABASE_URL=sqlite:////app/data/pgduty.db \
    PGDUTY_CONFIG=/app/config.yaml \
    PGDUTY_HOST=0.0.0.0 \
    PGDUTY_PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/healthz').status==200 else 1)"

CMD ["python", "run.py"]
