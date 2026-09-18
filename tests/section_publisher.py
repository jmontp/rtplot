"""Synthetic source driven over stdin by browser/protocol tests. No hardware."""
import json
import queue
import sys
import threading
import time

import numpy as np
from rtplot import client
from rtplot.client import Button, ControlsRow, Dial, Plot, PlotRow, Section, Slider, Text, TextInput, View

commands = queue.Queue()

def read_commands():
    for line in sys.stdin:
        commands.put(json.loads(line))

threading.Thread(target=read_commands, daemon=True).start()
if len(sys.argv) > 1:
    client.configure_port(int(sys.argv[1]))
else:
    client.local_plot()


def layout():
    # Stream order deliberately differs from section/DOM order.
    return [
        Plot(names=['advanced-signal'], title='Advanced trace', xrange=80, section='advanced'),
        ControlsRow([Text('status', 'Status', 'ready'), Button('stop', 'Stop')], section='status'),
        PlotRow([Plot(names=['setup-signal'], title='Setup trace', xrange=80)], columns=1, section='setup'),
        ControlsRow([Button('train', 'Train'), Button('record', 'Record'), Button('source_raw', 'Raw'),
                     Slider('gain', 'Gain', 0, 10, value=2), Dial('dial', 'Dial', 0, 10, value=3),
                     TextInput('note', 'Note', value='original')], section='setup'),
    ]

view = View([Section('status', 'Status'), Section('setup', 'Setup', 'Synthetic setup'),
             Section('advanced', 'Advanced', collapsible=True, collapsed=True)], persistent_section='status')
seed = {'controls': {'train': {'enabled': False, 'reason': 'Record first'}},
        'sections': {'setup': {'status': 'ready'}}}
client.initialize_plots(layout(), view=view, ui_state=seed)
print(json.dumps({'ready': True, 'session': client._session, 'generation': client._generation}), flush=True)
paused = False
sample = 0
while True:
    while not commands.empty():
        command = commands.get()
        op = command.get('op')
        result = None
        if op == 'patch':
            result = client.set_ui_state(command['patch'])
        elif op == 'burst':
            for i in range(command.get('count', 400)):
                client.set_ui_state({'controls': {'record': {'selected': bool(i % 2)}}})
            result = True
        elif op == 'raw':
            payload = {'session': client._session, 'generation': client._generation,
                       'revision': client._ui_revision, 'state': client._ui_state, **command['payload']}
            client.socket.send_string(client.SENDING_UI_STATE, client.zmq.SNDMORE)
            client.socket.send_json(payload)
        elif op == 'resend':
            client.socket.send_string(client.SENDING_PLOT_UPDATE)
            client.socket.send_json(client._wire_config(client.plot_desc_dict))
        elif op == 'replace':
            client.initialize_plots(layout(), view=view, ui_state=seed)
        elif op == 'pause':
            paused = command['value']
        elif op == 'disconnect':
            client.socket.disconnect('tcp://127.0.0.1:5555')
            client.control_socket.disconnect('tcp://127.0.0.1:5556')
            paused = True
        elif op == 'reconnect':
            client.socket.connect('tcp://127.0.0.1:5555')
            client.control_socket.connect('tcp://127.0.0.1:5556')
            paused = False
        elif op == 'quit':
            sys.exit(0)
        print(json.dumps({'command': command.get('serial'), 'revision': client._ui_revision,
                          'generation': client._generation, 'result': result}), flush=True)
    if not paused:
        client.send_array(np.array([[1000 + sample], [2000 + sample]], dtype=float))
        sample += 1
        events = client.poll_controls()
        if events.buttons:
            print(json.dumps({'buttons': events.buttons}), flush=True)
    time.sleep(.02)
