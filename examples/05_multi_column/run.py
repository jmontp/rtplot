"""Four live signals in the column layout chosen by the server."""

import math
import time
from pathlib import Path

from rtplot import client

client.local_plot()
client.initialize_plots([
    {"names": ["sine"], "title": "Sine", "yrange": [-1.2, 1.2]},
    {"names": ["cosine"], "title": "Cosine", "yrange": [-1.2, 1.2]},
    {"names": ["slow sine"], "title": "Slow sine", "yrange": [-1.2, 1.2]},
    {"names": ["beat"], "title": "Beat", "yrange": [-1.2, 1.2]},
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
