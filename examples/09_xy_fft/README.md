# Signal and FFT on independent axes

Install this checkout and start its browser server from the repository root:

```bash
python -m pip install -e '.[browser]'
python -m rtplot.server_browser
```

In a second terminal, run either configuration form:

```bash
python examples/09_xy_fft/run.py
python examples/09_xy_fft/run_typed.py --seconds 5 --snapshot /tmp/fft.html
```

Both scripts run for ten seconds by default. The left plot scrolls incoming
samples at 32 updates per second. The right plot shows an FFT computed by
the sender, replacing the full spectrum eight times per second after a
one-second warmup. A moving tone around 48 Hz and a fixed tone at 160 Hz
produce two visible peaks.

The sender uses a 1024 Hz sample rate, a 1024-sample Hann window, and
single-sided amplitude normalization. It floors amplitudes before converting
to dB and omits the zero-frequency bin for the logarithmic X axis.

`send_array()` carries only the scrolling trace. `send_xy('spectrum', x, y)`
targets the spectrum by ID, so the two plots can use different lengths and
update rates. Use `xscale='linear'` to display zero or negative X coordinates.
Static HTML exports keep the spectrum's actual frequencies and log scale.

Install this checkout's client in the sender environment as well as updating
the server. Existing downloaded executables do not include this feature.
See the [X/Y API](../../docs/api.md#xy-curves-and-fft-spectra) for shape rules,
clearing plots, multiple traces, and compatibility details.
