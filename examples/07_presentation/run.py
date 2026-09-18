"""Responsive presentation demo. All state and actions are synthetic."""
import math
import time
from rtplot import client


def configuration():
    rows = [
        {'section': 'status', 'controls': [
            {'type': 'text', 'id': 'hardware', 'label': 'Hardware', 'value': 'Simulated · ready', 'appearance': 'state'},
            {'type': 'button', 'id': 'stop', 'label': 'Stop', 'appearance': 'danger'},
        ]},
        {'section': 'setup', 'title': 'Preparation', 'controls': [
            {'type': 'text', 'id': 'help', 'label': '', 'value': 'Prepare the synthetic source before starting. No hardware is connected.', 'appearance': 'help'},
            {'type': 'button', 'id': 'prepare', 'label': 'Prepare', 'appearance': 'primary'},
            {'type': 'button', 'id': 'start', 'label': 'Start', 'appearance': 'primary'},
            {'type': 'text_input', 'id': 'note', 'label': 'Notes', 'value': 'Keep this edit while resizing'},
        ]},
        {'section': 'work', 'columns': 3, 'plots': [
            {'names': ['Signal', 'Reference'], 'title': 'Tracking', 'xrange': 120, 'min_height': 220, 'colors': ['#175fa5', '#a53c00'], 'line_style': ['solid', 'dashed']},
            {'names': ['Error'], 'title': 'Error', 'xrange': 120, 'min_height': 220, 'colors': ['#923d88']},
            {'names': ['Detail'], 'title': 'Detail', 'xrange': 120, 'min_height': 220, 'colors': ['#087563'], 'line_style': ['dotted']},
        ]},
        {'section': 'advanced', 'title': 'Source choice', 'exclusive': True, 'controls': [
            {'type': 'button', 'id': 'raw', 'label': 'Raw', 'appearance': 'choice'},
            {'type': 'button', 'id': 'smooth', 'label': 'Smoothed', 'appearance': 'choice'},
        ]},
        {'section': 'advanced', 'title': 'Optional settings', 'controls': [
            {'type': 'slider', 'id': 'gain', 'label': 'Gain', 'min': 0, 'max': 2, 'value': 1},
            {'type': 'button', 'id': 'reset', 'label': 'Reset settings', 'appearance': 'warning'},
            {'type': 'text', 'id': 'advanced_help', 'label': '', 'value': 'These controls change the example only. Expand sections and resize without resetting the stream.', 'appearance': 'help'},
        ]},
    ]
    view = {'persistent_section': 'status', 'essential_controls': ['hardware', 'stop'], 'sections': [
        {'id': 'status', 'title': 'Status', 'density': 'compact', 'show_heading': False},
        {'id': 'setup', 'title': 'Setup'},
        {'id': 'work', 'title': 'Work'},
        {'id': 'advanced', 'title': 'Advanced', 'navigation': 'secondary', 'collapsible': True, 'collapsed': True},
    ]}
    return rows, view


def main(make_configuration=configuration):
    client.local_plot()
    rows, view = make_configuration()
    client.initialize_plots(rows, view=view, ui_state={
        'controls': {'start': {'enabled': False, 'reason': 'Prepare the source first'}, 'raw': {'selected': True}},
        'sections': {'setup': {'status': 'ready'}, 'work': {'status': 'idle'}},
    })
    prepared = False
    try:
        while True:
            state = client.poll_controls()
            for action in state.buttons:
                if action == 'prepare':
                    prepared = True
                    client.set_ui_state({'controls': {'start': None}, 'sections': {'setup': {'status': 'complete'}}})
                elif action == 'start' and prepared:
                    client.set_display('hardware', 'Simulated · active')
                    client.set_ui_state({'sections': {'work': {'status': 'busy'}}})
                elif action == 'stop':
                    client.set_display('hardware', 'Simulated · stopped')
                    client.set_ui_state({'sections': {'work': {'status': 'ready'}}})
                elif action in ('raw', 'smooth'):
                    client.set_ui_state({'controls': {action: {'selected': True}}})
                elif action == 'reset':
                    client.set_ui_state({'controls': {'raw': {'selected': True}}})
            t = time.monotonic()
            client.send_array([math.sin(t), math.sin(t + .2), math.sin(t)-math.sin(t+.2), math.cos(3*t)])
            time.sleep(.02)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
