#!/usr/bin/env python
"""Calibrate `derive_streams()` against Strava's own smoothing.

WHY THIS EXISTS
---------------
Strava's `grade_smooth` / `velocity_smooth` are the output of *their*
smoothing, and the residual GBM is trained on that distribution. If
`services/activity_ingest/streams.py` derives grade over a different window,
uploaded activities land out of distribution and predictions degrade with no
error raised. This harness measures the drift so the two window constants in
`streams.py` can be tuned against ground truth rather than guessed.

It reports, per fixture pair:

  * p5 / p50 / p95 of `grade_smooth` — distribution shape
  * `v_flat` from `physics_model/calibration.py` — what actually feeds physics
  * end-to-end predicted time on one fixed GPX — what the user sees

and the deltas against the tolerances agreed in
`docs/plans/multi-source-activities/02-activity-abstraction.md`:

    |Δv_flat| < 2%      |Δpredicted time| < 1.5%

>>> THE CALIBRATION NUMBER DOES NOT EXIST YET. <<<
There is no ground-truth fixture in this repo, so this script has never been
run against real data. Do not quote a number from a synthetic fixture.


WHAT YOU MUST SUPPLY TO UNBLOCK IT
----------------------------------
Pick 3-10 of your own Strava *runs* — ideally a mix of flat road, rolling, and
steep trail, since grade smoothing drifts most where the terrain is roughest.
For each one, drop TWO files into `backend/tests/fixtures/stream_calibration/`
sharing the same base name:

  1. `<name>.strava.json`
     The raw Strava streams, exactly as `StravaService.download_streams()`
     returns them: a flat JSON object mapping stream name to a list of values.

         {"time": [...], "distance": [...], "altitude": [...],
          "grade_smooth": [...], "velocity_smooth": [...], "moving": [...]}

     Get it either from an existing cached-streams row in the DB, or straight
     from the API:

         curl -H "Authorization: Bearer $TOKEN" \\
           "https://www.strava.com/api/v3/activities/<ID>/streams?keys=time,distance,altitude,latlng,grade_smooth,velocity_smooth,moving&key_by_type=true" \\
           | python -c "import json,sys; d=json.load(sys.stdin); \\
                        json.dump({k: v['data'] for k, v in d.items()}, open('<name>.strava.json','w'))"

  2. `<name>.gpx`
     The ORIGINAL upload for that same activity — the file the watch produced,
     with per-point timestamps and elevation. Strava's own "Export GPX" is
     acceptable but second-best: it exports Strava's re-processed track, which
     makes the comparison flatter than reality. A raw watch export (Garmin
     Connect → Export Original) is the honest input.

Also drop in a reference route as `backend/tests/fixtures/reference_route.gpx`,
or let the script fall back to `backend/data/demo/utmb-sample.gpx`. Its only
job is to be a fixed route for the end-to-end time comparison; it does not
need timestamps.

Then, from `backend/` with the venv active:

    python scripts/calibrate_streams.py

If a pair fails the tolerance, tune `GRADE_SMOOTHING_DISTANCE_M` (and, if the
velocity distribution is the one drifting, `VELOCITY_SMOOTHING_TIME_S`) in
`services/activity_ingest/streams.py` and re-run. To sweep the grade window in
one go:

    python scripts/calibrate_streams.py --grade-window 10,20,30,40,60

Once a window passes on every pair: write the measured numbers into the plan
document, and keep the fixtures checked in — `tests/test_services/
test_derive_streams.py` enforces the same tolerance from then on.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.activity_ingest import streams as streams_mod  # noqa: E402
from services.activity_ingest.streams import derive_streams  # noqa: E402
from services.gpx_parser import parse_gpx_file  # noqa: E402
from services.physics_model.calibration import calibrate_user_params  # noqa: E402
from services.physics_prediction_service import PhysicsPredictionService  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
FIXTURE_DIR = BACKEND_DIR / 'tests' / 'fixtures' / 'stream_calibration'
REFERENCE_ROUTE = BACKEND_DIR / 'tests' / 'fixtures' / 'reference_route.gpx'
FALLBACK_ROUTE = BACKEND_DIR / 'data' / 'demo' / 'utmb-sample.gpx'

# Tolerances from docs/plans/multi-source-activities/02-activity-abstraction.md.
# The test imports these — keep the two in sync by importing, not copying.
V_FLAT_TOLERANCE_PCT = 2.0
PREDICTED_TIME_TOLERANCE_PCT = 1.5


def find_fixture_pairs(fixture_dir: Optional[Path] = None) -> List[Dict[str, Path]]:
    """Locate `<name>.strava.json` + `<name>.gpx` pairs, ignoring singletons."""
    fixture_dir = fixture_dir or FIXTURE_DIR
    if not fixture_dir.is_dir():
        return []
    pairs = []
    for strava_path in sorted(fixture_dir.glob('*.strava.json')):
        name = strava_path.name[: -len('.strava.json')]
        gpx_path = fixture_dir / f'{name}.gpx'
        if gpx_path.exists():
            pairs.append({'name': name, 'strava': strava_path, 'gpx': gpx_path})
    return pairs


def load_reference_route() -> Optional[List[Dict[str, float]]]:
    """Fixed route for the end-to-end comparison, as physics `gpx_points`."""
    path = REFERENCE_ROUTE if REFERENCE_ROUTE.exists() else FALLBACK_ROUTE
    if not path.exists():
        return None
    parsed = parse_gpx_file(path)
    # derive_streams with no `time` gives us distance + altitude, which is
    # exactly what physics needs — and keeps distance computed one way only.
    route = derive_streams(parsed['latitudes'], parsed['longitudes'], parsed['elevations'])
    if 'altitude' not in route:
        return None
    return [
        {'distance': d, 'elevation': e}
        for d, e in zip(route['distance'], route['altitude'])
    ]


def _v_flat(stream: Dict[str, List]) -> float:
    """v_flat as the production calibration path would compute it."""
    df = pd.DataFrame({
        'distance': stream['distance'],
        'velocity_smooth': stream['velocity_smooth'],
        'grade_smooth': stream['grade_smooth'],
        'moving': stream.get('moving', [True] * len(stream['distance'])),
    })
    return calibrate_user_params([df])['v_flat']


def _predicted_time_s(stream: Dict[str, List], route: List[Dict[str, float]]) -> Optional[float]:
    """End-to-end physics prediction on the fixed route, from these streams."""
    if route is None:
        return None
    df = pd.DataFrame({
        'distance': stream['distance'],
        'velocity_smooth': stream['velocity_smooth'],
        'grade_smooth': stream['grade_smooth'],
        'moving': stream.get('moving', [True] * len(stream['distance'])),
    })
    params = calibrate_user_params([df])
    result = PhysicsPredictionService().predict(route, params, user_id=None)
    return result.get('total_time_seconds')


def _percentiles(values) -> Dict[str, float]:
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return {'p5': float('nan'), 'p50': float('nan'), 'p95': float('nan')}
    p5, p50, p95 = np.percentile(arr, [5, 50, 95])
    return {'p5': float(p5), 'p50': float(p50), 'p95': float(p95)}


def _pct_delta(derived: Optional[float], reference: Optional[float]) -> Optional[float]:
    if derived is None or reference is None or not reference:
        return None
    return 100.0 * (derived - reference) / reference


def compare_pair(
    strava_path: Path,
    gpx_path: Path,
    route: Optional[List[Dict[str, float]]] = None,
) -> Dict:
    """Run both paths over one fixture pair and return the metrics + deltas.

    Args:
        strava_path: `<name>.strava.json`, streams as Strava returned them.
        gpx_path: the matching original `.gpx`.
        route: fixed route for the end-to-end check; loaded if omitted. Pass
            explicitly when comparing many pairs, so it is parsed once.

    Returns:
        Dict with `grade` percentiles for both paths, `v_flat_*`,
        `predicted_time_*`, the percentage deltas, and `passed` — which is
        False if any measurable delta exceeds its tolerance.
    """
    with open(strava_path, 'r', encoding='utf-8') as f:
        strava = json.load(f)

    missing = [k for k in ('distance', 'velocity_smooth', 'grade_smooth') if not strava.get(k)]
    if missing:
        raise ValueError(f'{strava_path.name} is missing required streams: {missing}')

    parsed = parse_gpx_file(gpx_path)
    derived = derive_streams(
        parsed['latitudes'], parsed['longitudes'], parsed['elevations'], parsed['times']
    )
    for key in ('grade_smooth', 'velocity_smooth'):
        if key not in derived:
            raise ValueError(
                f'{gpx_path.name} yielded no {key} — it needs per-point '
                f'elevation and timestamps to be usable as ground truth'
            )

    if route is None:
        route = load_reference_route()

    v_flat_strava = _v_flat(strava)
    v_flat_derived = _v_flat(derived)
    time_strava = _predicted_time_s(strava, route)
    time_derived = _predicted_time_s(derived, route)

    v_flat_delta = _pct_delta(v_flat_derived, v_flat_strava)
    time_delta = _pct_delta(time_derived, time_strava)

    checks = [
        (v_flat_delta, V_FLAT_TOLERANCE_PCT),
        (time_delta, PREDICTED_TIME_TOLERANCE_PCT),
    ]
    passed = all(abs(d) <= tol for d, tol in checks if d is not None)

    return {
        'name': strava_path.name[: -len('.strava.json')],
        'grade_strava': _percentiles(strava['grade_smooth']),
        'grade_derived': _percentiles(derived['grade_smooth']),
        'velocity_strava': _percentiles(strava['velocity_smooth']),
        'velocity_derived': _percentiles(derived['velocity_smooth']),
        'v_flat_strava': v_flat_strava,
        'v_flat_derived': v_flat_derived,
        'v_flat_delta_pct': v_flat_delta,
        'predicted_time_strava_s': time_strava,
        'predicted_time_derived_s': time_derived,
        'predicted_time_delta_pct': time_delta,
        'passed': passed,
    }


def _fmt(value: Optional[float], spec: str = '.3f') -> str:
    return 'n/a' if value is None or (isinstance(value, float) and np.isnan(value)) else format(value, spec)


def _print_report(report: Dict) -> None:
    g_s, g_d = report['grade_strava'], report['grade_derived']
    v_s, v_d = report['velocity_strava'], report['velocity_derived']
    print(f"\n--- {report['name']} ---")
    print(f"  {'metric':<24}{'strava':>12}{'derived':>12}{'delta':>12}")
    for label, key in (('grade p5 (%)', 'p5'), ('grade p50 (%)', 'p50'), ('grade p95 (%)', 'p95')):
        print(f'  {label:<24}{_fmt(g_s[key], ".2f"):>12}{_fmt(g_d[key], ".2f"):>12}'
              f'{_fmt(g_d[key] - g_s[key], "+.2f"):>12}')
    for label, key in (('velocity p5 (m/s)', 'p5'), ('velocity p50 (m/s)', 'p50'), ('velocity p95 (m/s)', 'p95')):
        print(f'  {label:<24}{_fmt(v_s[key], ".2f"):>12}{_fmt(v_d[key], ".2f"):>12}'
              f'{_fmt(v_d[key] - v_s[key], "+.2f"):>12}')

    v_delta = report['v_flat_delta_pct']
    t_delta = report['predicted_time_delta_pct']
    v_mark = 'n/a' if v_delta is None else ('PASS' if abs(v_delta) <= V_FLAT_TOLERANCE_PCT else 'FAIL')
    t_mark = 'n/a' if t_delta is None else ('PASS' if abs(t_delta) <= PREDICTED_TIME_TOLERANCE_PCT else 'FAIL')
    print(f'  {"v_flat (m/s)":<24}{_fmt(report["v_flat_strava"]):>12}'
          f'{_fmt(report["v_flat_derived"]):>12}{_fmt(v_delta, "+.2f") + "%":>12}'
          f'   [{v_mark}, tol ±{V_FLAT_TOLERANCE_PCT}%]')
    print(f'  {"predicted time (s)":<24}{_fmt(report["predicted_time_strava_s"], ".0f"):>12}'
          f'{_fmt(report["predicted_time_derived_s"], ".0f"):>12}{_fmt(t_delta, "+.2f") + "%":>12}'
          f'   [{t_mark}, tol ±{PREDICTED_TIME_TOLERANCE_PCT}%]')


def run(grade_windows: Optional[List[float]] = None,
        fixture_dir: Optional[Path] = None) -> int:
    fixture_dir = fixture_dir or FIXTURE_DIR
    pairs = find_fixture_pairs(fixture_dir)
    if not pairs:
        print(f'No fixture pairs found in {fixture_dir}.\n')
        print(__doc__.split('WHAT YOU MUST SUPPLY TO UNBLOCK IT')[1].strip())
        return 1

    route = load_reference_route()
    if route is None:
        print('WARNING: no reference route — skipping the end-to-end time check.')

    original_window = streams_mod.GRADE_SMOOTHING_DISTANCE_M
    windows = grade_windows or [original_window]
    all_passed = True

    try:
        for window in windows:
            streams_mod.GRADE_SMOOTHING_DISTANCE_M = window
            print(f'\n{"=" * 68}\nGRADE_SMOOTHING_DISTANCE_M = {window} m  '
                  f'(VELOCITY_SMOOTHING_TIME_S = {streams_mod.VELOCITY_SMOOTHING_TIME_S} s)\n{"=" * 68}')
            for pair in pairs:
                report = compare_pair(pair['strava'], pair['gpx'], route)
                _print_report(report)
                all_passed = all_passed and report['passed']
    finally:
        streams_mod.GRADE_SMOOTHING_DISTANCE_M = original_window

    print(f'\n{"=" * 68}')
    print('RESULT:', 'all pairs within tolerance' if all_passed else 'AT LEAST ONE PAIR OUT OF TOLERANCE')
    if all_passed:
        print('Write these numbers into '
              'docs/plans/multi-source-activities/02-activity-abstraction.md.')
    return 0 if all_passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--grade-window',
        help='Comma-separated grade windows in metres to sweep, '
             'e.g. 10,20,30,40,60. Defaults to the value in streams.py.',
    )
    args = parser.parse_args()
    windows = None
    if args.grade_window:
        windows = [float(w) for w in args.grade_window.split(',')]
    return run(windows)


if __name__ == '__main__':
    os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
    sys.exit(main())
