import pytest
from rtplot import client
from rtplot.client import Button, ControlsRow, Plot, Section, Text, View
from rtplot.ui_state import CAPABILITIES, declarations, merge_state, presentation_requested


def test_typed_presentation_matches_dictionaries_and_defaults(monkeypatch):
    sent=[]
    def ack(cfg, timeout):
        sent.append(client._wire_config(cfg))
        client._accept_ack({'capabilities':CAPABILITIES})
    monkeypatch.setattr(client,'_send_initialize_with_handshake',ack)
    rows=[ControlsRow([Text('state','State','Ready',appearance='state'), Button('stop','Stop',appearance='danger')],section='status'),
          ControlsRow([Button('raw','Raw',appearance='choice'),Button('smooth','Smooth',appearance='choice')],title='Source',exclusive=True),
          Plot(names=['signal'],min_height=220)]
    view=View([Section('status','Status',navigation='secondary',density='compact',show_heading=False)],essential_controls=['state','stop'])
    client.initialize_plots(rows,view=view)
    first=sent[-1]
    client.initialize_plots([r.to_dict() for r in rows],view=view.to_dict())
    second=sent[-1]
    first['__rtplot_view__']['rtplot']['generation']+=1
    assert first==second
    assert 'appearance' not in Button('stop','Stop').to_dict()  # Labels never assign meaning.
    assert 'min_height' not in Plot(names=['signal']).to_dict()


def test_exclusive_selection_is_authoritative_and_atomic():
    view, controls=declarations({'choice': {'exclusive':True,'controls':[
        {'type':'button','id':'a'},{'type':'button','id':'b'}]}})
    first=merge_state({}, {'controls':{'a':{'selected':True,'reason':'Keep reason'}}},controls,view)
    second=merge_state(first, {'controls':{'b':{'selected':True}}},controls,view)
    assert second['controls']['a']=={'reason':'Keep reason'}
    assert first['controls']['a']['selected'] is True
    with pytest.raises(ValueError,match='only one'):
        merge_state(second, {'controls':{'a':{'selected':True},'b':{'selected':True}}},controls,view)
    assert merge_state(second, {'controls':{'b':None}},controls,view)['controls']=={'a':{'reason':'Keep reason'}}


@pytest.mark.parametrize('rows,view',[
    ({'c':{'controls':[]}}, {'essential_controls':['missing']}),
    ({'p':{'names':['x'],'min_height':100}},{}),
    ({'c':{'controls':[{'type':'button','id':'go','appearance':'inferred'}]}},{}),
    ({'c':{'exclusive':True,'controls':[{'type':'text','id':'state'}]}},{}),
    ({}, {'sections':[{'id':'s','navigation':'hidden'}]}),
    ({}, {'sections':[{'id':'s','show_heading':'false'}]}),
])
def test_invalid_presentation_rejected(rows,view):
    with pytest.raises(ValueError): declarations(rows,view)


def test_old_server_warning_without_changing_legacy_state_api(monkeypatch):
    monkeypatch.setattr(client,'_send_initialize_with_handshake',lambda *_:client._accept_ack({'capabilities':['sections','ui_state_v1']}))
    with pytest.warns(RuntimeWarning,match='essential placement'):
        client.initialize_plots([ControlsRow([Button('stop','Stop')])],view=View([],essential_controls=['stop']))
    monkeypatch.setattr(client,'_publish_ui_if_due',lambda **_:None)
    assert client.set_ui_state({'controls':{'stop':{'enabled':False}}})
    view,registry=declarations({'p':{'names':['x']}},View([Section('s','S')]))
    assert not presentation_requested({'p':{'names':['x']}},view)
