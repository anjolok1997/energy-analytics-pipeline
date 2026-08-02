-- One row per country with its most recent known population and GDP.
-- row_number (not QUALIFY) keeps this portable across DuckDB / Postgres / BigQuery.

with ranked_pop as (
    select
        iso_code,
        country,
        population,
        row_number() over (
            partition by iso_code
            order by case when population is not null then year end desc nulls last
        ) as rn
    from {{ ref('stg_energy') }}
),

ranked_gdp as (
    select
        iso_code,
        gdp,
        row_number() over (
            partition by iso_code
            order by case when gdp is not null then year end desc nulls last
        ) as rn
    from {{ ref('stg_energy') }}
)

select
    p.iso_code,
    p.country,
    p.population    as latest_population,
    g.gdp           as latest_gdp
from ranked_pop p
left join ranked_gdp g
    on p.iso_code = g.iso_code and g.rn = 1
where p.rn = 1
