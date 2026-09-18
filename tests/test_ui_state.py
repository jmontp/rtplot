import pytest
from rtplot.ui_state import declarations, merge_state


@pytest.fixture
def declared():
    return declarations({'p': {'names': ['a'], 'section': 'work'},
                         'c': {'controls': [{'type': 'button', 'id': 'go'}], 'section': 'work'}},
                        {'sections': [{'id': 'work', 'visible': False}]})


def test_patches_reset_properties_without_mutating_existing_state(declared):
    view, controls = declared
    original = {'controls': {}, 'sections': {}}
    one = merge_state(original, {'controls': {'go': {'enabled': False, 'reason': 'Wait'}}}, controls, view)
    two = merge_state(one, {'controls': {'go': {'enabled': None}}, 'sections': {'work': {'visible': True}}}, controls, view)
    assert original == {'controls': {}, 'sections': {}}
    assert one['controls']['go']['enabled'] is False
    assert two['controls']['go'] == {'reason': 'Wait'}
    assert merge_state(two, {'controls': {'go': None}}, controls, view)['controls'] == {}


@pytest.mark.parametrize('patch', [
    {'controls': {'unknown': {'enabled': False}}},
    {'controls': {'go': {'enabled': 0}}},
    {'controls': {'go': {'value': 5}}},
    {'sections': {'work': {'collapsed': True}}},
    {'sections': {'work': {'status': 'success'}}},
    {'controls': {'go': {'reason': 'x' * 4097}}},
])
def test_invalid_state_rejected_atomically(declared, patch):
    view, controls = declared
    with pytest.raises(ValueError):
        merge_state({'controls': {}, 'sections': {}}, patch, controls, view)


@pytest.mark.parametrize('view,rows', [
    ({'sections': [{'id': 's'}, {'id': 's'}]}, {}),
    ({'sections': []}, {'p': {'names': ['x'], 'section': 'missing'}}),
    ({'sections': [{'id': 's'}], 'persistent_section': 's'}, {'p': {'names': ['x'], 'section': 's'}}),
])
def test_invalid_sections(view, rows):
    with pytest.raises(ValueError):
        declarations(rows, view)
