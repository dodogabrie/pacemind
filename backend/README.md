# Backend — Flask API

Flask REST API for GPX analysis, hybrid time prediction (physics + ML), Strava integration, AI race advisor, training plans, race calendar, and Stripe billing.

For the full architecture map (blueprints, services, models, repositories), see **[../CLAUDE.md](../CLAUDE.md)**.

## Quick Start

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in credentials
flask db upgrade
python app.py          # http://localhost:5000
```

## Environment

Minimum required in `backend/.env`:

```
STRAVA_CLIENT_ID=...
STRAVA_CLIENT_SECRET=...
```

Optional:

```
ANTHROPIC_API_KEY=...           # AI race advisor
DATABASE_URL=postgresql://...   # defaults to SQLite at instance/gpx_analyzer.db
FLASK_SECRET_KEY=...             # auto-generated in dev if missing
JWT_SECRET_KEY=...               # auto-generated in dev if missing
STRIPE_SECRET_KEY=...
STRIPE_WEBHOOK_SECRET=...
STRIPE_PRICE_MONTHLY=...
STRIPE_PRICE_YEARLY=...
STRIPE_PRICE_RACE_DAY=...
```

## Common Commands

```bash
# Run dev server
python app.py

# Tests
pytest                           # all tests
pytest tests/test_agent/         # agent only
pytest -m "not slow"             # skip model-training tests

# Database
./scripts/db-migrate.sh          # backup + lint + upgrade (preferred)
flask db migrate -m "message"    # generate migration (review per MIGRATIONS.md)
flask db upgrade                 # apply
./scripts/db-backup.sh [label]   # on-demand backup → backend/backups/

# Race calendar
python scripts/seed_races.py     # load curated race seed (idempotent)

# Speed up startup
python scripts/cache_global_curve.py    # pre-computes pace-grade curve
```

Dev default: `RUN_MIGRATIONS=0` — migrations are explicit, not auto-applied on every restart.

## Layout

```
backend/
├── api/             # Flask blueprints (auth, gpx, strava, agent, billing, ...)
├── services/        # Business logic (physics_model/, agent/, plan_engine, ...)
├── models/          # SQLAlchemy models
├── repositories/    # Data-access layer (BaseRepository[T])
├── config/          # hybrid_config.py, agent_config.py
├── migrations/      # Alembic — see MIGRATIONS.md
├── scripts/         # Maintenance + cache + seed loaders
├── data/            # Coaching knowledge corpus, race seed CSV
└── tests/           # pytest (see pytest.ini)
```

## Docs

- **[../CLAUDE.md](../CLAUDE.md)** — full architecture, blueprints, services, models.
- **[MIGRATIONS.md](MIGRATIONS.md)** — Alembic guards and idempotency rules.
- **[services/physics_model/README.md](services/physics_model/README.md)** — Minetti model and velocity equations.

## Troubleshooting

- **Slow startup (~30s):** run `python scripts/cache_global_curve.py`.
- **"ML model not found":** train via `cd ../data_analysis && python predictor/train.py`.
- **"STRAVA_CLIENT_ID not found":** create `backend/.env` from `.env.example`.
- **CORS errors:** check `CORS_ORIGINS` in `config.py` matches the frontend URL.
- **Stripe webhook (local):** `stripe listen --forward-to localhost:5000/api/billing/webhook`.
