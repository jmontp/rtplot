"""Six live signals in rows with two, one, and three columns."""

import math
import time
from pathlib import Path

from rtplot import client

client.local_plot()
client.initialize_plots([
    {"columns": 2, "plots": [
        {"names": ["sine"], "title": "Sine", "yrange": [-1.2, 1.2]},
        {"names": ["cosine"], "title": "Cosine", "yrange": [-1.2, 1.2]},
    ]},
    {"columns": 1, "plots": [
        {"names": ["slow sine"], "title": "Slow sine", "yrange": [-1.2, 1.2]},
    ]},
    {"columns": 3, "plots": [
        {"names": ["beat"], "title": "Beat", "yrange": [-1.2, 1.2]},
        {"names": ["ramp"], "title": "Ramp", "yrange": [-1.2, 1.2]},
        {"names": ["square"], "title": "Square", "yrange": [-1.2, 1.2]},
    ]},
])

for i in range(500):
    t = i / 50
    client.send_array([
        math.sin(2 * math.pi * t),
        math.cos(2 * math.pi * t),
        math.sin(math.pi * t),
        math.sin(2 * math.pi * t) * math.sin(0.2 * math.pi * t),
        2 * (t % 1) - 1,
        1.0 if math.sin(2 * math.pi * t) >= 0 else -1.0,
    ])
    time.sleep(0.02)

client.save_snapshot(str(Path(__file__).with_name("snapshot.html")))
