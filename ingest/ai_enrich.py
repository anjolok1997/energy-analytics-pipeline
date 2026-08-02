"""
Generate a short text briefing per country from the marts and write them back to
the warehouse (ai_country_briefings) so the dashboard can show text next to the
numbers.

    marts -> model -> ai_country_briefings + ai_output/sample_briefings.md

AI_BACKEND picks the generator:
    local     flan-t5 via transformers, runs offline on CPU (default)
    hf        Hugging Face inference API (needs HF_TOKEN)
    claude    Anthropic API (needs ANTHROPIC_API_KEY)
    template  no model, just formats the facts; used in CI and for the sample
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
        select country, snapshot_year, electricity_demand_twh,
               renewables_share_pct, fossil_share_pct, electricity_emissions_mtco2e
        from {schema}.mart_latest_snapshot
        order by electricity_demand_twh desc
        limit {TOP_N}
        """,
        engine,
    )
    trend = pd.read_sql(
        f"""
        select country, year, renewables_share_pct
        from {schema}.mart_renewables_transition
        where year = 2000
        """,
        engine,
    )
    return snapshot, trend


def build_context(row: pd.Series, trend: pd.DataFrame) -> dict:
    hist = trend[trend["country"] == row["country"]].set_index("year")["renewables_share_pct"]
    return {
        "country": row["country"],
        "year": int(row["snapshot_year"]),
        "demand_twh": float(row["electricity_demand_twh"]),
        "fossil_pct": float(row["fossil_share_pct"]),
        "renew_now": float(row["renewables_share_pct"]),
        "renew_2000": float(hist.get(2000)) if 2000 in hist.index else None,
    }


def make_prompt(ctx: dict) -> str:
    if ctx["renew_2000"] is not None:
        change = (
            f"renewables' share of energy rose from {ctx['renew_2000']:.1f}% in 2000 "
            f"to {ctx['renew_now']:.1f}% in {ctx['year']}"
        )
    else:
        change = f"renewables make up {ctx['renew_now']:.1f}% of energy in {ctx['year']}"
    return (
        f"Write a concise two-sentence briefing on {ctx['country']}'s electricity system "
        f"for a data-centre industry audience. Facts: electricity demand "
        f"{ctx['demand_twh']:.0f} TWh; fossil fuels {ctx['fossil_pct']:.1f}% of energy; "
        f"{change}. Mention what the fossil/renewable mix implies for large power "
        f"consumers like data centres."
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
    # No model: build the sentence straight from the numbers. Deterministic, so
    # it's what CI runs and what the committed sample uses.
    if ctx["fossil_pct"] >= 60:
        grid = f"a fossil-heavy grid ({ctx['fossil_pct']:.0f}% fossil, {ctx['renew_now']:.0f}% renewables)"
        implication = "meaningful exposure to fossil generation and carbon-intensive power for large consumers such as data centres"
    elif ctx["renew_now"] >= 40:
        grid = f"a notably clean grid ({ctx['renew_now']:.0f}% renewables)"
        implication = "ample low-carbon headroom for power-hungry infrastructure such as data centres"
    else:
        grid = f"a transitioning grid ({ctx['fossil_pct']:.0f}% fossil, {ctx['renew_now']:.0f}% renewables)"
        implication = "a mixed carbon profile for large power consumers such as data centres"
    trend = (
        f" up from {ctx['renew_2000']:.0f}% renewables in 2000"
        if ctx["renew_2000"] is not None
        else ""
    )
    return (
        f"{ctx['country']} drew about {ctx['demand_twh']:,.0f} TWh of electricity in "
        f"{ctx['year']}, on {grid}{trend}. That implies {implication}."
    )


def main() -> int:
    engine = get_engine()
    snapshot, trend = load_facts(engine)
    print(f"[ai] backend={BACKEND}  countries={len(snapshot)}")

    rows, md = [], [
        "# Energy briefings by country",
        f"_Backend: `{BACKEND}` · generated {dt.date.today()}_",
        "",
    ]
    for _, r in snapshot.iterrows():
        ctx = build_context(r, trend)
        text = summarise(ctx)
        rows.append({
            "country": ctx["country"], "snapshot_year": ctx["year"],
            "briefing": text, "model_backend": BACKEND,
            "generated_at": dt.datetime.now(dt.timezone.utc),
        })
        md += [f"### {ctx['country']}", text, ""]
        print(f"[ai]   {ctx['country']}")

    with engine.begin() as conn:
        pd.DataFrame(rows).to_sql("ai_country_briefings", conn, if_exists="replace", index=False)
    print(f"[ai] wrote {len(rows)} rows to 'ai_country_briefings'")

    os.makedirs("ai_output", exist_ok=True)
    with open(OUTPUT_MD, "w") as f:
        f.write("\n".join(md))
    print(f"[ai] wrote {OUTPUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
