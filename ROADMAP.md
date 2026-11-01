# Roadmap

## Shipped

The race-centered planning programme (Sprints 1–3) is in production. Highlights:

- **Plan editing & compliance** — `PATCH /api/training-plan/<id>`, `WorkoutCompletion` model, `PlanComplianceService` auto-matches Strava activities to planned workouts; weekly grid shows green/yellow/red compliance.
- **Race Dashboard** — `RaceDashboard.vue` with countdown, predicted time, compliance, fitness (TSB), embedded `AgentChat`. Backed by `GET /api/training-plan/<id>/dashboard`.
- **Adaptive agent coaching** — `get_plan_compliance` and `adjust_training_week` agent tools, with prompt rules for "only modify future weeks", taper preservation, and before/after confirmation.
- **Plan templates** — `plan_templates.py` (Trail 30K / 50K / 80K / Road Marathon) used by the agent as starting points.
- **Calendar export (ICS)** — `calendar_export_service.py` and `GET /api/training-plan/<id>/export/ics`.
- **Notifications** — `Notification` model + bell-icon UI for compliance summaries, coach suggestions, race countdowns.
- **Race calendar** — DB-backed `races` table, `RaceRepository`, public `/api/races` REST + `/races` UI, `search_tuneup_races` agent tool, A/B/C plan priority.
- **Billing & gating** — Stripe Checkout, `@requires_premium`, contextual `UpgradeModal`, race-day pass.
- **Race brief PDF** — `race_brief_service` for premium + race-day-pass users.

For the full architecture map, see [CLAUDE.md](CLAUDE.md).

## Future direction (Sprint 4 candidates)

Unranked — picked up as time and demand allow.

- **Race-day live tracking** — compare a live Strava activity against the pacing strategy in real time.
- **Crowd-sourced course difficulty** — when multiple users run the same GPX, surface predicted-vs-actual deltas to refine global priors.
- **Strava webhook** — replace polling-on-login with push-based activity sync (requires Strava webhook subscription).
- **Post-race AI report** — automatic comparison of actual splits vs prediction, identifying where time was gained/lost (extension of the existing race brief).
- **Email notifications** — currently in-app only; needs SendGrid/SES integration before this is worth shipping.
- **Social / coach sharing** — share a plan with a coach or training partner; collaborative editing.
- **Mobile (PWA)** — improve the offline / install experience for race-day use.
- **Garmin Connect / Coros ingestion** — alternatives to Strava for users on those ecosystems.
