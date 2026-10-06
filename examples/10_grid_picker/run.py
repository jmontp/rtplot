"""Controller-bank selection with a method dropdown and a weight grid.

Synthetic: no hardware, trained models or frozen weights. The manifest,
coefficients and torque are placeholders that exercise the selection protocol:
the grid requests checkpoints, and this application confirms or rejects them.
"""
import json
import math
import time
from rtplot import client

GRID = 'weights'
METHODS = [('M', 'Magnitude / steady torque'), ('D', 'Active damping'), ('E', 'Positive energy')]
# Ordered placeholder levels. Freeze numerical weights before training.
JERK = [('j1', 'J1: 1e-4'), ('j2', 'J2: 1e-3'), ('j3', 'J3: 1e-2')]
SHAKE = [('w1', 'W1: ×0.5'), ('w2', 'W2: ×1'), ('w3', 'W3: ×2')]
CALIBRATION = {'M': 0.8, 'D': 0.05, 'E': 1.6}  # fixed per-method calibration (synthetic)
UNAVAILABLE = {('D', 'j1', 'w1'): 'Hash mismatch', ('E', 'j3', 'w3'): 'Not exported'}
LABELS = dict(METHODS + JERK + SHAKE)


def manifest():
    """Map (method, x, y) and ('REF', x, None) to checkpoints, as an export manifest would."""
    entries = {}
    for method, _ in METHODS:
        for x, _ in JERK:
            for multiplier, (y, _) in zip((0.5, 1, 2), SHAKE):
                key = (method, x, y)
                entries[key] = {'controller_id': f'{method}-{x}-{y}', 'reason': UNAVAILABLE.get(key, ''),
                                'coefficient': CALIBRATION[method] * multiplier}
    for x, _ in JERK:
        entries[('REF', x, None)] = {'controller_id': f'ref-{x}', 'reason': '', 'coefficient': 0.0}
    return entries


def configuration():
    controls = [
        {'controls': [
            {'type': 'text', 'id': 'active_model', 'label': 'Active controller', 'value': 'Starting…',
             'appearance': 'state'},
            {'type': 'button', 'id': 'stop', 'label': 'Stop torque', 'appearance': 'danger'},
        ], 'section': 'status'},
        {'controls': [
            {'type': 'dropdown', 'id': 'method', 'label': 'Anti-shake method',
             'options': [{'value': m, 'label': label} for m, label in METHODS], 'value': 'M'},
            {'type': 'button', 'id': 'reference', 'label': 'Reference at this jerk', 'appearance': 'choice'},
            {'type': 'grid_picker', 'id': GRID, 'label': 'Training weights', 'x_label': 'Jerk weight',
             'y_label': 'Anti-shake weight multiplier',
             'x_options': [{'value': v, 'label': label} for v, label in JERK],
             'y_options': [{'value': v, 'label': label} for v, label in SHAKE],
             'value': {'x': 'j2', 'y': 'w2'}},
            {'type': 'text', 'id': 'readiness', 'label': 'Readiness', 'value': 'Ready'},
            {'type': 'button', 'id': 'enable', 'label': 'Enable torque', 'appearance': 'primary'},
        ], 'section': 'controller', 'title': 'Controller'},
        {'controls': [
            {'type': 'slider', 'id': 'mass', 'label': 'Body mass (kg)', 'min': 40, 'max': 120, 'value': 75, 'step': 1},
            {'type': 'slider', 'id': 'gain', 'label': 'Assistance gain', 'min': 0, 'max': 1, 'value': 0.5, 'step': 0.05},
        ], 'section': 'controller', 'title': 'Live settings'},
        {'names': ['Torque command (Nm)'], 'title': 'Torque command', 'yrange': [-40, 40], 'section': 'controller'},
    ]
    view = {'sections': [
        {'id': 'status', 'title': 'Status', 'density': 'compact', 'show_heading': False},
        {'id': 'controller', 'title': 'Controller'},
    ], 'persistent_section': 'status', 'essential_controls': ['active_model', 'stop']}
    return controls, view


