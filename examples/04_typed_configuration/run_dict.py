"""Typed-configuration example — dict form of the same script.

Identical behavior to ``run.py``; the plot and controls (including the
new ``color`` option on buttons, slider, and dial) are spelled as raw
dicts instead of typed dataclasses.
"""

import math
import os
import time

from rtplot import client

client.local_plot()

client.initialize_plots([
    {
        "names": ["signal"],
        "colors": ["b"],
        "yrange": [-6, 6],
        "title": "Interactive controls (dict form)",
        "ylabel": "amplitude",
    },
    {"controls": [
        {"type": "button", "id": "reset", "label": "Reset", "color": "#b0d4ff"},
        {"type": "button", "id": "pause", "label": "Pause", "color": "#ffd27a"},
    ]},
    {"controls": [
        {"type": "slider", "id": "gain", "label": "Gain",
         "min": 0, "max": 5, "value": 1.0,
         "step": 0.1, "format": "{:.2f}", "color": "g"},
    ]},
    {"controls": [
        {"type": "dial", "id": "freq", "label": "Freq (Hz)",
         "min": 0.1, "max": 5.0, "value": 1.0,
         "step": 0.05, "sensitivity": 0.5, "format": "{:.2f}",
         "color": "#c0392b"},
    ]},
    {"controls": [
        {"type": "text", "id": "status", "label": "Status", "value": "running"},
        {"type": "display", "id": "elapsed", "label": "t (s)", "format": "{:.1f}"},
    ]},
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
