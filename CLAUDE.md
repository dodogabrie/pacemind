# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PaceMind (formerly GPX Analyzer) is a full-stack web application for analyzing GPX running routes with ML-based time prediction, Strava integration, and AI-powered race coaching. It predicts segment-by-segment completion times using gradient boosting, calibrated to individual runners via their Strava history, and generates personalized training plans.

## Architecture

The project has four independent components, each with its own virtualenv/node_modules:

```
gpx_analyzer/
├── backend/       # Flask REST API (Python 3.12, SQLite, SQLAlchemy)
├── frontend/      # Vue 3 SPA (Vite, Tailwind, Leaflet, ECharts)
└── tests/         # Root-level integration tests (legacy)
```

### Backend (`backend/`)

Flask app factory pattern in `app.py` with `create_app()`. Key layers:

- **API blueprints** (`api/`): `auth`, `gpx`, `strava`, `prediction`, `performance`, `physics`, `hybrid`, `agent`, `demo`, `billing`, `training_plan`, `weather`, `notifications`, `routes` — each registered in `app.py`
- **Services** (`services/`): Business logic. Core prediction flow:
  - `physics_model/core.py` — Minetti-based physics pace model
  - `physics_model/calibration.py` — Flat pace extraction from Strava activities
  - `physics_model/pipeline.py` — Physics prediction pipeline
  - `hybrid_prediction_service.py` — Picks the tier; finish = moving × effort + learned passive stops + aid stops; 80 % interval
  - `segmentation_service.py` — Splits GPX into 50m segments with grade features
  - `residual_ml_service.py` — Tier 3 "your habits": ridge on fixed 200 m bins, target log(actual / Tier 2 physics) with params fitted only on earlier runs; per-user gate (beats Tier 2 on the last 20 walk-forward runs, ≥ 15) stored in `user_residual_models.metrics`; used only when the gate is open (#107)
  - `intensity_service.py` — HR intensity: speed-vs-%HRR fit (bursts inside easy runs), effort → intensity (race intensity falls with duration, prior + learned from confirmed races); Tier 2 × (I/I_ref)^-b (#108)
  - `race_detection_service.py` — scores activities as likely races (name, calendar race same day + place, planned race, effort, weekend morning); only Strava's flag or the user sets `Activity.is_race`
  - `parameter_learning_service.py` — Tier 2: `eligible_activities` (runs with streams, excluded + km-effort quality rule), `fit_params` (`calibrate_user_params` on the last 10), `stop_share`, `walk_forward` rows (shared by the interval, the race ratio, the HR intensity model and Tier 3) → conformal `prediction_interval` + `accuracy`; `train_async` for background retrains
  - `user_residual_service.py` — residual collection; feeds no model, only the Training include/exclude list (GH #100)
  - `agent/` — LLM-powered race advisor agent (Claude API with tool_use, tools defined in `tools.py`, handlers in `tool_handlers.py`, safety guardrails in `safety.py`, prompts in `prompts.py`). Conversations persisted to Postgres via `AgentConversation` model. Daily Anthropic token budget enforced per user.
- **Training plan services** (`services/`):
  - `plan_engine.py`, `plan_templates.py`, `plan_compliance_service.py` — training plan generation, templates, compliance scoring
  - `workout_service.py` — workout completion tracking
  - `season_planning_service.py` — multi-race season planning
  - `route_generation_service.py` — ORS-based route generation for training routes
  - `pace_zone_service.py` — pace zone calculation
  - `calendar_export_service.py` — iCal export
- **Race reporting** (`services/`):
  - `race_report_service.py`, `race_brief_data.py`, `race_brief_pdf.py` — downloadable race brief PDF (Premium + Race Day Pass)
- **Race calendar** (`services/`, `api/`):
  - `race_calendar_service.py` — primary DB-backed lookup (curated `races` table) merged with optional ITRA/FIDAL providers; reused by the agent's `search_tuneup_races` and the public `/api/races` endpoint. Scoring (`_score_race`) is shared so agent + UI rank identically.
  - `api/races.py` — public REST: `GET /api/races` (filters: date, country, distance, elev, surface, type, near_lat/lon + max_travel_km; sort: date|distance|fit_score), `GET /api/races/<id>`, `GET /api/races/by-slug/<slug>`, `POST /api/races/<id>/plan` (auth, idempotent on (user, race), creates a draft TrainingPlan with priority A/B/C), `GET /api/races/me/preferences`.
  - Seed data: `backend/data/races_seed.csv` + `backend/scripts/seed_races.py` (idempotent upsert on `source, external_id`).
- **Data enrichment services** (`services/`):
  - `weather_service.py` — Open-Meteo API for historical weather + forecasts, computes performance impact
  - `osm_terrain_service.py` — Overpass API for surface types (asphalt, gravel, dirt, rock, mud) and trail classification
  - `training_load_service.py` — ATL/CTL/TSB fitness/fatigue metrics from Strava activities
  - `notification_service.py` — in-app notifications
- **Monetization** (`api/billing.py`, `models/user_subscription.py`, `models/waitlist_signup.py`): Stripe integration for subscriptions (free, premium monthly/yearly, race day pass); waitlist signups persisted to DB
- **Repositories** (`repositories/`): Data-access layer; all inherit `BaseRepository[T]` and are registered in `repositories/__init__.py`. One repo per model.
- **Models** (`models/`): SQLAlchemy models, registered in `models/__init__.py`. Includes `User`, `StravaActivity`, `StravaActivityCache`, `GpxFile`, `Prediction`, `Race`, `RaceResult`, `TrainingPlan` (with `race_id` FK to `Race`), `TrainingRoute`, `WorkoutCompletion`, `UserTrainingPreferences`, `UserSubscription`, `WaitlistSignup`, `AgentConversation`, `AgentParamSnapshot`, `Notification`, `TerrainCache`, `WeatherCache`, `UserLearnedParams`, `UserResidualModel`, `UserActivityResidual`, `PerformanceSnapshot`, `GradePerformanceHistory`, `EvaluationStatus`, `SyncStatus`, `UserAchievement`. DB defaults to SQLite at `backend/instance/gpx_analyzer.db`, supports PostgreSQL via `DATABASE_URL` (production default).
- **Migrations**: Alembic via Flask-Migrate in `backend/migrations/`. See `backend/MIGRATIONS.md` for guards/idempotency rules.
- **Config**: `config/__init__.py` loads from `backend/.env`, `config/hybrid_config.py` has tier thresholds and default physics params

### Frontend (`frontend/`)

Vue 3 + Vite SPA:
- **Views** (`src/views/`): `Home`, `Analysis`, `Predict`, `Prediction`, `Training`, `TrainingPlan`, `RaceDashboard`, `RaceReport`, `Races` (public race calendar), `Routes`, `SeasonOverview`, `Demo` (anonymous UTMB demo), `Pricing`, `HowItWorks`, `About`, `Privacy`, `AuthSuccess`, `AuthError`
- **Stores** (`src/stores/`): Pinia stores for `auth`, `gpx`, `map`, `physics`, `prediction`, `subscription`, `notifications`, `routes`, `races`, `sync`, `trainingPlan`
- **Components** (`src/components/`): `MapView` (Leaflet), `ElevationProfile`/`ElevationPaceProfile` (ECharts), `AgentChat`, `PredictionResults`, `PredictionTrendChart`, `ActivitySelector`, `UpgradeModal`, `StatsPanel`, `CalibrationEditor`, `AchievementNotification`, `AnnotationModal`, `HowItWorksCharts`, `WeatherWidget`, `NotificationBell`, `PaceZoneSettings`, `PlanOverviewHeatmap`, `WeeklyPlanView`, `WorkoutBuilder`, `RaceHeader`, `RaceDetailPanel`/`RacesMap`, `RouteBrowser`/`RouteCreatePanel`/`RouteDetailPanel`/`RoutePreviewMap`/`RoutesMap`/`RoutesPanel`/`RouteThumb`
- **i18n**: Vue-i18n with locale files in `src/locales/` (en, it). Pricing values are hardcoded in `Pricing.vue` + locale files — must be updated atomically.

### Prediction Pipeline (core domain logic)

1. User uploads GPX → parsed into segments (50m) with grade features
2. Tier 2 (≥ 5 eligible runs): physics params calibrated on the user's last 10 eligible stream runs (`parameter_learning_service.fit_params`); Tier 1: `hybrid_config.DEFAULT_PARAMS`
3. Physics model predicts moving pace per 50 m segment (grade, fatigue, altitude); Tier 3 per-200 m habits if the user's gate is open; effort → heart-rate intensity when the user has HR (`intensity_service`), else ×0.95 (or learned race ratio) / ×1.05
4. Finish = moving + learned passive-stop share + user-entered aid stops; 80 % interval from walk-forward log errors on the user's own runs (conformal ranks)
5. Results: finish, moving + stops, interval, accuracy (`p80_pct`, `n`), 1km breakdown
6. Measure any change with the walk-forward harness (read-only): `docker exec -w /app/backend -e RUN_MIGRATIONS=0 trail-backend-1 python scripts/backtest_predictions.py --user 3 [--tier3] [--json out.json]`

## Common Commands

### Backend
```bash
cd backend
source venv/bin/activate
python app.py                          # Run dev server (port 5000)
pytest                                 # Run all backend tests
pytest tests/test_agent/               # Agent tests only
pytest -m "not slow"                   # Skip slow tests (model training)
pytest tests/test_services/test_personal_model.py::test_gate_rules  # Single test
```

### Frontend
```bash
cd frontend
npm run dev      # Dev server (port 5173)
npm run build    # Production build to dist/
```

### Database Migrations
```bash
cd backend
source venv/bin/activate
flask db migrate -m "description"      # Generate migration (REVIEW carefully, see backend/MIGRATIONS.md)
flask db upgrade                       # Apply migrations
./scripts/db-migrate.sh                # Backup + lint + upgrade (preferred)
./scripts/db-backup.sh [label]         # On-demand backup → backend/backups/
./scripts/lint_migration.sh            # Catch bad auto-generated migrations
```
Dev default: `RUN_MIGRATIONS=0` — migrations are explicit, not on every restart.

### Docker
```bash
docker compose up backend              # Run backend in container
docker compose run backend-test        # Run tests in container
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d  # Production (PostgreSQL, Gunicorn, Nginx)
```

### CI/CD
No GitHub Actions while the repo is private (minutes cost money): run tests on the tuf with `rtest`. CI (ruff + pytest) gets added only after the repo goes public (#138).

### Seed the race calendar
```bash
cd backend && python scripts/seed_races.py            # uses data/races_seed.csv
cd backend && python scripts/seed_races.py path.csv   # custom CSV
```

## Testing

Backend tests live in `backend/tests/` with pytest. Config in `backend/pytest.ini`.

- **Prediction tests** (`tests/test_services/test_param_fit.py`, `test_personal_model.py`, `test_intensity.py`, `test_race_detection.py`): Tier 2 fit, Tier 3 no-leak/grid/gate, HR intensity, race detector + flag + migration. Synthetic data, in-memory SQLite.
- **Agent tests** (`tests/test_agent/`): Agent service, safety guardrails, tool handlers
- **Root tests** (`tests/`): Legacy integration tests for rate limiter, Strava API, database, physics model, prediction pipeline, performance metrics
- Markers: `@pytest.mark.slow` (trains real models), `@pytest.mark.manual` (baseline updates)

## Environment Variables

Backend `backend/.env` (see also `.env.example` at root):
```
STRAVA_CLIENT_ID=...
STRAVA_CLIENT_SECRET=...
FLASK_SECRET_KEY=...        # Auto-generated in dev mode if missing
JWT_SECRET_KEY=...          # Auto-generated in dev mode if missing
DATABASE_URL=...            # PostgreSQL URI for prod (defaults to SQLite in dev)
STRIPE_SECRET_KEY=...       # Stripe billing integration
STRIPE_WEBHOOK_SECRET=...
STRIPE_PRICE_MONTHLY=...
STRIPE_PRICE_YEARLY=...
STRIPE_PRICE_RACE_DAY=...
```

## Key Configuration

- Tier thresholds, `TIER3_ENABLED`, segment grid: `backend/config/hybrid_config.py`; Tier 3 features/shrinkage/gate constants: `services/residual_ml_service.py`
- CORS origins default: `http://localhost:5173`
- DB: SQLite at `backend/instance/gpx_analyzer.db` (dev), PostgreSQL via `DATABASE_URL` (prod)
- Frontend API base: configured in Vite, points to `http://localhost:5000`

## Production Deployment

- `docker-compose.prod.yml` — Production overrides (PostgreSQL, Gunicorn, Nginx with rate limiting)
- `frontend/Dockerfile` — Multi-stage build (Node build + Nginx serve)
- `frontend/nginx.conf` — Rate limiting zones for API (60r/m) and auth (10r/m)
- `scripts/deploy.sh` — Deployment helper script (backs up DB, fails fast on migration error)
- `scripts/cleanup-agent-conversations.sh` — Periodic pruning of agent chat history
- `docker-compose.override.yml` — Symlink to `docker/docker-compose.dev.yml` (dev overrides, bind-mounts entrypoint.sh)

## Tracking Issues You Don't Fix In-Session

If during a task you discover a bug, a coaching/scientific mismatch, a code smell, or a design limitation that you cannot or should not fix in the current session (out of scope, too large, would require user input, etc.), you MUST persist it in BOTH places before ending the session — chat-only mentions disappear when the session closes:

1. **Inline `TODO` comment at the source location** so the next person touching that code sees it. Format:

   ```python
   # TODO(<tag> #<n> — see GH issues): <one-line summary>.
   # <2-4 line context: root cause, why not fixed now, sketch of the fix>.
   ```

   Use a stable `<tag>` per audit (e.g. `coach-review`, `security-review`, `perf-audit`) so related TODOs cluster grep-ably. The `#<n>` matches the GH issue number once known.

2. **GitHub issue** on `dodogabrie/trail_gpx_analyzer` via the `mcp__github__issue_write` tool (`method: 'create'`). Include:
   - Reproducer (inputs that trigger it) + observed vs. expected behaviour.
   - File / line references (the same lines that carry the TODO comment).
   - Citations to coaching / scientific literature when relevant (the project mixes coding and domain best practices).
   - Suggested fix sketch.
   - Label with the audit tag (e.g. `coach-review`).

After both are in place, mention them in your end-of-session summary with the issue numbers, so the user can prioritise.

Do NOT skip this even when the user only asked you to fix something else — the cost of recording an issue is small, and the cost of a regression silently re-introducing a known-bad pattern is high.

## Strava data rule

Strava's API Agreement (since 2024-11-11) forbids AI/ML on Strava data and
showing one user's data to another. Every model here is per-user and trained at
runtime (Tier 2 params, Tier 3 ridge in `UserResidualModel`). Never add
cross-athlete training, scrapers or a global curve built from many athletes.
