-- Fact table at country-year grain. One numeric row per observation, joinable
-- to dim_country on iso_code.

select
    energy_key,
    iso_code,
    year,
    electricity_generation_twh,
    electricity_demand_twh,
    electricity_demand_per_capita_kwh,
    energy_per_capita_kwh,
    energy_intensity_kwh_per_dollar,
    electricity_emissions_mtco2e,
    renewables_share_pct,
    low_carbon_share_pct,
    fossil_share_pct
from {{ ref('stg_energy') }}
