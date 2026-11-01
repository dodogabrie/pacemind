# Race Calendar — Scraping & Geocoding

Operational reference for the `races` table: how to populate it from
external sources and how to finish coordinate backfill against the ORS
free-tier quota.

## Sources

| Source | Coverage | Script | Lat/lon? |
|---|---|---|---|
| Curated CSV | Hand-picked flagship races | `data/races_seed.csv` | Yes, in CSV |
| Sterrato Gang | Italian trail | `scripts/scrape_sterratogang.py` | No, needs geocode |
| DUV | International ultras | `scripts/scrape_duv.py` | No, needs geocode |
| UTMB World Series | UTMB-Index races | `scripts/scrape_utmb.py` | Yes, in JSON |

All scrapers write a CSV under `backend/data/`. `scripts/seed_races.py`
upserts on `(source, external_id)` — re-runs are idempotent.

## Run order

```bash
# 1. Scrape
docker compose exec backend python scripts/scrape_duv.py --year 2026
docker compose exec backend python scripts/scrape_duv.py --year 2027
docker compose exec backend python scripts/scrape_utmb.py
docker compose exec backend python scripts/scrape_sterratogang.py

# 2. Seed (idempotent)
docker compose exec backend python scripts/seed_races.py data/duv_2026.csv
docker compose exec backend python scripts/seed_races.py data/duv_2027.csv
docker compose exec backend python scripts/seed_races.py data/utmb_world_series.csv
docker compose exec backend python scripts/seed_races.py data/sterratogang.csv

# 3. Geocode rows missing lat/lon
docker compose exec backend python scripts/geocode_races.py
```

Smoke tests for the scrapers live under `tests/test_scrapers/` — run
`pytest tests/test_scrapers` after touching any parser.

## Source-specific notes

### DUV (`statistik.d-u-v.org`)
Server-rendered HTML, paginated 1000 rows/page. Total page count comes
from the `"X to Y of Z search results"` marker. Time-based events
(`24h`, `12h`, …) are filtered — they have no comparable distance.
DUV uses IOC-style country codes; unmapped codes log a warning and the
row is still emitted with empty country.

### UTMB (`utmb.world`)
Two-phase scrape:
1. Index page ships ~65 events as `__NEXT_DATA__` JSON with lat/lon.
2. Per-event tenant subdomain (e.g. `mrww.utmb.world`) ships a
   `listOfRaces` slice with the *real* per-race distance/elevation gain.

If a tenant fetch fails or the slice is missing, the row falls back to
the band-derived nominal km (`ws100M = 161 km` etc.) so an outage on
one subdomain doesn't drop the whole event. Some races are on
non-UTMB domains (e.g. WSER on `wser.org`) and always use fallback.

### Sterrato Gang
Regex-based card parser. Brittle to layout changes — the smoke test
fixture catches drift.

## Finishing coordinate backfill

UTMB rows arrive with lat/lon already populated. **DUV (~3,500 rows)
and Sterrato Gang (~380 rows) need geocoding** via ORS Pelias.

ORS free tier: **1,000 requests/day**, 40 req/min. The geocoder sleeps
1.6 s between calls (≈37/min) to stay under the rate limit.

Backlog of ~3,800 rows therefore takes **~4 days** of bounded runs:

```bash
# Day N: geocode up to today's quota
docker compose exec backend python scripts/geocode_races.py --limit 1000

# Final day: pick up everything left
docker compose exec backend python scripts/geocode_races.py
```

Recommended: install a local cron until the backlog clears.

```cron
# Daily DUV/Sterrato geocode pass — drop once the backlog is empty
0 9 * * * cd /home/edoardo/Documents/RnD/gpx_analyzer && \
  docker compose exec -T backend python scripts/geocode_races.py --limit 1000 \
  >> /tmp/geocode.log 2>&1
```

Remove the cron line once a daily run reports `0 races need geocoding`.

`scripts/geocode_races.py` only touches rows where
`lat IS NULL OR lon IS NULL`, so re-running is safe and incremental.
A miss leaves the row's coordinates NULL and the race stays invisible
to `_provider_db` in `services/race_calendar_service.py` until a future
geocode succeeds — track misses by re-running with `--limit` low and
inspecting the log.

## Health checks

```bash
# How many races are missing lat/lon, by source?
docker compose exec backend python -c "
from app import create_app
from models import Race
app = create_app()
with app.app_context():
    from sqlalchemy import func, or_
    from database import db
    rows = db.session.query(
        Race.source, func.count(Race.id),
        func.sum(func.cast(or_(Race.lat == None, Race.lon == None), db.Integer))
    ).group_by(Race.source).all()
    for src, total, missing in rows:
        print(f'{src:14s} total={total:5d}  missing_coords={missing or 0}')
"
```

## Adding a new source

1. Write `scripts/scrape_<source>.py` emitting the CSV columns
   consumed by `seed_races.py` (see existing scrapers for the schema).
2. Add a fixture + pytest under `tests/test_scrapers/` so future
   layout drift fails CI rather than silently scraping zero rows.
3. Use `source='<source>'` in the CSV — the upsert key is
   `(source, external_id)`, so cross-source duplicates are tolerated
   and dedupe happens at lookup time in `_dedupe_candidates`.
