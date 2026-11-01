"""Tier 3 personal model: grade units, fixed grid, no same-activity leak, learning, gate."""

import math
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from services import parameter_learning_service as pls
from services import residual_ml_service as rms
from services.physics_prediction_service import PhysicsPredictionService

PARAMS = {'v_flat': 3.0, 'k_up': 1.0, 'k_tech': 1.0, 'a_param': 3.0, 'k_terrain_up': 1.08,
          'k_terrain_down': 1.12, 'k_terrain_flat': 1.05, 'fatigue_alpha': 0.3}


def _course(seed, km=12):
    """Rolling course: flats, 5-25 % climbs, descents; 10 m resolution."""
    rng = np.random.default_rng(seed)
    d = np.arange(0, km * 1000 + 1, 10.0)
    slope = np.repeat(rng.choice([0.0, 0.06, 0.2, -0.1, -0.2], size=len(d) // 100 + 1), 100)[:len(d)]
    return d, 300 + np.cumsum(slope * 10.0)


def _physics(d, z):
    return PhysicsPredictionService().predict(
        [{'distance': float(a), 'elevation': float(b)} for a, b in zip(d, z)], PARAMS)


def test_assert_fraction_rejects_percent():
    rms.assert_fraction([0.1, -0.12, 0.05])
    with pytest.raises(ValueError):
        rms.assert_fraction([10.0, -12.0, 5.0])  # percent: F1


def test_course_bins_fixed_200m_grid_in_fractions():
    d, z = _course(0)
    res = _physics(d, z)
    bins = rms.course_bins(res)
    n = len(res['segments']) // 4
    assert bins['X'].shape == (n, len(rms.FEATURES))
    assert np.abs(bins['grade']).max() < 0.35  # fractions, not percent
    assert bins['physics_s'].sum() == pytest.approx(sum(s['time_s'] for s in res['segments'][:4 * n]))
    onehot = bins['X'][:, :len(rms.GRADE_EDGES) + 1]
    assert (onehot.sum(1) == 1).all()


def test_course_bins_refuse_percent_segments():
    res = _physics(*_course(0))
    for s in res['segments']:
        s['grade'] *= 100
    with pytest.raises(ValueError):
        rms.course_bins(res)


def test_actual_bin_times_count_only_moving_seconds():
    d = np.arange(0, 1001, 10.0)
    streams = {'distance': list(d), 'time': list(range(len(d))), 'moving': [True] * len(d)}
    np.testing.assert_allclose(rms.actual_bin_times(streams, 5), [20] * 5)
    streams['moving'] = [i % 2 == 0 for i in range(len(d))]  # half of the seconds paused
    assert rms.actual_bin_times(streams, 5).sum() == pytest.approx(50, abs=1)
    assert rms.actual_bin_times({'distance': list(d)}, 5) is None


def test_walk_forward_never_uses_the_target_or_later_runs(monkeypatch):
    """The target (log(actual / physics)) must come from params fitted strictly before it."""
    t0 = datetime(2026, 1, 1)
    acts = []
    for i in range(9):
        d, z = _course(i, km=5)
        acts.append(SimpleNamespace(id=i, start_date=t0 + timedelta(days=i), moving_time_s=2000 + i,
                                    streams={'distance': list(d), 'altitude': list(z)}))
    seen = []

    def fake_fit(prior):
        seen.append(list(prior))
        return PARAMS

    monkeypatch.setattr(pls, 'fit_params', fake_fit)
    rows = pls.walk_forward(acts)
    assert [r['activity'].id for r in rows] == [5, 6, 7, 8]
    for r, prior in zip(rows, seen):
        assert r['activity'] not in prior
        assert all(p.start_date < r['activity'].start_date for p in prior)
        assert r['log_error'] == pytest.approx(math.log(r['activity'].moving_time_s / r['physics']['total_time_seconds']))


def _rows(n, steep_factor=1.25, noise=0.03, seed=0):
    """Walk-forward-like rows: actual = physics x steep_factor on >15 % climbs, x noise per run."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        res = _physics(*_course(100 + i))
        bins = rms.course_bins(res)
        actual = bins['physics_s'] * np.where(bins['grade'] > 0.15, steep_factor, 1.0) * math.exp(rng.normal(0, noise))
        moving = actual.sum() + res['total_time_seconds'] - bins['physics_s'].sum()
        rows.append({'activity': SimpleNamespace(moving_time_s=moving), 'is_race': False, 'physics': res,
                     'bins': bins, 'actual_s': actual,
                     'log_error': math.log(moving / res['total_time_seconds'])})
    return rows


def test_fit_learns_a_steep_climb_habit_and_shrinks_it():
    rows = _rows(30)
    bundle = rms.fit(rows)
    bins = rows[0]['bins']
    mult = rms.bin_multipliers(bundle, bins)
    steep, flat = mult[bins['grade'] > 0.15].mean(), mult[np.abs(bins['grade']) < 0.03].mean()
    assert steep > flat * 1.05          # learned: slower than physics on steep climbs
    assert steep < 1.25                 # shrunk toward Tier 2 (30 runs -> half weight)
    assert bundle['shrink'] == pytest.approx(30 / (30 + rms.SHRINK_K))


def test_evaluate_opens_gate_when_the_habit_is_real():
    g = rms.evaluate(_rows(32))
    assert g['n_eval'] == 20
    assert g['open'] and g['reason'] == 'better'
    assert g['mape_t3'] < g['mape_t2']


def test_gate_rules():
    worse = [0.10, -0.12, 0.08, -0.09, 0.11] * 4
    better = [e * 0.5 for e in worse]
    assert rms.gate(worse, better)['open']
    assert rms.gate(worse[:10], better[:10])['reason'] == 'not_enough_history'   # n < 15
    assert rms.gate(worse, worse)['reason'] == 'not_better'                      # no gain
    assert rms.gate(better, worse)['reason'] == 'not_better'
    # Lower MAPE but a larger systematic bias: stays closed.
    t2 = [0.10, -0.10] * 10
    t3 = [0.07] * 20
    g = rms.gate(t2, t3)
    assert g['mape_t3'] < g['mape_t2'] and g['reason'] == 'worse_bias' and not g['open']
    assert rms.gate([], [])['reason'] == 'not_enough_history'


def test_race_ratio_shrinks_toward_095():
    train = [{'is_race': False, 'log_error': 0.0}] * 10
    assert rms.race_ratio(train) == {'ratio': 0.95, 'n_races': 0}
    one = rms.race_ratio(train + [{'is_race': True, 'log_error': math.log(0.85)}])
    assert 0.85 < one['ratio'] < 0.95 and one['n_races'] == 1
    many = rms.race_ratio(train + [{'is_race': True, 'log_error': math.log(0.85)}] * 30)
    assert many['ratio'] == pytest.approx(0.85, abs=0.01)


def test_races_are_de_effort_adjusted_and_weighted_up():
    rows = _rows(6, steep_factor=1.0, noise=0.0)
    rows[0]['is_race'] = True
    X, y, w, g = rms.training_set(rows, math.log(0.9))
    first = g == 0
    assert y[first].mean() == pytest.approx(-math.log(0.9), abs=1e-6)
    assert w[first].sum() == pytest.approx(rms.RACE_WEIGHT * w[g == 1].sum())


def test_hybrid_uses_tier3_only_when_gate_open(monkeypatch):
    from unittest.mock import MagicMock
    import services.training_load_service as tls
    from services.hybrid_prediction_service import HybridPredictionService, TIER_2, TIER_3
    rows = _rows(32)
    bundle = rms.fit(rows)
    record = SimpleNamespace(to_dict=lambda: PARAMS, param_uncertainties={'stop_share': 0.0, 'log_errors': [],
                             'race_ratio': {'ratio': 0.9, 'n_races': 4}},
                             n_activities_used=10, optimization_score=None)
    params_repo = MagicMock()
    params_repo.get_for_user.return_value = record
    model_repo = MagicMock()
    monkeypatch.setattr(tls.TrainingLoadService, 'get_training_load', lambda self, uid: {'tsb': 0.0})
    route = [{'distance': float(a), 'elevation': float(b)} for a, b in zip(*_course(7))]

    for gate_open in (True, False):
        model_repo.get_for_user.return_value = SimpleNamespace(
            metrics={'open': gate_open, 'reason': 'better' if gate_open else 'not_better', 'n_eval': 20,
                     't3_log_errors': [0.01] * 20}, model_blob=rms._serialize(bundle))
        svc = HybridPredictionService(learned_params_repo=params_repo, residual_model_repo=model_repo)
        r = svc.predict(3, route)
        race = svc.predict(3, route, effort='race')
        assert r['metadata']['tier'] == (TIER_3 if gate_open else TIER_2)
        assert r['metadata']['personal_model']['active'] is gate_open
        assert race['moving_time_seconds'] == pytest.approx(0.9 * r['moving_time_seconds'])  # personal race ratio
        if gate_open:
            assert r['moving_time_seconds'] > _physics(*_course(7))['total_time_seconds']  # steep habit applied
