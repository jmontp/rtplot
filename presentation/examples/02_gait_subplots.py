"""End-to-end client example: stream a multi-subplot robot-style layout.

Start the rtplot server yourself first, then run:

    python presentation/examples/02_gait_subplots.py
"""

import math
import time

from rtplot import client


VIEWER = "http://127.0.0.1:8050"


client.local_plot()
client.initialize_plots([
    {
        "names": ["hip", "knee", "ankle"],
        "title": "Joint angles",
        "ylabel": "deg",
        "yrange": [-80, 80],
        "xrange": 350,
        "colors": ["#42c7b7", "#f2b84b", "#ee6f73"],
    },
    {
        "names": ["command", "measured"],
        "title": "Torque tracking",
        "ylabel": "Nm/kg",
        "yrange": [-2.5, 2.5],
        "xrange": 350,
        "colors": ["#6aa5ff", "#82cf73"],
    },
])

print("Open", VIEWER, "to see the live plot.")
for i in range(700):
    t = i * 0.01
    hip = 35 * math.sin(2 * math.pi * 0.8 * t)
    knee = 55 * math.sin(2 * math.pi * 0.8 * t + 1.1)
    ankle = 22 * math.sin(2 * math.pi * 0.8 * t - 0.7)
    command = 1.4 * math.sin(2 * math.pi * 0.8 * t)
    measured = command + 0.25 * math.sin(2 * math.pi * 4.0 * t)
    client.send_array([hip, knee, ankle, command, measured])
    time.sleep(0.01)
print("Sent gait-style subplot stream.")
