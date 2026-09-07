# Dockerfile — the published Nerva image (ghcr.io/andrei649/nerva).
#
# The same shape docker-compose.quickstart.yml builds inline, extracted so it can
# be published to a registry: `docker run` is the third install path alongside
# `brew install` and `winget install`, and it is the only one that works
# identically on every OS.
#
# The posture is deliberately the same as the native install:
#
#   * it binds 127.0.0.1 and nothing else. The image does NOT publish a port —
#     the compose file uses host networking so `boot_guards.assert_safe_bind` is
#     satisfied without a token. An image that bound 0.0.0.0 by default would put
#     a personal AI on whatever network the container joined, which is exactly
#     the thing the bind guard exists to prevent;
#   * the data root is a volume, never a layer. Personal state baked into an image
#     is personal state pushed to a registry;
#   * dependencies install from the hash-pinned lockfile, so an image built today
#     and one built next year contain the same code;
#   * no cloud key is ever an ARG or an ENV here. They arrive at run time or not
#     at all — a secret in a build argument is a secret in the image history.
#
# Build:  docker build -t nerva .
# Run:    docker run --network host -v nerva_data:/data nerva
FROM python:3.12-slim

# Fail fast and unbuffered: a container whose logs arrive after it dies is a
# container nobody can debug.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JARVIS_HOST=127.0.0.1 \
    JARVIS_PORT=8080 \
    JARVIS_HOME=/data \
    JARVIS_HUD=v2

WORKDIR /app

# The lockfile first, so a source-only change does not reinstall the world.
COPY requirements-beta.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements-beta.lock

COPY . .

# The data root is a volume. Declared here so a `docker run` without -v still
# keeps state out of the writable layer rather than silently losing it on rm.
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=3).status == 200 else 1)"

CMD ["python", "serve.py"]
