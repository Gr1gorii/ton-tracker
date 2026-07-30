FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN addgroup --system tontracker && adduser --system --ingroup tontracker tontracker

WORKDIR /app/backend
COPY backend/requirements.runtime.txt backend/requirements.runtime.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.runtime.lock

COPY backend/ /app/backend/
COPY ops/ /app/ops/
RUN mkdir -p /data /backups && chown -R tontracker:tontracker /app /data /backups

USER tontracker
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=3)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
