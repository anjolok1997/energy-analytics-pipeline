"""
Write a short natural-language narrative per country that reports its result on
the decarbonisation leaderboard (mart_decarbonization_leaderboard) alongside its
latest snapshot, and store it back in the warehouse (ai_country_briefings) so the
dashboard can show a plain-English read next to the numbers.

    marts -> narrative -> ai_country_briefings + ai_output/sample_briefings.md

The leaderboard (a tested dbt model) does the analysis -- rank each country by how
much its renewables share grew since 2000. This step just phrases that result.

AI_BACKEND picks the generator:
    local     flan-t5 via transformers, runs offline on CPU (default)
    hf        Hugging Face inference API (needs HF_TOKEN)
    claude    Anthropic API (needs ANTHROPIC_API_KEY)
    template  no model, just phrases the facts; used in CI and for the sample
"""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd
from sqlalchemy import create_engine

TOP_N = int(os.environ.get("AI_TOP_N", "8"))
BACKEND = os.environ.get("AI_BACKEND", "local").lower()
OUTPUT_MD = "ai_output/sample_briefings.md"


def get_engine():
    url = os.environ.get("WAREHOUSE_URL", "duckdb:///warehouse.duckdb")
    return create_engine(url)


def load_facts(engine):
    schema = "main" if engine.url.get_backend_name() == "duckdb" else "analytics"
    snapshot = pd.read_sql(
        f"""
        select iso_code, country, snapshot_year, electricity_demand_twh,
               renewables_share_pct, fossil_share_pct
        from {schema}.mart_latest_snapshot
        order by electricity_demand_twh desc
        limit {TOP_N}
        """,
        engine,
    )
    board = pd.read_sql(
        f"""
        select iso_code, rank_fastest, countries_ranked,
               renewables_share_2000, renewables_share_latest, renewables_change_pts
        from {schema}.mart_decarbonization_leaderboard
        """,
        engine,
    )
    return snapshot, board


def build_context(row: pd.Series, board: pd.DataFrame) -> dict:
    match = board[board["iso_code"] == row["iso_code"]]
    ctx = {
        "country": row["country"],
        "year": int(row["snapshot_year"]),
        "demand_twh": float(row["electricity_demand_twh"]),
        "fossil_pct": float(row["fossil_share_pct"]),
        "renew_now": float(row["renewables_share_pct"]),
        "rank": None,
    }
    if not match.empty:
        b = match.iloc[0]
        ctx.update({
            "rank": int(b["rank_fastest"]),
            "countries": int(b["countries_ranked"]),
            "renew_2000": float(b["renewables_share_2000"]),
            "change_pts": float(b["renewables_change_pts"]),
        })
    return ctx


def make_prompt(ctx: dict) -> str:
    if ctx["rank"] is not None:
        facts = (
            f"It ranks {ctx['rank']} of {ctx['countries']} countries for growth in "
            f"renewables since 2000: renewables' share of energy went from "
            f"{ctx['renew_2000']:.1f}% in 2000 to {ctx['renew_now']:.1f}% in {ctx['year']} "
            f"({ctx['change_pts']:+.1f} points). It used {ctx['demand_twh']:.0f} TWh of "
            f"electricity in {ctx['year']}, currently {ctx['fossil_pct']:.0f}% fossil."
        )
    else:
        facts = (
            f"In {ctx['year']} it used {ctx['demand_twh']:.0f} TWh of electricity; "
            f"renewables are {ctx['renew_now']:.1f}% of energy, fossil {ctx['fossil_pct']:.0f}%."
        )
    return (
        f"Write a plain-English two-sentence read on how {ctx['country']} is doing in "
        f"the shift to renewable energy, for a general audience. Facts: {facts}"
    )


def summarise(ctx: dict) -> str:
    if BACKEND == "local":
        return _local(make_prompt(ctx))
    if BACKEND == "hf":
        return _hf(make_prompt(ctx))
    if BACKEND == "claude":
        return _claude(make_prompt(ctx))
    return _template(ctx)


_PIPE = None


