"""Hello-world rtplot example — typed configuration form.

Identical behavior to ``run.py``; the only difference is that the plot
is described with the typed ``Plot`` dataclass instead of a raw dict.
Both forms serialize to the same on-the-wire config, so pick whichever
your editor makes more pleasant.
"""

import math
import os
import time

from rtplot import client
from rtplot.client import Plot

client.local_plot()

client.initialize_plots([
    Plot(
        names=["signal"],
        colors=["b"],
        yrange=(-1.5, 1.5),
        title="Hello sine wave",
        xlabel="sample",
        ylabel="amplitude",
    ),
])

HZ = 100
DURATION_S = 8.0
for i in range(int(DURATION_S * HZ)):
    t = i / HZ
    client.send_array(math.sin(2 * math.pi * 1.0 * t))
    time.sleep(1.0 / HZ)

snapshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshot.html")
client.save_snapshot(snapshot_path, animate=True)
print(f"wrote {snapshot_path}")
