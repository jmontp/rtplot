"""Command-driven real client for X/Y browser acceptance tests."""
import json
import queue
import sys
import threading
import time

import numpy as np
from rtplot import client
from rtplot.client import Plot, PlotRow, Section, View


commands = queue.Queue()
def read_commands():
    for line in sys.stdin:
        commands.put(json.loads(line))
threading.Thread(target=read_commands, daemon=True).start()
if len(sys.argv) > 1:
    client.configure_port(int(sys.argv[1]))
else:
    client.local_plot()


def initialize(xy_only=False):
    plots = [Plot(names=['magnitude', 'reference'], mode='xy', id='spectrum',
                  title='Spectrum', xlabel='Frequency (Hz)', xscale='log', show=[True, False]),
             Plot(names=['curve'], mode='xy', id='curve', title='Curve')]
    if not xy_only:
        plots.insert(0, Plot(names=['before'], xrange=32))
        plots.insert(2, Plot(names=['after'], xrange=32))
    client.initialize_plots([PlotRow(plots, columns=2, section='plots')],
                            view=View([Section('plots', 'Plots', collapsible=True)]))


initialize()
print(json.dumps({'ready': True, 'session': client._session, 'generation': client._generation}), flush=True)
while True:
    while not commands.empty():
        c = commands.get()
        op = c['op']
        if op == 'xy':
            client.send_xy(c['id'], np.asarray(c['x']), np.asarray(c['y']))
        elif op == 'stream':
            client.send_array(np.asarray(c['y'], dtype=float))
        elif op == 'replace':
            initialize(c.get('xy_only', False))
        elif op == 'patch':
            client.set_ui_state(c['patch'])
        elif op == 'raw':
            meta = {'id': 'spectrum', 'session': client._session, 'generation': client._generation,
                    'num_samples': 1, 'num_traces': 2, **c.get('meta', {})}
            frames = [b'7', json.dumps(meta).encode(), np.array(c.get('x', [1]), dtype='<f8').tobytes(),
                      np.array(c.get('y', [[9], [10]]), dtype='<f4').tobytes()]
            if c.get('bad_size'): frames[-1] = b'bad'
            if c.get('bad_json'): frames[1] = b'{'
            if c.get('extra_frame'): frames.append(b'extra')
            client.socket.send_multipart(frames)
        print(json.dumps({'command': c['serial'], 'generation': client._generation}), flush=True)
    client.poll_controls()
    time.sleep(.01)
