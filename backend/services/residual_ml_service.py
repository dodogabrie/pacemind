"""Tier 3: personal corrections on top of Tier 2 physics, learned walk-forward.

Target, per 200 m of course: log(actual moving time / Tier 2 physics time),
where the physics params for an activity are fitted ONLY on the activities
before it (`parameter_learning_service.walk_forward`). A same-activity fit
would erase exactly the habits we want to learn (pred-review F3).

Features are what is known before the race (course shape + fitness before the
start), never the pace actually run. Train and serve go through the same
`course_bins()` on the physics 50 m segments, so the grid and the grade unit
(fraction) cannot drift apart.

Model: ridge on one-hot grade bins + a few standardised linear terms; the
coefficients ARE the habits ("on 15-25 % climbs you are 8 % slower than the
model"). Picked over a monotone HistGradientBoosting in the walk-forward
(scripts/backtest_predictions.py --tier3). Predictions shrink toward Tier 2
with little data, and a per-user gate only switches Tier 3 on when the user's
own walk-forward shows it beats Tier 2.
"""

import io
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional

import joblib
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold

from repositories import UserResidualModelRepository
from config.hybrid_config import get_logger, SEGMENT_LENGTH_M

logger = get_logger(__name__)

PHYSICS_STEP_M = 50  # PhysicsPredictionService resamples the course every 50 m
GRADE_EDGES = (-0.25, -0.15, -0.08, -0.03, 0.03, 0.08, 0.15, 0.25)
"""Grade bins (fraction). Steep descents/climbs are where runners differ most from Minetti."""
LINEAR_FEATURES = ('cum_time_h', 'cum_down_km', 'alt_km', 'climb_len_km', 'descent_len_km', 'tsb')
FEATURES = tuple(f'grade_bin_{i}' for i in range(len(GRADE_EDGES) + 1)) + LINEAR_FEATURES

Y_CLIP = 1.0            # |log ratio| per 200 m; beyond is GPS/pause noise, not a habit
RACE_WEIGHT = 3.0       # a race says more about race day than a training jog
SHRINK_K = 30           # activities: correction scaled by n / (n + 30); half weight at ~30 runs
ALPHAS = (1.0, 10.0, 100.0, 1000.0)

GATE_MIN_TRAIN = 10     # activities before a held-out one before we evaluate it
GATE_MAX_EVAL = 20      # the last 20, like the Tier 2 interval
GATE_MIN_EVAL = 15
"""Held-out activities needed to open the gate. With ~15 paired errors the
standard error of the mean ΔMAPE is ~0.7-1 pt on this kind of data (sd of the
per-activity difference 3-4 pts), so 'better by more than one SE' is a real
signal and not a coin flip; below 15 the SE is as large as any plausible gain."""

RACE_PRIOR = 0.95
RACE_PRIOR_K = 3        # races: ratio shrinks toward 0.95 like n / (n + 3)


def assert_fraction(grades) -> None:
    """Grades here are fractions (0.10 = 10 %). Percent sneaking in (F1) trips this."""
    g = np.abs(np.asarray(grades, dtype=float))
    if len(g) and float(np.median(g)) > 0.5:
        raise ValueError(f'grades look like percent (median |g| = {np.median(g):.1f}); expected fractions')


def _run_length_km(sign: np.ndarray) -> np.ndarray:
    """Length (km) of the same-sign stretch each bin belongs to."""
    out = np.zeros(len(sign))
    start = 0
    for i in range(1, len(sign) + 1):
        if i == len(sign) or sign[i] != sign[start]:
            out[start:i] = (i - start) * SEGMENT_LENGTH_M / 1000
            start = i
    return out


def course_bins(physics_result: Dict, tsb: float = 0.0) -> Dict[str, np.ndarray]:
    """Physics 50 m segments -> fixed 200 m bins: features + physics time per bin.

    The trailing < 200 m keeps its physics time (no correction)."""
    k = SEGMENT_LENGTH_M // PHYSICS_STEP_M
    segs = physics_result['segments']
    n = len(segs) // k
    g = np.array([s['grade'] for s in segs[:n * k]], dtype=float).reshape(n, k)
    assert_fraction(g.ravel())
    length = np.array([s['length_m'] for s in segs[:n * k]], dtype=float).reshape(n, k)
    t = np.array([s['time_s'] for s in segs[:n * k]], dtype=float).reshape(n, k).sum(1)
    z = np.array([s['elevation_m'] for s in segs[:n * k]], dtype=float).reshape(n, k).mean(1)
    dz = g * length
    grade = dz.sum(1) / length.sum(1)
    down = np.clip(-dz, 0, None).sum(1)
    sign = np.where(grade > 0.03, 1, np.where(grade < -0.03, -1, 0))
    run = _run_length_km(sign)

    cols = {f'grade_bin_{i}': (np.digitize(grade, GRADE_EDGES) == i).astype(float)
            for i in range(len(GRADE_EDGES) + 1)}
    cols.update(
        cum_time_h=(np.cumsum(t) - t) / 3600,
        cum_down_km=(np.cumsum(down) - down) / 1000,
        alt_km=z / 1000,
        climb_len_km=np.where(sign > 0, run, 0.0),
        descent_len_km=np.where(sign < 0, run, 0.0),
        tsb=np.full(n, float(tsb)),
    )
    return {'X': np.column_stack([cols[f] for f in FEATURES]), 'physics_s': t, 'grade': grade}


