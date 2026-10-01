"""A scrolling signal and independently updated FFT, using dictionary config."""
import argparse
import time
from pathlib import Path

import numpy as np
from rtplot import client


def run(layout):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--snapshot', type=Path, help='Optional output HTML path')
    args = parser.parse_args()
    client.local_plot()
    client.initialize_plots(layout)

    fs, n, batch = 1024, 1024, 32
    history = np.zeros(n)
    window = np.hanning(n)
    frequencies = np.fft.rfftfreq(n, 1 / fs)
    phase, sample = 0.0, 0
    start = time.monotonic()
    for block in range(max(1, int(args.seconds * fs / batch))):
        client.poll_controls()
        # Slowly sweep one tone; keep a smaller second tone at 160 Hz.
        t = (sample + np.arange(batch)) / fs
        tone = 48 + 12 * np.sin(2 * np.pi * .2 * t)
        phases = phase + np.cumsum(2 * np.pi * tone / fs)
        phase = phases[-1]
        values = np.sin(phases) + .25 * np.sin(2 * np.pi * 160 * t)
        client.send_array(values.reshape(1, -1))
        history = np.roll(history, -batch)
        history[-batch:] = values
        sample += batch

        # Scrolling updates at 32 Hz; spectra update at 8 Hz after warmup.
        if sample >= n and block % 4 == 3:
            magnitude = np.abs(np.fft.rfft(history * window)) / window.sum()
            magnitude[1:-1] *= 2  # Single-sided amplitude; exclude DC/Nyquist.
            magnitude_db = 20 * np.log10(np.maximum(magnitude, 1e-12))
            client.send_xy('spectrum', frequencies[1:], magnitude_db[1:])
        time.sleep(max(0, start + sample / fs - time.monotonic()))

    if args.snapshot:
        time.sleep(.1)  # Let the server receive the final update before export.
        client.save_snapshot(str(args.snapshot))


if __name__ == '__main__':
    run([{'columns': 2, 'plots': [
        {'names': ['signal'], 'title': 'Live signal', 'xrange': 1024,
         'xlabel': 'Sample in rolling window', 'ylabel': 'Amplitude', 'yrange': [-1.5, 1.5]},
        {'names': ['magnitude'], 'id': 'spectrum', 'mode': 'xy', 'xscale': 'log',
         'title': 'FFT spectrum', 'xlabel': 'Frequency (Hz)', 'ylabel': 'Amplitude (dB re 1)',
         'yrange': [-100, 5]},
    ]}])
