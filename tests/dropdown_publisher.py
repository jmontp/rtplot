"""Presentation fixture with the same stdin interface as section_publisher."""
import json
import math
import queue
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples/07_presentation'))
from run import configuration
from rtplot import client

commands = queue.Queue()
def read():
    for line in sys.stdin:
        commands.put(json.loads(line))
threading.Thread(target=read, daemon=True).start()
client.local_plot()
rows, view = configuration()
rows.insert(0, client.ControlsRow([client.Dropdown('mode', 'Signal mode', ['raw', {'value': 'smooth', 'label': 'Smoothed'}])], section='setup').to_dict())
client.initialize_plots(rows, view=view, ui_state={'controls': {
    'start': {'enabled': False, 'reason': 'Prepare the source first'}, 'raw': {'selected': True}},
    'sections': {'setup': {'status': 'ready'}, 'work': {'status': 'idle'}}})
print(json.dumps({'ready': True, 'session': client._session, 'generation': client._generation}), flush=True)
i = 0
while True:
    while not commands.empty():
        command = commands.get()
        if command['op'] == 'set':
            client.set_dropdown('mode', command['value'])
            result = None
        elif command['op'] == 'stale':
            client.socket.send_string(client.SENDING_TEXT_INPUT, client.zmq.SNDMORE)
            client.socket.send_json({'id': 'mode', 'value': 'raw', 'session': client._session,
                                     'generation': client._generation - 1})
            result = None
        elif command['op'] == 'values':
            result = client.poll_controls().values
        else:
            result = client.set_ui_state(command['patch'])
        print(json.dumps({'command': command['serial'], 'result': result}), flush=True)
    client.send_array([math.sin(i/20), math.sin(i/20+.2), math.sin(i/20)-math.sin(i/20+.2), math.cos(i/6)])
    i += 1
    events = client.poll_controls()
    if events.buttons:
        print(json.dumps({'buttons': events.buttons}), flush=True)
    time.sleep(.02)
