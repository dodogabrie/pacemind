# Phase 1 — Activity abstraction

**Status:** 📋 planned
**Estimate:** ~1 week
**Depends on:** [Phase 0](01-identity-decoupling.md)
**Blocks:** phases 2 and 3

---

## Goal

An activity is a first-class PaceMind object with a `source`, not a Strava
record. Adding a source becomes "write a normalizer", not "touch ten services".

## Design decision: evolve the table, do not create a new one

`strava_activities` holds real user data and is read from ~10 services (see
[00 — coupling audit](00-coupling-audit.md#2-activity-storage--medium-block)).
A parallel `activities` table would mean a dual-write period, a data migration
and a long tail of "which table is authoritative" bugs.

Instead: **add columns, relax constraints, rename in place.**

### Schema changes

```
strava_activities -> activities            (rename table)

  strava_id     -> nullable=True           (kept for Strava rows / back-compat)
+ source          String(32)  NOT NULL  default 'strava'
+ external_id     String(128) nullable    -- provider's id, or a content hash
                                          -- for uploads
+ dedup_key       String(64)  nullable    -- see below
+ sport_type      String(32)  nullable    -- run / trail_run / hike / other
+ moving_time_s   Integer     nullable
+ elapsed_time_s  Integer     nullable
+ elevation_gain_m Float      nullable

  UNIQUE (user_id, source, external_id)
  INDEX  (user_id, dedup_key)
  keep   INDEX ix_strava_activity_user_date (user_id, start_date)
```

`StravaActivity` stays as a module-level alias of the new `Activity` class so
nothing breaks on day one:

```python
# backend/models/activity.py
class Activity(db.Model):
    __tablename__ = 'activities'
    ...

# backend/models/strava_activity.py  (deprecation shim, delete after migration)
from models.activity import Activity as StravaActivity  # noqa: F401
```

Then migrate call sites in a follow-up commit, mechanically, and delete the shim.

### Deduplication

The same run can arrive from Strava *and* from a Garmin FIT *and* from a bulk
zip. Dedup on a stable content key rather than on provider ids:

```python
dedup_key = sha256(f"{user_id}|{round(start_ts/60)}|{round(distance_m/50)}").hexdigest()[:32]
```

Minute-level start time and 50 m distance buckets absorb the small differences
between a device's own record and Strava's re-processing of it, without
collapsing genuinely distinct sessions.

**Amended in phase 2 (issue #83).** `round()` produces exact buckets, not a
tolerance: 21097 m and 21127 m are 30 m apart but hash into buckets 422 and
423, so the same session from two sources could still become two rows. The
stored key format is unchanged — no re-backfill — but the *lookup* is now a
two-step:

1. `dedup_candidate_keys()` enumerates the neighbouring `(minute, distance)`
   buckets, wide enough to cover the tolerance below, and probes them in one
   indexed `IN` query against `ix_activity_user_dedup` (exact bucket first).
2. `is_same_session()` confirms a candidate against the *real* start time and
   distance: +/-120 s, and `max(50 m, 0.5%)` of distance.

The distance tolerance is relative because a watch and a provider's
re-processing diverge further over a 170 km ultra than over a 5 km run; a fixed
50 m window is too tight for the former. The probe is capped at +/-1 km of
buckets so the key list stays small.

**Source precedence** when a duplicate arrives: `garmin > upload(.fit) > strava > upload(.gpx)`.
Rationale: the device's own FIT has sensor-derived distance and velocity; GPX is
the lossiest. On a higher-precedence arrival, replace the streams and record the
change; on a lower-precedence one, keep what we have and just link the id.

### Supporting tables

- `strava_activity_cache` — leave alone. It caches the *Strava activity list*
  and is a Strava-specific optimisation. Do not generalise it.
- `sync_status` — generalise: add `provider` (String(32), default `'strava'`)
  and relax the `user_id` unique constraint to `UNIQUE (user_id, provider)` so
  a Strava sync and a file import can be in flight simultaneously. The
  `current_step` vocabulary already fits (`selecting_activities`,
  `downloading_streams`, …); add `parsing_files`, `importing`.

## `ActivityIngestService` (new)

`backend/services/activity_ingest/`

```
__init__.py            -> ActivityIngestService, NORMALIZERS registry
normalizers/strava.py  -> wraps today's strava_sync_service payload
normalizers/fit.py     -> phase 2
normalizers/tcx.py     -> phase 2
normalizers/gpx.py     -> phase 2
streams.py             -> derive_streams(), the canonical builder
```

Every normalizer returns the same tuple:

```python
NormalizedActivity(
    source: str,
    external_id: str | None,
    name: str,
    start_date: datetime,       # tz-aware, UTC
    distance_m: float,
    moving_time_s: int | None,
    sport_type: str | None,
    streams: dict[str, list],   # canonical keys, see below
)
```

Canonical streams keys — note that `latlng` is **not** among the keys we
request from Strava today (`services/strava_service.py:132` asks for time,
altitude, grade_smooth, velocity_smooth, heartrate, cadence, moving, distance,
watts), so it is not stored for existing activities; decide explicitly whether
to start requesting it. The rest is what Strava returns, so no consumer
changes:

```
time, distance, altitude, latlng, velocity_smooth,
grade_smooth, moving, heartrate, cadence, watts
```

Missing keys are omitted, never zero-filled. Consumers already check for
presence (`physics_prediction_service.py:31`, `user_residual_service.py:64`,
`performance_tracker.py:517`).

`ActivityIngestService.ingest(user_id, normalized)` owns: dedup lookup,
precedence resolution, row upsert, streams persistence (filesystem + DB, reusing
`services/cache_service.py:117`'s path logic), and residual recollection
triggering.

## ⚠️ The distribution-drift risk — this phase owns it

Strava does not return raw data. `grade_smooth` and `velocity_smooth` are the
output of *their* smoothing. Our residual GBM
(`services/residual_ml_service.py`, features in `config/hybrid_config.py`) is
trained on that distribution. If `derive_streams()` computes grade with a
different window, the model goes out of distribution and **predictions degrade
with no error raised**.

### Mitigation, in order

1. **One derivation path.** `derive_streams(lat, lon, ele, time, distance=None)`
   in `activity_ingest/streams.py` is the *only* place non-Strava grade and
   velocity are computed. No normalizer rolls its own.
2. **Calibrate it against ground truth.** For a set of activities where we hold
   both the Strava streams and the original GPX/FIT, run both paths and compare:
   - distribution of `grade_smooth` (KS statistic, or simply p5/p50/p95)
   - `v_flat` from `physics_model/calibration.py:30`
   - end-to-end predicted time on a fixed GPX
   Tune the smoothing window until the deltas are inside an agreed tolerance
   (proposal: |Δv_flat| < 2%, |Δpredicted time| < 1.5%).

   > ⚠️ **TODO(strava-review) — consider inverting this.** Tuning a window to
   > match Strava's closed smoothing is reverse engineering a black box that
   > can change without notice, and the calibration only holds until it does.
   > `altitude` and `distance` are already stored for every Strava activity
   > (`services/strava_service.py:132`), so we can recompute `grade_smooth`
   > with *our* derivation across the whole history and retrain the residual
   > model on that. One distribution per source, by construction, instead of a
   > permanent dependency held inside a tolerance. Costs a retrain; decide
   > before phase 1 starts.
3. **Record the source on residuals.** Add `source` to `UserActivityResidual`
   so drift is *measurable* after the fact and can be corrected per-source if it
   turns out to be irreducible.
4. **Write the calibration as a test.** A fixture pair (Strava streams + the
   matching GPX) checked into `backend/tests/fixtures/`, asserting the tolerance
   above. This is what stops a future refactor from silently breaking it.

Do not ship [phase 2](03-file-ingest.md) until step 2 has produced a number.

## Migration

New Alembic revision. Guarded, per `backend/MIGRATIONS.md`:

1. `op.rename_table('strava_activities', 'activities')` (guard on existence of
   the old name — makes it re-runnable).
2. Add the new columns with server defaults, then backfill:
   `UPDATE activities SET source='strava', external_id=CAST(strava_id AS VARCHAR)`.
3. Backfill `dedup_key` with the formula above (doable in SQL, or a short Python
   data-migration loop — the table is small per user).
4. `alter_column('strava_id', nullable=True)`, then add the unique + index.

Rename the FK-referencing indices explicitly rather than relying on the DB to
carry them; SQLite (dev) and Postgres (prod) behave differently here — test both.

## Call sites to migrate (follow-up commit, mechanical)

`training_load_service.py:53,90` · `performance_tracker.py:285` ·
`physics_prediction_service.py:139-146` · `training_capacity_inference.py:230-236` ·
`agent/tool_handlers/knowledge.py:143` · `api/routes.py:337` ·
`user_residual_service.py` · `plan_compliance_service.py` ·
`repositories/strava_activity_repository.py` (rename to `ActivityRepository`,
keep `get_by_strava_id`, add `get_by_external_id(user_id, source, external_id)`)

Backend tests construct `StravaActivity(...)` directly in several places — the
alias keeps them green through the rename; update them in the same follow-up.

## Acceptance criteria

- [ ] `activities` table exists with `source`; all existing rows are `'strava'`.
- [ ] No behaviour change for existing users — same predictions, same plans.
      Verify by snapshotting a prediction before and after on the same input.
- [ ] `derive_streams()` calibrated, with the tolerance numbers written into
      this document and enforced by a test.
- [ ] `ActivityIngestService.ingest()` is the single write path for activities.
- [ ] Ingesting the same activity twice, from two sources, yields one row.
