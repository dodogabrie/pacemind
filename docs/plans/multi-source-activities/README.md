# Epic — Multi-source activities: decoupling PaceMind from Strava

**Status:** ⏸️ deferred (2026-09-11) — nothing implemented, and not next.
**Owner:** —
**Suggested branch:** `feat/multi-source-activities`

---

## Status update — 2026-09-11: we are staying on Strava for now

The epic was written assuming we had a compliance problem. We do not, at least
not in production:

- Tier 3 is **per-user**. `services/residual_ml_service.py` trains a GBM on one
  athlete's residuals and stores the blob in `UserResidualModel`; the backend
  never loads a global model from disk.
- The physics baseline is Minetti et al. (2002) — published literature, not
  athlete data (`services/physics_model/core.py:14`).
- The cross-athlete branch (`data_analysis/predictor/train.py`,
  `build_global_curve()`, `scraper/`) is **dead code**:
  `data_analysis/data/processed/` is empty and `residual_model.joblib` does not
  exist. Now marked deprecated in `CLAUDE.md`.

Showing an athlete their own prediction is explicitly preserved by Strava's
own announcement of the 2024-11-11 changes ("tools that help users understand
their data and performance"). So Strava stays.

**What still needs a decision, in priority order:**

1. **The agent → Anthropic path.** Sending Strava-derived data to a third-party
   LLM is the one thing likely to fail an app review; community reports say any
   mention of AI draws a rejection, and Strava has given no official answer on
   inference-vs-training. Unresolved.
2. **Developer program, from 2026-06-01.** Standard API access requires an
   active Strava subscription ($11.99/mo per developer, not per app). Verify
   ours before it breaks production login.
3. **Any future global model** must be trained on data users donate explicitly
   (vendor export upload), never on API data. That is the real reason to build
   [phase 2](03-file-ingest.md) — not the "no Strava account" UX story the
   phase currently leads with.

**Cheaper alternative to phases 0-2, if the goal is a usable day zero:** accept
a self-declared recent race result, convert it with the existing
`riegel_flat_pace()` (`services/vdot_service.py:125`) and feed `v_flat` to the
physics tier. One endpoint, no identity work, works for anonymous mobile
visitors. `generate_plan()` already takes declared athlete numbers as arguments
(`services/plan_engine.py:2732`), so plans work with zero activity data too.

**Before resuming this epic, fix the two design errors found in review:**
see the ⚠️ notes in [phase 1](02-activity-abstraction.md) (the `dedup_key`
formula does not deduplicate; the drift mitigation chases Strava's smoothing
instead of removing the dependency on it).

---

## Why

Today PaceMind is structurally a Strava app:

- **You cannot have a user without Strava.** `users.strava_user_id` is
  `nullable=False, unique=True` (`backend/models/user.py:42`) and the only login
  path is the Strava OAuth callback (`backend/api/auth.py:61`).
- **`strava_activities` is the only activity store**, read by ~10 services
  (training load, compliance, residual ML, agent tools, capacity inference…).
- Every runner we target already owns a Garmin / Suunto / COROS / Polar. Strava
  is a *relay* they happen to use, not the source of truth. Requiring it costs
  us signups and puts a third party between us and our core data.
- Strava's API terms have tightened around using athlete data to train models —
  worth verifying against current ToS before scaling, and a good reason not to
  depend on it exclusively.

The good news: **the scientific core is already source-agnostic.**
`services/physics_model/calibration.py:30` takes DataFrames with
`grade_smooth` / `velocity_smooth` / `distance`; `segmentation_service.py` and
`user_residual_service.py` work off a plain dict of arrays. Nothing in the model
layer knows about Strava. The coupling is entirely in **identity** and
**ingest plumbing**.

## Target architecture

```
     identity                      ingest                        domain
┌────────────────┐      ┌──────────────────────────┐      ┌──────────────────┐
│ User           │      │  ActivityIngestService   │      │ physics model    │
│  (email/OAuth) │      │                          │      │ segmentation     │
│                │      │  normalizers:            │      │ residual ML      │
│ UserConnection │─────▶│   strava   (API)         │─────▶│ training load    │
│  provider      │      │   garmin   (webhook/FIT) │      │ compliance       │
│  external_id   │      │   upload   (fit/tcx/gpx) │      │ agent tools      │
│  tokens        │      │   aggregator (later)     │      │                  │
└────────────────┘      └──────────────────────────┘      └──────────────────┘
                                     │
                                     ▼
                          canonical streams dict
             {time, distance, altitude, latlng, velocity_smooth,
              grade_smooth, moving, heartrate, cadence, watts}
                                     │
                                     ▼
                        activities table (source, external_id)
```

The canonical streams dict is **already** the de-facto internal contract — it is
exactly what Strava returns (`services/strava_service.py:132`). We keep it and
teach every other source to produce it.

## Phases

Read them in order; each is independently shippable.

| # | Plan | Est. | Cost | Blocks |
|---|---|---|---|---|
| 0 | [Identity decoupling](01-identity-decoupling.md) | 3-5 d | €0 | — |
| 1 | [Activity abstraction](02-activity-abstraction.md) | ~1 w | €0 | phase 0 |
| 2 | [Multi-format file ingest](03-file-ingest.md) | ~1 w | €0 | phase 1 |
| 3 | [Direct device integrations](04-device-integrations.md) | weeks (mostly waiting) | €0 | phase 1; **apply to Garmin on day 1** |
| — | [Aggregators: decision record](05-aggregators-decision.md) | — | $399+/mo | deferred, revisit on trigger |

Background reading: [00 — Coupling audit](00-coupling-audit.md) documents exactly
where Strava is wired in, with file/line references. Start there if you are
picking this epic up cold.

## Sequencing note

**Phase 3's Garmin application should be submitted on day 1**, in parallel with
phase 0 — it is free, and the review queue is measured in weeks. Everything else
runs on our own clock.

## Definition of done for the epic

- [ ] A user can sign up, upload a season of training, get a calibrated
      prediction and a training plan **without ever touching Strava**.
- [ ] Strava is one connection among several, revocable without account loss.
- [ ] Adding a new data source = one normalizer file + one registry entry.
- [ ] Predictions from non-Strava sources are validated to be within an agreed
      tolerance of Strava-sourced ones (see phase 1's distribution-drift risk).

## Key risk, stated once

Strava returns `grade_smooth` and `velocity_smooth` **already filtered by their
algorithm**. The residual GBM is trained on that distribution. If we compute
grade differently for uploaded files, the model silently goes out of
distribution and predictions degrade with no error surfacing. Phase 1 owns the
mitigation — do not ship phase 2 without it.
