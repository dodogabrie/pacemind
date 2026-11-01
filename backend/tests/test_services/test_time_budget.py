"""Sanity tests for hours <-> km/elevation conversions."""
import pytest

from services.physics_model.time_budget import (
    DEFAULT_V_FLAT_M_S,
    effort_for_workout,
    predict_distance_for_time,
    predict_time_for_distance,
)


class TestRoundTrip:
    @pytest.mark.parametrize('hours,ratio', [
        (1.0, 0.0),    # flat 1h
        (2.5, 30.0),   # rolling
        (5.0, 70.0),   # mountain long
    ])
    def test_round_trip_within_5_percent(self, hours, ratio):
        km, elev = predict_distance_for_time(hours, ratio, learned_params=None,
                                             effort='long_run')
        round_hours = predict_time_for_distance(km, elev, learned_params=None,
                                                effort='long_run')
        assert km > 0
        assert abs(round_hours - hours) / hours < 0.05, (
            f'round-trip drift > 5%: {hours}h -> {km}km/{elev}m -> {round_hours}h'
        )


class TestSanity:
    def test_flat_hour_default_runner_is_about_8_to_10_km(self):
        """At default v_flat (~6:30/km) and 'easy' effort (0.85x), 1h flat
        should land in [7.5, 11] km. Sanity bounds, not exactness.
        """
        km, _ = predict_distance_for_time(1.0, 0.0, effort='easy')
        assert 7.5 <= km <= 11.0, km

    def test_steeper_grade_means_fewer_km_per_hour(self):
        flat_km, _ = predict_distance_for_time(2.0, 0.0, effort='long_run')
        rolling_km, _ = predict_distance_for_time(2.0, 50.0, effort='long_run')
        mountain_km, _ = predict_distance_for_time(2.0, 100.0, effort='long_run')
        assert flat_km > rolling_km > mountain_km

    def test_more_hours_means_more_km(self):
        a, _ = predict_distance_for_time(1.0, 30.0, effort='long_run')
        b, _ = predict_distance_for_time(3.0, 30.0, effort='long_run')
        assert b > a

    def test_zero_hours_zero_km(self):
        km, elev = predict_distance_for_time(0.0, 50.0)
        assert km == 0.0 and elev == 0.0

    def test_zero_km_zero_hours(self):
        assert predict_time_for_distance(0.0, 0.0) == 0.0

    def test_default_v_flat_matches_6_30_min_km(self):
        # 6:30 / km == 60 / 6.5 = 9.23 km/h == 2.564 m/s
        assert abs(DEFAULT_V_FLAT_M_S - 2.564) < 0.01


class TestEffortMapping:
    def test_long_run_maps_to_long_run(self):
        assert effort_for_workout('long_run') == 'long_run'

    def test_tempo_intervals_hill_repeats_map_to_tempo(self):
        for wt in ('tempo', 'intervals', 'hill_repeats',
                   'vert_session', 'race_simulation'):
            assert effort_for_workout(wt) == 'tempo', wt

    def test_easy_default_for_unknown(self):
        assert effort_for_workout('totally_made_up_type') == 'easy'

    def test_recovery_easy_pickups_strides_treated_as_easy_or_recovery(self):
        # All non-hard types should classify into the easy/recovery bucket.
        for wt in ('easy', 'recovery', 'easy_pickups', 'easy_strides',
                   'rest', 'strength'):
            assert effort_for_workout(wt) in ('easy', 'recovery'), wt


class TestEffortDiscount:
    def test_tempo_faster_than_easy(self):
        # Same hours, same ratio — tempo should cover more km than easy.
        easy_km, _ = predict_distance_for_time(1.5, 30.0, effort='easy')
        tempo_km, _ = predict_distance_for_time(1.5, 30.0, effort='tempo')
        assert tempo_km > easy_km

    def test_long_run_slower_than_easy(self):
        easy_km, _ = predict_distance_for_time(1.5, 30.0, effort='easy')
        long_km, _ = predict_distance_for_time(1.5, 30.0, effort='long_run')
        assert long_km < easy_km
