"""Typed plot-configuration rtplot example.

Same behavior as example 03 (buttons, slider, dial, displays driving a
live sine wave), but written against the typed configuration API —
``Plot``, ``ControlsRow``, ``Button``, ``Slider``, ``Dial``, ``Display``,
``Text`` — instead of the raw dicts. The on-the-wire format is identical;
this is purely an ergonomics shim so your editor can autocomplete field
names and catch typos at call time.

To run this:
  1. Start the server in a separate terminal:  python -m rtplot.server_browser
  2. (optional) open http://localhost:8050 in a browser.
  3. Run this script:                          python run.py
"""

import math
import os
import time

from rtplot import client
from rtplot.client import Plot, ControlsRow, Button, Slider, Dial, Display, Text

client.local_plot()

client.initialize_plots([
    Plot(
        names=["signal"],
        colors=["b"],
        yrange=(-6, 6),
        title="Interactive controls (typed API)",
        ylabel="amplitude",
    ),
    ControlsRow([
        Button("reset", "Reset", color="#b0d4ff"),
        Button("pause", "Pause", color="#ffd27a"),
    ]),
    ControlsRow([
        Slider("gain", "Gain", min=0, max=5, value=1.0,
               step=0.1, format="{:.2f}", color="g"),
    ]),
    ControlsRow([
        Dial("freq", "Freq (Hz)", min=0.1, max=5.0, value=1.0,
             step=0.05, sensitivity=0.5, format="{:.2f}",
             color="#c0392b"),
    ]),
    ControlsRow([
        Text("status", "Status", value="running"),
        Display("elapsed", "t (s)", format="{:.1f}"),
    ]),
])

running = True
t0 = time.time()
HZ = 100
DURATION_S = 15.0
for _ in range(int(DURATION_S * HZ)):
    ctrl = client.poll_controls()

    for btn in ctrl.buttons:
        if btn == "reset":
            t0 = time.time()
        elif btn == "pause":
            running = not running
            client.set_display("status", "paused" if not running else "running")

    gain = ctrl.values.get("gain", 1.0)
    freq = ctrl.values.get("freq", 1.0)

    t = time.time() - t0
    amp = gain * math.sin(2 * math.pi * freq * t) if running else 0.0

    client.set_display("elapsed", t)
    client.send_array(amp)
    time.sleep(1.0 / HZ)

snapshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshot.html")
client.save_snapshot(snapshot_path, animate=True)
print(f"wrote {snapshot_path}")
