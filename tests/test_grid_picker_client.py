import pytest
from rtplot import client
from rtplot.ui_state import CAPABILITIES, declarations, merge_state

X = ['j1', {'value': 'j2', 'label': 'J2: 1e-3'}, 'j3']
Y = [{'value': 'w1', 'label': 'W1'}, 'w2']


class Socket:
    def __init__(self): self.sent = []
    def send_string(self, *args): pass
    def send_json(self, payload): self.sent.append(payload)


def grid(**kwargs):
    return client.GridPicker('g', 'Weights', X, Y, x_label='Jerk', y_label='Shake', **kwargs)


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(client, '_send_initialize_with_handshake', lambda *_: client._accept_ack({'capabilities': CAPABILITIES}))
    socket = Socket()
    monkeypatch.setattr(client, 'socket', socket)
    client.initialize_plots([client.ControlsRow([
        grid(value=('j2', 'w2')), client.Dropdown('method', 'Method', ['M', 'D']),
        client.Text('readout', 'Active', ''), client.Button('ref', 'Reference')])])
    return socket


def test_typed_and_dictionary_declarations_match():
    typed = grid(value=('j2', 'w1'), active=False).to_dict()
    assert typed == {'type': 'grid_picker', 'id': 'g', 'label': 'Weights', 'x_label': 'Jerk', 'y_label': 'Shake',
                     'x_options': X, 'y_options': Y, 'value': {'x': 'j2', 'y': 'w1'}, 'active': False}
    _, registry = declarations({'row': {'controls': [typed]}})
    assert registry['g'] == {'type': 'grid_picker', 'section': None, 'x_options': ['j1', 'j2', 'j3'],
                             'y_options': ['w1', 'w2'], 'default': {'x': 'j2', 'y': 'w1'}, 'active': False}
    # Arbitrary finite axes; an omitted value confirms the first X and Y options.
    _, registry = declarations({'row': {'controls': [client.GridPicker('g', 'G', ['a'], ['b', 'c', 'd', 'e']).to_dict()]}})
    assert registry['g']['default'] == {'x': 'a', 'y': 'b'}


@pytest.mark.parametrize('change', [
    {'x_options': []}, {'y_options': None}, {'x_options': ['a', 'a']}, {'y_options': ['']},
    {'x_options': [{'value': 'a', 'label': 1}]}, {'x_options': [1]}, {'value': {'x': 'j9', 'y': 'w1'}},
    {'value': {'x': 'j1'}}, {'value': ['j1', 'w1']}, {'active': 'yes'}, {'x_label': 3},
])
def test_invalid_declarations(change):
    control = {**grid().to_dict(), **change}
    with pytest.raises(ValueError):
        declarations({'row': {'controls': [control]}})


def test_state_validation_and_reset():
    view, registry = declarations({'row': {'controls': [grid().to_dict(), {'type': 'button', 'id': 'b', 'label': 'B'}]}})
    empty = {'controls': {}, 'sections': {}}
    state = merge_state(empty, {'controls': {'g': {'value': {'x': 'j3', 'y': 'w2'}, 'active': False, 'request': 'r',
                                                   'cells': {'j1': {'w1': {'enabled': False, 'reason': 'Not exported'}}}}}},
                        registry, view)
    assert state['controls']['g']['cells']['j1']['w1']['reason'] == 'Not exported'
    assert merge_state(state, {'controls': {'g': {'value': None, 'cells': None}}}, registry, view)['controls']['g'] == {
        'active': False, 'request': 'r'}
    for bad in ({'value': {'x': 'j9', 'y': 'w1'}}, {'cells': {'j9': {}}}, {'cells': {'j1': {'w9': {}}}},
                {'cells': {'j1': {'w1': {'color': 'red'}}}}, {'cells': {'j1': {'w1': {'enabled': 1}}}},
                {'active': 1}, {'message': 3}, {'unknown': 1}):
        with pytest.raises(ValueError):
            merge_state(empty, {'controls': {'g': bad}}, registry, view)
    with pytest.raises(ValueError):  # grid properties belong only to grid pickers
        merge_state(empty, {'controls': {'b': {'value': {'x': 'j1', 'y': 'w1'}}}}, registry, view)


