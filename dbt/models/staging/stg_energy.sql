-- Clean, typed, one row per (country, year).
-- Filters out non-country aggregates: OWID mixes real countries with roll-ups
-- like 'World' or 'Europe (Ember)', and only real countries carry a 3-letter
-- ISO code. Also builds a surrogate key for uniqueness testing.

with source as (
    select * from {{ source('raw', 'raw_energy') }}
),

cleaned as (
    select
        country,
        iso_code,
        cast(year as integer)                          as year,
        cast(population as double)                      as population,
        cast(gdp as double)                            as gdp,
        cast(electricity_generation as double)         as electricity_generation_twh,
        cast(electricity_demand as double)             as electricity_demand_twh,
        cast(electricity_demand_per_capita as double)  as electricity_demand_per_capita_kwh,
        cast(energy_per_capita as double)              as energy_per_capita_kwh,
        cast(energy_per_gdp as double)                 as energy_intensity_kwh_per_dollar,
        cast(greenhouse_gas_emissions as double)       as electricity_emissions_mtco2e,
        cast(renewables_share_energy as double)        as renewables_share_pct,
        cast(low_carbon_share_energy as double)        as low_carbon_share_pct,
        cast(fossil_share_energy as double)            as fossil_share_pct,
        cast(solar_share_energy as double)             as solar_share_pct,
        cast(wind_share_energy as double)              as wind_share_pct
    from source
    -- keep only real countries (3-letter ISO code), drop aggregates
    where iso_code is not null
      and length(iso_code) = 3
)

select
    -- surrogate key: unique per country-year, safe to test
    iso_code || '-' || cast(year as varchar) as energy_key,
    *
from cleaned
