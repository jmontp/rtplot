import pytest
from rtplot import client
from rtplot.ui_state import CAPABILITIES, declarations


def test_typed_and_dictionary_dropdown(monkeypatch):
    monkeypatch.setattr(client, '_send_initialize_with_handshake', lambda *_: client._accept_ack({'capabilities': CAPABILITIES}))
    dropdown = client.Dropdown('mode', 'Mode', ['raw', {'value': 'smooth', 'label': 'Smoothed'}])
    client.initialize_plots([client.ControlsRow([dropdown])])
    assert client._control_registry['mode']['options'] == ['raw', 'smooth']
    _, registry = declarations({'row': {'controls': [dropdown.to_dict()]}})
    assert registry == client._control_registry
    class Socket:
        def send_string(self, *args): pass
        def send_json(self, payload): self.payload = payload
    socket = Socket()
    monkeypatch.setattr(client, 'socket', socket)
    client.set_dropdown('mode', 'smooth')
    assert socket.payload == {'id': 'mode', 'value': 'smooth', 'session': client._session, 'generation': client._generation}
    for cid, value in [('missing', 'raw'), ('mode', 'invalid'), ('mode', 1)]:
        with pytest.raises(ValueError): client.set_dropdown(cid, value)


@pytest.mark.parametrize('options,value', [([], 'x'), (['x', 'x'], 'x'), ([1], 1), ([{'value': 'x', 'label': 1}], 'x'), (['x'], 'y'), (['x'], None)])
def test_invalid_choices(options, value):
    with pytest.raises(ValueError):
        declarations({'row': {'controls': [{'type': 'dropdown', 'id': 'mode', 'options': options, 'value': value}]}})


def test_old_server_warning(monkeypatch):
    monkeypatch.setattr(client, '_send_initialize_with_handshake', lambda *_: None)
    with pytest.warns(RuntimeWarning, match='Dropdowns require'):
        client.initialize_plots([client.ControlsRow([client.Dropdown('mode', 'Mode', ['raw'])])])
    with pytest.raises(RuntimeError): client.set_dropdown('mode', 'raw')
