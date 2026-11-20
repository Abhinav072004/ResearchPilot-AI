FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN --mount=type=secret,id=researchpilot_build_ca \
    if [ -s /run/secrets/researchpilot_build_ca ]; then export PIP_CERT=/run/secrets/researchpilot_build_ca; fi \
    && pip install --no-cache-dir -r requirements.txt \
    && useradd --system --uid 10001 app
COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 agents ./agents
COPY --chown=10001:10001 rag ./rag
COPY --chown=10001:10001 ingestion ./ingestion
COPY --chown=10001:10001 connectors ./connectors
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 alembic.ini .
RUN mkdir -p /app/data && chown 10001:10001 /app/data
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD ["python","-c","import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready', timeout=2).close()"]
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--forwarded-allow-ips","*","--no-access-log"]
