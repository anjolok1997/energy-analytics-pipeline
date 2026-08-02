-- Latest reported year per country, for ranking and comparison tiles.
-- Latest = most recent year where both demand and renewables share are present.

with reported as (
    -- only years where the key measures are actually published
    select *
    from {{ ref('fct_country_energy') }}
    where electricity_demand_twh is not null
      and renewables_share_pct is not null
),

demand_years as (
    select
        r.*,
        row_number() over (
            partition by r.iso_code
            order by r.year desc
        ) as rn
    from reported r
)

select
    d.iso_code,
    c.country,
    c.latest_population,
    c.latest_gdp,
    d.year                              as snapshot_year,
    d.electricity_demand_twh,
    d.electricity_generation_twh,
    d.electricity_demand_per_capita_kwh,
    d.energy_intensity_kwh_per_dollar,
    d.electricity_emissions_mtco2e,
    d.renewables_share_pct,
    d.fossil_share_pct
from demand_years d
inner join {{ ref('dim_country') }} c
    on d.iso_code = c.iso_code
where d.rn = 1
