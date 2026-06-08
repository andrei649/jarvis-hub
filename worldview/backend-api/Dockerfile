# WorldView 4D API. Build context: worldview/ (so the workspace lockfile is available)
#   docker build -f backend-api/Dockerfile -t worldview-api .
# NOTE: not built/validated in this repo's CI (no Docker daemon there) — treat as a template.
FROM node:22-slim AS build
WORKDIR /app
# Workspace manifests + lockfile first, for layer caching.
COPY package.json package-lock.json ./
COPY backend-api/package.json backend-api/package.json
COPY frontend/package.json frontend/package.json
RUN npm ci
COPY backend-api ./backend-api
RUN npm run build --workspace backend-api

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production
COPY package.json package-lock.json ./
COPY backend-api/package.json backend-api/package.json
COPY frontend/package.json frontend/package.json
RUN npm ci --omit=dev --workspace backend-api --include-workspace-root
COPY --from=build /app/backend-api/dist ./backend-api/dist
WORKDIR /app/backend-api
EXPOSE 4000
# Toggle the consumers with ENABLE_LIVE_WRITER=1 / ENABLE_HISTORY_WRITER=1.
CMD ["node", "dist/server.js"]
