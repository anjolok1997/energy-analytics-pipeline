# Global Energy Analytics Pipeline

An end-to-end analytics pipeline on a public dataset: ingest, warehouse, transform
and test with dbt, add a text-enrichment step, and serve it to a Metabase dashboard.
Runs locally on DuckDB with no setup, or on Postgres + Metabase via Docker.

Data is [Our World in Data's energy dataset](https://github.com/owid/energy-data)
(country × year electricity and energy metrics). The headline question it answers:
**which countries have shifted to renewables the fastest since 2000?** A tested dbt
model ranks them, and everything downstream — the hero chart, the dashboards, the
per-country briefings — is built off that one leaderboard.

![Who's winning the shift to renewables](dashboard/decarbonization_leaderboard.png)

_Rendered by `dashboard/hero_chart.py` straight from the `mart_decarbonization_leaderboard`
model, so it stays in sync with the data._

## Architecture

```mermaid
flowchart LR
    A[OWID energy CSV] -->|python ingest| B[(DuckDB / Postgres)]
    B -->|dbt: staging + marts + tests| C[analytics tables]
    C -->|local model| D[ai_country_briefings]
    C --> E[Metabase]
    D --> E
    F[GitHub Actions: CI + weekly cron] -.-> A
```

## Stack

- Python (pandas, SQLAlchemy) for ingestion
- DuckDB for local dev, Postgres for the deployed warehouse
- dbt for modelling and tests
- transformers (local flan-t5) for the enrichment step, swappable to HF or Claude
- GitHub Actions for CI and a scheduled refresh
- Metabase for the dashboard

The dbt models are plain SQL and run unchanged on DuckDB, Postgres or BigQuery
(BigQuery is just another target in `profiles.yml`). There's also a Dagster
version of the pipeline in `orchestration/` as a reference; it isn't deployed.

## Run it locally

No Docker needed — everything runs against a local DuckDB file.

```bash
pip install -r requirements.txt

python ingest/load_energy_data.py                 # extract + load
cd dbt && dbt build --profiles-dir . && cd ..     # transform + test
python ingest/ai_enrich.py                        # briefings -> warehouse + markdown
```

Or `make pipeline`. That leaves a `warehouse.duckdb` with the full model graph.

The first `ai_enrich.py` run downloads a small flan-t5 model (~250MB, cached
after). Set `LOCAL_MODEL=google/flan-t5-small` for less memory, or
`AI_BACKEND=template` to skip the model entirely.

## Run it with Postgres + Metabase

```bash
docker compose up -d          # Postgres :5432, Metabase :3000
cp .env.example .env
export $(grep -v '^#' .env | xargs)

python ingest/load_energy_data.py
cd dbt && dbt build --profiles-dir . --target prod && cd ..
python ingest/ai_enrich.py
```

Open http://localhost:3000, add the `energy` Postgres database (models are in the
`analytics` schema), and build the dashboard.

Or skip the clicking — `make dashboard` runs all of the above and provisions the
Metabase dashboards automatically via its API. See [`dashboard/README.md`](dashboard/README.md)
for the quick-start.

### Dashboards

`build_dashboard.py` provisions two dashboards through the Metabase API:

- **Global electricity & the shift to renewables** — who's decarbonising fastest
  (the leaderboard), the biggest electricity consumers, renewables share over time,
  and the per-country briefings.
- **Country deep-dive** — pick a country from a dropdown to see its plain-English
  read, its renewables-vs-fossil transition over time, and its leaderboard rank.

## Tests

`dbt build` runs the tests as part of the build (also in CI):

- `not_null` + `unique` surrogate keys at staging and fact grain
- `not_null` + `unique` on `dim_country.iso_code`
- `relationships`: every fact row's `iso_code` exists in `dim_country`

Staging drops OWID's non-country aggregates (World, regions, etc.) by keeping only
rows with a 3-letter ISO code.

## Orchestration

`.github/workflows/scheduled_refresh.yml` re-runs the pipeline every Monday on the
free tier. In practice the OWID source updates infrequently (roughly annually), so
the weekly cron rarely changes the numbers — it's here to show the refresh wiring,
not because the data needs it that often. `ci.yml` runs the pipeline on every push
and fails if any test fails. `orchestration/energy_orchestration/definitions.py` is
the same pipeline expressed as Dagster assets, for reference.

## Enrichment backends

`ingest/ai_enrich.py` reads the leaderboard + snapshot marts and writes a short,
plain-English briefing per country back into the warehouse — each one narrating
that country's leaderboard result (its rank and how its renewables share moved
since 2000). The analysis lives in the tested dbt model; this step just phrases it.
`AI_BACKEND`:

- `local` — flan-t5 via transformers, offline, no cost (default)
- `hf` — Hugging Face inference API (`HF_TOKEN`)
- `claude` — Anthropic API (`ANTHROPIC_API_KEY`)
- `template` — no model, formats the facts; used in CI and for the committed sample

## Layout

```
ingest/          load_energy_data.py, ai_enrich.py
dbt/models/      staging/ + marts/ (dim_country, fct_country_energy, 3 marts)
dashboard/       build_dashboard.py (Metabase API), hero_chart.py (PNG)
orchestration/   Dagster reference (not deployed)
.github/         ci + scheduled refresh
docker-compose.yml, requirements.txt, Makefile
```

Data: Our World in Data — Energy, CC BY 4.0.
