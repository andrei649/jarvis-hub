# WorldView — convenience targets. Run from worldview/.
.PHONY: help infra-up infra-down db-apply install dev-frontend dev-api workers

help:
	@echo "WorldView monorepo targets:"
	@echo "  make infra-up      # start Redpanda + TimescaleDB + Redis (docker compose)"
	@echo "  make infra-down    # stop infra"
	@echo "  make db-apply      # apply db/schema/*.sql to \$$DATABASE_URL"
	@echo "  make install       # install JS + Python deps for all workspaces"
	@echo "  make dev-frontend  # run the Next.js dashboard"
	@echo "  make dev-api       # run the Fastify 4D API"
	@echo "  make workers       # run ingestion workers (STEP 3)"

infra-up:
	docker compose up -d

infra-down:
	docker compose down

db-apply:
	for f in db/schema/*.sql; do psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$$f"; done

install:
	npm install
	cd ingestion-workers && python -m pip install -r requirements.txt

dev-frontend:
	npm run dev --workspace frontend

dev-api:
	npm run dev --workspace backend-api

workers:
	cd ingestion-workers && python -m worldview_ingest
