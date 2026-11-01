import services.route_matcher as rm


def test_rematch_only_when_route_inputs_change(monkeypatch):
    calls = []
    monkeypatch.setattr(rm, 'match_routes_to_plan', lambda plan, prefs: calls.append(plan.weeks))
    day = {'workout_type': 'easy', 'distance_km': 10, 'notes': 'a'}
    rm.rematch_day_if_changed(1, dict(day, notes='b'), day)
    assert calls == []
    rm.rematch_day_if_changed(1, dict(day, distance_km=14), day)
    assert len(calls) == 1
