![Logo of the project](https://github.com/jmontp/rtplot/blob/master/.images/signature-stationery.png)

# rtplot — real-time plotting over ZMQ

**rtplot** lets a Python script push live data to a plot window — locally, or
across the network — with a few lines of code on the sender side. The plot
window runs in any modern browser and supports interactive controls
(buttons, sliders, dials, text and numeric displays) that feed values
back into the sending script in real time.

Typical use: a robot or data-acquisition script runs on a Raspberry Pi or
microcontroller host, and you watch live signals and tweak gains from a
laptop on the same network.

---

## Table of contents

- [Highlights](#highlights)
- [Install](#install)
- [60-second quickstart](#60-second-quickstart)
- [Interactive controls](#interactive-controls)
  - [Reading controls from Python](#reading-controls-from-python)
  - [Pushing values into displays](#pushing-values-into-displays)
  - [Element reference](#element-reference)
- [Plot configuration](#plot-configuration)
- [Sending data](#sending-data)
- [Saving data](#saving-data)
- [Networking modes](#networking-modes)
- [Performance tuning](#performance-tuning)
- [CLI reference](#cli-reference)
- [Examples](#examples)

---

## Highlights

- **Fast.** Binary WebSocket deltas push data at up to 1 kHz. The
  browser coalesces incoming samples into a single repaint per
  `requestAnimationFrame`, so rendering runs at your monitor's refresh
  rate (typically 60 Hz, 120 Hz on higher-refresh displays) regardless
  of how fast samples arrive.
- **Browser-based.** The plot window is served by aiohttp and rendered
  by uPlot in any modern browser. No desktop GUI toolkit to install,
  works over SSH port forwarding out of the box.
- **Remote-friendly.** Either the sender or the plot host can bind —
  pick whichever fits your network. Works across LAN, WSL, and SSH
  tunnels.
- **Plot config lives with the data.** The sender declares the plot
  layout, so a Pi running your experiment owns the look of its own
  dashboards.
- **Interactive controls.** Declare buttons, sliders, dials,
  numeric/text displays in the same `initialize_plots` call. Poll from
  your tight loop; no threads, no callbacks.
- **Save to Parquet** with a single button click or `client.save_plot()`
  call.

---

## Install

Install rtplot with the server bundle — this is the normal path and
gets you everything:

```bash
pip install "better-rtplot[browser]"
```

This pulls `aiohttp` (for serving the plot UI) plus `pandas` + `pyarrow`
(for saving runs to Parquet). If you only need the sender side — your
script pushes data to someone else's plot host and you don't run a
server locally — you can install the client-only minimum instead:

```bash
pip install better-rtplot
```

In that case, if you later try to launch a server locally you'll get a
clear error telling you to add the `[browser]` extra.

WSL users: nothing extra needed. The plot window is served by HTTP, so
just open the URL rtplot prints in your Windows browser.

---

## 60-second quickstart

**Terminal 1 — start the plot server:**

```bash
python -m rtplot.server_browser
```

It prints a URL like `http://localhost:8050` — open that in your
browser. The page stays blank until a client sends a plot config.

**Terminal 2 — send data:**

```python
from rtplot import client
import numpy as np, time

client.local_plot()                     # send to the server on 127.0.0.1
client.initialize_plots(["sin", "cos"]) # one plot with two named traces

for i in range(10000):
    t = i * 0.01
    client.send_array([np.sin(t), np.cos(t)])
    time.sleep(0.01)
```

That's it. The browser tab you opened will start drawing the two
traces in real time.

---

## Interactive controls

Declare a control row inline in your plot layout:

```python
from rtplot import client
import numpy as np, time

client.local_plot()
client.initialize_plots([
    {"names": ["signal"], "yrange": [-6, 6]},
    {"controls": [
        {"type": "button", "id": "reset", "label": "Reset"},
        {"type": "button", "id": "pause", "label": "Pause"},
        {"type": "slider", "id": "gain",  "label": "Gain",
         "min": 0, "max": 5, "value": 1.0, "step": 0.1, "format": "{:.2f}"},
    ]},
    {"controls": [
        {"type": "dial",    "id": "freq", "label": "Freq (Hz)",
         "min": 0.1, "max": 5.0, "value": 1.0, "step": 0.05,
         "sensitivity": 0.5, "format": "{:.2f}"},
        {"type": "display", "id": "t",    "label": "t (s)", "format": "{:.2f}"},
        {"type": "text",    "id": "msg",  "label": "Status",
         "value": "running"},
    ]},
])

running = True
t0 = time.time()
while True:
    ctrl = client.poll_controls()
    for btn in ctrl.buttons:
        if btn == "reset": t0 = time.time()
        if btn == "pause": running = not running

    gain = ctrl.values.get("gain", 1.0)
    freq = ctrl.values.get("freq", 1.0)
    t = time.time() - t0
    amp = gain * np.sin(2 * np.pi * freq * t) if running else 0.0

    client.set_display("t", t)
    client.set_display("msg", "paused" if not running else "running")
    client.send_array(amp)
    time.sleep(0.01)
```

### Reading controls from Python

```python
ctrl = client.poll_controls()           # non-blocking, cheap to call every loop
gain = ctrl.values.get("gain", 1.0)     # latest slider/dial value
for btn_id in ctrl.buttons:             # list of buttons fired since last poll
    handle(btn_id)
```

`poll_controls()` returns a `ControlState(values, buttons)` namedtuple:

- `values` — a `dict` of `{element_id: float}` for every slider and dial
  the server has told the client about. Defaults declared in
  `initialize_plots` are pre-seeded so the **first** call already sees
  them.
- `buttons` — a `list` of button ids fired since the previous poll, in
  order. The list is cleared on return, so each event is delivered
  exactly once.

Call it from your tight loop before computing the next sample. No
threads, no callbacks, no missed events.

### Pushing values into displays

```python
client.set_display("t", 12.34)       # numeric display box
client.set_display("msg", "running") # text field
```

`set_display()` accepts either a number (for `type: "display"` elements)
or a string (for `type: "text"` elements). Updates are coalesced on the
server and rebroadcast to every connected browser at ~30 Hz.

### Element reference

| Type | Purpose | Notable fields |
|---|---|---|
| `button` | Fires a discrete event when clicked | `id`, `label` |
| `slider` | Scalar input via horizontal range | `id`, `label`, `min`, `max`, `value`, `step`, `format` |
| `dial` | Scalar input via rotational drag | same as slider, plus `sensitivity` (full turns per range sweep; default `1.0`) |
| `display` | Read-only numeric readout | `id`, `label`, `format` |
| `text` | Read-only text field (prompts, status) | `id`, `label`, `value` |

Slider and dial widgets both render as **`[widget] [−] [number input] [+]`**,
so you can drag, type a value directly, or nudge by `step`. The dial
accepts "round and round" circular drag — each full rotation walks the
value through `(max − min) × sensitivity`, so `sensitivity: 0.25` gives
you four rotations per sweep for fine control.

The `format` field accepts Python-style `{:.Nf}` strings (e.g. `"{:.2f}"`).

---

## Plot configuration

Each entry in `initialize_plots` is one of:

- an **integer** — `client.initialize_plots(3)` → one plot with 3 anonymous
  traces
- a **string** — `client.initialize_plots("torque")` → one plot with one
  named trace
- a **list of strings** — one plot, one trace per name
- a **list of lists of strings** — one plot per sublist
- a **dict** — one plot, with full styling options (below)
- a **list of dicts** — multiple plots with full styling

A styled plot dict accepts any of:

| Key | Meaning |
|---|---|
| `names` | **Required.** List of trace names. |
| `colors` | List of per-trace colors. Single letter (`r g b c m y k w`) or any CSS color string. |
| `line_style` | `"-"` for dashed, `""` (or anything else) for solid, per trace. |
| `line_width` | Per-trace line width in pixels. |
| `title` | Plot title. |
| `xlabel` / `ylabel` | Axis labels. |
| `yrange` | `[ymin, ymax]` — pins the Y axis and significantly speeds up rendering. |
| `xrange` | Integer number of samples visible at once (default 200). |

Special row entries (not plots themselves):

- `{"controls": [...]}` — a row of interactive controls (see
  [Interactive controls](#interactive-controls))
- `{"non_plot_labels": ["name1", "name2"]}` — extra scalar names that ride
  along with `send_array` and get saved into the output Parquet file, but
  aren't rendered as traces

---

## Sending data

```python
client.send_array(scalar)           # float
client.send_array([a, b, c])        # 1-D list: one sample per trace
client.send_array(np.array([...]))  # 1-D numpy array: one sample per trace
client.send_array(np.array([[...]]))# 2-D (num_traces, N): N samples at once
```

Passing a 2-D array with `N > 1` lets you push a batch of samples per
`send_array` call, which is the fastest way to get many samples through
without dropping frames.

---

## Saving data

The server saves every sample it has received since the latest
`initialize_plots` call to a Parquet file, including any
`non_plot_labels` data that rode along with your normal data.

Trigger a save from either side:

- **Browser UI:** click the **Save Plot** button.
- **Python:** `client.save_plot("my_run")`

Control where things get written:

```bash
python -m rtplot.server_browser -sd ./saved_plots -sn experiment1
```

- `-sd` / `--save-dir` — target directory
- `-sn` / `--save-name` — filename prefix (a timestamp is always appended)

### Save non-plot signals alongside the plotted ones

```python
client.initialize_plots([
    {"names": ["hip_angle", "knee_angle"]},
    {"non_plot_labels": ["battery", "cpu_temp", "loop_latency"]},
])
```

Send `battery`, `cpu_temp` and `loop_latency` as extra rows after the
plotted traces in each `send_array` call; they won't be drawn but they
will land in the Parquet file.

---

## Networking modes

rtplot uses ZMQ, so either the sender or the plot host can be the one
that *binds* a socket. Pick whichever works for your network and
firewalls.

**Mode A — plot host binds, sender connects** *(typical for lab laptops)*

```bash
# on the plot host (e.g. your laptop)
python -m rtplot.server_browser
```

```python
# on the sender (e.g. the Pi)
from rtplot import client
client.configure_ip("192.168.1.42")   # the laptop's LAN IP
```

**Mode B — sender binds, plot host connects** *(typical when the sender
has a static IP and the viewer roams around)*

```bash
# on the plot host
python -m rtplot.server_browser -p 192.168.1.50   # the sender's IP
```

```python
# on the sender
from rtplot import client
# no configure_ip call needed — the default behavior binds
```

If you pass `-p host:port` to the server, rtplot also derives the control
return-channel endpoint from that same host/port (it uses `port+1`). This
means sliders, buttons, and dials work transparently in both modes with
no extra config.

---

## Performance tuning

If you start running out of frames, try these, in roughly this order:

1. **Pin the Y range.** `{"yrange": [-2, 2]}` on each plot lets the
   renderer skip autoscaling work and gives the single biggest win.
2. **Batch your samples.** Pass a 2-D numpy array to `send_array` so N
   samples ship per call.
3. **Shrink the window.** Fewer pixels to redraw per frame.
4. **Reduce `line_width`.** Thicker lines cost more to rasterize.
5. **Use the `-s N` / `--skip N` server flag** to push every Nth sample
   batch to the browser instead of every one. Add `-a` / `--adaptable`
   to let the server tune `N` to your data rate automatically.
6. **Increase `xrange`.** Counterintuitively, a longer visible history
   can be cheaper than a short one because the browser ring-buffers the
   data and only replaces the tail on each push.

---

## CLI reference

`python -m rtplot.server_browser` accepts:

| Flag | Default | Meaning |
|---|---|---|
| `-p HOST[:PORT]` | (bind) | Connect to a sender at this address instead of binding |
| `--host HOST` | `0.0.0.0` | HTTP bind interface |
| `--port N` | `8050` | HTTP port |
| `--no-browser` | off | Don't try to open a browser on startup |
| `--rate N` | `1000` | Max WebSocket push rate (Hz) |
| `-n N` / `--skip N` | `1` | Push every Nth sample batch |
| `-a` / `--adaptable` | off | Auto-tune skip rate to data rate |
| `-c` / `--column` | row | Lay plots out in columns instead of rows |
| `-d` / `--debug` | off | Extra debug logging |
| `-sd DIR` / `--save-dir DIR` | cwd | Where to write `.parquet` saves |
| `-sn NAME` / `--save-name NAME` | — | Prefix for saved filenames |

---

## Examples

- [`rtplot/example_code.py`](rtplot/example_code.py) — a walk through
  every `initialize_plots` signature, plus a controls demo at the bottom.
- [`rtplot/interactive_test.py`](rtplot/interactive_test.py) — a guided
  end-to-end test that walks you through clicking buttons, dragging
  sliders, typing into the number input, using the ± nudge arrows, and
  spinning the dial. Good for smoke-testing a fresh install.

  ```bash
  python -m rtplot.server_browser &
  python -m rtplot.interactive_test
  ```
