"""Hello-world rtplot example: stream one sine wave to one plot.

To run this:
  1. Start the server in a separate terminal:  python -m rtplot.server_browser
  2. (optional) open http://localhost:8050 in a browser.
  3. Run this script:                          python run.py

The script streams a 1 Hz sine wave for 8 seconds, then saves a
static HTML snapshot of the current plot next to itself for the
gallery.
"""

import math
import os
import time

from rtplot import client

# Point the client at a server on the same machine.
client.local_plot()

# Declare one plot with one trace. Only "names" is required; everything
# else is optional styling.
client.initialize_plots([
    {
        "names": ["signal"],
        "colors": ["b"],
        "yrange": [-1.5, 1.5],
        "title": "Hello sine wave",
        "xlabel": "sample",
        "ylabel": "amplitude",
    },
])

# Stream 8 seconds at 100 Hz.
HZ = 100
DURATION_S = 8.0
for i in range(int(DURATION_S * HZ)):
    t = i / HZ
    client.send_array(math.sin(2 * math.pi * 1.0 * t))
    time.sleep(1.0 / HZ)

# Save a static snapshot of the current plot for the gallery.
snapshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshot.html")
client.save_snapshot(snapshot_path, animate=True)
print(f"wrote {snapshot_path}")
