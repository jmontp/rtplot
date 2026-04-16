"""Multi-subplot rtplot example: three stacked plots with different signals.

To run this:
  1. Start the server in a separate terminal:  python -m rtplot.server_browser
  2. (optional) open http://localhost:8050 in a browser.
  3. Run this script:                          python run.py

Streams a sine + cosine pair, a damped oscillation, and a random walk
into three separate subplots. Ends by saving a static HTML snapshot.
"""

import math
import os
import random
import time

from rtplot import client

client.local_plot()

# Three plots in a list. Each plot is a dict with its own trace names,
# styling, and y-range. Plots stack vertically in the default layout.
client.initialize_plots([
    {
        "names": ["sin", "cos"],
        "colors": ["b", "r"],
        "yrange": [-1.5, 1.5],
        "title": "Quadrature signal",
        "ylabel": "amplitude",
    },
    {
        "names": ["impulse response"],
        "colors": ["g"],
        "yrange": [-1.2, 1.2],
        "title": "Damped oscillator",
        "ylabel": "position",
    },
    {
        "names": ["random walk"],
        "colors": ["m"],
        "yrange": [-8, 8],
        "title": "Random walk",
        "ylabel": "value",
        "xlabel": "sample",
    },
])

HZ = 100
DURATION_S = 10.0
walk = 0.0
for i in range(int(DURATION_S * HZ)):
    t = i / HZ
    sin_v = math.sin(2 * math.pi * 1.0 * t)
    cos_v = math.cos(2 * math.pi * 1.0 * t)
    # Damped 2 Hz oscillation, ~3 s decay.
    damped = math.cos(2 * math.pi * 2.0 * t) * math.exp(-t / 3.0)
    walk += random.gauss(0, 0.18)
    # Clip the walk gently so it doesn't drift off the y-range too often.
    walk = max(-7.5, min(7.5, walk))
    client.send_array([sin_v, cos_v, damped, walk])
    time.sleep(1.0 / HZ)

snapshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshot.html")
client.save_snapshot(snapshot_path, animate=True)
print(f"wrote {snapshot_path}")
