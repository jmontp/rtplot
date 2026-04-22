"""Hook example: tune a sine wave from browser controls.

Start the plot host first, then run:

    python presentation/examples/00_sine_controls.py

Open http://127.0.0.1:8050, then drag Magnitude or Frequency.
"""

import math
import time

from rtplot import client


VIEWER = "http://127.0.0.1:8050"
DEFAULT_MAGNITUDE = 3.4
DEFAULT_FREQUENCY_HZ = 1.7


client.local_plot()
client.initialize_plots([
    {
        "names": ["sine"],
        "title": "Sine generator",
        "ylabel": "amplitude",
        "yrange": [-5.5, 5.5],
        "xrange": 300,
        "colors": ["#0e7cc9"],
    },
    {
        "controls": [
            {
                "type": "slider",
                "id": "magnitude",
                "label": "Magnitude",
                "min": 0.0,
                "max": 5.0,
                "value": DEFAULT_MAGNITUDE,
                "step": 0.1,
                "format": "{:.1f}",
            },
            {
                "type": "dial",
                "id": "frequency",
                "label": "Frequency (Hz)",
                "min": 0.1,
                "max": 4.0,
                "value": DEFAULT_FREQUENCY_HZ,
                "step": 0.1,
                "format": "{:.1f}",
            },
            {
                "type": "display",
                "id": "value",
                "label": "Current y",
                "format": "{:.2f}",
            },
        ]
    },
])

print("Open", VIEWER, "and tune the sine wave for 20 seconds.")
start = time.time()
end = start + 20
while time.time() < end:
    ctrl = client.poll_controls()
    magnitude = ctrl.values.get("magnitude", DEFAULT_MAGNITUDE)
    frequency_hz = ctrl.values.get("frequency", DEFAULT_FREQUENCY_HZ)
    elapsed = time.time() - start
    y = magnitude * math.sin(2 * math.pi * frequency_hz * elapsed)
    client.set_display("value", y)
    client.send_array(y)
    time.sleep(0.01)

print("Sine control example finished.")