def _local(prompt: str) -> str:
    # flan-t5-base runs on CPU. Swap LOCAL_MODEL for -small (lighter) or -large.
    # Weights download once and cache.
    global _PIPE
    if _PIPE is None:
        from transformers import pipeline
        _PIPE = pipeline("text2text-generation", model=os.environ.get("LOCAL_MODEL", "google/flan-t5-base"))
    return _PIPE(prompt, max_new_tokens=90, do_sample=False)[0]["generated_text"].strip()


def _hf(prompt: str) -> str:
    import requests
    model = os.environ.get("HF_MODEL", "google/flan-t5-base")
    r = requests.post(
        f"https://api-inference.huggingface.co/models/{model}",
        headers={"Authorization": f"Bearer {os.environ['HF_TOKEN']}"},
        json={"inputs": prompt, "parameters": {"max_new_tokens": 90}},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()[0]["generated_text"].strip()


def _claude(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-3-5-haiku-latest", max_tokens=140,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def _template(ctx: dict) -> str:
    # No model: phrase the leaderboard result straight from the numbers.
    # Deterministic, so it's what CI runs and what the committed sample uses.
    if ctx["rank"] is None:
        return (
            f"{ctx['country']} used about {ctx['demand_twh']:,.0f} TWh of electricity in "
            f"{ctx['year']}, currently {ctx['renew_now']:.0f}% renewables and "
            f"{ctx['fossil_pct']:.0f}% fossil. (No 2000 baseline, so it isn't ranked.)"
        )
    chg = ctx["change_pts"]
    if chg >= 20:
        pace = "a rapid shift to renewables"
    elif chg >= 8:
        pace = "a steady shift toward renewables"
    elif chg > 0:
        pace = "only a slow shift toward renewables"
    else:
        pace = "essentially no shift toward renewables"
    top = ctx["rank"] <= ctx["countries"] * 0.25
    standing = "near the top of" if top else "in the middle of" if ctx["rank"] <= ctx["countries"] * 0.6 else "near the bottom of"
    change_str = "roughly flat" if abs(chg) < 0.5 else f"{chg:+.0f} points"
    return (
        f"{ctx['country']} ranks {ctx['rank']} of {ctx['countries']} for growth in renewable "
        f"energy since 2000 — {standing} the pack, with {pace}. Renewables went from "
        f"{ctx['renew_2000']:.0f}% to {ctx['renew_now']:.0f}% of its energy "
        f"({change_str}), while it used {ctx['demand_twh']:,.0f} TWh of electricity in "
        f"{ctx['year']} ({ctx['fossil_pct']:.0f}% still fossil)."
    )


def main() -> int:
    engine = get_engine()
    snapshot, board = load_facts(engine)
    print(f"[ai] backend={BACKEND}  countries={len(snapshot)}")

    rows, md = [], [
        "# Decarbonisation narratives by country",
        f"_Backend: `{BACKEND}` · generated {dt.date.today()}_",
        "",
    ]
    for _, r in snapshot.iterrows():
        ctx = build_context(r, board)
        text = summarise(ctx)
        rows.append({
            "country": ctx["country"], "snapshot_year": ctx["year"],
            "briefing": text, "model_backend": BACKEND,
            "generated_at": dt.datetime.now(dt.timezone.utc),
        })
        md += [f"### {ctx['country']}", text, ""]
        print(f"[ai]   {ctx['country']}")

    # drop-then-append: to_sql("replace") reflects the table, which fails on
    # DuckDB re-runs (Postgres-only catalog). See load_energy_data.load().
    with engine.begin() as conn:
        conn.exec_driver_sql('DROP TABLE IF EXISTS ai_country_briefings')
        pd.DataFrame(rows).to_sql("ai_country_briefings", conn, if_exists="append", index=False)
    print(f"[ai] wrote {len(rows)} rows to 'ai_country_briefings'")

    os.makedirs("ai_output", exist_ok=True)
    with open(OUTPUT_MD, "w") as f:
        f.write("\n".join(md))
    print(f"[ai] wrote {OUTPUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
