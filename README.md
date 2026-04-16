# rtplot — real-time plotting over ZMQ

**rtplot** lets a Python script push live data to a plot window — locally, or
across the network — with a few lines of code on the sender side. The plot
window runs in any modern browser and supports interactive controls
(buttons, sliders, dials, text and numeric displays) that feed values
back into the sending script in real time.

Typical use: a robot or data-acquisition script runs on a Raspberry Pi or
microcontroller host, and you watch live signals and tweak gains from a
laptop on the same network.

**Looking for runnable examples?** Every subfolder in
[`examples/`](examples/) is a small, self-contained script with its own
`README.md` and a static `snapshot.html` you can open in a browser to
preview what the plot looks like without running anything.

---

## Table of contents

- [How it works](#how-it-works)
- [Your first plot, step by step](#your-first-plot-step-by-step)
- [Highlights](#highlights)
- [Install](#install)
- [Interactive controls](#interactive-controls)
- [Plot configuration](#plot-configuration)
- [Sending data](#sending-data)
- [Saving data](#saving-data)
- [Browser UI features](#browser-ui-features)
- [Networking modes](#networking-modes)
- [Viewing the plot from another device](#viewing-the-plot-from-another-device)
- [Performance tuning](#performance-tuning)
- [CLI reference](#cli-reference)
- [Client API reference](#client-api-reference)
- [Examples gallery](#examples-gallery)

---

## How it works

rtplot has two pieces that run independently:

- The **server** is a small program that shows plots in a web browser.
  You start it once (or download it as a standalone Windows / Linux /
  macOS binary from the
  [Releases page](https://github.com/jmontp/rtplot/releases)) and it
  sits there waiting for data.
- The **client** is a tiny Python library you import from your own
  script. Calling `client.send_array(value)` in your loop makes a new
  data point appear on the server's plot.

Picture it like this:

```
    ┌──────────────────────┐            ┌──────────────────────┐
    │  Your Python script  │            │    rtplot-server     │
    │                      │            │                      │
    │ from rtplot import   │── ZMQ ───▶ │  ┌────────────────┐  │
    │    client            │   :5555    │  │ browser tab at │  │
    │                      │            │  │ localhost:8050 │  │
    │ client.send_array()  │ ◀── ZMQ ── │  └────────────────┘  │
    │                      │   :5556    │                      │
    └──────────────────────┘            └──────────────────────┘
       (the client lib)                   (the exe or module)
```

Data flows from your script to the server on **ZMQ port 5555**. When
the server runs the interactive-controls feature, button clicks and
slider values flow **back** to your script on port **5556**. The
server also hosts an HTTP page on port **8050** that any browser can
open to see the live plot.

The two pieces don't have to run on the same machine. Running rtplot
on a Raspberry Pi and watching the plots from your laptop is the same
code — just tell the client where the server is (or vice versa).

---

## Your first plot, step by step

**Step 0** — install rtplot with the browser server bundled:

```bash
pip install "better-rtplot[browser]"
```

**Step 1** — start the server. In **one** terminal:

```bash
python -m rtplot.server_browser
```

It prints a URL like `http://localhost:8050`. Open that in a browser.
The page is blank for now — no data has been sent yet, which is fine.

**Step 2** — write and run your script. In **another** terminal, save
this as `my_plot.py`:

```python
from rtplot import client
import time

client.local_plot()                         # point at the server on this machine
client.initialize_plots(["my signal"])      # declare one plot with one trace

for i in range(1000):
    client.send_array(i * 0.01)             # ship one sample per iteration
    time.sleep(0.01)
```

Run it: `python my_plot.py`.

**Step 3** — switch back to the browser tab. A rising-line plot is
now drawing itself in real time.

That's everything you need to get started. The rest of this README is
a reference for options, styling, interactive controls, and remote
networking, plus a [gallery of example scripts](examples/) you can
preview as static snapshots before running them yourself.

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
  tunnels. The browser UI has live Bind / Connect buttons so you can
  retarget without restarting the server.
- **Plot config lives with the data.** The sender declares the plot
  layout, so a Pi running your experiment owns the look of its own
  dashboards.
- **Interactive controls.** Declare buttons, sliders, dials, and
  numeric / text displays in the same `initialize_plots` call. Poll
  from your tight loop; no threads, no callbacks.
- **Save to Parquet** with a single button click or `client.save_plot()`
  call.
- **Static HTML snapshots.** `client.save_snapshot("out.html")` writes
  a self-contained HTML file with the current trace data and uPlot
  inlined. Perfect for commit-to-repo gallery previews or emailing a
  "here's what I saw" artifact.

---

## Install

### Normal path — pip

Install rtplot with the server bundle:

```bash
pip install "better-rtplot[browser]"
```

This pulls `aiohttp` (for serving the plot UI) plus `pandas` +
`pyarrow` (for saving runs to Parquet). If you only need the sender
side — your script pushes data to someone else's plot host and you
don't run a server locally — you can install the client-only minimum:

```bash
pip install better-rtplot
```

In that case, if you later try to launch a server locally you'll get a
clear error telling you to add the `[browser]` extra.

WSL users: nothing extra needed. The plot window is served by HTTP, so
just open the URL rtplot prints in your Windows browser.

### No-Python path — prebuilt binary

Every tagged release on GitHub ships a standalone `rtplot-server`
binary built for **windows-x64**, **linux-x86_64**, and
**macos-arm64**. Download from the
[Releases page](https://github.com/jmontp/rtplot/releases) and run
directly — no Python install needed on that machine.

On Windows the binary opens a small Tk status window
(`rtplot/server_browser_gui.py`) that shows the listening URL, ZMQ
status, a configurable save directory, an optional demo sender for
smoke-testing end-to-end connectivity, and a collapsable log panel.
Senders still need Python + `pip install better-rtplot`; the binary
only replaces the *server* side, which is the part most people don't
want to set up on a plot-viewing machine.

| Platform | Asset name |
|---|---|
| Windows | `rtplot-server-<version>-windows-x64.exe` |
| Linux | `rtplot-server-<version>-linux-x86_64.tar.gz` |
| macOS (Apple Silicon) | `rtplot-server-<version>-macos-arm64.tar.gz` |

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
| `button` | Fires a discrete event when clicked | `id`, `label`, `height` |
| `slider` | Scalar input via horizontal range | `id`, `label`, `min`, `max`, `value`, `step`, `format`, `height` |
| `dial` | Scalar input via vertical drag on a circular indicator | same as slider, plus `sensitivity` (fraction of value range per rotation; default `1.0`) |
| `display` | Read-only numeric readout | `id`, `label`, `format`, `height` |
| `text` | Read-only text field (prompts, status) | `id`, `label`, `value`, `height` |

Slider and dial widgets both render as **`[widget] [−] [number input] [+]`**,
so you can drag, type a value directly, or nudge by `step`. The dial
uses a vertical pointer drag — drag up to increase — and the
`sensitivity` field controls how many units of value change one full
rotation covers. `sensitivity: 1.0` (default) maps one rotation to the
full `(max − min)` range; `sensitivity: 0.25` needs four rotations to
sweep the range for finer control.

The `format` field accepts Python-style `{:.Nf}` strings (e.g.
`"{:.2f}"`). The `height` field is an optional multiplier on the
standard row height (default `1`) — e.g. `"height": 2` gives a dial
that's twice as tall (and therefore twice as wide), or a button with
twice the click target.

See [`examples/03_interactive_controls/`](examples/03_interactive_controls/)
for a runnable walkthrough of the full control palette.

---

## Plot configuration

Each entry in `initialize_plots` is one of:

- an **integer** — `client.initialize_plots(3)` → one plot with 3
  anonymous traces
- a **string** — `client.initialize_plots("torque")` → one plot with
  one named trace
- a **list of strings** — one plot, one trace per name
- a **list of lists of strings** — one plot per sublist
- a **dict** — one plot, with full styling options (below)
- a **list of dicts** — multiple plots with full styling

A styled plot dict accepts any of:

| Key | Meaning |
|---|---|
| `names` | **Required.** List of trace names. |
| `colors` | List of per-trace colors. Single letter (`r g b c m y k w`) or any CSS color string. |
| `line_style` | Per-trace dash style. `"-"` means dashed; anything else is solid. |
| `line_width` | Per-trace line width in pixels. |
| `title` | Plot title. |
| `xlabel` / `ylabel` | Axis labels. |
| `yrange` | `[ymin, ymax]` — pins the Y axis and significantly speeds up rendering. |
| `xrange` | Integer number of samples visible at once (default 200). |
| `height` | Per-plot height multiplier (default `1.0`). Use `2` for a plot that's twice as tall as the others in the layout. |

Special row entries (not plots themselves):

- `{"controls": [...]}` — a row of interactive controls (see
  [Interactive controls](#interactive-controls))
- `{"non_plot_labels": ["name1", "name2"]}` — extra scalar names that
  ride along with `send_array` and get saved into the output Parquet
  file, but aren't rendered as traces

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

- **Browser UI:** click the **Save Plot** button in the header.
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

### Static HTML snapshots

```python
client.save_snapshot("preview.html", animate=True)
```

Writes a self-contained HTML file with uPlot JS + CSS inlined and the
current window of trace data embedded. Opens offline in any browser,
around 65 KB. Control widgets are *not* captured — only the plot
portion — so the snapshot is the right artifact to commit to a repo as
a visual regression baseline or to attach to an email. With
`animate=True` the snapshot embeds a small replay loop so the trace
keeps scrolling (nicer for gallery previews).

The `server_url` argument defaults to `http://localhost:8050`; set it
explicitly when snapshotting a remote server or one running on a
non-default `--port`.

---

## Browser UI features

The browser tab isn't just a passive plot — the header bar and a
hamburger-menu settings panel give you live control over the server
without restarting it.

**Header controls**

| Element | What it does |
|---|---|
| Status pill | Live data rate + render rate (e.g. `Data 480 Hz · Render 60 Hz`). Turns red when the server marks the stream unhealthy. |
| **Save Plot** button | Writes a Parquet file of the current buffer to the server's save directory. |
| `ZMQ …` indicator | Shows whether the server is currently **binding** (`ZMQ bind *:5555`) or **connecting outbound** (`ZMQ → host:port`). |
| IP input | Type a `host[:port]` to retarget before clicking **Connect**. |
| **Connect** / **Bind** buttons | Flip the server between *connect-to-a-sender* and *bind-and-wait* modes at runtime. The active mode is highlighted; the other is clickable. |
| WebSocket status | `connected` / `disconnected, retrying…` — for the browser-to-server link, not the ZMQ link. |
| **☰** menu button | Opens the Settings panel (below). |

**Settings panel (☰)**

| Setting | Meaning |
|---|---|
| UI font scale | 0.7× – 2.0× multiplier on every piece of browser-side text. Good for demos, projectors, and high-DPI screens. |
| Visible samples per plot | Overrides the declared `xrange` — lets a viewer zoom out or in without touching the sender script. |
| Max plot refresh rate | Caps repaints at N Hz. The panel reports the monitor's measured refresh rate via `requestAnimationFrame` calibration, so you know the ceiling. Leave blank to use the monitor Hz as the cap. |

All settings are persisted in `localStorage`, so a refresh keeps your
preferences. The **Reset to defaults** button clears them.

---

## Networking modes

rtplot uses ZMQ, so either the sender or the plot host can be the one
that *binds* a socket. Pick whichever works for your network and
firewalls. You can also flip modes from the browser UI's **Bind** /
**Connect** buttons without restarting the server.

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

## Viewing the plot from another device

The section above is about the link between your *sender script* and the
*plot host* (the machine running `rtplot.server_browser`). This section
is about the other relationship: the link between the plot host and a
separate *viewer device* — a phone, tablet, or another laptop that just
wants to open the browser UI.

**You don't need SSH for this.** The plot host already runs a plain HTTP
server on port `8050`, bound to every interface, and the viewer device
is only a web browser. All you need to do is get traffic from the
viewer to port `8050` on the plot host.

### On the same LAN (phone, tablet, another laptop on the same Wi-Fi)

1. Find the plot host's LAN IP:

   ```powershell
   ipconfig | findstr IPv4       # Windows
   ```
   ```bash
   ip -4 addr | grep inet        # Linux/WSL
   ```

2. Open `http://<lan_ip>:8050` in the browser on the viewer device.

3. If Windows, allow inbound connections on port `8050` through Windows
   Defender Firewall. The very first time you run
   `python -m rtplot.server_browser`, Windows pops up an "Allow Python to
   receive connections" dialog — tick **Private networks** and click
   **Allow**. If you missed the dialog, add the rule manually from an
   elevated PowerShell:

   ```powershell
   # PowerShell as Administrator
   New-NetFirewallRule -DisplayName "rtplot" `
       -Direction Inbound -LocalPort 8050 -Protocol TCP `
       -Action Allow -Profile Private
   ```

   Only allow on **Private** (home / trusted Wi-Fi), not **Public**,
   unless you know what you're doing. To remove the rule later:

   ```powershell
   Remove-NetFirewallRule -DisplayName "rtplot"
   ```

No router configuration, no SSH tunneling, no external accounts. Just a
firewall exception.

### WSL2 wrinkle

If you run the server inside WSL2 instead of native Windows, WSL2's
`localhost` auto-forward lets **you** reach it from your Windows browser,
but does **not** forward traffic from the LAN. To expose a WSL2-hosted
server to other devices you need one extra hop — a Windows-side port
proxy that forwards incoming LAN traffic into WSL2:

```powershell
# PowerShell as Administrator
$wslIp = (wsl hostname -I).Trim().Split()[0]
netsh interface portproxy add v4tov4 `
    listenport=8050 listenaddress=0.0.0.0 `
    connectport=8050 connectaddress=$wslIp
New-NetFirewallRule -DisplayName "rtplot wsl" `
    -Direction Inbound -LocalPort 8050 -Protocol TCP `
    -Action Allow -Profile Private
```

WSL2's IP changes on every reboot, so rerun the `netsh` line after a
restart (or just run `rtplot.server_browser` from native Windows and
skip this whole step).

To undo:
```powershell
netsh interface portproxy delete v4tov4 listenport=8050 listenaddress=0.0.0.0
Remove-NetFirewallRule -DisplayName "rtplot wsl"
```

### Across the internet (viewer on cellular, another network, etc.)

Two easy options, neither of which requires touching your router:

**Cloudflare Tunnel** (free, one-shot URL):

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:8050
```

Prints an `https://<random>.trycloudflare.com` URL valid for the
lifetime of the command — paste it into the viewer's browser. Kill the
command when you're done.

**Tailscale** (private mesh VPN, best for recurring setups):

Install [Tailscale](https://tailscale.com) on both the plot host and
every viewer device. Each device gets a stable `100.x.y.z` IP that
works from any network. Open `http://100.x.y.z:8050` on the viewer.

Both tunnel paths forward the HTTP + WebSocket traffic that the browser
needs; neither involves ZMQ, since the viewer is browser-only. Your
sender script keeps talking to the plot host locally as usual.

### Ports at a glance

| Port | What it's for | Who actually needs it open |
|---|---|---|
| `8050` (TCP) | HTTP + WebSocket to the browser UI | the plot host, inbound from viewers |
| `5555` (TCP) | ZMQ data (sender → server) | only the sender and the plot host |
| `5556` (TCP) | ZMQ control return channel (server → sender) | only the sender and the plot host |

For the "other device is a viewer" case, you only need to expose `8050`.
`5555` / `5556` are between the sender script and the plot host — they
do not need to be reachable from the viewer device at all.

---

## Performance tuning

If you start running out of frames, try these, in roughly this order:

1. **Pin the Y range.** `{"yrange": [-2, 2]}` on each plot lets the
   renderer skip autoscaling work and gives the single biggest win.
2. **Batch your samples.** Pass a 2-D numpy array to `send_array` so N
   samples ship per call.
3. **Cap the plot refresh rate** from the browser's ☰ Settings menu.
   The ring buffers keep accumulating samples; only the repaint rate
   is throttled.
4. **Shrink the window.** Fewer pixels to redraw per frame.
5. **Reduce `line_width`.** Thicker lines cost more to rasterize.
6. **Use the `-n N` / `--skip N` server flag** to push every Nth sample
   batch to the browser instead of every one. Add `-a` / `--adaptable`
   to let the server tune `N` to your data rate automatically.
7. **Increase `xrange`.** Counterintuitively, a longer visible history
   can be cheaper than a short one because the browser ring-buffers the
   data and only replaces the tail on each push.

---

## CLI reference

`python -m rtplot.server_browser` accepts:

| Flag | Default | Meaning |
|---|---|---|
| `-p HOST[:PORT]` / `--pi_ip` | (bind) | Connect to a sender at this address instead of binding |
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

## Client API reference

Every function below is imported from `rtplot.client`:

| Function | Purpose |
|---|---|
| `local_plot()` | Point the client at a server on `127.0.0.1:5555`. Shorthand for `configure_ip("127.0.0.1")`. |
| `plot_to_neurobionics_tv()` | Point at the lab's wall-display host (`141.212.77.23:5555`). |
| `configure_ip(ip)` | Connect to a server at `ip`, `host:port`, or a full `tcp://host:port` string. Also connects the control return-channel socket to `port+1`. |
| `configure_port(port)` | Rebind the local publisher to a different port (for senders running in bind mode). |
| `initialize_plots(desc)` | Declare the plot layout. Accepts int, str, dict, list-of-strings, list-of-lists, or list-of-dicts (see [Plot configuration](#plot-configuration)). |
| `send_array(A)` | Push one or more samples. Accepts float, list, 1-D numpy array, or 2-D `(num_traces, N)` numpy array. |
| `set_display(id, value)` | Update a `display` (numeric) or `text` (string) element. |
| `poll_controls()` | Drain the return channel non-blocking; returns `ControlState(values, buttons)`. |
| `save_plot(name)` | Ask the server to save the current buffer to a Parquet file with prefix `name`. |
| `save_snapshot(path, server_url=None, animate=False)` | Download a self-contained static HTML snapshot of the current plot to `path`. |

---

## Examples gallery

The [`examples/`](examples/) directory is a small, self-contained
gallery. Each folder has a `run.py` you can copy, a `README.md` that
explains what the code is teaching, and a pre-generated `snapshot.html`
you can open in a browser to see what the live plot looked like —
no server, no Python, no network required.

| Example | What it teaches |
|---|---|
| [`examples/01_hello_world/`](examples/01_hello_world/) | The minimum three client calls: `local_plot`, `initialize_plots`, `send_array`. One plot, one sine wave. |
| [`examples/02_multiple_subplots/`](examples/02_multiple_subplots/) | Multi-plot layouts, multi-trace plots, per-plot styling, flat-list `send_array`. Three subplots, four traces. |
| [`examples/03_interactive_controls/`](examples/03_interactive_controls/) | Buttons, sliders, dials, and display boxes that drive your Python loop live. |

To run any example, start the server in one terminal and `python run.py`
in another from inside the example's folder — see
[`examples/README.md`](examples/README.md) for details and the
regenerate-all-snapshots one-liner.

For an end-to-end smoke test of the full control palette (the gallery's
snapshots can't capture interactive widget state),
[`rtplot/interactive_test.py`](rtplot/interactive_test.py) walks a
human through clicking each button, dragging the slider to specific
values, typing into the number input, using the ± nudge arrows, and
spinning the dial:

```bash
python -m rtplot.server_browser &
python -m rtplot.interactive_test
```
