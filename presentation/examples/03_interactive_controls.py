"""End-to-end client example: browser controls affect the Python loop.

Start the rtplot server yourself first, then run:

    python presentation/examples/03_interactive_controls.py

Open http://127.0.0.1:8050, then drag Gain/Frequency or press Reset.
"""

import math
import time

from rtplot import client


VIEWER = "http://127.0.0.1:8050"


client.local_plot()
client.initialize_plots([
    {
        "names": ["controlled signal"],
        "title": "Interactive signal",
        "ylabel": "amplitude",
        "yrange": [-5.5, 5.5],
        "xrange": 300,
    },
    {
        "controls": [
            {"type": "button", "id": "reset", "label": "Reset phase"},
            {
                "type": "slider",
                "id": "gain",
                "label": "Gain",
                "min": 0,
                "max": 5,
                "value": 1.0,
                "step": 0.1,
                "format": "{:.1f}",
            },
            {
                "type": "dial",
                "id": "freq",
                "label": "Frequency",
                "min": 0.2,
                "max": 4.0,
                "value": 1.0,
                "step": 0.1,
                "format": "{:.1f}",
            },
            {"type": "display", "id": "elapsed", "label": "Elapsed", "format": "{:.1f}"},
            {"type": "text", "id": "status", "label": "Status", "value": "running"},
        ]
    },
])

print("Open", VIEWER, "and interact with the controls for 12 seconds.")
phase_t0 = time.time()
end = time.time() + 12
while time.time() < end:
    ctrl = client.poll_controls()
    if "reset" in ctrl.buttons:
        phase_t0 = time.time()
        print("Reset button received")
    gain = ctrl.values.get("gain", 1.0)
    freq = ctrl.values.get("freq", 1.0)
    elapsed = time.time() - phase_t0
    y = gain * math.sin(2 * math.pi * freq * elapsed)
    client.set_display("elapsed", elapsed)
    client.set_display("status", "gain={:.1f}, freq={:.1f}".format(gain, freq))
    client.send_array(y)
    time.sleep(0.01)
print("Interactive run finished.")
