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
client.initialize_plots(rows, view=view, ui_state={'controls': {
    'start': {'enabled': False, 'reason': 'Prepare the source first'}, 'raw': {'selected': True}},
    'sections': {'setup': {'status': 'ready'}, 'work': {'status': 'idle'}}})
print(json.dumps({'ready': True, 'session': client._session, 'generation': client._generation}), flush=True)
i = 0
while True:
    while not commands.empty():
        command = commands.get()
        result = client.set_ui_state(command['patch']) if command['op'] == 'patch' else None
        print(json.dumps({'command': command['serial'], 'result': result}), flush=True)
    client.send_array([math.sin(i/20), math.sin(i/20+.2), math.sin(i/20)-math.sin(i/20+.2), math.cos(i/6)])
    i += 1
    events = client.poll_controls()
    if events.buttons:
        print(json.dumps({'buttons': events.buttons}), flush=True)
    time.sleep(.02)
