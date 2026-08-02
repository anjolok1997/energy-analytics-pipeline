"""
Provision the Metabase dashboard from scratch via the Metabase REST API.

Idempotent-ish: on a fresh Metabase it runs first-time setup (creating the admin
user below), connects the Postgres warehouse, and builds the four dashboard tiles
described in the README. Re-running against an already-set-up Metabase logs in
with the same credentials and rebuilds the cards + dashboard.

    python dashboard/build_dashboard.py

Env (all optional, sensible defaults for the local docker-compose stack):
    MB_URL            Metabase base URL           (http://localhost:3000)
    MB_EMAIL          admin email to create/login (admin@energy.local)
    MB_PASSWORD       admin password              (energy-admin-1)
    PG_HOST           Postgres host as seen by Metabase (energy-postgres)
    PG_PORT/PG_DB/PG_USER/PG_PASSWORD  warehouse connection
"""
from __future__ import annotations

import os
import sys
import time

import requests

MB_URL = os.environ.get("MB_URL", "http://localhost:3000").rstrip("/")
MB_EMAIL = os.environ.get("MB_EMAIL", "admin@energy.local")
MB_PASSWORD = os.environ.get("MB_PASSWORD", "energy-admin-1")

PG = {
    "host": os.environ.get("PG_HOST", "energy-postgres"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "dbname": os.environ.get("PG_DB", "energy"),
    "user": os.environ.get("PG_USER", "energy"),
    "password": os.environ.get("PG_PASSWORD", "energy"),
}

ANALYTICS = "analytics"   # dbt marts schema
PUBLIC = "public"         # raw + ai briefings


def api(session: requests.Session, method: str, path: str, **kw):
    r = session.request(method, f"{MB_URL}/api{path}", timeout=60, **kw)
    if not r.ok:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
    return r.json() if r.text else {}


def wait_healthy():
    for _ in range(60):
        try:
            if requests.get(f"{MB_URL}/api/health", timeout=5).json().get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(3)
    sys.exit("Metabase never became healthy at " + MB_URL)


def authenticate(session: requests.Session) -> None:
    props = requests.get(f"{MB_URL}/api/session/properties", timeout=30).json()
    token = props.get("setup-token")
    if token:
        print("[mb] first-time setup: creating admin user")
        res = api(session, "POST", "/setup", json={
            "token": token,
            "user": {
                "first_name": "Energy", "last_name": "Admin",
                "email": MB_EMAIL, "password": MB_PASSWORD, "site_name": "Energy Analytics",
            },
            "prefs": {"site_name": "Energy Analytics", "allow_tracking": False},
        })
        session.headers["X-Metabase-Session"] = res["id"]
    else:
        print("[mb] already set up: logging in")
        res = api(session, "POST", "/session", json={"username": MB_EMAIL, "password": MB_PASSWORD})
        session.headers["X-Metabase-Session"] = res["id"]


def connect_warehouse(session: requests.Session) -> int:
    existing = api(session, "GET", "/database")
    dbs = existing.get("data", existing) if isinstance(existing, dict) else existing
    for db in dbs:
        if db.get("name") == "Energy warehouse":
            print(f"[mb] warehouse already connected (id={db['id']})")
            return db["id"]
    print("[mb] connecting Postgres warehouse")
    db = api(session, "POST", "/database", json={
        "engine": "postgres",
        "name": "Energy warehouse",
        "details": {
            "host": PG["host"], "port": PG["port"], "dbname": PG["dbname"],
            "user": PG["user"], "password": PG["password"], "ssl": False,
        },
    })
    db_id = db["id"]
    api(session, "POST", f"/database/{db_id}/sync_schema")
    # wait for tables to appear so native queries resolve schemas
    for _ in range(30):
        meta = api(session, "GET", f"/database/{db_id}/metadata")
        names = {t["name"] for t in meta.get("tables", [])}
        if {"mart_latest_snapshot", "ai_country_briefings"} <= names:
            break
        time.sleep(2)
    return db_id


def make_card(session, db_id, name, sql, display, viz=None):
    card = api(session, "POST", "/card", json={
        "name": name,
        "display": display,
        "dataset_query": {"type": "native", "native": {"query": sql}, "database": db_id},
        "visualization_settings": viz or {},
    })
    print(f"[mb]   card: {name} (id={card['id']})")
    return card["id"]


def build_cards(session, db_id) -> list[dict]:
    cards = []

    cards.append({"id": make_card(
        session, db_id, "Top electricity consumers (latest year)",
        f"""select country, round(electricity_demand_twh) as demand_twh
            from {ANALYTICS}.mart_latest_snapshot
            where electricity_demand_twh is not null
            order by electricity_demand_twh desc
            limit 10""",
        "bar",
        {"graph.dimensions": ["country"], "graph.metrics": ["demand_twh"]},
    ), "row": 0, "col": 0, "size_x": 12, "size_y": 7})

    cards.append({"id": make_card(
        session, db_id, "Renewables share of energy over time",
        f"""select year, country, round(renewables_share_pct::numeric, 1) as renewables_share_pct
            from {ANALYTICS}.mart_renewables_transition
            where country in ('China','United States','Germany','Brazil','India','United Kingdom')
            order by year""",
        "line",
        {"graph.dimensions": ["year", "country"], "graph.metrics": ["renewables_share_pct"]},
    ), "row": 0, "col": 12, "size_x": 12, "size_y": 7})

    cards.append({"id": make_card(
        session, db_id, "Renewables share vs electricity emissions",
        f"""select country,
                   round(renewables_share_pct::numeric, 1) as renewables_share_pct,
                   round(electricity_emissions_mtco2e)      as emissions_mtco2e,
                   round(electricity_demand_twh)            as demand_twh
            from {ANALYTICS}.mart_latest_snapshot
            where renewables_share_pct is not null
              and electricity_emissions_mtco2e is not null""",
        "scatter",
        {"graph.dimensions": ["renewables_share_pct"],
         "graph.metrics": ["emissions_mtco2e"],
         "scatter.bubble": "demand_twh"},
    ), "row": 7, "col": 0, "size_x": 12, "size_y": 7})

    cards.append({"id": make_card(
        session, db_id, "AI country briefings",
        f"""select country, snapshot_year, briefing
            from {PUBLIC}.ai_country_briefings
            order by snapshot_year desc, country""",
        "table",
    ), "row": 7, "col": 12, "size_x": 12, "size_y": 7})

    return cards


def build_dashboard(session, cards) -> int:
    dash = api(session, "POST", "/dashboard", json={
        "name": "Global Energy Analytics",
        "description": "Electricity demand, the renewables transition, and AI briefings "
                       "by country. Built from the OWID energy dataset via dbt.",
    })
    dash_id = dash["id"]
    dashcards = [{
        "id": -(i + 1), "card_id": c["id"],
        "row": c["row"], "col": c["col"], "size_x": c["size_x"], "size_y": c["size_y"],
        "parameter_mappings": [], "visualization_settings": {},
    } for i, c in enumerate(cards)]
    api(session, "PUT", f"/dashboard/{dash_id}", json={"dashcards": dashcards})
    print(f"[mb] dashboard built (id={dash_id})")
    return dash_id


def main() -> int:
    wait_healthy()
    session = requests.Session()
    authenticate(session)
    db_id = connect_warehouse(session)
    cards = build_cards(session, db_id)
    dash_id = build_dashboard(session, cards)
    print("\n" + "=" * 60)
    print(f"Dashboard ready:  {MB_URL}/dashboard/{dash_id}")
    print(f"Log in with:      {MB_EMAIL} / {MB_PASSWORD}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())