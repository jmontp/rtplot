"""End-to-end client example: stream a live sine wave.

Start the rtplot server yourself first, then run:

    python presentation/examples/01_sine_stream.py
"""

import math
import time

from rtplot import client


VIEWER = "http://127.0.0.1:8050"


client.local_plot()
client.initialize_plots([
    {
        "names": ["sine"],
        "title": "End-to-end sine stream",
        "ylabel": "amplitude",
        "yrange": [-1.2, 1.2],
        "xrange": 300,
    }
])

print("Open", VIEWER, "to see the live plot.")
for i in range(600):
    t = i * 0.01
    client.send_array(math.sin(2 * math.pi * 1.5 * t))
    time.sleep(0.01)
print("Sent 600 samples.")
