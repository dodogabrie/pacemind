"""Walk-forward backtest of the finish-time prediction, READ-ONLY.

Every target is an eligible stream run of the user; it is predicted from its
own recorded track with params fitted only on the runs before it, through the
production functions in services/parameter_learning_service.py.

    docker exec -w /app/backend -e RUN_MIGRATIONS=0 trail-backend-1 \\
        python scripts/backtest_predictions.py --user 3 [--json /tmp/bt.json] \\
        [--no-quality-filter] [--min-prior 10] [--no-interval] [--tier3]

Always reports 'intens' = Tier 2 x the HR intensity multiplier at the target's
OWN observed %HRR (intensity model fitted on earlier runs), with subsets 'hard'
(top-quartile observed %HRR) and 'races' (is_race; 'raceeff' = the race-effort
intensity the product would choose, without peeking at the race's HR).

--tier3 also reports Tier 3 (services/residual_ml_service.py) on top of the
same Tier 2 prediction: 'tier3' = the model trained on the walk-forward rows of
the runs before the target (always applied); 'gated' = what production would
show, i.e. Tier 3 only if the gate computed on those same earlier runs is open.
Each row's physics uses params fitted only on the runs before THAT row.

Every DB connection is forced into a read-only transaction and the session is
rolled back at the end. Postgres only (the guard uses SET SESSION).
"""
# TODO(pred-review #37 — see GH issues): one user, training runs only, the
# recorded track as the GPX, n~39: differences < 2 MAPE points are noise. Add
# organiser-GPX robustness (perturbed D+) and race-labelled targets after P13.
import argparse
import json
import logging
import os
import sys
import warnings

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)

ap = argparse.ArgumentParser()
ap.add_argument('--user', type=int, required=True)
ap.add_argument('--json')
ap.add_argument('--no-quality-filter', action='store_true',
                help='anchor mode: no quality rule; drop only targets with moving time > 40000 s')
ap.add_argument('--min-prior', type=int, default=10)
ap.add_argument('--no-interval', action='store_true', help='skip the (slow) walk-forward interval')
ap.add_argument('--tier3', action='store_true', help='also report the (disabled) Tier 3 GBM path')
args = ap.parse_args()

from app import create_app  # noqa: E402
from database import db  # noqa: E402
from sqlalchemy import event  # noqa: E402

app = create_app()

with app.app_context():
    @event.listens_for(db.engine, 'connect')
    def _read_only(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute('SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY')
        cur.close()
        dbapi_conn.commit()
    db.engine.dispose()
    assert db.session.execute(db.text('show transaction_read_only')).scalar() == 'on'

    from models import Activity
    from services import parameter_learning_service as pls
    from services.physics_prediction_service import PhysicsPredictionService

    if args.no_quality_filter:
        pls.QUALITY_MAX_RATIO = float('inf')

    physics = PhysicsPredictionService()
    user = args.user
    targets = pls.eligible_activities(user)
    if args.no_quality_filter:
        targets = [a for a in targets if a.moving_time_s <= 40000]

    summ = [dict(date=a.start_date, km=a.distance / 1000, dplus=a.elevation_gain_m or 0,
                 mov=a.moving_time_s, ela=a.elapsed_time_s)
            for a in Activity.query.filter_by(user_id=user).order_by(Activity.start_date)
            if a.moving_time_s and a.distance > 3000]

    # One walk-forward row per activity with >= 5 eligible runs before it: its
    # Tier 2 prediction from params fitted only on those runs. Targets, the
    # interval (last 20 rows before a target) and Tier 3 training all reuse them.
    wf = []
    for a in targets:
        prior = pls.eligible_activities(user, before=a.start_date)
        if len(prior) < pls.TIER_2_MIN_ACTIVITIES:
            continue
        params = pls.fit_params(prior)
        res = physics.predict(pls.track_points(a), params, user_id=None)
        wf.append({'activity': a, 'is_race': bool(getattr(a, 'is_race', False)), 'physics': res,
                   'log_error': np.log(a.moving_time_s / res['total_time_seconds']), 'n_prior': len(prior),
                   'params': params})
    if args.tier3:
        from services import residual_ml_service as rms
        rms.attach_bins(user, wf)

    from services import intensity_service as ins
    hr_profile = ins.profile_hr(user)
    rows = []
    for j, w in enumerate(wf):
        a = w['activity']
        if w['n_prior'] < args.min_prior:
            continue
        prior = pls.eligible_activities(user, before=a.start_date)
        mov = w['physics']['total_time_seconds']
        share = pls.stop_share(prior)
        r = dict(id=a.id, date=a.start_date.isoformat(), km=a.distance / 1000,
                 act_mov=a.moving_time_s, act_ela=a.elapsed_time_s, is_race=w['is_race'],
                 prod_mov=mov, prod_ela=mov * (1 + share), stop_share=share)

        # Intensity (HR): the model fitted on earlier runs only, applied (a) at the
        # run's OWN observed %HRR and (b) for races, at the race-effort intensity
        # the product would pick (duration prior + offset from earlier races).
        im = ins.fit(prior, w['params'], *hr_profile, ref_activities=prior[-pls.CALIBRATION_WINDOW:])
        i_obs = im and ins.observed_intensity(a.streams, w['params'], im)
        if i_obs:
            m = ins.time_multiplier(im, i_obs)
            r.update(i_obs=i_obs, intens_mov=mov * m, intens_ela=mov * m * (1 + share))
            if w['is_race']:
                im['race_offset'] = ins.race_offset([x['race_hr'] for x in wf[:j] if x.get('race_hr')])
                re = ins.moving_at_effort(im, 'race', mov)['moving_s']
                r.update(raceeff_mov=re, raceeff_ela=re * (1 + share))
                w['race_hr'] = {'intensity': i_obs, 'hours': a.moving_time_s / 3600}
        if not args.no_interval:
            errs = [float(x['log_error']) for x in wf[:j]][-20:]
            lo, hi = pls.prediction_interval(errs, 'TIER_2_PARAMETER_LEARNING')
            r.update(lo=lo, hi=hi, log_errors=errs)
        if args.tier3:
            train = [x for x in wf[:j] if x['bins'] is not None]
            bundle = rms.fit(train)
            if bundle and w['bins'] is not None:
                t3 = rms.corrected_total(bundle, w['physics'], w['bins'])
                g = rms.evaluate(train)
                gated = t3 if g['open'] else mov
                r.update(tier3_mov=t3, tier3_ela=t3 * (1 + share), gated_mov=gated,
                         gated_ela=gated * (1 + share), gate=g['reason'])

        # Baselines on all prior summary runs >= 10 km (last 10), as in the review.
        last = [p for p in summ if p['date'] < a.start_date and p['km'] >= 10][-10:]
        effort_km = r['km'] + (a.elevation_gain_m or 0) / 100
        for t in ('mov', 'ela'):
            pe = [p[t] / (p['km'] + p['dplus'] / 100) for p in last if p[t]]
            r[f'kmeffort_{t}'] = float(np.median(pe)) * effort_km
            rg = [p[t] * (effort_km / (p['km'] + p['dplus'] / 100)) ** 1.06 for p in last if p[t]]
            r[f'riegel_{t}'] = float(np.median(rg))
        rows.append(r)
        print(f"{r['date'][:10]} {r['km']:5.1f} km  actual {a.moving_time_s:6d}s  prod {mov:7.0f}s "
              f"({(mov / a.moving_time_s - 1) * 100:+5.1f}%)", flush=True)

    db.session.rollback()


def stats(rows, model, t):
    rows = [r for r in rows if r.get(f'act_{t}')]
    e = np.array([(r[f'{model}_{t}'] - r[f'act_{t}']) / r[f'act_{t}'] for r in rows])
    if not len(e):
        return None
    return dict(n=len(e), mape=100 * np.mean(abs(e)), mdape=100 * np.median(abs(e)),
                bias=100 * np.mean(e), p80=100 * np.percentile(abs(e), 80))


def coverage(rows, t):
    rows = [r for r in rows if r.get(f'act_{t}') and 'lo' in r]
    if not rows:
        return None
    inside = [r['prod_' + t] * r['lo'] <= r['act_' + t] <= r['prod_' + t] * r['hi'] for r in rows]
    half = [100 * (r['hi'] - r['lo']) / 2 for r in rows]
    return 100 * np.mean(inside), float(np.mean(half))


def boot_delta(rows, t, a='prod', b='riegel', n=5000):
    rows = [r for r in rows if r.get(f'act_{t}')]
    d = np.array([abs(r[f'{a}_{t}'] - r[f'act_{t}']) / r[f'act_{t}']
                  - abs(r[f'{b}_{t}'] - r[f'act_{t}']) / r[f'act_{t}'] for r in rows])
    rng = np.random.default_rng(0)
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(n)]
    return 100 * d.mean(), 100 * np.percentile(bs, 2.5), 100 * np.percentile(bs, 97.5)


