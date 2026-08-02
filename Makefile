# Convenience commands. Run `make help` to list them.
# Local dev uses DuckDB (no Docker). `make deploy-*` targets use Postgres.

.PHONY: help install ingest transform enrich pipeline dashboard-up dashboard-down clean

help:
	@echo "install        Install Python dependencies"
	@echo "pipeline       Run the full local pipeline (ingest -> dbt -> AI) on DuckDB"
	@echo "ingest         Load the OWID dataset into the warehouse"
	@echo "transform      Run dbt build (models + tests)"
	@echo "enrich         Run the AI enrichment step"
	@echo "dashboard-up   Start Postgres + Metabase (docker compose)"
	@echo "dashboard-down Stop Postgres + Metabase"
	@echo "clean          Remove the local DuckDB file and dbt artifacts"

install:
	pip install -r requirements.txt

ingest:
	python ingest/load_energy_data.py

transform:
	cd dbt && dbt build --profiles-dir .

enrich:
	python ingest/ai_enrich.py

# One command, full local run.
pipeline: ingest transform enrich
	@echo "Pipeline complete. Warehouse: warehouse.duckdb"

dashboard-up:
	docker compose up -d
	@echo "Metabase starting at http://localhost:3000 (first boot ~1 min)"

dashboard-down:
	docker compose down

clean:
	rm -f warehouse.duckdb
	rm -rf dbt/target dbt/logs