def actual_bin_times(streams: Dict, n_bins: int) -> Optional[np.ndarray]:
    """Moving seconds spent in each 200 m of the recorded track."""
    if 'time' not in streams or 'distance' not in streams:
        return None
    d = np.maximum.accumulate(np.asarray(streams['distance'], dtype=float))
    tt = np.asarray(streams['time'], dtype=float)
    moving = np.asarray(streams.get('moving') or [True] * len(d), dtype=bool)
    moving_s = np.cumsum(np.diff(tt, prepend=tt[0]) * moving)
    return np.diff(np.interp(np.arange(n_bins + 1) * SEGMENT_LENGTH_M, d, moving_s))


def race_ratio(rows: List[Dict]) -> Dict:
    """Personal race / training speed ratio from walk-forward Tier 2 errors, shrunk to 0.95."""
    races = [r['log_error'] for r in rows if r['is_race']]
    train = [r['log_error'] for r in rows if not r['is_race']]
    if not races or len(train) < 5:
        return {'ratio': RACE_PRIOR, 'n_races': len(races)}
    w = len(races) / (len(races) + RACE_PRIOR_K)
    log_ratio = w * (np.mean(races) - np.mean(train)) + (1 - w) * math.log(RACE_PRIOR)
    return {'ratio': float(math.exp(log_ratio)), 'n_races': len(races)}


def training_set(rows: List[Dict], log_race: float):
    """Stack the bins of every row. Races are de-effort-adjusted (the ratio is
    applied separately at serve) and weighted up; each activity gets the same
    total weight whatever its length."""
    X, y, w, g = [], [], [], []
    for i, r in enumerate(rows):
        b = r['bins']
        actual = r['actual_s']
        ok = (actual > 0) & (b['physics_s'] > 0)
        if ok.sum() < 5:
            continue
        yi = np.clip(np.log(actual[ok] / b['physics_s'][ok]) - (log_race if r['is_race'] else 0.0), -Y_CLIP, Y_CLIP)
        X.append(b['X'][ok])
        y.append(yi)
        w.append(np.full(ok.sum(), (RACE_WEIGHT if r['is_race'] else 1.0) / ok.sum()))
        g.append(np.full(ok.sum(), i))
    if not X:
        return None
    return np.vstack(X), np.concatenate(y), np.concatenate(w), np.concatenate(g)


def fit(rows: List[Dict]) -> Optional[Dict]:
    """Model bundle trained on these rows (each row = one past activity)."""
    rr = race_ratio(rows)
    data = training_set(rows, math.log(rr['ratio']))
    if data is None:
        return None
    X, y, w, groups = data
    n_act = len(set(groups))
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    sd[:len(GRADE_EDGES) + 1] = 1.0  # one-hots stay 0/1 so their coefficients read as log ratios
    mu[:len(GRADE_EDGES) + 1] = 0.0
    Xs = (X - mu) / sd

    # Group-aware CV by activity: 200 m bins of one run are strongly correlated.
    best, best_err = ALPHAS[-1], float('inf')
    folds = GroupKFold(n_splits=min(5, n_act))
    for alpha in ALPHAS:
        err = 0.0
        for tr, te in folds.split(Xs, y, groups):
            m = Ridge(alpha=alpha).fit(Xs[tr], y[tr], sample_weight=w[tr])
            err += float(np.sum(w[te] * (m.predict(Xs[te]) - y[te]) ** 2))
        if err < best_err:
            best, best_err = alpha, err
    model = Ridge(alpha=best).fit(Xs, y, sample_weight=w)
    return {'model': model, 'mu': mu, 'sd': sd, 'alpha': best, 'n_activities': n_act,
            'shrink': n_act / (n_act + SHRINK_K), 'race_ratio': rr}


def bin_multipliers(bundle: Dict, bins: Dict) -> np.ndarray:
    r = bundle['model'].predict((bins['X'] - bundle['mu']) / bundle['sd'])
    return np.exp(bundle['shrink'] * np.clip(r, -Y_CLIP, Y_CLIP))


def corrected_total(bundle: Dict, physics_result: Dict, bins: Dict) -> float:
    """Tier 2 total + the Tier 3 change on the full 200 m bins."""
    return physics_result['total_time_seconds'] + float(np.sum(bins['physics_s'] * (bin_multipliers(bundle, bins) - 1)))


