"""
Download the OWID global energy dataset and load a curated raw table. All the
actual transformation happens in dbt downstream.

Target warehouse comes from WAREHOUSE_URL (a SQLAlchemy URL), so the same code
loads a local DuckDB file or a Postgres instance:

    python ingest/load_energy_data.py
    WAREHOUSE_URL=postgresql+psycopg2://energy:energy@localhost:5432/energy \\
        python ingest/load_energy_data.py
"""
from __future__ import annotations

import io
import os
import sys

import pandas as pd
import requests
from sqlalchemy import create_engine, text

SOURCE_URL = (
    "https://raw.githubusercontent.com/owid/energy-data/master/owid-energy-data.csv"
)

# Pull a subset rather than all 130 columns.
CURATED_COLUMNS = [
    "country",
    "iso_code",
    "year",
    "population",
    "gdp",
    "electricity_generation",          # TWh generated
    "electricity_demand",              # TWh consumed
    "electricity_demand_per_capita",   # kWh per person
    "energy_per_capita",               # kWh per person (primary energy)
    "energy_per_gdp",                  # kWh per $ of GDP
    "greenhouse_gas_emissions",        # MtCO2e from electricity
    "renewables_share_energy",         # % of primary energy
    "low_carbon_share_energy",         # % (renewables + nuclear)
    "fossil_share_energy",             # %
    "solar_share_energy",              # %
    "wind_share_energy",               # %
]

RAW_TABLE = "raw_energy"


def get_engine():
    url = os.environ.get("WAREHOUSE_URL", "duckdb:///warehouse.duckdb")
    print(f"[ingest] target warehouse: {url}")
    return create_engine(url)


def extract() -> pd.DataFrame:
    print(f"[ingest] downloading {SOURCE_URL}")
    resp = requests.get(SOURCE_URL, timeout=120, headers={"User-Agent": "energy-pipeline"})
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text), usecols=CURATED_COLUMNS)
    print(f"[ingest] downloaded {len(df):,} rows, {len(df.columns)} columns")
    return df


def load(df: pd.DataFrame, engine) -> None:
    with engine.begin() as conn:
        df.to_sql(RAW_TABLE, conn, if_exists="replace", index=False)
    with engine.connect() as conn:
        n = conn.execute(text(f"SELECT count(*) FROM {RAW_TABLE}")).scalar()
    print(f"[ingest] loaded {n:,} rows into '{RAW_TABLE}'")


def main() -> int:
    engine = get_engine()
    df = extract()
    load(df, engine)
    print("[ingest] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
