# Phase 2 — Multi-format file ingest

**Status:** 🔨 backend implemented — **not shippable** until #82 lands
**Estimate:** ~1 week
**Depends on:** [Phase 1](02-activity-abstraction.md) — specifically a
calibrated `derive_streams()`
**Cost:** €0

---

## Goal

A new user with no Strava can bring a **season of training history in one drop**,
and it must not feel like data entry. Every watch vendor supports a bulk export;
we accept the archive as-is.

This is the phase that actually makes Strava optional in practice, and it costs
nothing but engineering time.

## The user-facing flow

```
1. "Import your training history"   → per-vendor instructions with a direct link
2. User requests their export       → vendor emails a zip (minutes to 48h)
3. User drags the zip onto PaceMind → background job, live progress bar
4. Done                             → calibration runs, predictions available
```

Vendor bulk exports (verify the links at implementation time, they move):

| Vendor | Route | Contents |
|---|---|---|
| Garmin | Account → *Export Your Data* (GDPR request) | zip of `.fit` |
| Suunto | Suunto app / account export | `.fit` / `.gpx` |
| Polar | Flow → Account → export | `.tcx` / `.gpx` |
| COROS | COROS app export | `.fit` / `.gpx` |
| Strava | Account → *Download or Delete Your Account* → request archive | `.fit.gz` / `.gpx.gz` / `.tcx.gz` + `activities.csv` |

Note the last row: a Strava archive import is a **useful escape hatch even for
Strava users**, because it sidesteps API rate limits and the ToS questions
around bulk pulls.

## Formats

| Format | Parser | Notes |
|---|---|---|
| `.fit` | `fitparse` or `garmin-fit-sdk` | **Preferred.** Sensor-derived distance and speed, plus HR, cadence, power. Better than anything we can reconstruct from coordinates. |
| `.tcx` | `lxml` / stdlib ElementTree | Has distance and HR per trackpoint. |
| `.gpx` | `gpxpy` (already a dependency) | Lossiest — coordinates and elevation only; distance and velocity must be derived. |
| `.gz` | stdlib | Strava archives ship gzipped. |
| `.zip` | stdlib | The container. |

Add exactly one dependency to `backend/requirements.txt`. `fitparse` is the
lighter, more permissive option; `garmin-fit-sdk` is official and tracks new FIT
messages faster. Recommendation: **`fitparse`**, and revisit only if we hit an
unparsable file in the wild.

## Implementation

### Endpoints

```
POST   /api/activities/import        multipart, one archive or N loose files
GET    /api/activities/import/status SSE or poll, backed by sync_status
DELETE /api/activities/import        cancel an in-flight import
```

Reuse the existing background-job shape from
`backend/services/strava_sync_service.py:37` (`sync_user_async` →
`_sync_user_background`) and the `sync_status` row (now keyed by
`(user_id, provider)` after phase 1). The frontend already knows how to render
that progress — `frontend/src/stores/sync.js`.

**Do not extend `backend/api/gpx.py:16`.** That endpoint uploads *route* files
for prediction; activities are a different object with a different lifecycle.
Sharing it would conflate the two and confuse both the API and the UI.

### Processing rules

- **Stream, don't load.** A Garmin export can be 800 files / several hundred MB.
  Extract to a temp dir, process file by file, delete as you go. Cap the upload
  size and reject archives above it with a clear message.
- **Filter by sport.** Only running / trail running / hiking feed the model.
  Cycling and swimming from the same export must be skipped, not silently
  averaged into training load.
- **Partial failure is normal.** One corrupt FIT must not abort the import.
  Collect per-file errors, finish the rest, and report
  "812 imported, 3 skipped (unreadable)" with the filenames.
- **Idempotent.** Re-dropping the same zip changes nothing, thanks to
  `dedup_key` from phase 1.
- **Trigger downstream work once**, at the end: calibration
  (`physics_model/calibration.py`), residual collection, tier-2/tier-3 training
  (`strava_sync_service.py:346,368`) — not once per file.

### Time zones

FIT stores UTC; GPX may carry an offset or nothing; TCX is usually UTC. Normalize
to tz-aware UTC in the normalizer, and derive the *local* date from the
activity's start coordinates when we need a calendar day (training load and plan
compliance bucket by day — an off-by-one here shifts a whole week's ATL/CTL).

## Frontend

- New `ActivityImport.vue`: dropzone, per-vendor instruction accordion,
  progress, result summary with the skipped-file list.
- Surface it in the empty states that currently say "connect Strava"
  (`Predict.vue`, `Training.vue`, `ActivitySelector.vue`).
- i18n: en + it, per the project convention.

## Risks

| Risk | Mitigation |
|---|---|
| Derived streams from `.gpx` differ from Strava's → prediction drift | Owned by phase 1; this phase must not ship before that tolerance number exists |
| Large upload times out behind Nginx | Raise `client_max_body_size` in `frontend/nginx.conf`; accept the file and process async so the request returns fast |
| Zip-bomb / path traversal in archives | Validate member paths, cap uncompressed size and member count, extract into a per-job temp dir |
| Disk fills up from streams JSON | `cache_service` already writes streams to the filesystem; measure per-activity size and set a retention/compression policy before inviting bulk imports |

## Shipped in the backend

| Piece | Where |
|---|---|
| Normalizers | `backend/services/activity_ingest/normalizers/{fit,tcx,gpx}.py`, registered in `NORMALIZERS` |
| Archive guards | `backend/services/activity_ingest/archive.py` (zip bomb, path traversal, per-member and total caps) |
| Background job | `backend/services/activity_import_service.py` (`provider='upload'` on `sync_status`) |
| Endpoints | `backend/api/activities.py` — POST/GET/DELETE `/api/activities/import` |
| Dependency | `fitparse` (the one allowed addition); TCX via stdlib ElementTree, GPX via `gpxpy`, `.gz`/`.zip` via stdlib |
| Upload ceiling | 512 MB — `MAX_UPLOAD_BYTES`, `Config.MAX_CONTENT_LENGTH`, and a `location /api/activities/import` block in `nginx/{dev,prod}.conf` |
| Local calendar day | `activities.start_date_local` + `Activity.local_date`, consumed by `plan_compliance_service` |

**Release gate:** `derive_streams()` is still uncalibrated (issue #82). Every
non-FIT import goes through it, so the distribution-drift risk in the table
above is live. Do not put this in front of users before that tolerance number
exists.

## Acceptance criteria

- [ ] Drop a real Garmin export zip → activities appear, sport-filtered,
      deduped, with a progress bar throughout.
- [ ] Same for a Strava archive zip and a Polar TCX export.
- [ ] Re-importing the same archive is a no-op.
- [ ] A corrupt file is reported, not fatal.
- [ ] After import, calibration and a prediction run end-to-end with zero
      Strava API calls.
