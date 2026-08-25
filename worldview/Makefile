# WorldView — convenience targets. Run from worldview/.
.PHONY: help infra-up infra-down db-apply install dev-frontend dev-api workers

help:
	@echo "WorldView monorepo targets:"
	@echo "  make infra-up      # start Redpanda + TimescaleDB + Redis (docker compose)"
	@echo "  make infra-down    # stop infra"
	@echo "  make db-apply      # apply db/schema/*.sql to \$$DATABASE_URL"
	@echo "  make db-seed       # load the Strait of Hormuz demo scenario (historical)"
	@echo "  make seed-live     # seed Redis live-state for LIVE mode (no workers needed)"
	@echo "  make install       # install JS + Python deps for all workspaces"
	@echo "  make dev-frontend  # run the Cesium dashboard (Vite)"
	@echo "  make dev-api       # run the Fastify 4D API"
	@echo "  make workers       # run ingestion workers (STEP 3)"

infra-up:
	docker compose up -d

infra-down:
	docker compose down

db-apply:
	for f in db/schema/*.sql; do psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$$f"; done

db-seed:
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/seed/demo.sql

seed-live:
	node scripts/seed-live.mjs

install:
	npm install
	cd ingestion-workers && python -m pip install -r requirements.txt

dev-frontend:
	npm run dev --workspace frontend

dev-api:
	npm run dev --workspace backend-api

workers:
	cd ingestion-workers && python -m worldview_ingest
