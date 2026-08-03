# Dashboard

Two Metabase dashboards on the energy marts:

- **Global electricity & the shift to renewables** — who's decarbonising fastest
  (the leaderboard), the biggest electricity consumers, renewables share over time,
  and the per-country briefings.
- **Country deep-dive** — pick a country from a dropdown to see its plain-English
  read, its renewables-vs-fossil transition over time, and its leaderboard rank.

`build_dashboard.py` provisions both through the Metabase REST API — first-time
admin setup, the Postgres connection, every card, the country filter, and the
dashboard layouts — so there's nothing to click through by hand.

There's also `hero_chart.py`, which renders a static PNG of the leaderboard
(`decarbonization_leaderboard.png`) that the top-level README embeds — no
Metabase needed to see the headline result.

## Quick start

From the repo root, with Docker running:

```bash
make dashboard
```

That brings up Postgres + Metabase, loads the warehouse, builds the dbt models
on the `prod` (Postgres) target, generates the briefings, renders the hero chart,
and provisions both dashboards. When it finishes it prints their URLs, like
`http://localhost:3000/dashboard/1`.

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

**Global electricity & the shift to renewables**

| Tile | Type | Source |
|---|---|---|
| Who's decarbonising fastest | bar | `mart_decarbonization_leaderboard` |
| Biggest electricity consumers | bar | `mart_latest_snapshot` |
| Renewables share over time | line | `mart_renewables_transition` |
| Country narratives | table | `ai_country_briefings` |

**Country deep-dive** (driven by a `Country` dropdown parameter)

| Tile | Type | Source |
|---|---|---|
| Where this country stands | table | `ai_country_briefings` |
| Renewables vs fossil over time | line | `mart_renewables_transition` |
| Decarbonisation rank & change | table | `mart_decarbonization_leaderboard` |