def evaluate(rows: List[Dict]) -> Dict:
    """Walk-forward Tier 3 vs Tier 2 on the user's last GATE_MAX_EVAL activities."""
    t2, t3 = [], []
    for i in range(max(GATE_MIN_TRAIN, len(rows) - GATE_MAX_EVAL), len(rows)):
        bundle = fit(rows[:i])
        if bundle is None:
            continue
        r = rows[i]
        actual = r['activity'].moving_time_s
        t2.append(math.log(actual / r['physics']['total_time_seconds']))
        t3.append(math.log(actual / corrected_total(bundle, r['physics'], r['bins'])))
    return gate(t2, t3)


def gate(t2_log_errors: List[float], t3_log_errors: List[float]) -> Dict:
    """Open only if Tier 3 has lower MAPE by more than one standard error and no worse |bias|."""
    n = len(t3_log_errors)
    out = {'open': False, 'n_eval': n, 't3_log_errors': list(map(float, t3_log_errors))}
    if n == 0:
        out['reason'] = 'not_enough_history'
        return out
    # Relative error of the prediction, (pred - actual) / actual = exp(-e) - 1.
    e2 = np.exp(-np.asarray(t2_log_errors)) - 1
    e3 = np.exp(-np.asarray(t3_log_errors)) - 1
    d = np.abs(e3) - np.abs(e2)
    se = float(np.std(d, ddof=1) / math.sqrt(n)) if n > 1 else float('inf')
    out.update(
        mape_t2=float(100 * np.mean(np.abs(e2))), mape_t3=float(100 * np.mean(np.abs(e3))),
        bias_t2=float(100 * np.mean(e2)), bias_t3=float(100 * np.mean(e3)),
        dmape_se=100 * se,
    )
    if n < GATE_MIN_EVAL:
        out['reason'] = 'not_enough_history'
    elif not (np.mean(d) + se < 0):
        out['reason'] = 'not_better'
    elif abs(out['bias_t3']) > abs(out['bias_t2']):
        out['reason'] = 'worse_bias'
    else:
        out['open'], out['reason'] = True, 'better'
    return out


def habits(bundle: Dict) -> Dict[str, float]:
    """Readable coefficients: grade bins as % slower(+)/faster(-) than Tier 2;
    linear terms as % per 1 SD of the feature. Shrinkage included."""
    coef = bundle['model'].coef_ * bundle['shrink']
    return {f: round(100 * (math.exp(c) - 1), 1) for f, c in zip(FEATURES, coef)}


def _serialize(bundle: Dict) -> bytes:
    buf = io.BytesIO()
    joblib.dump(bundle, buf, compress=3)
    return buf.getvalue()


class ResidualMLService:
    """Train/store/load the per-user Tier 3 bundle (table user_residual_models)."""

    def __init__(self, residual_model_repo=None):
        self.repo = residual_model_repo or UserResidualModelRepository()

    def train_from_rows(self, user_id: int, rows: List[Dict]) -> Optional[Dict]:
        """rows = parameter_learning_service.walk_forward() output with bins attached
        (see attach_bins). Stores the model and the gate; returns the gate dict."""
        rows = [r for r in rows if r.get('bins') is not None]
        bundle = fit(rows)
        if bundle is None:
            return None
        g = evaluate(rows)
        g['habits'] = habits(bundle)
        g['race_ratio'] = bundle['race_ratio']
        self.repo.save_model(
            user_id, model_blob=_serialize(bundle), n_activities_used=bundle['n_activities'],
            n_segments_trained=int(sum(len(r['bins']['physics_s']) for r in rows)),
            metrics=g, model_config={'alpha': bundle['alpha'], 'shrink': bundle['shrink']},
            feature_importance=g['habits'], residual_variance=None,
            last_trained=datetime.now(timezone.utc),
        )
        self.repo.commit()
        logger.info(f"Tier 3 for user {user_id}: gate {'open' if g['open'] else 'closed'} ({g['reason']}), "
                    f"n_eval={g['n_eval']} mape t2={g.get('mape_t2')} t3={g.get('mape_t3')}")
        return g

    def get_bundle(self, user_id: int) -> Optional[Dict]:
        """The bundle, only when the user's gate is open."""
        rec = self.repo.get_for_user(user_id)
        if not rec or not (rec.metrics or {}).get('open'):
            return None
        try:
            return joblib.load(io.BytesIO(rec.model_blob))
        except Exception as e:  # stale pickle from the pre-rebuild GBM
            logger.warning(f"Could not load Tier 3 model for user {user_id}: {e}")
            return None


def attach_bins(user_id: Optional[int], rows: List[Dict]) -> List[Dict]:
    """Add course bins, actual bin times and fitness (strictly before the start) to walk-forward rows."""
    from services.training_load_service import TrainingLoadService
    tsb = {}
    if user_id:
        loads = TrainingLoadService().get_training_load_batch(user_id, [r['activity'].start_date for r in rows])
        tsb = {k: v.get('tsb', 0.0) for k, v in loads.items()}
    for r in rows:
        a = r['activity']
        start = a.start_date.replace(tzinfo=None)
        bins = course_bins(r['physics'], tsb.get(start, 0.0))
        actual = actual_bin_times(a.streams, len(bins['physics_s']))
        r['bins'], r['actual_s'] = (bins, actual) if actual is not None else (None, None)
    return rows
