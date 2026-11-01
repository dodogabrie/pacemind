# 00 — Strava coupling audit

**Status:** ✅ done (audit only, no code changes)
**Purpose:** map every place Strava is assumed, so the later phases can be
scoped honestly. All references verified against `main` at the time of writing.

---

## 1. Identity — hard block

| What | Where |
|---|---|
| `strava_user_id` is `nullable=False, unique=True` | `backend/models/user.py:42` |
| Only login path is Strava OAuth | `backend/api/auth.py:54` (auth url), `backend/api/auth.py:61` (callback) |
| User creation is Strava-shaped | `backend/repositories/user_repository.py:14` `find_or_create_from_strava` |
| Token storage lives on `User` (encrypted via Fernet) | `backend/models/user.py:46-48`, properties at `:79-107` |
| Token refresh endpoint | `backend/api/auth.py:150` |

**Implication:** there is no such thing as a PaceMind account today. A row in
`users` *is* a Strava athlete. This is the only genuine blocker — everything
else is refactoring.

Frontend equivalents: `frontend/src/components/AuthGate.vue`,
`frontend/src/stores/auth.js`, `frontend/src/App.vue`,
`frontend/src/router/index.js`.

## 2. Activity storage — medium block

`backend/models/strava_activity.py`:

```python
strava_id  = db.Column(db.BigInteger, nullable=False)   # no source column
name       = db.Column(db.String(255), nullable=False)
distance   = db.Column(db.Float, nullable=False)
start_date = db.Column(db.DateTime, nullable=False)
_streams   = db.Column('streams', db.JSON, nullable=True)
```

No `source`, no generic `external_id`, `strava_id` is `NOT NULL`.

### Consumers (read paths that must keep working)

| Service | Reference |
|---|---|
| Training load (ATL/CTL/TSB) | `backend/services/training_load_service.py:53`, `:90` |
| Performance tracker | `backend/services/performance_tracker.py:285` |
| Physics prediction (long-run lookup) | `backend/services/physics_prediction_service.py:139-146` |
| Training capacity inference | `backend/services/training_capacity_inference.py:230-236` |
| Agent knowledge tool | `backend/services/agent/tool_handlers/knowledge.py:143` |
| Route aggregation | `backend/api/routes.py:337` |
| Residual collection | `backend/services/user_residual_service.py` |
| Plan compliance | `backend/services/plan_compliance_service.py` |

### Write paths

| Path | Reference |
|---|---|
| Background sync creates rows | `backend/services/strava_sync_service.py:302` |
| Cache service creates/updates rows + writes streams JSON to disk | `backend/services/cache_service.py:117` |
| Repository lookups keyed by Strava id | `backend/repositories/strava_activity_repository.py:40` `get_by_strava_id` |

### Supporting tables

- `strava_activity_cache` (`backend/models/strava_activity_cache.py`) — 24h
  snapshot of the *activity list*, purely a Strava API-saving device.
- `sync_status` (`backend/models/sync_status.py`) — per-user background sync
  progress with `status`, `current_step`, `total_activities`,
  `downloaded_activities`. **Reusable as-is for file-import progress.**

## 3. Streams format — not actually coupled

The internal contract is the dict Strava returns, requested at
`backend/services/strava_service.py:132`:

```python
['time', 'altitude', 'grade_smooth', 'velocity_smooth',
 'heartrate', 'cadence', 'moving', 'distance', 'watts']
```

Consumers only require subsets of it:

| Consumer | Required keys |
|---|---|
| `services/physics_prediction_service.py:31` | `distance`, `velocity_smooth`, `grade_smooth` |
| `services/user_residual_service.py:64` | `distance`, `velocity_smooth`, `grade_smooth` |
| `services/performance_tracker.py:517` | `velocity_smooth`, `grade_smooth`, `moving` |
| `services/segmentation_service.py:79` | `velocity_smooth` (+ `altitude`, `distance`, `latlng`) |
| `services/physics_model/calibration.py:51` | `velocity_smooth`, `grade_smooth` (as DataFrame cols) |

**This format is derivable from any GPS track.** It is a good canonical
representation and we should keep it rather than invent a new one.

## 4. What is *not* coupled

- `services/physics_model/*` — pure functions over DataFrames.
- `services/segmentation_service.py` — operates on the streams dict.
- `services/plan_engine.py`, `plan_templates.py` — no Strava awareness.
- `services/gpx_parser.py` — already parses arbitrary GPX into
  `{latitudes, longitudes, elevations, times, waypoints}`, though **not** into
  the canonical streams shape (phase 1 bridges this).
- GPX upload endpoint exists (`backend/api/gpx.py:16`) but is for *route* files,
  not activities — different concern, do not overload it.

## 5. Dependency inventory

`backend/requirements.txt` has **no FIT/TCX parser** and no Garmin/Polar/COROS
client. `gpxpy==1.6.2` is the only track-parsing dependency. Phase 2 adds one.

## 6. Scope estimate

| Area | Files touched (approx.) |
|---|---|
| Identity | 6 backend + 5 frontend |
| Activity model + repo | 4 backend + 1 migration |
| Consumer call sites | ~10, mostly mechanical rename |
| Ingest service (new) | ~6 new files |
| Tests | `backend/tests/` — sync, performance tracker, compliance, agent fixtures all construct `StravaActivity` directly |
