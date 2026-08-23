# WorldView dashboard. Build context: worldview/ (workspace lockfile)
#   docker build -f frontend/Dockerfile -t worldview-frontend .
# Provide NEXT_PUBLIC_* at build time (they're inlined by Next at build).
# NOTE: not built/validated in this repo's CI (no Docker daemon there) — treat as a template.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package.json
COPY backend-api/package.json backend-api/package.json
RUN npm ci
COPY frontend ./frontend
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
ARG NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN
RUN npm run build --workspace frontend

FROM node:22-slim
WORKDIR /app/frontend
ENV NODE_ENV=production
COPY --from=build /app/node_modules /app/node_modules
# .next must be node-writable (Next writes .next/cache at runtime); everything
# else stays root-owned read-only.
COPY --from=build --chown=node:node /app/frontend/.next ./.next
COPY --from=build /app/frontend/package.json ./package.json
COPY --from=build /app/frontend/next.config.mjs ./next.config.mjs
EXPOSE 3000
# AUD-4/F14: run as the image's built-in unprivileged `node` user; npm/npx state
# lives under the node-owned /home/node.
USER node
# No HEALTHCHECK: this Next.js app exposes no health/liveness route today (grep
# of worldview/frontend found no /health or /healthz route or handler), so any
# probe would invent an endpoint. Add a route before wiring a probe.
CMD ["npx", "next", "start", "-p", "3000"]
