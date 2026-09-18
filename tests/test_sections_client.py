"""Client capability negotiation and equivalent typed/dictionary declarations."""
import pytest
from rtplot import client
from rtplot.client import Button, ControlsRow, Plot, PlotRow, Section, View
from rtplot.ui_state import META_KEY


def test_typed_and_dictionary_forms_and_generation(monkeypatch):
    sent = []
    def acknowledge(cfg, timeout):
        sent.append(client._wire_config(cfg))
        client._accept_ack({'session': client._session, 'generation': client._generation,
                            'source_epoch': 'epoch', 'capabilities': ['sections', 'ui_state_v1']})
    monkeypatch.setattr(client, '_send_initialize_with_handshake', acknowledge)
    rows = [ControlsRow([Button('go', 'Go')], section='status'),
            PlotRow([Plot(names=['a']), Plot(names=['b'])], columns=2, section='work')]
    view = View([Section('status', 'Status'), Section('work', 'Work', collapsible=True)], 'status')
    seed = {'controls': {'go': {'enabled': False}}}
    client.initialize_plots(rows, view=view, ui_state=seed)
    client.initialize_plots([r.to_dict() for r in rows], view=view.to_dict(), ui_state=seed)
    first, second = sent
    assert second[META_KEY]['rtplot']['generation'] == first[META_KEY]['rtplot']['generation'] + 1
    first[META_KEY]['rtplot']['generation'] += 1
    assert first == second
    published = []
    monkeypatch.setattr(client, '_publish_ui_if_due', lambda force=False: published.append(force))
    assert client.set_ui_state({'controls': {'go': {'enabled': False}}}) is False
    assert client._ui_revision == 0
    assert client.set_ui_state({'controls': {'go': None}}) is True
    assert client._ui_revision == 1
    assert client._ui_state == {'controls': {}, 'sections': {}}
    assert published.count(True) == 1


def test_incompatible_server_explicit_warning_and_no_false_enforcement(monkeypatch):
    monkeypatch.setattr(client, '_send_initialize_with_handshake', lambda *_: client._accept_ack({'type': 'config_ack'}))
    with pytest.warns(RuntimeWarning, match='NOT enforced'):
        client.initialize_plots([Plot(names=['a'], section='work')], view=View([Section('work', 'Work')]))
    with pytest.raises(RuntimeError, match='enforcement is unavailable'):
        client.set_ui_state({'sections': {'work': {'visible': False}}})
    # Legacy initialization itself needs no new capability.
    client.initialize_plots([Plot(names=['a'])])


def test_stale_ack_and_command_epoch(monkeypatch):
    monkeypatch.setattr(client, '_server_capabilities', {'ui_state_v1'})
    monkeypatch.setattr(client, '_source_epoch', 'current')
    event = {'session': client._session, 'generation': client._generation, 'source_epoch': 'current'}
    assert client._current_event(event)
    assert not client._current_event({**event, 'source_epoch': 'old'})
    assert not client._accept_ack({**event, 'generation': client._generation - 1})
