# WorldView dashboard — Vite static build served by nginx.
# Build context: worldview/ (workspace lockfile)
#   docker build -f frontend/Dockerfile -t worldview-frontend .
# Provide VITE_* at build time (Vite inlines them into the bundle).
# NOTE: not built/validated in this repo's CI (no Docker daemon there) — treat as a template.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package.json
COPY backend-api/package.json backend-api/package.json
RUN npm ci
COPY frontend ./frontend
ARG VITE_API_URL
ARG VITE_WS_URL
ARG VITE_CESIUM_ION_TOKEN
ARG VITE_TILE_URL
ENV VITE_API_URL=$VITE_API_URL \
    VITE_WS_URL=$VITE_WS_URL \
    VITE_CESIUM_ION_TOKEN=$VITE_CESIUM_ION_TOKEN \
    VITE_TILE_URL=$VITE_TILE_URL
# The build also mirrors Cesium's runtime assets (Workers + Assets, incl. the bundled Natural
# Earth II basemap) into the output, so the image needs no CDN and no Cesium account.
RUN npm run build --workspace frontend

FROM nginx:1.27-alpine
COPY --from=build --chown=nginx:nginx /app/frontend/dist /usr/share/nginx/html
# Single-page app: every path serves index.html; hashed assets get a long cache.
RUN printf 'pid /tmp/nginx.pid;\n\
events {}\n\
http {\n\
  include /etc/nginx/mime.types;\n\
  client_body_temp_path /tmp/client_body;\n\
  proxy_temp_path /tmp/proxy;\n\
  fastcgi_temp_path /tmp/fastcgi;\n\
  uwsgi_temp_path /tmp/uwsgi;\n\
  scgi_temp_path /tmp/scgi;\n\
  access_log /dev/stdout;\n\
  error_log /dev/stderr;\n\
  server {\n\
    listen 3000;\n\
    root /usr/share/nginx/html;\n\
    location /assets/ { expires 1y; add_header Cache-Control "public, immutable"; }\n\
    location /cesium/ { expires 1y; add_header Cache-Control "public, immutable"; }\n\
    location / { try_files $uri $uri/ /index.html; }\n\
  }\n\
}\n' > /etc/nginx/nginx.conf \
 && rm -f /etc/nginx/conf.d/default.conf \
 && chown -R nginx:nginx /var/cache/nginx
EXPOSE 3000
# AUD-4/F14: run as the image's built-in unprivileged `nginx` user. Port 3000 is
# already non-privileged; the master pid and all temp paths are relocated to
# /tmp so no root-owned path is written at runtime.
USER nginx
# Static bundle, no app-level health route to probe: the SPA answers `/` from
# disk, so that is the liveness signal.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD wget --spider -q http://127.0.0.1:3000/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
