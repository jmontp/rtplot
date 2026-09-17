"""Typed equivalent of run.py's four-plot multi-column example."""

import math
import time
from pathlib import Path

from rtplot import client
from rtplot.client import Plot

client.local_plot()
client.initialize_plots([
    Plot(names=["sine"], title="Sine", yrange=(-1.2, 1.2)),
    Plot(names=["cosine"], title="Cosine", yrange=(-1.2, 1.2)),
    Plot(names=["slow sine"], title="Slow sine", yrange=(-1.2, 1.2)),
    Plot(names=["beat"], title="Beat", yrange=(-1.2, 1.2)),
])

for i in range(500):
    t = i / 50
    client.send_array([
        math.sin(2 * math.pi * t),
        math.cos(2 * math.pi * t),
        math.sin(math.pi * t),
        math.sin(2 * math.pi * t) * math.sin(0.2 * math.pi * t),
    ])
    time.sleep(0.02)

client.save_snapshot(str(Path(__file__).with_name("snapshot.html")))
