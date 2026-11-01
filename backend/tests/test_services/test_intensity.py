"""HR intensity model: recovers speed-vs-%HRR from easy runs with bursts, HR lag, fallbacks, race effort."""

import math
from types import SimpleNamespace

import numpy as np
import pytest

from services import intensity_service as ins

PARAMS = {'v_flat': 3.0, 'k_up': 1.0, 'k_tech': 1.0, 'a_param': 3.0, 'k_terrain_up': 1.08,
          'k_terrain_down': 1.12, 'k_terrain_flat': 1.05, 'fatigue_alpha': 0.3}
HR_MAX, HR_REST = 180, 60


def _run(base_hrr=0.5, burst_hrr=0.85, seconds=5400, seed=0):
    """Flat 1 Hz run: easy with 3-min bursts every 15 min. Speed = k * %HRR (b = 1);
    HR follows the effort 30 s late, as a real heart does."""
    rng = np.random.default_rng(seed)
    t = np.arange(seconds)
    hrr = np.where((t % 900) >= 720, burst_hrr, base_hrr)
    speed = 5.0 * hrr
    hr_effort = HR_REST + hrr * (HR_MAX - HR_REST)
    hr = np.concatenate([np.full(30, hr_effort[0]), hr_effort[:-30]]) + rng.normal(0, 1, seconds)
    d = np.cumsum(speed)
    return SimpleNamespace(streams={'time': t.tolist(), 'distance': d.tolist(), 'altitude': [100.0] * seconds,
                                    'heartrate': hr.tolist(), 'moving': [True] * seconds})


def test_fit_recovers_intensity_slope_from_bursts():
    acts = [_run(seed=i) for i in range(5)]
    m = ins.fit(acts, PARAMS, HR_MAX, HR_REST)
    assert m['b'] == pytest.approx(1.0, abs=0.1)
    assert m['i_ref'] == pytest.approx(0.5, abs=0.05)     # mostly easy
    # A race at 85 % HRR is ~1.7x faster than the easy calibration runs.
    assert ins.time_multiplier(m, 0.85) == pytest.approx(0.5 / 0.85, rel=0.1)


def test_hr_max_estimated_when_profile_missing_and_no_hr_falls_back():
    acts = [_run(seed=i) for i in range(4)]
    hr_max, hr_rest = ins.hr_bounds(acts)
    assert 150 < hr_max <= 185 and hr_rest == ins.DEFAULT_HR_REST
    no_hr = [SimpleNamespace(streams={k: v for k, v in a.streams.items() if k != 'heartrate'}) for a in acts]
    assert ins.fit(no_hr, PARAMS) is None
    assert ins.fit(acts[:2], PARAMS, HR_MAX, HR_REST) is None    # < 3 runs with HR


def test_race_intensity_prior_falls_with_duration_and_learns_from_races():
    assert ins.race_intensity_prior(1) > ins.race_intensity_prior(3) > ins.race_intensity_prior(24) >= 0.5
    assert ins.race_offset([]) == 0.0
    held = [{'intensity': ins.race_intensity_prior(5) + 0.08, 'hours': 5}] * 3
    assert ins.race_offset(held) == pytest.approx(0.08 * 3 / 4)   # shrunk like n / (n + 1)


def test_moving_at_effort_is_consistent_and_gives_bpm():
    m = {'b': 1.0, 'i_ref': 0.5, 'hr_max': HR_MAX, 'hr_rest': HR_REST, 'race_offset': 0.0}
    train = ins.moving_at_effort(m, 'training', 3 * 3600)
    assert train['moving_s'] == pytest.approx(3 * 3600)
    race = ins.moving_at_effort(m, 'race', 3 * 3600)
    hours = race['moving_s'] / 3600
    assert race['intensity'] == pytest.approx(ins.race_intensity_prior(hours), abs=0.01)  # fixed point
    assert race['moving_s'] < train['moving_s'] < ins.moving_at_effort(m, 'recovery', 3 * 3600)['moving_s']
    assert HR_REST < race['hr_low'] < race['hr_high'] <= HR_MAX


def test_hybrid_race_effort_uses_intensity_when_available():
    from unittest.mock import MagicMock
    from services.hybrid_prediction_service import HybridPredictionService
    model = {'b': 1.0, 'i_ref': 0.5, 'hr_max': HR_MAX, 'hr_rest': HR_REST, 'race_offset': 0.0}
    record = SimpleNamespace(to_dict=lambda: PARAMS, n_activities_used=10, optimization_score=None,
                             param_uncertainties={'stop_share': 0.0, 'log_errors': [], 'intensity': model})
    repo, model_repo = MagicMock(), MagicMock()
    repo.get_for_user.return_value = record
    model_repo.get_for_user.return_value = None
    svc = HybridPredictionService(learned_params_repo=repo, residual_model_repo=model_repo)
    route = [{'distance': d, 'elevation': 300.0} for d in range(0, 30001, 50)]
    train, race = svc.predict(3, route), svc.predict(3, route, effort='race')
    assert race['metadata']['intensity']['hr_low'] > HR_REST
    expected = ins.moving_at_effort(model, 'race', train['moving_time_seconds'])['moving_s']
    assert race['moving_time_seconds'] == pytest.approx(expected)
    assert race['moving_time_seconds'] < 0.8 * train['moving_time_seconds']   # far below the old x0.95
    assert math.isclose(sum(s['time_s'] for s in race['segments']), race['moving_time_seconds'], rel_tol=1e-6)


def test_sustainability_levels_follow_race_intensity_and_history():
    m = {'b': 0.4, 'i_ref': 0.6, 'hr_max': HR_MAX, 'hr_rest': HR_REST, 'race_offset': 0.0,
         'efforts': [{'hours': 5.0, 'intensity': 0.80, 'name': 'Montanaro', 'date': '2026-05-10'},
                     {'hours': 1.5, 'intensity': 0.95, 'name': 'short', 'date': '2026-06-01'}]}
    race_i = ins.effort_intensity(m, 'race', 5)
    assert ins.sustainability(m, race_i - 0.10, 5)['level'] == 'easy'
    assert ins.sustainability(m, race_i, 5)['level'] == 'sustainable'
    assert ins.sustainability(m, race_i + 0.04, 5)['level'] == 'hard'
    v = ins.sustainability(m, race_i + 0.10, 5)
    assert v['level'] == 'too_hard'
    # the short 1.5 h run is not evidence for a 5 h race
    assert v['best']['name'] == 'Montanaro'


def test_moving_at_hr_harder_is_faster_and_reports_verdict():
    m = {'b': 0.4, 'i_ref': 0.6, 'hr_max': HR_MAX, 'hr_rest': HR_REST, 'race_offset': 0.0, 'efforts': []}
    easy, hard = ins.moving_at_hr(m, HR_REST + 0.6 * (HR_MAX - HR_REST), 3600 * 5), ins.moving_at_hr(m, HR_MAX - 5, 3600 * 5)
    assert hard['moving_s'] < easy['moving_s'] == pytest.approx(3600 * 5, rel=1e-3)
    assert hard['verdict']['level'] == 'too_hard' and hard['target_hr'] == HR_MAX - 5
