"""Typed equivalent of run.py."""
import run as demo
from rtplot.client import (Button, ControlsRow, Dropdown, GridPicker, Plot, Section, Slider,
                           Text, View)


def configuration():
    controls = [
        ControlsRow([Text('active_model', 'Active controller', 'Starting…', appearance='state'),
                     Button('stop', 'Stop torque', appearance='danger')], section='status'),
        ControlsRow([
            Dropdown('method', 'Anti-shake method',
                     [{'value': m, 'label': label} for m, label in demo.METHODS], value='M'),
            Button('reference', 'Reference at this jerk', appearance='choice'),
            GridPicker(demo.GRID, 'Training weights',
                       x_options=[{'value': v, 'label': label} for v, label in demo.JERK],
                       y_options=[{'value': v, 'label': label} for v, label in demo.SHAKE],
                       x_label='Jerk weight', y_label='Anti-shake weight multiplier', value=('j2', 'w2')),
            Text('readiness', 'Readiness', 'Ready'),
            Button('enable', 'Enable torque', appearance='primary'),
        ], section='controller', title='Controller'),
        ControlsRow([Slider('mass', 'Body mass (kg)', 40, 120, 75, step=1),
                     Slider('gain', 'Assistance gain', 0, 1, 0.5, step=0.05)],
                    section='controller', title='Live settings'),
        Plot(names=['Torque command (Nm)'], title='Torque command', yrange=(-40, 40), section='controller'),
    ]
    view = View([Section('status', 'Status', density='compact', show_heading=False),
                 Section('controller', 'Controller')],
                persistent_section='status', essential_controls=['active_model', 'stop'])
    return controls, view


if __name__ == '__main__':
    try:
        demo.main(configuration)
    except KeyboardInterrupt:
        pass
