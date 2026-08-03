# Convenience commands. Run `make help` to list them.
# Local dev uses DuckDB (no Docker). `make deploy-*` targets use Postgres.

.PHONY: help install ingest transform briefings hero pipeline dashboard-up dashboard-down dashboard-build dashboard clean

help:
	@echo "install          Install Python dependencies"
	@echo "pipeline         Run the full local pipeline (ingest -> dbt -> briefings -> hero) on DuckDB"
	@echo "ingest           Load the OWID dataset into the warehouse"
	@echo "transform        Run dbt build (models + tests)"
	@echo "briefings        Write the per-country briefing text"
	@echo "hero             Render the leaderboard hero chart (PNG the README embeds)"
	@echo "dashboard-up     Start Postgres + Metabase (docker compose)"
	@echo "dashboard-down   Stop Postgres + Metabase"
	@echo "dashboard-build  Provision the Metabase dashboard via its API"
	@echo "dashboard        Plug-and-play: containers -> load Postgres -> build dashboard"
	@echo "clean            Remove the local DuckDB file and dbt artifacts"

install:
	pip install -r requirements.txt

ingest:
	python ingest/load_energy_data.py

transform:
	cd dbt && dbt build --profiles-dir .

briefings:
	python ingest/briefings.py

hero:
	python dashboard/hero_chart.py

# One command, full local run.
pipeline: ingest transform briefings hero
	@echo "Pipeline complete. Warehouse: warehouse.duckdb"

dashboard-up:
	docker compose up -d
	@echo "Metabase starting at http://localhost:3000 (first boot ~1 min)"

dashboard-down:
	docker compose down

dashboard-build:
	python dashboard/build_dashboard.py

# Plug-and-play: bring up the stack, load the Postgres warehouse, build the dashboard.
# Assumes WAREHOUSE_URL / POSTGRES_* point at the compose Postgres (see .env.example).
dashboard: dashboard-up
	@echo "Waiting for Postgres..."
	@until docker exec energy-postgres pg_isready -U energy >/dev/null 2>&1 || \
	       pg_isready -h localhost -U energy >/dev/null 2>&1; do sleep 2; done
	python ingest/load_energy_data.py
	cd dbt && dbt build --profiles-dir . --target prod && cd ..
	python ingest/briefings.py
	python dashboard/hero_chart.py
	python dashboard/build_dashboard.py

clean:
	rm -f warehouse.duckdb
	rm -rf dbt/target dbt/logs