def fallback_configuration(entries):
    """Flat controller dropdown with full labels, for servers without grid_picker_v1."""
    options = [{'value': e['controller_id'], 'label': describe(key, e)} for key, e in entries.items() if not e['reason']]
    return [{'controls': [
        {'type': 'dropdown', 'id': 'controller', 'label': 'Controller', 'options': options, 'value': 'M-j2-w2'},
        {'type': 'text', 'id': 'active_model', 'label': 'Active controller', 'value': 'Starting…'},
        {'type': 'button', 'id': 'enable', 'label': 'Enable torque'},
        {'type': 'button', 'id': 'stop', 'label': 'Stop torque'},
    ]}, {'names': ['Torque command (Nm)'], 'title': 'Torque command', 'yrange': [-40, 40]}]


def describe(key, entry=None):
    method, x, y = key
    if method == 'REF':
        text = f'Reference · {LABELS[x]}'
    else:
        text = f'{LABELS[method]} · {LABELS[x]} · {LABELS[y]}'
    if entry is not None:
        text += f" · coefficient {entry['coefficient']:.3g} · {entry['controller_id']}"
    return text


class ControllerBank:
    """Application side: maps grid coordinates to checkpoints and owns the active controller.

    Policy for this experiment: switch only with torque OFF; a switch resets
    controller histories, warms up, and requires a separate Enable.
    """

    def __init__(self, entries=None, load_seconds=0.4, warmup_seconds=1.0, log=print):
        self.entries = entries or manifest()
        self.load_seconds, self.warmup_seconds, self.log = load_seconds, warmup_seconds, log
        self.method, self.x, self.y, self.reference = 'M', 'j2', 'w2', False
        self.seen_method = self.method
        self.torque_on, self.flat = False, False
        self.loading = None        # (key, request_id, finishes_at)
        self.queued = None         # latest resolved target while loading
        self.ready_at, self.ready = 0.0, True
        self.switches, self.requests = [], []
        self.mass, self.gain, self.phase = 75.0, 0.5, 0.0

    # ---- layout -------------------------------------------------------------
    def start(self, make_configuration=configuration):
        controls, view = make_configuration()
        try:
            client.initialize_plots(controls, view=view, ui_state=self.ui_state())
        except RuntimeError:
            # Older server: never present a grid whose cell states it cannot enforce.
            self.flat = True
            client.initialize_plots(fallback_configuration(self.entries))
        self.publish_confirmed(None, initial=True)

    def key(self):
        return ('REF', self.x, None) if self.reference else (self.method, self.x, self.y)

    def cells(self, method):
        return {(x, y): {'label': f"{method} · c={self.entries[(method, x, y)]['coefficient']:.3g}",
                         'enabled': not self.entries[(method, x, y)]['reason'],
                         'reason': self.entries[(method, x, y)]['reason']}
                for x, _ in JERK for y, _ in SHAKE}

    def ui_state(self):
        locked = {'enabled': False, 'reason': 'Stop torque before switching controllers'} if self.torque_on else {'enabled': None, 'reason': None}
        return {'controls': {
            GRID: {**locked, 'busy': bool(self.loading) or None},
            'method': dict(locked), 'reference': {**locked, 'selected': self.reference or None},
            'enable': ({'enabled': False, 'reason': 'Torque is on'} if self.torque_on else
                       {'enabled': False, 'reason': 'Wait for the controller to be ready'} if not self.ready else
                       {'enabled': None, 'reason': None}),
        }}

    # ---- confirmation -------------------------------------------------------
    def publish_confirmed(self, request_id, message='', initial=False):
        key = self.key()
        values = {'active_model': describe(key, self.entries[key]),
                  'readiness': 'Ready' if self.ready else 'Warming up…'}
        if self.flat:
            client.set_display('active_model', values['active_model'])
            if 'dropdown_v1' in client.server_capabilities():
                client.set_dropdown('controller', self.entries[key]['controller_id'])
            return
        values['method'] = self.method
        client.set_grid_picker(GRID, self.x, self.y, active=not self.reference, cells=self.cells(self.method),
                               message=message, request_id=request_id, values=values, ui_state=self.ui_state())
        self.seen_method = self.method

    def reject(self, request_id, reason):
        client.reject_grid_request(GRID, request_id, reason, values={'method': self.method}, ui_state=self.ui_state())
        self.seen_method = self.method

    def switch(self, key, request_id, now):
        """Begin loading an available checkpoint. Torque stays off until Enable."""
        self.loading = (key, request_id, now + self.load_seconds)
        self.ready = False
        client.set_ui_state({'controls': {GRID: {'busy': True, 'message': f'Loading {describe(key)}…'},
                                          'enable': {'enabled': False, 'reason': 'Loading controller'}}})

    def finish(self, now):
        key, request_id, _ = self.loading
        self.loading = None
        if key[0] == 'REF':
            self.reference, self.x = True, key[1]
        else:
            self.method, self.x, self.y, self.reference = key[0], key[1], key[2], False
        self.ready_at = now + self.warmup_seconds  # controller and filter histories reset here
        entry = self.entries[key]
        self.switches.append(key)
        self.log(json.dumps({'event': 'switch', 'controller_id': entry['controller_id'], 'method': key[0],
                             'x': key[1], 'y': key[2], 'coefficient': entry['coefficient'],
                             'mass': self.mass, 'gain': self.gain, 'time': time.time()}))
        self.publish_confirmed(request_id)

    def resolve(self, key, request_id, now):
        entry = self.entries.get(key)
        if self.torque_on:
            self.reject(request_id, 'Rejected: stop torque before switching controllers')
        elif entry is None or entry['reason']:
            self.reject(request_id, f"{describe(key)} unavailable: {entry['reason'] if entry else 'not in manifest'}")
        elif key == self.key():
            self.publish_confirmed(request_id)   # acknowledged; no switch
        else:
            self.switch(key, request_id, now)

    # ---- polling ------------------------------------------------------------
    def step(self, controls, now):
        self.mass = controls.values.get('mass', 75.0)
        self.gain = controls.values.get('gain', 0.5)
        if 'stop' in controls.buttons and self.torque_on:
            self.torque_on = False
            client.set_ui_state(self.ui_state())
        if 'enable' in controls.buttons and not self.torque_on and self.ready and not self.loading:
            self.torque_on = True
            client.set_ui_state(self.ui_state())
        if not self.ready and not self.loading and now >= self.ready_at:
            self.ready = True
            client.set_display('readiness', 'Ready')
            client.set_ui_state(self.ui_state())
        target = self.flat_target(controls) if self.flat else self.grid_target(controls)
        if target is not None:
            if self.loading:
                self.queued = target   # sequential: keep only the latest resolved choice
            else:
                self.resolve(*target, now)
        if self.loading and now >= self.loading[2]:
            self.finish(now)
            if self.queued is not None:
                target, self.queued = self.queued, None
                self.resolve(*target, now)

    def grid_target(self, controls):
        """Resolve one explicit final (method, x, y) or reference from this poll's input."""
        requests = [r for r in controls.grid_requests if r.id == GRID]
        self.requests.extend(requests)
        method = controls.values.get('method', self.seen_method)
        method_changed, self.seen_method = method != self.seen_method, method
        if requests:
            last = requests[-1]
            return (method, last.x, last.y), last.request_id
        if 'reference' in controls.buttons:
            return ('REF', self.x, None), None
        if method_changed:
            # A method change keeps the confirmed coordinates (and leaves reference mode).
            return (method, self.x, self.y), None
        return None

    def flat_target(self, controls):
        chosen = controls.values.get('controller')
        current = self.entries[self.key()]['controller_id']
        if chosen and chosen != current and (not self.loading or self.entries[self.loading[0]]['controller_id'] != chosen):
            return next(k for k, e in self.entries.items() if e['controller_id'] == chosen), None
        return None

    def sample(self):
        self.phase += 0.02
        coefficient = self.entries[self.key()]['coefficient']
        assist = 0.0 if not self.torque_on else self.gain * self.mass * 0.4
        return assist * (math.sin(self.phase) + 0.2 * coefficient * math.sin(5 * self.phase))


def main(make_configuration=configuration):
    client.local_plot()
    bank = ControllerBank()
    bank.start(make_configuration)
    while True:
        bank.step(client.poll_controls(), time.monotonic())
        client.send_array([bank.sample()])
        time.sleep(0.01)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
