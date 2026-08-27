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
COPY --from=build /app/frontend/dist /usr/share/nginx/html
# Single-page app: every path serves index.html; hashed assets get a long cache.
RUN printf 'server {\n\
  listen 3000;\n\
  root /usr/share/nginx/html;\n\
  location /assets/ { expires 1y; add_header Cache-Control "public, immutable"; }\n\
  location /cesium/ { expires 1y; add_header Cache-Control "public, immutable"; }\n\
  location / { try_files $uri $uri/ /index.html; }\n\
}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 3000
