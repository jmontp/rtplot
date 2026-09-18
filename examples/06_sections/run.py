"""Dictionary form of the sections example; uses the same synthetic loop."""
from run_typed import run


def configuration():
    return [
        {'names': ['detail'], 'title': 'Detail signal', 'xrange': 400, 'section': 'advanced'},
        {'section': 'status', 'controls': [
            {'type': 'text', 'id': 'status', 'label': 'Status', 'value': 'Setup required'},
            {'type': 'button', 'id': 'stop', 'label': 'Stop'},
            {'type': 'button', 'id': 'pause', 'label': 'Simulate interruption'},
        ]},
        {'section': 'setup', 'controls': [
            {'type': 'button', 'id': 'prepare', 'label': 'Prepare source'},
            {'type': 'button', 'id': 'start', 'label': 'Start work'},
            {'type': 'text_input', 'id': 'note', 'label': 'Notes', 'value': 'Edit while streaming'},
        ]},
        {'section': 'work', 'columns': 2, 'plots': [
            {'names': ['signal'], 'title': 'Synthetic signal', 'xrange': 400},
            {'names': ['reference'], 'title': 'Reference', 'xrange': 400},
        ]},
        {'section': 'advanced', 'controls': [
            {'type': 'slider', 'id': 'gain', 'label': 'Gain', 'min': 0, 'max': 2, 'value': 1},
            {'type': 'button', 'id': 'raw', 'label': 'Raw'},
            {'type': 'button', 'id': 'smooth', 'label': 'Smooth'},
        ]},
    ], {
        'persistent_section': 'status',
        'sections': [
            {'id': 'status', 'title': 'Status'},
            {'id': 'setup', 'title': 'Setup'},
            {'id': 'work', 'title': 'Active work'},
            {'id': 'advanced', 'title': 'Advanced', 'description': 'Optional display settings',
             'collapsible': True, 'collapsed': True},
        ],
    }


if __name__ == '__main__':
    run(configuration)
