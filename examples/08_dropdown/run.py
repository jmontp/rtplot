"""A synthetic signal controlled by a native dropdown; no hardware required."""
import math
import time
from rtplot import client


def configuration():
    return [
        {'controls': [
            {'type': 'dropdown', 'id': 'wave', 'label': 'Waveform',
             'options': [{'value': 'sine', 'label': 'Sine wave'},
                         {'value': 'square', 'label': 'Square wave'}, 'triangle'], 'value': 'sine'},
            {'type': 'button', 'id': 'reset', 'label': 'Reset waveform'},
            {'type': 'text', 'id': 'state', 'label': 'Current waveform', 'value': 'sine'},
        ]},
        {'names': ['Signal'], 'title': 'Waveform preview', 'xrange': 300},
    ]


def main(make_configuration=configuration):
    client.local_plot()
    client.initialize_plots(make_configuration())
    index = 0
    while True:
        controls = client.poll_controls()
        wave = controls.values.get('wave', 'sine')
        if 'reset' in controls.buttons:
            client.set_dropdown('wave', 'sine')
            wave = 'sine'
        phase = index / 30
        value = {'sine': math.sin(phase), 'square': 1 if math.sin(phase) >= 0 else -1,
                 'triangle': 2 / math.pi * math.asin(math.sin(phase))}[wave]
        client.set_display('state', wave)
        client.send_array([value])
        index += 1
        time.sleep(.02)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
