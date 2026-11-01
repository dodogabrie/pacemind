"""Pretty-print a generated training plan for narrow terminals.

Renders one week per section, one day per line — easy to read on phones
or split panes. Designed to inspect plan_engine output during coaching
review.

Usage:
    python scripts/preview_plan.py                        # default ultra
    python scripts/preview_plan.py --weeks 12 --km 50     # custom race
    python scripts/preview_plan.py --mountain-days Sat Sun  # restrict
    python scripts/preview_plan.py --json out.json        # also save raw

All distance / elevation prefs default to a sensible 88km / 4000m race
similar to a UTMB-CCC-style ultra. Override with CLI flags.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import plan_engine  # noqa: E402

DAYS_ORDER = [
    'Monday', 'Tuesday', 'Wednesday', 'Thursday',
    'Friday', 'Saturday', 'Sunday',
]


def _phase_of(week: dict) -> str:
    theme = week.get('theme') or ''
    head = theme.split('—', 1)[0].strip()
    return head.split()[0] if head else ''


def _format_day(day: dict) -> list[str]:
    """Return one or two lines describing a single day."""
    wt = day['workout_type']
    name = day['day']
    km = float(day.get('distance_km') or 0)
    elev = float(day.get('elevation_m') or 0)
    title = day.get('title') or wt.replace('_', ' ').title()

    if wt == 'rest':
        return [f"  {name:<9} REST"]

    metric = f"{km:>4.1f} km / {int(elev):>4} m D+"
    head = f"  {name:<9} {wt:<15} {metric}"
    lines = [head]
    if title and title.lower() not in ('rest day', wt.replace('_', ' ')):
        lines.append(f"             {title}")
    notes = (day.get('notes') or '').strip()
    if notes:
        lines.append(f"             {notes}")
    return lines


def render_plan(weeks: list[dict]) -> str:
    out: list[str] = []
    for w in weeks:
        phase = _phase_of(w)
        theme = w.get('theme') or ''
        total_km = float(w.get('total_km') or 0)
        total_elev = int(w.get('total_elevation_m') or 0)

        header = f"Week {w['week_number']:>2}  ·  {phase:<8}  ·  {theme}"
        out.append(header)
        out.append('-' * min(len(header), 60))

        by_day = {d['day']: d for d in w['days']}
        for dname in DAYS_ORDER:
            d = by_day.get(dname)
            if d is None:
                out.append(f"  {dname:<9} —")
                continue
            out.extend(_format_day(d))

        out.append(f"  {'TOTAL':<9} {total_km:>4.1f} km / {total_elev:>4} m D+")
        out.append('')
    return '\n'.join(out)


def build_plan(args: argparse.Namespace) -> list[dict]:
    prefs: dict = {
        'max_weekly_km': args.max_weekly_km,
        'terrain_profile': args.terrain_profile,
    }
    if args.mountain_days:
        prefs['mountain_days'] = args.mountain_days

    return plan_engine.generate_plan(
        total_weeks=args.weeks,
        race_distance_km=args.km,
        race_elevation_m=args.elev,
        race_date=args.race_date,
        athlete_weekly_km=args.athlete_km,
        athlete_weekly_elev=args.athlete_elev,
        athlete_longest_run_km=args.athlete_long_run,
        athlete_category=args.category,
        long_run_day=args.long_run_day,
        rest_days=args.rest_days,
        prefs=prefs,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--weeks', type=int, default=16)
    p.add_argument('--km', type=float, default=88.0, help='race distance')
    p.add_argument('--elev', type=float, default=4000.0, help='race D+ (m)')
    p.add_argument('--race-date', default='2026-05-31')
    p.add_argument('--athlete-km', type=float, default=70.0)
    p.add_argument('--athlete-elev', type=float, default=2000.0)
    p.add_argument('--athlete-long-run', type=float, default=30.0)
    p.add_argument('--category', default='cat_2', choices=['cat_1', 'cat_2'])
    p.add_argument('--long-run-day', default='Sunday')
    p.add_argument('--rest-days', nargs='*', default=['Friday'])
    p.add_argument('--max-weekly-km', type=float, default=100.0)
    p.add_argument('--terrain-profile', default='mountain',
                   choices=['flat_urban', 'rolling_hills', 'mountain'])
    p.add_argument('--mountain-days', nargs='*', default=None,
                   help='restrict mountain workouts to these days (e.g. Saturday Sunday)')
    p.add_argument('--json', metavar='PATH',
                   help='also dump the raw plan as JSON to PATH')
    args = p.parse_args()

    weeks = build_plan(args)
    print(render_plan(weeks))

    if args.json:
        with open(args.json, 'w') as fh:
            json.dump(weeks, fh, indent=2, default=str)
        print(f"[wrote raw JSON to {args.json}]")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
