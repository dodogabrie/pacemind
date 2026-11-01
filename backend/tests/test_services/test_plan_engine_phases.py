"""Phase assignment: combinatorial coverage of total_weeks x category."""
import pytest

from services.plan_engine import assign_phases


@pytest.mark.parametrize('total_weeks', [2, 4, 6, 8, 12, 18, 24])
@pytest.mark.parametrize('category', ['cat_1', 'cat_2'])
def test_assign_phases_invariants(total_weeks, category):
    phases = assign_phases(total_weeks, category)
    assert len(phases) == total_weeks
    assert phases[-1] == 'Race', "last week must be Race"
    if total_weeks >= 6:
        assert phases.count('Taper') == 2
    elif total_weeks >= 2:
        assert phases.count('Taper') == 1


def test_recovery_inserted_in_long_block():
    """A 12-week cat_2 plan should include at least one Recovery week
    inside the build block (3:1 modulation).
    """
    phases = assign_phases(12, 'cat_2')
    assert 'Recovery' in phases
