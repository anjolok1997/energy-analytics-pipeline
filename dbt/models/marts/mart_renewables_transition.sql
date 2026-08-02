-- Generation-mix shares per country over time, from 2000 on. Feeds the
-- renewables trend chart.

select
    f.iso_code,
    c.country,
    f.year,
    f.renewables_share_pct,
    f.low_carbon_share_pct,
    f.fossil_share_pct,
    f.electricity_emissions_mtco2e
from {{ ref('fct_country_energy') }} f
inner join {{ ref('dim_country') }} c
    on f.iso_code = c.iso_code
where f.year >= 2000
  and f.renewables_share_pct is not null
