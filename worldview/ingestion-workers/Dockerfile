# WorldView ingestion workers. Build context: worldview/ingestion-workers/
#   docker build -t worldview-ingest .
#   docker run --rm -e KAFKA_BROKERS=redpanda:29092 worldview-ingest tle
# NOTE: not built/validated in this repo's CI (no Docker daemon there) — treat as a template.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worldview_ingest ./worldview_ingest

# Pick the worker at runtime: adsb | ais | tle | ew | context
ENTRYPOINT ["python", "-m", "worldview_ingest"]
CMD ["adsb"]
