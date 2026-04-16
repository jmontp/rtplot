"""Multi-subplot rtplot example — typed configuration form.

Identical behavior to ``run.py``; the three plots are described with the
typed ``Plot`` dataclass instead of raw dicts.
"""

import math
import os
import random
import time

from rtplot import client
from rtplot.client import Plot

client.local_plot()

client.initialize_plots([
    Plot(
        names=["sin", "cos"],
        colors=["b", "r"],
        yrange=(-1.5, 1.5),
        title="Quadrature signal",
        ylabel="amplitude",
    ),
    Plot(
        names=["impulse response"],
        colors=["g"],
        yrange=(-1.2, 1.2),
        title="Damped oscillator",
        ylabel="position",
    ),
    Plot(
        names=["random walk"],
        colors=["m"],
        yrange=(-8, 8),
        title="Random walk",
        ylabel="value",
        xlabel="sample",
    ),
])

HZ = 100
DURATION_S = 10.0
walk = 0.0
for i in range(int(DURATION_S * HZ)):
    t = i / HZ
    sin_v = math.sin(2 * math.pi * 1.0 * t)
    cos_v = math.cos(2 * math.pi * 1.0 * t)
    damped = math.cos(2 * math.pi * 2.0 * t) * math.exp(-t / 3.0)
    walk += random.gauss(0, 0.18)
    walk = max(-7.5, min(7.5, walk))
    client.send_array([sin_v, cos_v, damped, walk])
    time.sleep(1.0 / HZ)

snapshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshot.html")
client.save_snapshot(snapshot_path, animate=True)
print(f"wrote {snapshot_path}")
