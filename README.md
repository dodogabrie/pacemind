# PaceMind

**AI pacing coach for trail & ultra racing.** Predict your finish time on any GPX course, calibrate to your Strava history, and race with an AI advisor by your side.

[![CI](https://github.com/dodogabrie/trail_gpx_analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/dodogabrie/trail_gpx_analyzer/actions/workflows/ci.yml)
[![License: MPL 2.0](https://img.shields.io/badge/License-MPL_2.0-brightgreen.svg)](LICENSE)
[![Status: Beta](https://img.shields.io/badge/status-beta-orange.svg)]()

> Demo: _coming soon — add your staging URL here._

## Why PaceMind

Most "race time calculators" use a flat pace and a course elevation number. Trail runners know that isn't how a race actually unfolds.

- **Calibrated to you.** We read your Strava history to learn your climbing efficiency, downhill technique, and fatigue curve. Your physiology, not an average runner.
- **Terrain-aware.** A 15% grade on technical rock isn't 15% on fire road. We model surface, gradient, and cumulative elevation.
- **AI coach in your pocket.** Ask your race advisor anything — "where should I push?", "should I walk this climb?" — and get personalised, course- and weather-aware answers.
- **Honest by design.** PaceMind gives you a confidence interval, not a crystal ball.

## Who it's for

- Trail & ultra runners preparing 1–5 target races per year (50–170 km)
- Runners who want coaching-grade pacing without hiring a coach
- Private coaches (Coach & Team plan — waitlist)

## Pricing

| Plan | Price | For |
|---|---|---|
| **Free** | $0 | 1 prediction/month, 3 AI messages/day, physics baseline |
| **Premium** | $9/month or $79/year | 15 AI chats/day, 5 plans/month, race reports, weather, terrain, plan compliance, PDF export |
| **Race Day Pass** | $4 / 7 days | Premium features for race week — 8 chats/day, 2 plans across 7 days |
| **Coach & Team** | _coming soon_ | Dashboard for up to 10 athletes, white-label briefs, CSV export |

[Full pricing](https://pacemind.app/pricing) · Cancel anytime · 7-day money-back on first Premium subscription.

## How it works

A 3-tier hybrid prediction system:

1. **Physics baseline** (Minetti energy-cost model) — works with zero personal data.
2. **Parameter learning** — after 5 Strava activities, physics coefficients are personalised for you (uphill, downhill, flat, terrain).
3. **ML residual correction** — after 15 activities, a Gradient Boosting regressor learns the residual errors that pure physics can't capture.

**Enrichment:** OSM surface types (asphalt, gravel, rock, mud), Open-Meteo historical + forecast weather, ATL/CTL/TSB training load.

**AI layer:** Claude-powered race advisor with tool-use for plan editing, waypoint management, pacing strategy, and race briefings — with safety guardrails and per-plan rate limits.

## Quick Start

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in STRAVA_*, ANTHROPIC_API_KEY, optional STRIPE_*
flask db upgrade
python app.py          # http://localhost:5000

# Frontend (in a second terminal)
cd frontend
npm install
npm run dev            # http://localhost:5173
```

Required env vars in `backend/.env`: `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`. Optional but recommended: `ANTHROPIC_API_KEY` (AI advisor), `STRIPE_*` (billing).

## Components

- **[backend/](backend/)** — Flask REST API, prediction pipeline, AI agent, billing, race calendar.
- **[frontend/](frontend/)** — Vue 3 SPA, maps, charts, agent chat, billing UI.

## Tech Stack

**Backend:** Python 3.12, Flask, SQLAlchemy, Alembic, scikit-learn, scipy, pandas, gpxpy, anthropic, stripe, cryptography (Fernet).
**Frontend:** Vue 3, Vite, Pinia, Vue Router, Tailwind, Leaflet, ECharts, Axios.
**External APIs (free or pay-per-use):** Open-Meteo (weather), Overpass / OpenStreetMap (terrain), Strava (activities), Claude (advisor), Stripe (billing).

## Documentation

- **[CLAUDE.md](CLAUDE.md)** — architecture map, conventions, common commands.
- **[backend/MIGRATIONS.md](backend/MIGRATIONS.md)** — DB migration guards.
- **[backend/services/physics_model/README.md](backend/services/physics_model/README.md)** — Minetti model derivation.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — how to contribute, run tests, code style.
- **[CHANGELOG.md](CHANGELOG.md)** — release notes.
- **[ROADMAP.md](ROADMAP.md)** — what shipped + future direction.

## License

Mozilla Public License 2.0, see [LICENSE](LICENSE). Copyright (c) 2024-2026 Edoardo Gabrielli.

You can use PaceMind in any project, open or closed. If you change its files and distribute them, those changed files stay under MPL-2.0 and their source must be published.

Developed as an R&D project for trail running route analysis and AI-powered race advisory.
