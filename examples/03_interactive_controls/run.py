"""Interactive controls rtplot example.

Shows the full control-widget palette — buttons, a slider, a dial, a
text display, and a numeric display — and reacts to them in the send
loop. The browser tab lets you change gain & frequency live, pause the
signal, and reset a counter.

To run this:
  1. Start the server in a separate terminal:  python -m rtplot.server_browser
  2. (optional) open http://localhost:8050 in a browser.
  3. Run this script:                          python run.py

Because the snapshot endpoint captures data only (not control widget
state), the saved snapshot shows the plot portion only. To see the
controls themselves you need to run the script locally.
"""

import math
import os
import time

from rtplot import client

client.local_plot()

plot = {
    "names": ["signal"],
    "colors": ["b"],
    "yrange": [-6, 6],
    "title": "Interactive controls",
    "ylabel": "amplitude",
}

buttons_row = {"controls": [
    {"type": "button", "id": "reset", "label": "Reset"},
    {"type": "button", "id": "pause", "label": "Pause"},
]}
slider_row = {"controls": [
    {"type": "slider", "id": "gain",
     "label": "Gain", "min": 0, "max": 5, "value": 1.0,
     "step": 0.1, "format": "{:.2f}"},
]}
dial_row = {"controls": [
    {"type": "dial", "id": "freq",
     "label": "Freq (Hz)", "min": 0.1, "max": 5.0, "value": 1.0,
     "step": 0.05, "sensitivity": 0.5, "format": "{:.2f}"},
]}
displays_row = {"controls": [
    {"type": "text", "id": "status", "label": "Status", "value": "running"},
    {"type": "display", "id": "elapsed", "label": "t (s)", "format": "{:.1f}"},
]}

client.initialize_plots([
    plot,
    buttons_row,
    slider_row,
    dial_row,
    displays_row,
])

running = True
t0 = time.time()
HZ = 100
DURATION_S = 15.0
for _ in range(int(DURATION_S * HZ)):
    ctrl = client.poll_controls()

    # React to button events that fired since last poll.
    for btn in ctrl.buttons:
        if btn == "reset":
            t0 = time.time()
        elif btn == "pause":
            running = not running
            client.set_display("status", "paused" if not running else "running")

    # Read current slider / dial values (with sensible defaults).
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