def test_set_grid_picker_publishes_one_atomic_revision(ready):
    revision = client._ui_revision
    client.set_grid_picker('g', 'j3', 'w1', cells={('j1', 'w2'): {'enabled': False, 'reason': 'Not exported'}},
                           message='', request_id='req-1', values={'method': 'D', 'readout': 'D · J3'},
                           ui_state={'controls': {'ref': {'selected': None}, 'g': {'busy': None}}})
    payload = ready.sent[-1]
    assert payload['revision'] == revision + 1
    assert payload['state']['controls']['g'] == {'value': {'x': 'j3', 'y': 'w1'}, 'active': True, 'request': 'req-1',
                                                 'cells': {'j1': {'w2': {'enabled': False, 'reason': 'Not exported'}}},
                                                 'message': ''}
    assert payload['values'] == {'method': {'value': 'D', 'revision': revision + 1},
                                 'readout': {'value': 'D · J3', 'revision': revision + 1}}
    # Linked dropdown values update locally, so the next poll does not look like a request.
    assert client._control_values['method'] == 'D'
    assert client.grid_selection('g') == ('j3', 'w1', True)
    assert client.grid_cell_state('g', 'j1', 'w2')['enabled'] is False
    # Identical rejections are still new revisions that resolve their request IDs.
    client.reject_grid_request('g', 'req-2', 'Torque is on')
    client.reject_grid_request('g', 'req-3', 'Torque is on')
    assert [p['state']['controls']['g']['request'] for p in ready.sent[-2:]] == ['req-2', 'req-3']
    assert ready.sent[-1]['revision'] == revision + 3
    assert client.grid_selection('g') == ('j3', 'w1', True)
    client.set_grid_picker('g', 'j3', 'w1', active=False)
    assert 'request' not in client._ui_state['controls']['g'] and client.grid_selection('g')[2] is False


@pytest.mark.parametrize('args,kwargs', [
    (('missing', 'j1', 'w1'), {}), (('method', 'M', 'w1'), {}), (('g', 'j9', 'w1'), {}), (('g', 'j1', 'w9'), {}),
    (('g', 'j1', 'w1'), {'cells': {('j9', 'w1'): {}}}), (('g', 'j1', 'w1'), {'values': {'method': 'X'}}),
    (('g', 'j1', 'w1'), {'values': {'ref': 'x'}}), (('g', 'j1', 'w1'), {'values': {'missing': 'x'}}),
    (('g', 'j1', 'w1'), {'ui_state': {'controls': {'missing': {}}}}),
])
def test_invalid_grid_updates_publish_nothing(ready, args, kwargs):
    before = (len(ready.sent), client._ui_revision, client._ui_state)
    with pytest.raises(ValueError):
        client.set_grid_picker(*args, **kwargs)
    assert (len(ready.sent), client._ui_revision, client._ui_state) == before


def test_grid_requests_channel_filters_stale_events(ready, monkeypatch):
    epoch = client._source_epoch = 'epoch'
    events = [
        {'type': 'grid', 'id': 'g', 'x': 'j1', 'y': 'w1', 'request_id': 'a', 'session': client._session,
         'generation': client._generation, 'source_epoch': epoch},
        {'type': 'grid', 'id': 'g', 'x': 'j3', 'y': 'w2', 'request_id': 'old', 'session': client._session,
         'generation': client._generation - 1, 'source_epoch': epoch},
        {'type': 'grid', 'id': 'g', 'x': 'j2', 'y': 'w2', 'request_id': 'b', 'session': client._session,
         'generation': client._generation, 'source_epoch': epoch},
        {'type': 'button', 'id': 'ref', 'session': client._session, 'generation': client._generation, 'source_epoch': epoch},
    ]

    class Control:
        def recv_json(self, flags=0):
            if not events: raise client.zmq.Again()
            return events.pop(0)
    monkeypatch.setattr(client, 'control_socket', Control())
    state = client.poll_controls()
    assert state.grid_requests == [client.GridRequest('g', 'j1', 'w1', 'a'), client.GridRequest('g', 'j2', 'w2', 'b')]
    values, buttons = state  # existing two-item unpacking keeps working
    assert buttons == ['ref'] and isinstance(values, dict)
    assert client.poll_controls().grid_requests == []  # drained once per poll


def test_unsupported_server_requires_explicit_fallback(monkeypatch):
    monkeypatch.setattr(client, '_send_initialize_with_handshake', lambda *_: client._accept_ack(
        {'capabilities': [c for c in CAPABILITIES if c != 'grid_picker_v1']}))
    with pytest.raises(RuntimeError, match='Grid pickers require'):
        client.initialize_plots([client.ControlsRow([grid()])])
    assert 'grid_picker_v1' not in client.server_capabilities()
    with pytest.raises(RuntimeError):
        client.set_grid_picker('g', 'j1', 'w1')