summary = {}
print(f"\nuser {args.user}, targets {len(rows)}, quality filter {'off' if args.no_quality_filter else 'on'}")
if args.tier3:
    from collections import Counter
    print('gate at each target:', dict(Counter(r.get('gate') for r in rows)))
hard_cut = np.percentile([r['i_obs'] for r in rows if 'i_obs' in r] or [1], 75)
print(f"hard efforts = observed %HRR >= {100 * hard_cut:.0f}% (top quartile of targets)")
for subset, sel in (('all', rows), ('>=30km', [r for r in rows if r['km'] >= 30]),
                    ('hard', [r for r in rows if r.get('i_obs', 0) >= hard_cut]),
                    ('races', [r for r in rows if r['is_race']])):
    if not sel:
        continue
    for t in ('mov', 'ela'):
        print(f"\n[{subset} / {'moving' if t == 'mov' else 'elapsed'}]   n   MAPE  MdAPE   bias    P80")
        for m in ('prod', 'riegel', 'kmeffort', 'tier3', 'gated', 'intens', 'raceeff'):
            s = stats([r for r in sel if f'{m}_{t}' in r], m, t)
            if s:
                summary[f'{subset}/{t}/{m}'] = s
                print(f"  {m:9s} {s['n']:3d} {s['mape']:5.1f} {s['mdape']:6.1f} {s['bias']:+6.1f} {s['p80']:6.1f}")
        if subset == 'all':
            c = coverage(sel, t)
            if c:
                summary[f'coverage/{t}'] = c
                print(f"  80% interval coverage {c[0]:.0f}%  mean half-width ±{c[1]:.1f}%")
            d = boot_delta(sel, t)
            summary[f'dmape_prod_riegel/{t}'] = d
            print(f"  ΔMAPE prod−riegel {d[0]:+.2f} (95% CI {d[1]:+.2f}..{d[2]:+.2f})")
        for m in ('tier3', 'gated', 'intens', 'raceeff'):
            mrows = [r for r in sel if f'{m}_{t}' in r]
            if len(mrows) >= 3:
                d = boot_delta(mrows, t, a=m, b='prod')
                summary[f'{subset}/dmape_{m}_prod/{t}'] = d
                print(f"  ΔMAPE {m}−prod {d[0]:+.2f} (95% CI {d[1]:+.2f}..{d[2]:+.2f}, n={len(mrows)})")

if args.json:
    json.dump(dict(rows=rows, summary=summary), open(args.json, 'w'), indent=1, default=float)
