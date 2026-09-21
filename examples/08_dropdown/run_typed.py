"""Typed equivalent of run.py."""
import run as demo
from rtplot.client import Button, ControlsRow, Dropdown, Plot, Text


def configuration():
    return [ControlsRow([
        Dropdown('wave', 'Waveform', [{'value': 'sine', 'label': 'Sine wave'},
                 {'value': 'square', 'label': 'Square wave'}, 'triangle'], value='sine'),
        Button('reset', 'Reset waveform'), Text('state', 'Current waveform', 'sine'),
    ]), Plot(names=['Signal'], title='Waveform preview', xrange=300)]


if __name__ == '__main__':
    try:
        demo.main(configuration)
    except KeyboardInterrupt:
        pass
