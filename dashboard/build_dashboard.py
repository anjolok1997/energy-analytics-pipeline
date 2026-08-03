"""
Provision the Metabase dashboards from scratch via the Metabase REST API.

Builds two dashboards, each tile answering one plain question:

  Overview — "Global electricity & the shift to renewables"
    * Who's decarbonising fastest   (leaderboard: renewables growth since 2000)
    * Biggest electricity consumers
    * Renewables share over time
    * Country narratives

  Country deep-dive — pick a country from a dropdown and see:
    * where it stands (the narrative)
    * its renewables-vs-fossil transition over time
    * its leaderboard rank and change

Idempotent-ish: on a fresh Metabase it runs first-time admin setup; otherwise it
logs in, re-syncs the warehouse, archives previously built dashboards/cards, and
rebuilds. Run after the pipeline has loaded the Postgres warehouse.

    python dashboard/build_dashboard.py

Env (all optional, defaults match the local docker stack): MB_URL, MB_EMAIL,
MB_PASSWORD, PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

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
PUBLIC = "public"         # raw + narratives
DEFAULT_COUNTRY = "Germany"

REQUIRED_TABLES = {
    "mart_latest_snapshot", "mart_renewables_transition",
    "mart_decarbonization_leaderboard", "ai_country_briefings",
}


def api(session, method, path, **kw):
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


def authenticate(session):
    props = requests.get(f"{MB_URL}/api/session/properties", timeout=30).json()
    token = props.get("setup-token")
    if token:
        print("[mb] first-time setup: creating admin user")
        res = api(session, "POST", "/setup", json={
            "token": token,
            "user": {"first_name": "Energy", "last_name": "Admin",
                     "email": MB_EMAIL, "password": MB_PASSWORD, "site_name": "Energy Analytics"},
            "prefs": {"site_name": "Energy Analytics", "allow_tracking": False},
        })
    else:
        print("[mb] logging in")
        res = api(session, "POST", "/session", json={"username": MB_EMAIL, "password": MB_PASSWORD})
    session.headers["X-Metabase-Session"] = res["id"]


def connect_warehouse(session) -> int:
    dbs = api(session, "GET", "/database")
    dbs = dbs.get("data", dbs) if isinstance(dbs, dict) else dbs
    db_id = next((d["id"] for d in dbs if d.get("name") == "Energy warehouse"), None)
    if db_id is None:
        print("[mb] connecting Postgres warehouse")
        db_id = api(session, "POST", "/database", json={
            "engine": "postgres", "name": "Energy warehouse",
            "details": {"host": PG["host"], "port": PG["port"], "dbname": PG["dbname"],
                        "user": PG["user"], "password": PG["password"], "ssl": False},
        })["id"]
    print("[mb] syncing warehouse schema")
    api(session, "POST", f"/database/{db_id}/sync_schema")
    for _ in range(40):
        meta = api(session, "GET", f"/database/{db_id}/metadata")
        names = {t["name"] for t in meta.get("tables", [])}
        if REQUIRED_TABLES <= names:
            return db_id, meta
        time.sleep(2)
    sys.exit("warehouse tables never synced into Metabase")


def field_map(meta) -> dict:
    """(schema, table, column) -> field id"""
    out = {}
    for t in meta["tables"]:
        for f in t["fields"]:
            out[(t["schema"], t["name"], f["name"])] = f["id"]
    return out


def archive_previous(session):
    """Archive dashboards/cards from earlier runs so we rebuild cleanly."""
    for coll in ("/dashboard", "/card"):
        items = api(session, "GET", coll)
        items = items.get("data", items) if isinstance(items, dict) else items
        for it in items:
            if it.get("name", "").startswith(("Global electricity", "Country deep-dive",
                                              "Global Energy Analytics")) or \
               it.get("name") in CARD_NAMES:
                try:
                    api(session, "PUT", f"{coll}/{it['id']}", json={"archived": True})
                except Exception:
                    pass


CARD_NAMES = set()


def make_card(session, db_id, name, sql, display, viz=None, template_tags=None):
    CARD_NAMES.add(name)
    native = {"query": sql}
    if template_tags:
        native["template-tags"] = template_tags
    card = api(session, "POST", "/card", json={
        "name": name, "display": display,
        "dataset_query": {"type": "native", "native": native, "database": db_id},
        "visualization_settings": viz or {},
    })
    print(f"[mb]   card: {name} (id={card['id']})")
    return card["id"]


def country_tag(field_id):
    return {"country": {
        "id": str(uuid.uuid4()), "name": "country", "display-name": "Country",
        "type": "dimension", "dimension": ["field", field_id, None],
        "widget-type": "string/=",
    }}


# ---------------------------------------------------------------- overview ----

def build_overview(session, db_id):
    cards = []
    cards.append({"id": make_card(
        session, db_id, "Who's decarbonising fastest (renewables growth since 2000)",
        f"""select country, renewables_change_pts as change_in_renewables_pts
            from {ANALYTICS}.mart_decarbonization_leaderboard
            order by rank_fastest
            limit 15""",
        "bar",
        {"graph.dimensions": ["country"], "graph.metrics": ["change_in_renewables_pts"]},
    ), "row": 0, "col": 0, "size_x": 12, "size_y": 8})

    cards.append({"id": make_card(
        session, db_id, "Biggest electricity consumers (latest year)",
        f"""select country, round(electricity_demand_twh) as demand_twh
            from {ANALYTICS}.mart_latest_snapshot
            where electricity_demand_twh is not null
            order by electricity_demand_twh desc
            limit 10""",
        "bar",
        {"graph.dimensions": ["country"], "graph.metrics": ["demand_twh"]},
    ), "row": 0, "col": 12, "size_x": 12, "size_y": 8})

    cards.append({"id": make_card(
        session, db_id, "Renewables share of energy over time",
        f"""select year, country, round(cast(renewables_share_pct as numeric), 1) as renewables_share_pct
            from {ANALYTICS}.mart_renewables_transition
            where country in ('Denmark','Germany','United Kingdom','China','United States','India')
            order by year""",
        "line",
        {"graph.dimensions": ["year", "country"], "graph.metrics": ["renewables_share_pct"]},
    ), "row": 8, "col": 0, "size_x": 12, "size_y": 8})

    cards.append({"id": make_card(
        session, db_id, "Country narratives",
        f"""select country, briefing
            from {PUBLIC}.ai_country_briefings
            order by snapshot_year desc, country""",
        "table",
    ), "row": 8, "col": 12, "size_x": 12, "size_y": 8})

    dash = api(session, "POST", "/dashboard", json={
        "name": "Global electricity & the shift to renewables",
        "description": "Which countries are moving to renewables the fastest, who uses "
                       "the most power, and how the mix has changed — from the OWID energy "
                       "dataset via dbt.",
    })["id"]
    api(session, "PUT", f"/dashboard/{dash}", json={"dashcards": [
        {"id": -(i + 1), "card_id": c["id"], "row": c["row"], "col": c["col"],
         "size_x": c["size_x"], "size_y": c["size_y"],
         "parameter_mappings": [], "visualization_settings": {}}
        for i, c in enumerate(cards)]})
    print(f"[mb] overview dashboard built (id={dash})")
    return dash


# --------------------------------------------------------------- deep-dive ----

def build_country_detail(session, db_id, fmap):
    pid = uuid.uuid4().hex[:8]
    cards = []

    cards.append({"card_id": make_card(
        session, db_id, "Where this country stands",
        f"""select briefing
            from {PUBLIC}.ai_country_briefings
            where 1=1 [[ and {{{{country}}}} ]]""",
        "table",
        template_tags=country_tag(fmap[(PUBLIC, "ai_country_briefings", "country")]),
    ), "row": 0, "col": 0, "size_x": 24, "size_y": 3})

    cards.append({"card_id": make_card(
        session, db_id, "Renewables vs fossil over time",
        f"""select year,
                   round(cast(renewables_share_pct as numeric), 1) as renewables_pct,
                   round(cast(fossil_share_pct as numeric), 1)     as fossil_pct
            from {ANALYTICS}.mart_renewables_transition
            where 1=1 [[ and {{{{country}}}} ]]
            order by year""",
        "line",
        {"graph.dimensions": ["year"], "graph.metrics": ["renewables_pct", "fossil_pct"]},
        template_tags=country_tag(fmap[(ANALYTICS, "mart_renewables_transition", "country")]),
    ), "row": 3, "col": 0, "size_x": 14, "size_y": 8})

    cards.append({"card_id": make_card(
        session, db_id, "Decarbonisation rank & change",
        f"""select rank_fastest        as global_rank,
                   countries_ranked     as of_countries,
                   renewables_share_2000 as renewables_2000_pct,
                   renewables_share_latest as renewables_now_pct,
                   renewables_change_pts   as change_pts
            from {ANALYTICS}.mart_decarbonization_leaderboard
            where 1=1 [[ and {{{{country}}}} ]]""",
        "table",
        template_tags=country_tag(fmap[(ANALYTICS, "mart_decarbonization_leaderboard", "country")]),
    ), "row": 3, "col": 14, "size_x": 10, "size_y": 8})

    dash = api(session, "POST", "/dashboard", json={
        "name": "Country deep-dive",
        "description": "Pick a country to see where it stands on the renewables shift, its "
                       "transition over time, and its leaderboard rank.",
    })["id"]
    api(session, "PUT", f"/dashboard/{dash}", json={
        "parameters": [{"id": pid, "name": "Country", "slug": "country",
                        "type": "string/=", "sectionId": "string",
                        "default": [DEFAULT_COUNTRY]}],
        "dashcards": [
            {"id": -(i + 1), "card_id": c["card_id"], "row": c["row"], "col": c["col"],
             "size_x": c["size_x"], "size_y": c["size_y"],
             "parameter_mappings": [{"parameter_id": pid, "card_id": c["card_id"],
                                     "target": ["dimension", ["template-tag", "country"]]}],
             "visualization_settings": {}}
            for i, c in enumerate(cards)],
    })
    print(f"[mb] country deep-dive built (id={dash})")
    return dash


def main() -> int:
    wait_healthy()
    s = requests.Session()
    authenticate(s)
    db_id, meta = connect_warehouse(s)
    fmap = field_map(meta)
    archive_previous(s)
    overview = build_overview(s, db_id)
    detail = build_country_detail(s, db_id, fmap)
    print("\n" + "=" * 60)
    print(f"Overview:    {MB_URL}/dashboard/{overview}")
    print(f"Deep-dive:   {MB_URL}/dashboard/{detail}")
    print(f"Log in with: {MB_EMAIL} / {MB_PASSWORD}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
