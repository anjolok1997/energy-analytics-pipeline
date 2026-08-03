-- Decarbonisation leaderboard: which countries have shifted to renewables the
-- most since 2000. One transparent metric -- the change in renewables' share of
-- energy from 2000 to the latest year -- ranked across all countries that have a
-- 2000 baseline (so everyone is measured over the same window).

with series as (
    select iso_code, country, year, renewables_share_pct
    from {{ ref('mart_renewables_transition') }}
    where renewables_share_pct is not null
),

baseline as (
    select iso_code, renewables_share_pct as renewables_share_2000
    from series
    where year = 2000
),

latest as (
    select
        iso_code,
        country,
        year                as latest_year,
        renewables_share_pct as renewables_share_latest,
        row_number() over (partition by iso_code order by year desc) as rn
    from series
)

select
    l.iso_code,
    l.country,
    l.latest_year,
    -- cast to numeric so round(x, 1) is portable (Postgres has no round(double, int))
    round(cast(b.renewables_share_2000 as numeric), 1)                        as renewables_share_2000,
    round(cast(l.renewables_share_latest as numeric), 1)                      as renewables_share_latest,
    round(cast(l.renewables_share_latest - b.renewables_share_2000 as numeric), 1) as renewables_change_pts,
    row_number() over (order by l.renewables_share_latest - b.renewables_share_2000 desc) as rank_fastest,
    count(*) over ()                                                          as countries_ranked
from latest l
inner join baseline b on l.iso_code = b.iso_code
where l.rn = 1
