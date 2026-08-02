# Dashboard

A four-tile Metabase dashboard on the energy marts: top electricity consumers,
the renewables transition over time, renewables vs emissions, and the AI
country briefings.

`build_dashboard.py` provisions the whole thing through the Metabase REST API —
first-time admin setup, the Postgres connection, the four cards, and the
dashboard layout — so there's nothing to click through by hand.

## Quick start

From the repo root, with Docker running:

```bash
make dashboard
```

That brings up Postgres + Metabase, loads the warehouse, builds the dbt models
on the `prod` (Postgres) target, generates the briefings, and provisions the
dashboard. When it finishes it prints a URL like `http://localhost:3000/dashboard/1`.

Log in with the credentials it prints (default `admin@energy.local` /
`energy-admin-1`), open the dashboard, and you're done.

## Run just the provisioning step

If the Postgres warehouse is already loaded (you've run the pipeline against the
`prod` target), build only the dashboard:

```bash
make dashboard-build          # or: python dashboard/build_dashboard.py
```

Re-running is safe: it logs in with the same admin, reuses the existing
warehouse connection, and rebuilds the cards and dashboard.

## Configuration

All optional — defaults match the local `docker-compose` stack:

| Env var | Default | Purpose |
|---|---|---|
| `MB_URL` | `http://localhost:3000` | Metabase base URL |
| `MB_EMAIL` / `MB_PASSWORD` | `admin@energy.local` / `energy-admin-1` | admin login it creates/uses |
| `PG_HOST` | `energy-postgres` | Postgres host **as Metabase sees it** (the container name on the shared Docker network) |
| `PG_PORT` / `PG_DB` / `PG_USER` / `PG_PASSWORD` | `5432` / `energy` / `energy` / `energy` | warehouse connection |

> `PG_HOST` defaults to the container name because Metabase connects from inside
> its own container over the Docker network — not via `localhost`.

## Tiles

| Tile | Type | Source |
|---|---|---|
| Top electricity consumers | bar | `mart_latest_snapshot` |
| Renewables share over time | line | `mart_renewables_transition` |
| Renewables vs emissions | scatter | `mart_latest_snapshot` |
| AI country briefings | table | `ai_country_briefings` |