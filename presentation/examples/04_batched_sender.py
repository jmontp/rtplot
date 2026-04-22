"""End-to-end client example: send batched numpy arrays.

Start the rtplot server yourself first, then run:

    python presentation/examples/04_batched_sender.py
"""

import time

import numpy as np

from rtplot import client


VIEWER = "http://127.0.0.1:8050"


client.local_plot()
client.initialize_plots([
    {
        "names": ["fast sine", "fast cosine"],
        "title": "Batched sender",
        "yrange": [-1.2, 1.2],
        "xrange": 600,
    }
])

print("Open", VIEWER, "to see batched updates.")
sample_rate = 1000
batch_size = 50
for batch in range(120):
    idx = np.arange(batch * batch_size, (batch + 1) * batch_size)
    t = idx / sample_rate
    data = np.vstack([
        np.sin(2 * np.pi * 2.0 * t),
        np.cos(2 * np.pi * 2.0 * t),
    ])
    client.send_array(data)
    time.sleep(batch_size / sample_rate)
print("Sent", 120 * batch_size, "samples as numpy batches.")
