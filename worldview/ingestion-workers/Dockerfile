# WorldView ingestion workers. Build context: worldview/ingestion-workers/
#   docker build -t worldview-ingest .
#   docker run --rm -e KAFKA_BROKERS=redpanda:29092 worldview-ingest tle
# NOTE: not built/validated in this repo's CI (no Docker daemon there) — treat as a template.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Dedicated unprivileged user (uid 10001, AUD-4/F14): workers need only read
# access to the package plus network sockets — no root, no privileged ports.
RUN useradd --uid 10001 --user-group --create-home --shell /usr/sbin/nologin appuser
COPY --chown=10001:10001 worldview_ingest ./worldview_ingest
USER 10001:10001

# No HEALTHCHECK: these are long-running Kafka consumers with no HTTP surface
# (grep of worldview_ingest found no fastapi/flask/aiohttp/http.server), so any
# probe would invent an endpoint. Observe liveness via consumer-lag metrics.
# Pick the worker at runtime: adsb | ais | tle | ew | context
ENTRYPOINT ["python", "-m", "worldview_ingest"]
CMD ["adsb"]
