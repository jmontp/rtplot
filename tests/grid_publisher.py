"""Grid picker fixture: the example controller bank plus a stdin command interface."""
import json
import math
import queue
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples/10_grid_picker'))
from run import ControllerBank, configuration
from rtplot import client

commands = queue.Queue()
def read():
    for line in sys.stdin:
        commands.put(json.loads(line))
threading.Thread(target=read, daemon=True).start()
client.local_plot()
log = []
# "flat" forces the explicit fallback layout used with servers lacking grid_picker_v1.
flat = 'flat' in sys.argv[1:]
bank = ControllerBank(load_seconds=0.2, warmup_seconds=0.3, log=log.append)
bank.start(configuration, grid=not flat)
print(json.dumps({'ready': True, 'session': client._session, 'generation': client._generation}), flush=True)
while True:
    while not commands.empty():
        command = commands.get()
        op = command['op']
        if op == 'state':
            result = {'method': bank.method, 'x': bank.x, 'y': bank.y, 'reference': bank.reference,
                      'torque_on': bank.torque_on, 'switches': [list(k) for k in bank.switches],
                      'requests': [list(r) for r in bank.requests], 'log': len(log),
                      'loading': bool(bank.loading), 'ready': bank.ready}
        elif op == 'patch':
            result = client.set_ui_state(command['patch'])
        elif op == 'reinit':
            # A new layout generation: requests from the old one must be dropped.
            bank = ControllerBank(load_seconds=bank.load_seconds, warmup_seconds=0.3, log=log.append)
            bank.start(configuration, grid=not flat)
            result = client._generation
        else:
            result = None
        print(json.dumps({'command': command['serial'], 'result': result}), flush=True)
    bank.step(client.poll_controls(), time.monotonic())
    client.send_array([bank.sample()])
    time.sleep(.01)
