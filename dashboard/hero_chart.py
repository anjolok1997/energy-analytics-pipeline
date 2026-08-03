"""
Render the project's hero visual: a dumbbell chart of the countries that shifted
to renewables the most since 2000, straight from the decarbonisation leaderboard
mart. Writes a PNG that the README embeds (so it shows on GitHub with no run).

    python dashboard/hero_chart.py

Reads WAREHOUSE_URL (defaults to the local DuckDB file), so run it after the
pipeline has built the marts.
"""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")  # headless: no display needed
import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import create_engine

TOP_N = int(os.environ.get("HERO_TOP_N", "15"))
OUT = os.environ.get("HERO_OUT", "dashboard/decarbonization_leaderboard.png")

INK = "#1a1a2e"
GREY = "#b9c0c9"
GREEN = "#2a9d5c"


def load(engine) -> pd.DataFrame:
    schema = "main" if engine.url.get_backend_name() == "duckdb" else "analytics"
    return pd.read_sql(
        f"""
        select country, renewables_share_2000, renewables_share_latest,
               renewables_change_pts, latest_year
        from {schema}.mart_decarbonization_leaderboard
        order by rank_fastest
        limit {TOP_N}
        """,
        engine,
    )


def render(df: pd.DataFrame) -> None:
    df = df.iloc[::-1].reset_index(drop=True)  # biggest gain on top
    latest_year = int(df["latest_year"].max())
    y = range(len(df))

    fig, ax = plt.subplots(figsize=(10, 7.5))

    # connecting line from 2000 -> latest, then the two dots
    for i, r in df.iterrows():
        ax.plot([r["renewables_share_2000"], r["renewables_share_latest"]], [i, i],
                color=GREEN, linewidth=2.5, zorder=1, solid_capstyle="round")
    ax.scatter(df["renewables_share_2000"], y, color=GREY, s=70, zorder=2, label="2000")
    ax.scatter(df["renewables_share_latest"], y, color=GREEN, s=90, zorder=3, label=str(latest_year))

    # country labels + change annotation
    ax.set_yticks(list(y))
    ax.set_yticklabels(df["country"], fontsize=11, color=INK)
    xmax = df["renewables_share_latest"].max()
    for i, r in df.iterrows():
        ax.annotate(f"+{r['renewables_change_pts']:.0f} pts",
                    (r["renewables_share_latest"], i), xytext=(8, 0),
                    textcoords="offset points", va="center", fontsize=9,
                    color=GREEN, fontweight="bold")

    ax.set_xlim(-2, xmax + 12)
    ax.set_xlabel("Renewables' share of energy (%)", fontsize=11, color=INK)
    ax.set_title("Who's winning the shift to renewables",
                 fontsize=18, fontweight="bold", color=INK, pad=16, loc="left")
    ax.text(0, 1.015, f"Change in renewables' share of energy, 2000 → {latest_year}. "
            f"Top {len(df)} countries.", transform=ax.transAxes, fontsize=11, color="#5b6472")

    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(left=False)
    ax.grid(axis="x", color="#eceef1", zorder=0)
    ax.legend(loc="lower right", frameon=False, fontsize=10)
    ax.text(0, -0.09, "Source: Our World in Data — Energy (CC BY 4.0)",
            transform=ax.transAxes, fontsize=8.5, color="#8a929c")

    fig.tight_layout()
    fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"[hero] wrote {OUT}")


def main() -> int:
    engine = create_engine(os.environ.get("WAREHOUSE_URL", "duckdb:///warehouse.duckdb"))
    render(load(engine))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
