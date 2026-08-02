"""
Dagster version of the same two steps (ingest, then dbt build). Not deployed --
the scheduled runner for this repo is the GitHub Actions cron in
.github/workflows/scheduled_refresh.yml. This is here as a local reference:

    pip install dagster dagster-webserver dagster-dbt
    dagster dev -f orchestration/energy_orchestration/definitions.py
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    Definitions,
    ScheduleDefinition,
    asset,
    define_asset_job,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = PROJECT_ROOT / "dbt"


@asset(compute_kind="python")
def raw_energy(context: AssetExecutionContext) -> None:
    """Run the ingestion script that lands raw_energy."""
    context.log.info("Running OWID energy ingestion")
    subprocess.run(
        ["python", str(PROJECT_ROOT / "ingest" / "load_energy_data.py")],
        check=True,
    )


@asset(deps=[raw_energy], compute_kind="dbt")
def dbt_models(context: AssetExecutionContext) -> None:
    """Build the dbt staging and mart models."""
    context.log.info("Running dbt build")
    subprocess.run(
        ["dbt", "build", "--profiles-dir", "."],
        cwd=str(DBT_DIR),
        check=True,
    )


refresh_job = define_asset_job("weekly_refresh", selection="*")

weekly_schedule = ScheduleDefinition(
    job=refresh_job,
    cron_schedule="0 6 * * 1",  # Mondays 06:00
)

defs = Definitions(
    assets=[raw_energy, dbt_models],
    jobs=[refresh_job],
    schedules=[weekly_schedule],
)
