# Test fixtures

## `stream_calibration/` — ground truth for `derive_streams()`

**This directory is empty, and that is the open item blocking phase 2 of the
multi-source-activities epic.**

`services/activity_ingest/streams.py` derives `grade_smooth` and
`velocity_smooth` for non-Strava activities. Strava's own values are the output
of *their* smoothing, and the residual GBM is trained on that distribution — so
until we measure our derivation against theirs, the smoothing windows in
`streams.py` are an educated guess, and drift would degrade predictions with no
error raised.

Drop matched pairs in here, sharing a base name:

- `<name>.strava.json` — streams exactly as `StravaService.download_streams()`
  returns them: `{"time": [...], "distance": [...], "altitude": [...],
  "grade_smooth": [...], "velocity_smooth": [...], "moving": [...]}`
- `<name>.gpx` — the **original** upload for that same activity, with per-point
  elevation and timestamps (Garmin Connect → Export Original beats Strava's own
  GPX export, which re-exports Strava's re-processed track).

Optionally `reference_route.gpx` in `tests/fixtures/` as the fixed route for the
end-to-end time comparison; otherwise `data/demo/utmb-sample.gpx` is used.

Then:

```bash
cd backend && source venv/bin/activate
python scripts/calibrate_streams.py                        # report
python scripts/calibrate_streams.py --grade-window 10,20,30,40,60   # sweep
```

`tests/test_services/test_derive_streams.py` skips its tolerance check while
this directory is empty and enforces it (|Δv_flat| < 2%, |Δpredicted time| <
1.5%) as soon as a pair is present.

Full instructions: the module docstring of `backend/scripts/calibrate_streams.py`.
