"""Browser-based rtplot server.

Drop-in replacement for ``rtplot.server`` that renders the realtime plots in
a web browser via aiohttp + uPlot instead of pyqtgraph + Qt. The ZMQ
protocol exposed to clients is identical, so existing client code keeps
working unchanged.
"""

import argparse
import asyncio
import datetime
import json
import os
import struct
import sys
import time
import webbrowser
from collections import OrderedDict
from time import perf_counter

import numpy as np
import zmq
import zmq.asyncio

# pyzmq's asyncio integration needs event_loop.add_reader(), which the
# Windows-default ProactorEventLoop (Python 3.8+) does not implement.
# Without this policy override, zmq_receiver() throws on its very first
# recv_string, the task dies silently, and any data the client pushes
# after that gets dropped — the browser plot stays blank with no visible
# error. Force SelectorEventLoop on Windows before any asyncio loop is
# created so pyzmq's reader-based integration works.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    from aiohttp import WSMsgType, web
except ImportError as _exc:
    import sys
    _missing = getattr(_exc, "name", None) or "aiohttp"
    sys.stderr.write(
        "\n[rtplot] Cannot import '{m}'. The browser server requires the\n"
        "'browser' extra (aiohttp, plus pandas + pyarrow for saving plots).\n"
        "\n"
        "Install it with:\n"
        "    pip install 'better-rtplot[browser]'\n"
        "\n"
        "If you only need the Qt-based server, run 'python -m rtplot.server'\n"
        "instead (that one uses pyqtgraph + PySide6 from the 'server' extra).\n"
        "\n".format(m=_missing)
    )
    sys.exit(1)

############################
# Command Line Arguments #
###########################

parser = argparse.ArgumentParser(
    description=(
        "Browser-based realtime plotter. Speaks the same ZMQ protocol as"
        " rtplot.server but renders plots in a web browser."
    )
)

parser.add_argument(
    "-p",
    "--pi_ip",
    help=(
        "The IP address for the pi. If supplied, the server connects to that"
        " address; otherwise it binds and waits for the client to connect."
    ),
    action="store",
    type=str,
)

parser.add_argument(
    "-c",
    "--column",
    help="Create new plots in separate columns instead of rows",
    action="store_false",
)

parser.add_argument(
    "-d", "--debug", help="Add debug text output", action="store_true"
)

parser.add_argument(
    "-n",
    "--skip",
    help="Push every Nth incoming sample batch to the browser",
    action="store",
    type=int,
    default=1,
)

parser.add_argument(
    "-sd",
    "--save-dir",
    help="Directory to save the data to. Default is the current directory.",
    action="store",
    type=str,
    default=os.getcwd(),
)

parser.add_argument(
    "-sn",
    "--save-name",
    help="Optional prefix for saved files.",
    action="store",
    type=str,
    default=None,
)

parser.add_argument(
    "-a",
    "--adaptable",
    help=(
        "Adapt the browser push rate so the server can keep up with the"
        " incoming data stream."
    ),
    action="store_true",
    default=False,
)

parser.add_argument(
    "--host",
    help=(
        "Interface to bind the HTTP server to. Default 0.0.0.0 so the page"
        " is reachable from a Windows browser when running inside WSL or"
        " from other machines on the LAN."
    ),
    action="store",
    type=str,
    default="0.0.0.0",
)

parser.add_argument(
    "--port",
    help="HTTP port to serve the browser UI on (default 8050)",
    action="store",
    type=int,
    default=8050,
)

parser.add_argument(
    "--no-browser",
    help="Do not auto-open the system browser on startup",
    action="store_true",
    default=False,
)

parser.add_argument(
    "--rate",
    help=(
        "Maximum WebSocket push rate in Hz. The server only sends when new"
        " samples have arrived, so this caps the push frequency without"
        " pinning the asyncio loop. Default 1000."
    ),
    action="store",
    type=int,
    default=1000,
)

args = parser.parse_args()

NEW_SUBPLOT_IN_ROW = args.column
DEBUG_TEXT_ENABLED = args.debug
SKIP_PLOT_DATAPOINTS = args.skip
ADAPT_SKIP_PLOT_DATAPOINTS = args.adaptable

PLOT_SAVE_PATH = os.path.abspath(args.save_dir)
if not os.path.exists(PLOT_SAVE_PATH):
    os.makedirs(PLOT_SAVE_PATH)
print(f"Plots will be saved in: {PLOT_SAVE_PATH}")

PLOT_SAVE_NAME = args.save_name

###############################
# Local storage configuration #
###############################

DEFAULT_NUM_DATAPOINTS_IN_PLOT = 200
MAX_LOCAL_STORAGE = 10_000_000
INITIAL_NUM_TRACES = 50

local_storage_buffer = np.zeros((INITIAL_NUM_TRACES, MAX_LOCAL_STORAGE))

# Binary message format pushed to browsers:
#   uint8  msg_type   (0 = snapshot, 1 = delta)
#   uint8  status     (0 = green,    1 = red)
#   uint8  non_plot   (count of non-plot traces, just for the header)
#   uint8  pad
#   uint32 num_traces
#   uint32 num_samples
#   float32 fps
#   float32[num_traces * num_samples]  data, row-major
HEADER_FMT = "<BBBxIIf"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MSG_SNAPSHOT = 0
MSG_DELTA = 1

# Mutable plot state (mirrors what server.py keeps in module globals).
state = {
    "li": DEFAULT_NUM_DATAPOINTS_IN_PLOT,
    "buffer_bounds": np.array([0, DEFAULT_NUM_DATAPOINTS_IN_PLOT]),
    "num_datapoints_in_plot": DEFAULT_NUM_DATAPOINTS_IN_PLOT,
    "traces_per_plot": [],
    "trace_labels": [],
    "non_plot_labels": [],
    "local_storage_buffer_num_trace": 1,
    "num_traces": 0,
    "num_non_plot_traces": 0,
    "config_dict": None,
    "config_message": None,
    "fps": 0.0,
    "title_color": "green",
    "initialized": False,
    "last_pushed_li": DEFAULT_NUM_DATAPOINTS_IN_PLOT,
    "skip": SKIP_PLOT_DATAPOINTS,
    "data_rate_counter": 0,
    "data_between_adaptations": 0,
    # Layout ordering: list of {"kind": "plot", "index": N} or
    # {"kind": "controls", "index": N} entries in the order the user supplied.
    "layout": [],
    # List of rows, each a list of control element dicts.
    "control_rows": [],
    # Current slider values keyed by element id (seeded from 'value').
    "slider_values": {},
    # Latest display-box values keyed by element id (pushed via set_display).
    "display_values": {},
    # Set of display ids with a pending browser broadcast.
    "display_dirty": set(),
}


def reset_buffer_state(num_datapoints_in_plot, num_traces, num_non_plot_traces):
    """Reset the buffer indices when a new plot config arrives."""
    state["num_datapoints_in_plot"] = num_datapoints_in_plot
    state["li"] = num_datapoints_in_plot
    state["buffer_bounds"] = np.array([0, num_datapoints_in_plot])
    state["local_storage_buffer_num_trace"] = num_traces + 1
    state["num_traces"] = num_traces
    state["num_non_plot_traces"] = num_non_plot_traces
    state["last_pushed_li"] = num_datapoints_in_plot
    local_storage_buffer[
        : num_traces + 1 + num_non_plot_traces, : num_datapoints_in_plot
    ] = 0


def parse_config(json_config):
    """Translate a client plot config into the buffer/trace metadata.

    Mirrors the bookkeeping in server.initialize_plot but skips all of the
    Qt-side widget creation (the browser handles rendering).
    """
    traces_per_plot = []
    trace_info = []
    non_plot_labels = []
    control_rows = []
    slider_values = {}
    layout = []
    num_datapoints_in_plot = DEFAULT_NUM_DATAPOINTS_IN_PLOT

    plot_counter = 0
    for plot_description in json_config.values():
        if "non_plot_labels" in plot_description:
            non_plot_labels = plot_description["non_plot_labels"]
            continue

        if "controls" in plot_description:
            row = plot_description["controls"]
            for element in row:
                if element.get("type") in ("slider", "dial") and "value" in element:
                    slider_values[element["id"]] = float(element["value"])
            layout.append({"kind": "controls", "index": len(control_rows)})
            control_rows.append(row)
            continue

        trace_names = plot_description["names"]
        traces_per_plot.append(len(trace_names))

        if "xrange" in plot_description:
            num_datapoints_in_plot = plot_description["xrange"]

        for name in trace_names:
            trace_info.append((name, plot_counter))

        layout.append({"kind": "plot", "index": plot_counter})
        plot_counter += 1

    state["traces_per_plot"] = traces_per_plot
    state["trace_labels"] = trace_info
    state["non_plot_labels"] = non_plot_labels
    state["control_rows"] = control_rows
    # Preserve display values across re-init when the same ids are reused;
    # drop ids that are no longer declared so stale data doesn't linger.
    active_display_ids = {
        el["id"]
        for row in control_rows
        for el in row
        if el.get("type") == "display"
    }
    state["display_values"] = {
        k: v for k, v in state["display_values"].items() if k in active_display_ids
    }
    state["display_dirty"] = {d for d in state["display_dirty"] if d in active_display_ids}
    state["slider_values"] = slider_values
    state["layout"] = layout

    num_traces = sum(traces_per_plot)
    reset_buffer_state(num_datapoints_in_plot, num_traces, len(non_plot_labels))

    print("Initialized Plot!                 ")
    return num_datapoints_in_plot


def save_current_plot(log_name=None):
    """Persist the current buffer to a Parquet file.

    Identical layout to ``server.save_current_plot`` so saved files are
    interchangeable between the Qt and browser servers. pandas + pyarrow
    are optional and may be absent from slim builds (e.g. the Windows
    exe). In that case we log a clear message and return without
    raising — the receiver loop must not die because the user clicked
    Save.
    """
    try:
        import pandas as pd  # local import keeps Parquet deps optional
    except ImportError as exc:
        print(
            "[rtplot] Save Plot unavailable: "
            f"pandas/pyarrow not installed in this build ({exc})."
        )
        return

    li = state["li"]
    num_datapoints_in_plot = state["num_datapoints_in_plot"]
    trace_labels = state["trace_labels"]
    non_plot_labels = state["non_plot_labels"]
    local_storage_buffer_num_trace = state["local_storage_buffer_num_trace"]
    num_non_plot_traces = state["num_non_plot_traces"]

    num_subplots = 0
    trace_names = []
    for i, (trace_name, subplot_index) in enumerate(trace_labels):
        local_storage_buffer[i, li] = subplot_index
        num_subplots = max(subplot_index, num_subplots)
        trace_names.append(trace_name)

    local_storage_buffer[
        local_storage_buffer_num_trace : local_storage_buffer_num_trace
        + num_non_plot_traces,
        li,
    ] = -1

    num_traces = len(trace_labels)
    trace_names.append("Time(s)")
    local_storage_buffer[num_traces, li] = num_subplots + 1

    timestamp = str(datetime.datetime.now()).replace(" ", "_").replace(":", "-")

    if log_name is None or log_name is False or log_name == "":
        if PLOT_SAVE_NAME is not None:
            log_name = PLOT_SAVE_NAME + "_"
        else:
            log_name = "rtplot_"

    log_name += timestamp
    total_name = os.path.join(PLOT_SAVE_PATH, log_name + ".parquet")

    df = pd.DataFrame(
        local_storage_buffer[
            : local_storage_buffer_num_trace + len(non_plot_labels),
            num_datapoints_in_plot : li + 1,
        ].T,
        columns=trace_names + non_plot_labels,
    )
    df.to_parquet(total_name)
    print(f"Saved the plot as {total_name}")


###############################
# WebSocket connection mgmt #
###############################

ws_clients = set()


async def broadcast_text(message):
    """Send a JSON dict to every connected client as a text frame."""
    if not ws_clients:
        return
    payload = json.dumps(message)
    dead = []
    for ws in ws_clients:
        try:
            await ws.send_str(payload)
        except (ConnectionResetError, RuntimeError):
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


async def broadcast_binary(payload):
    """Send raw bytes to every connected client as a binary frame."""
    if not ws_clients or payload is None:
        return
    dead = []
    for ws in ws_clients:
        try:
            await ws.send_bytes(payload)
        except (ConnectionResetError, RuntimeError):
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


def make_data_message(msg_type, lo, hi):
    """Pack a binary delta/snapshot message for ``local_storage_buffer[:, lo:hi]``."""
    num_traces = state["num_traces"]
    n_samples = hi - lo
    if n_samples <= 0 or num_traces <= 0:
        return None
    status_int = 1 if state["title_color"] == "red" else 0
    non_plot = state["num_non_plot_traces"]
    fps = float(state["fps"]) if state["fps"] else 0.0
    header = struct.pack(
        HEADER_FMT, msg_type, status_int, non_plot, num_traces, n_samples, fps
    )
    payload = np.ascontiguousarray(
        local_storage_buffer[:num_traces, lo:hi], dtype=np.float32
    )
    return header + payload.tobytes()


def make_snapshot_message():
    bounds = state["buffer_bounds"]
    return make_data_message(MSG_SNAPSHOT, int(bounds[0]), int(bounds[1]))


def build_config_message(config_dict):
    """Convert the client-supplied OrderedDict into a JSON-friendly message."""
    plots = []
    non_plot_labels = []
    for key, plot_description in config_dict.items():
        if "non_plot_labels" in plot_description:
            non_plot_labels = plot_description["non_plot_labels"]
            continue
        if "controls" in plot_description:
            continue
        plots.append(
            {
                "key": key,
                "names": plot_description.get("names", []),
                "colors": plot_description.get("colors"),
                "line_style": plot_description.get("line_style"),
                "line_width": plot_description.get("line_width"),
                "title": plot_description.get("title"),
                "xlabel": plot_description.get("xlabel"),
                "ylabel": plot_description.get("ylabel"),
                "xrange": plot_description.get("xrange"),
                "yrange": plot_description.get("yrange"),
                "height": plot_description.get("height"),
            }
        )
    return {
        "type": "config",
        "plots": plots,
        "non_plot_labels": non_plot_labels,
        "controls": state["control_rows"],
        "layout": state["layout"],
        "slider_values": dict(state["slider_values"]),
        "display_values": dict(state["display_values"]),
        "row_layout": bool(NEW_SUBPLOT_IN_ROW),
    }


###############
# ZMQ setup #
###############

ZMQ_DEFAULT_PORT = 5555
ZMQ_CONTROL_PORT = ZMQ_DEFAULT_PORT + 1
zmq_ctx = zmq.asyncio.Context()
zmq_socket = None
control_push_socket = None

# Live description of the current ZMQ wiring, used by the browser status pill
# and reported back to clients on connect/reconfigure.
zmq_status = {"mode": "bind", "target": f"*:{ZMQ_DEFAULT_PORT}"}


def _normalize_connect_target(ip, port=ZMQ_DEFAULT_PORT):
    """Return ``(tcp://...endpoint, host:port label)`` for a user-supplied IP.

    ``port`` is the default port used when the caller only supplies a host.
    When the caller supplies a host + port, that port is honored and ``port``
    is ignored.
    """
    ip = ip.strip()
    if ip.startswith("tcp://"):
        endpoint = ip
        label = ip[len("tcp://") :]
    elif ip.count(":") == 1:
        endpoint = f"tcp://{ip}"
        label = ip
    else:
        endpoint = f"tcp://{ip}:{port}"
        label = f"{ip}:{port}"
    return endpoint, label


def _control_target_from_data(ip):
    """Given a data-socket IP spec, derive the matching control-socket IP spec.

    The control channel lives at ``data_port + 1``. If the user provided an
    explicit port, we bump it by 1; otherwise we default to ``ZMQ_CONTROL_PORT``.
    """
    ip = ip.strip()
    raw = ip[len("tcp://"):] if ip.startswith("tcp://") else ip
    if raw.count(":") >= 1:
        host, port_str = raw.rsplit(":", 1)
        try:
            return f"{host}:{int(port_str) + 1}"
        except ValueError:
            return f"{host}:{ZMQ_CONTROL_PORT}"
    return f"{raw}:{ZMQ_CONTROL_PORT}"


def _open_zmq_socket(connect_ip=None):
    """Create a fresh SUB socket bound or connected per ``connect_ip``."""
    sock = zmq_ctx.socket(zmq.SUB)
    if connect_ip:
        endpoint, label = _normalize_connect_target(connect_ip)
        sock.connect(endpoint)
        zmq_status["mode"] = "connect"
        zmq_status["target"] = label
        print(f"ZMQ: connected to {endpoint}")
    else:
        sock.bind(f"tcp://*:{ZMQ_DEFAULT_PORT}")
        zmq_status["mode"] = "bind"
        zmq_status["target"] = f"*:{ZMQ_DEFAULT_PORT}"
        print(f"ZMQ: bound on tcp://*:{ZMQ_DEFAULT_PORT}")
    sock.setsockopt_string(zmq.SUBSCRIBE, "")
    return sock


def _open_control_socket(connect_ip=None):
    """Create the return-channel PUSH socket aligned with the data socket.

    Mirrors the bind/connect orientation of _open_zmq_socket so calling
    Connect/Bind in the browser reconfigures both sockets consistently.
    """
    sock = zmq_ctx.socket(zmq.PUSH)
    sock.setsockopt(zmq.SNDHWM, 1000)
    # Don't linger on close — stale events should be dropped on reconfigure.
    sock.setsockopt(zmq.LINGER, 0)
    if connect_ip:
        control_ip = _control_target_from_data(connect_ip)
        endpoint, _ = _normalize_connect_target(control_ip, port=ZMQ_CONTROL_PORT)
        sock.connect(endpoint)
        print(f"ZMQ control: connected to {endpoint}")
    else:
        sock.bind(f"tcp://*:{ZMQ_CONTROL_PORT}")
        print(f"ZMQ control: bound on tcp://*:{ZMQ_CONTROL_PORT}")
    return sock


zmq_socket = _open_zmq_socket(connect_ip=args.pi_ip)
control_push_socket = _open_control_socket(connect_ip=args.pi_ip)

RECEIVED_PLOT_UPDATE = 0
RECEIVED_DATA = 1
SAVE_PLOT = 3
RECEIVED_DISPLAY = 4


async def send_control_event(event):
    """Forward a control event to the user's Python process, best-effort."""
    if control_push_socket is None:
        return
    try:
        await control_push_socket.send_json(event, flags=zmq.DONTWAIT)
    except zmq.Again:
        pass
    except zmq.ZMQError:
        pass


async def recv_array_async():
    md = await zmq_socket.recv_json()
    msg = await zmq_socket.recv()
    arr = np.frombuffer(memoryview(msg), dtype=md["dtype"])
    return arr.reshape(md["shape"])


async def zmq_receiver():
    """Drain the ZMQ socket as fast as possible into the local buffer."""
    last_time = perf_counter()
    first_time = perf_counter()
    fps = None

    while True:
        try:
            received = await zmq_socket.recv_string()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"ZMQ receive error: {exc}")
            await asyncio.sleep(0.1)
            continue

        try:
            category = int(received)
        except ValueError:
            if DEBUG_TEXT_ENABLED:
                print(f"Had a value error. Expected int, received: {received}")
            else:
                print(
                    "Lost synchronization between client and server."
                    " Please restart client"
                )
            continue

        if category == RECEIVED_PLOT_UPDATE:
            cfg = await zmq_socket.recv_json(object_pairs_hook=OrderedDict)
            parse_config(cfg)
            state["config_dict"] = cfg
            state["config_message"] = build_config_message(cfg)
            state["initialized"] = True
            state["data_rate_counter"] = 0
            state["data_between_adaptations"] = 0
            if ADAPT_SKIP_PLOT_DATAPOINTS:
                state["skip"] = 1
            fps = None
            state["fps"] = 0.0
            last_time = perf_counter()
            first_time = perf_counter()
            await broadcast_text(state["config_message"])
            snap = make_snapshot_message()
            if snap is not None:
                await broadcast_binary(snap)
            # Echo seeded slider defaults back to the client so its first
            # poll_controls() call already sees the declared initial values.
            for sid, svalue in state["slider_values"].items():
                await send_control_event({"type": "slider", "id": sid, "value": svalue})

        elif category == RECEIVED_DATA:
            arr = await recv_array_async()
            if not state["initialized"]:
                continue

            num_values = arr.shape[1]
            li = state["li"]
            num_traces = state["num_traces"]
            num_non_plot_traces = state["num_non_plot_traces"]
            local_storage_buffer_num_trace = state["local_storage_buffer_num_trace"]

            local_storage_buffer[:num_traces, li : li + num_values] = arr[
                :num_traces, :
            ]

            now = perf_counter()
            dt = now - last_time
            last_time = now
            if dt > 0:
                if fps is None:
                    fps = 1.0 / dt
                else:
                    s = float(np.clip(dt * 3.0, 0, 1))
                    fps = fps * (1 - s) + (1.0 / dt) * s
                state["fps"] = fps

            curr_timestamp = now - first_time
            local_storage_buffer[
                local_storage_buffer_num_trace - 1, li : li + num_values
            ] = curr_timestamp

            if num_non_plot_traces > 0 and arr.shape[0] >= (
                local_storage_buffer_num_trace + num_non_plot_traces
            ):
                local_storage_buffer[
                    local_storage_buffer_num_trace : local_storage_buffer_num_trace
                    + num_non_plot_traces,
                    li : li + num_values,
                ] = arr[
                    local_storage_buffer_num_trace : local_storage_buffer_num_trace
                    + num_non_plot_traces,
                    :,
                ]

            state["li"] = li + num_values
            state["buffer_bounds"][0] += num_values
            state["buffer_bounds"][1] += num_values

            # The browser path is now decoupled from the data path (deltas only
            # carry the new samples), so the green/red logic can stay relaxed —
            # the server keeps up so long as the asyncio loop is keeping up.
            state["title_color"] = "green"

        elif category == SAVE_PLOT:
            log_name = await zmq_socket.recv_string()
            try:
                save_current_plot(log_name)
            except Exception as exc:  # noqa: BLE001
                print(f"[rtplot] save_current_plot failed: {exc}")

        elif category == RECEIVED_DISPLAY:
            payload = await zmq_socket.recv_json()
            display_id = payload.get("id")
            value = payload.get("value")
            if display_id is None:
                continue
            if not isinstance(value, (int, float, str)):
                continue
            if state["display_values"].get(display_id) != value:
                state["display_values"][display_id] = value
                state["display_dirty"].add(display_id)


async def reconfigure_zmq(app, connect_ip=None):
    """Tear down the running receiver, swap the socket, restart the receiver.

    ``connect_ip`` is None to bind on the default port, or a "host[:port]"
    string to connect outbound to a publisher. Resets the plot buffer state
    so the browser doesn't show data from the previous source.
    """
    global zmq_socket
    global control_push_socket

    old_task = app.get("zmq_task")
    if old_task is not None:
        old_task.cancel()
        try:
            await old_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    try:
        zmq_socket.close(0)
    except Exception:  # noqa: BLE001
        pass
    try:
        if control_push_socket is not None:
            control_push_socket.close(0)
    except Exception:  # noqa: BLE001
        pass

    # Give the OS a moment to release the freed TCP ports before we try
    # to re-bind them. Linux usually releases immediately; Windows can
    # hold on briefly even with linger=0, which caused "Bind doesn't work"
    # reports in the exe. 150 ms is empirically enough in both cases.
    await asyncio.sleep(0.15)

    # Retry the open with a small backoff in case the OS is still
    # releasing the port. Three quick attempts cover the typical Windows
    # rebind race without making the UI feel sluggish.
    def _try_open_zmq(ip):
        last_exc = None
        for attempt in range(3):
            try:
                return _open_zmq_socket(connect_ip=ip)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                print(f"ZMQ open failed (attempt {attempt + 1}/3): {exc}")
                time.sleep(0.1 * (attempt + 1))
        raise last_exc if last_exc else RuntimeError("zmq open failed")

    def _try_open_control(ip):
        last_exc = None
        for attempt in range(3):
            try:
                return _open_control_socket(connect_ip=ip)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                print(f"ZMQ control open failed (attempt {attempt + 1}/3): {exc}")
                time.sleep(0.1 * (attempt + 1))
        raise last_exc if last_exc else RuntimeError("zmq control open failed")

    try:
        zmq_socket = _try_open_zmq(connect_ip)
    except Exception as exc:  # noqa: BLE001
        print(f"ZMQ reconfigure failed ({exc}); keeping previous state")
        # Leave zmq_status pointing at whatever the caller asked for so
        # the browser knows the new intent; the zmq_socket global may be
        # in a partially-closed state but we'll retry on the next click.
        await broadcast_zmq_status()
        return

    try:
        control_push_socket = _try_open_control(connect_ip)
    except Exception as exc:  # noqa: BLE001
        print(f"ZMQ control reconfigure failed ({exc}); control channel offline")
        control_push_socket = None

    state["initialized"] = False
    state["config_message"] = None
    state["num_traces"] = 0
    state["last_pushed_li"] = state["li"]
    state["control_rows"] = []
    state["layout"] = []
    state["slider_values"] = {}
    state["display_values"] = {}
    state["display_dirty"] = set()

    await broadcast_zmq_status()
    app["zmq_task"] = asyncio.create_task(zmq_receiver())


async def broadcast_zmq_status():
    await broadcast_text(
        {"type": "zmq_status", "mode": zmq_status["mode"], "target": zmq_status["target"]}
    )


async def display_pusher():
    """Push any dirty display-box values to browsers at ~30 Hz."""
    target_dt = 1.0 / 30.0
    while True:
        await asyncio.sleep(target_dt)
        if not ws_clients:
            continue
        dirty = state["display_dirty"]
        if not dirty:
            continue
        values = {k: state["display_values"][k] for k in dirty}
        state["display_dirty"] = set()
        await broadcast_text({"type": "display_update", "values": values})


async def ws_pusher():
    """Push new samples to all browsers as binary delta frames.

    Sleeps at 1/args.rate between iterations and only sends when the receiver
    has actually accumulated new samples since the last push, so it never
    burns CPU on no-op pushes. When the unsent backlog is bigger than the
    visible window we send a snapshot instead of a delta.
    """
    target_dt = 1.0 / max(1, args.rate)
    while True:
        await asyncio.sleep(target_dt)
        if not ws_clients or not state["initialized"]:
            continue

        current_li = state["li"]
        last_li = state["last_pushed_li"]
        if current_li <= last_li:
            continue

        num_traces = state["num_traces"]
        if num_traces == 0:
            continue

        window = state["num_datapoints_in_plot"]
        n_new = current_li - last_li
        if n_new >= window:
            payload = make_snapshot_message()
        else:
            payload = make_data_message(MSG_DELTA, last_li, current_li)

        state["last_pushed_li"] = current_li

        if payload is not None:
            await broadcast_binary(payload)


###################
# HTTP / WebSocket #
###################

INDEX_HTML = """<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<title>rtplot</title>
<link rel=\"stylesheet\" href=\"/static/uPlot.min.css\" />
<style>
  html, body { margin: 0; padding: 0; height: 100%; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif; background: #fafafa; color: #222; }
  #header { display: flex; align-items: center; gap: 16px; padding: 8px 16px; background: #fff; border-bottom: 1px solid #ddd; position: sticky; top: 0; z-index: 10; }
  #header h1 { margin: 0; font-size: calc(18px * var(--ui-scale)); font-weight: 600; }
  #status { font-size: calc(14px * var(--ui-scale)); padding: 4px 10px; border-radius: 4px; background: #eee; }
  #status.green { background: #d4f5d4; color: #186a18; }
  #status.red { background: #f9d4d4; color: #8a1a1a; }
  .btn { padding: 6px 12px; font-size: calc(14px * var(--ui-scale)); border: 1px solid #888; background: #fff; cursor: pointer; border-radius: 4px; }
  /* zmq mode buttons: the currently-active mode is green + not clickable, the other is white + clickable */
  .btn.zmq-active { background: #d4f5d4; color: #186a18; border-color: #8dc88d; cursor: default; }
  .btn.zmq-active:hover { background: #d4f5d4; }
  .btn.zmq-disabled { background: #f0f0f0; color: #aaa; border-color: #ccc; cursor: not-allowed; }
  .btn.zmq-disabled:hover { background: #f0f0f0; }
  .btn:hover { background: #f0f0f0; }
  #ip-input { padding: 6px 8px; font-size: calc(13px * var(--ui-scale)); border: 1px solid #888; border-radius: 4px; width: 170px; font-family: monospace; }
  #zmq-mode { font-size: calc(12px * var(--ui-scale)); color: #555; padding: 2px 8px; background: #eef; border-radius: 4px; }
  #ws-status { font-size: calc(12px * var(--ui-scale)); color: #666; margin-left: auto; }
  #plots { display: flex; padding: 12px; gap: 12px; }
  #plots.row { flex-direction: column; }
  #plots.col { flex-direction: row; flex-wrap: wrap; }
  .plot-wrap { background: #fff; border: 1px solid #ddd; border-radius: 4px; padding: 8px; flex: 1 1 auto; min-width: 320px; }
  .plot-title { font-size: 13px; font-weight: 600; margin: 0 0 4px 4px; color: #333; }
  :root { --ctrl-unit-h: 38px; --ui-scale: 1; }
  .ctrl-row { display: flex; gap: 12px; align-items: center; padding: 10px 14px; background: #fff; border: 1px solid #ddd; border-radius: 4px; flex-wrap: wrap; }
  .ctrl-item { display: flex; align-items: center; gap: 6px; }
  .ctrl-item.flex { flex: 1 1 220px; min-width: 200px; }
  .ctrl-item label { font-size: calc(13px * var(--ui-scale)); color: #444; }
  .ctrl-btn { padding: 8px 16px; font-size: calc(14px * var(--ui-scale)); border: 1px solid #888; background: #fff; cursor: pointer; border-radius: 4px; font-weight: 500; display: flex; align-items: center; justify-content: center; }
  .ctrl-item-tall > .ctrl-btn { align-self: stretch; padding-top: 0; padding-bottom: 0; font-size: calc(16px * var(--ui-scale)); }
  .ctrl-item-tall > .ctrl-rangeinput,
  .ctrl-item-tall > .ctrl-dial,
  .ctrl-item-tall > .ctrl-numinput,
  .ctrl-item-tall > .ctrl-nudgebtn,
  .ctrl-item-tall > .ctrl-val { align-self: center; }
  .ctrl-btn:hover { background: #f0f0f0; }
  .ctrl-btn:active { background: #e2e2e2; }
  .ctrl-slider .ctrl-rangeinput { flex: 1; min-width: 120px; }
  .ctrl-numinput { width: 72px; font-family: monospace; font-size: calc(13px * var(--ui-scale)); padding: 4px 6px; border: 1px solid #b8b8b8; border-radius: 3px; background: #fff; color: #222; text-align: right; -moz-appearance: textfield; }
  .ctrl-numinput::-webkit-outer-spin-button,
  .ctrl-numinput::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
  .ctrl-nudgebtn { width: 26px; height: 26px; font-size: calc(15px * var(--ui-scale)); font-weight: 600; line-height: 1; padding: 0; border: 1px solid #b8b8b8; background: #f7f7f7; color: #333; cursor: pointer; border-radius: 3px; }
  .ctrl-nudgebtn:hover { background: #e9e9e9; }
  .ctrl-nudgebtn:active { background: #dcdcdc; }
  .ctrl-dial { cursor: ns-resize; flex: 0 0 auto; touch-action: none; user-select: none; }
  .ctrl-dial-dragging { cursor: ns-resize; }
  .ctrl-dial .dial-track { fill: #fafafa; stroke: #bcbcbc; stroke-width: 2.5; }
  .ctrl-dial .dial-indicator { stroke: #2a5db0; stroke-width: 4; stroke-linecap: round; }
  .ctrl-dial .dial-arrow { fill: #c0c0c0; pointer-events: none; user-select: none; }
  .ctrl-dial:hover .dial-track { stroke: #888; }
  .ctrl-dial:hover .dial-arrow { fill: #888; }
  .ctrl-val { font-family: monospace; font-size: calc(13px * var(--ui-scale)); min-width: 56px; text-align: right; color: #222; }
  .ctrl-display .ctrl-val { background: #f3f3f3; padding: 4px 10px; border-radius: 3px; min-width: 72px; border: 1px solid #e2e2e2; }
  .ctrl-textval { background: #eef3ff; padding: 6px 12px; border-radius: 3px; border: 1px solid #c8d6ff; color: #1a3a7a; text-align: left; min-width: 160px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: calc(14px * var(--ui-scale)); }
  #menu-btn { margin-left: 8px; width: 34px; height: 34px; padding: 0; font-size: calc(18px * var(--ui-scale)); line-height: 1; display: flex; align-items: center; justify-content: center; }
  #menu-panel { position: fixed; top: 56px; right: 16px; background: #fff; border: 1px solid #ccc; border-radius: 6px; box-shadow: 0 4px 14px rgba(0,0,0,0.12); padding: 16px 18px; min-width: 260px; z-index: 20; display: none; }
  #menu-panel.open { display: block; }
  #menu-panel h2 { margin: 0 0 10px 0; font-size: calc(14px * var(--ui-scale)); font-weight: 600; color: #333; text-transform: uppercase; letter-spacing: 0.03em; }
  #menu-panel .menu-row { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; }
  #menu-panel .menu-row:last-child { margin-bottom: 0; }
  #menu-panel label { font-size: calc(12px * var(--ui-scale)); color: #555; font-weight: 500; }
  #menu-panel .menu-ctrl { display: flex; align-items: center; gap: 8px; }
  #menu-panel input[type=range] { flex: 1; }
  #menu-panel input[type=number] { width: 88px; font-family: monospace; font-size: calc(13px * var(--ui-scale)); padding: 4px 6px; border: 1px solid #b8b8b8; border-radius: 3px; text-align: right; -moz-appearance: textfield; }
  #menu-panel input[type=number]::-webkit-outer-spin-button,
  #menu-panel input[type=number]::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
  #menu-panel .menu-val { font-family: monospace; font-size: calc(12px * var(--ui-scale)); min-width: 44px; text-align: right; color: #333; }
  #menu-panel .menu-hint { font-size: calc(11px * var(--ui-scale)); color: #888; margin-top: 2px; }
  #menu-panel .menu-reset { margin-top: 6px; font-size: calc(11px * var(--ui-scale)); background: transparent; border: none; color: #2a5db0; cursor: pointer; padding: 2px 0; text-align: left; }
  #menu-panel .menu-reset:hover { text-decoration: underline; }
</style>
</head>
<body>
  <div id=\"header\">
    <h1>rtplot</h1>
    <div id=\"status\" class=\"green\">Rate: -- Hz</div>
    <button id=\"save-btn\" class=\"btn\">Save Plot</button>
    <div id=\"zmq-mode\">ZMQ: --</div>
    <input id=\"ip-input\" type=\"text\" placeholder=\"host[:port]\" />
    <button id=\"connect-btn\" class=\"btn\">Connect</button>
    <button id=\"bind-btn\" class=\"btn\">Bind</button>
    <div id=\"ws-status\">connecting...</div>
    <button id=\"menu-btn\" class=\"btn\" title=\"Settings\" aria-label=\"Settings\">&#9776;</button>
  </div>
  <div id=\"menu-panel\" aria-hidden=\"true\">
    <h2>Settings</h2>
    <div class=\"menu-row\">
      <label for=\"menu-font\">UI font scale</label>
      <div class=\"menu-ctrl\">
        <input id=\"menu-font\" type=\"range\" min=\"0.7\" max=\"2.0\" step=\"0.05\" value=\"1\" />
        <span id=\"menu-font-val\" class=\"menu-val\">1.00x</span>
      </div>
    </div>
    <div class=\"menu-row\">
      <label for=\"menu-xrange\">Visible samples per plot</label>
      <div class=\"menu-ctrl\">
        <input id=\"menu-xrange\" type=\"number\" min=\"10\" step=\"10\" placeholder=\"auto\" />
        <span class=\"menu-val\">samples</span>
      </div>
    </div>
    <div class=\"menu-row\">
      <label for=\"menu-maxfps\">Max plot refresh rate</label>
      <div class=\"menu-ctrl\">
        <input id=\"menu-maxfps\" type=\"number\" min=\"1\" step=\"1\" placeholder=\"auto\" />
        <span class=\"menu-val\">Hz</span>
      </div>
      <div id=\"menu-monitor-hint\" class=\"menu-hint\">Monitor: measuring…</div>
    </div>
    <button id=\"menu-reset\" class=\"menu-reset\" type=\"button\">Reset to defaults</button>
  </div>
  <div id=\"plots\" class=\"row\"></div>
  <script src=\"/static/uPlot.iife.min.js\"></script>
  <script>
    (function () {
      const COLOR_MAP = {
        r: 'rgb(255,0,0)', g: 'rgb(0,200,0)', b: 'rgb(0,0,255)',
        c: 'rgb(0,200,200)', m: 'rgb(200,0,200)', y: 'rgb(200,200,0)',
        k: 'rgb(0,0,0)', w: 'rgb(255,255,255)'
      };
      const DEFAULT_COLORS = ['r', 'g', 'b', 'c', 'm', 'y'];

      function resolveColor(c) {
        if (c == null) return 'rgb(0,0,0)';
        if (Array.isArray(c) && c.length >= 3) return `rgb(${c[0]},${c[1]},${c[2]})`;
        if (typeof c === 'string') {
          if (COLOR_MAP[c]) return COLOR_MAP[c];
          return c;
        }
        return 'rgb(0,0,0)';
      }

      const plotsDiv = document.getElementById('plots');
      const statusDiv = document.getElementById('status');
      const wsStatus = document.getElementById('ws-status');
      const saveBtn = document.getElementById('save-btn');
      const ipInput = document.getElementById('ip-input');
      const connectBtn = document.getElementById('connect-btn');
      const bindBtn = document.getElementById('bind-btn');
      const zmqMode = document.getElementById('zmq-mode');
      const menuBtn = document.getElementById('menu-btn');
      const menuPanel = document.getElementById('menu-panel');
      const menuFontInput = document.getElementById('menu-font');
      const menuFontVal = document.getElementById('menu-font-val');
      const menuXrangeInput = document.getElementById('menu-xrange');
      const menuMaxfpsInput = document.getElementById('menu-maxfps');
      const menuMonitorHint = document.getElementById('menu-monitor-hint');
      const menuResetBtn = document.getElementById('menu-reset');

      // ---- Detect the monitor's refresh rate on page load ----
      // Browsers deliberately don't expose the hardware refresh rate
      // (fingerprinting), so we calibrate it by running rAF callbacks
      // for ~500 ms and counting. requestAnimationFrame is locked to
      // the display refresh, so frames_per_sec == monitor Hz as long
      // as the tab is active during calibration.
      let monitorHz = 0;
      (function measureMonitorHz() {
        let count = 0;
        let start = 0;
        function tick(t) {
          if (start === 0) start = t;
          count += 1;
          const elapsed = t - start;
          if (elapsed < 500) {
            requestAnimationFrame(tick);
          } else {
            const measured = count * 1000 / elapsed;
            // Snap to common refresh rates so users see clean numbers
            // (60/75/90/120/144/165/240) instead of 59.8.
            const common = [30, 48, 50, 60, 72, 75, 90, 100, 120, 144, 165, 240];
            let best = measured;
            let bestDiff = Infinity;
            for (const c of common) {
              const d = Math.abs(measured - c);
              if (d < bestDiff && d / c < 0.05) { bestDiff = d; best = c; }
            }
            monitorHz = Math.round(best);
            if (menuMonitorHint) {
              menuMonitorHint.textContent = `Monitor: ${monitorHz} Hz (rAF cap)`;
            }
            menuMaxfpsInput.placeholder = `auto = ${monitorHz}`;
          }
        }
        requestAnimationFrame(tick);
      })();

      // ---- Persistent client-side settings (hamburger menu) ----
      const SETTINGS_KEY = 'rtplotSettings.v1';
      const DEFAULT_SETTINGS = { fontScale: 1.0, visibleSamples: null, maxFps: null };
      let settings = Object.assign({}, DEFAULT_SETTINGS);
      try {
        const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
        settings = Object.assign(settings, saved);
      } catch (e) {}
      function saveSettings() {
        try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch (e) {}
      }
      function applyFontScale() {
        const s = Number(settings.fontScale) || 1;
        document.documentElement.style.setProperty('--ui-scale', s);
        menuFontInput.value = s;
        menuFontVal.textContent = s.toFixed(2) + 'x';
      }
      function applyVisibleSamples() {
        // Zoom uPlot's x scale to show only the newest N samples. If N is
        // null/unset, or >= the plot's full xrange, show everything. This
        // never adds data — it only hides older samples.
        const n = settings.visibleSamples;
        plots.forEach(p => {
          let lo = 0, hi = p.xrange - 1;
          if (n && Number.isFinite(n) && n > 0 && n < p.xrange) {
            lo = p.xrange - n;
          }
          try { p.uplot.setScale('x', { min: lo, max: hi }); } catch (e) {}
        });
      }
      function syncMenuInputs() {
        menuFontInput.value = Number(settings.fontScale) || 1;
        menuFontVal.textContent = (Number(settings.fontScale) || 1).toFixed(2) + 'x';
        menuXrangeInput.value = settings.visibleSamples || '';
        menuMaxfpsInput.value = settings.maxFps || '';
      }
      menuBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        menuPanel.classList.toggle('open');
      });
      document.addEventListener('click', (e) => {
        if (!menuPanel.classList.contains('open')) return;
        if (menuPanel.contains(e.target) || menuBtn.contains(e.target)) return;
        menuPanel.classList.remove('open');
      });
      menuFontInput.addEventListener('input', () => {
        settings.fontScale = Number(menuFontInput.value);
        applyFontScale();
        saveSettings();
      });
      menuXrangeInput.addEventListener('change', () => {
        const v = Number(menuXrangeInput.value);
        settings.visibleSamples = (Number.isFinite(v) && v > 0) ? v : null;
        applyVisibleSamples();
        saveSettings();
      });
      menuMaxfpsInput.addEventListener('change', () => {
        const v = Number(menuMaxfpsInput.value);
        settings.maxFps = (Number.isFinite(v) && v > 0) ? v : null;
        saveSettings();
      });
      menuResetBtn.addEventListener('click', () => {
        settings = Object.assign({}, DEFAULT_SETTINGS);
        saveSettings();
        syncMenuInputs();
        applyFontScale();
        applyVisibleSamples();
      });
      applyFontScale();
      syncMenuInputs();

      const HEADER_SIZE = 16;
      const MSG_SNAPSHOT = 0;
      const MSG_DELTA = 1;

      let plots = [];          // { uplot, xs, traceCount, startIdx, xrange, buffers, height }
      let totalTraces = 0;
      let socket = null;
      let pendingFrame = false;
      let lastStatus = { fps: 0, statusByte: 0, nonPlot: 0, dirty: true };
      const controlElements = { displays: {}, displayFormats: {}, displayKinds: {}, sliders: {} };

      function sendCtrl(msg) {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify(msg));
        }
      }

      function parseDisplayFormat(fmt) {
        if (typeof fmt !== 'string') return null;
        const m = fmt.match(/\\{:\\.(\\d+)f\\}/);
        if (m) return { kind: 'fixed', digits: parseInt(m[1], 10) };
        return null;
      }

      function formatDisplay(id, value) {
        if (value === null || value === undefined) return '--';
        if (controlElements.displayKinds[id] === 'text') return String(value);
        if (typeof value === 'string') return value;
        if (Number.isNaN(value)) return '--';
        const fmt = controlElements.displayFormats[id];
        if (fmt && fmt.kind === 'fixed') return Number(value).toFixed(fmt.digits);
        return String(value);
      }

      function makeScalarControl(el, renderWidget) {
        const hasMin = el.min !== undefined && Number.isFinite(Number(el.min));
        const hasMax = el.max !== undefined && Number.isFinite(Number(el.max));
        const min = hasMin ? Number(el.min) : -Infinity;
        const max = hasMax ? Number(el.max) : Infinity;
        const step = (el.step !== undefined && Number(el.step) > 0) ? Number(el.step) : 0.01;
        const fmt = parseDisplayFormat(el.format);
        const formatVal = (v) => (fmt && fmt.kind === 'fixed')
          ? Number(v).toFixed(fmt.digits)
          : String(v);
        const clampRound = (v) => {
          v = Math.max(min, Math.min(max, Number(v)));
          const base = hasMin ? min : 0;
          const snapped = Math.round((v - base) / step) * step + base;
          return Number(snapped.toFixed(10));
        };
        let value = clampRound((el.value !== undefined) ? Number(el.value) : (hasMin ? min : 0));

        const item = document.createElement('div');
        item.className = 'ctrl-item ctrl-slider flex';
        if (el.label) {
          const lbl = document.createElement('label');
          lbl.textContent = el.label;
          item.appendChild(lbl);
        }

        let widget = null;
        const input = document.createElement('input');
        input.type = 'number';
        input.className = 'ctrl-numinput';
        if (hasMin) input.min = min;
        if (hasMax) input.max = max;
        input.step = step;
        input.value = formatVal(value);

        // fromDrag is true when the scalar control is being updated by a
        // widget's own drag handler — in that case the widget already owns
        // its visual state and setValue should not reset it.
        const applyLocal = (v, fromDrag) => {
          value = clampRound(v);
          input.value = formatVal(value);
          if (widget && widget.setValue) widget.setValue(value, !!fromDrag);
        };
        const commit = (v, fromDrag) => {
          applyLocal(v, fromDrag);
          sendCtrl({ type: 'control_slider', id: el.id, value: Number(value) });
        };

        const sensitivity = (el.sensitivity !== undefined && Number.isFinite(Number(el.sensitivity)))
          ? Number(el.sensitivity)
          : 1.0;
        widget = renderWidget({
          min, max, step, initial: value,
          commit, applyLocal,
          sensitivity, hasMin, hasMax,
        });
        if (widget && widget.node) item.appendChild(widget.node);

        const minusBtn = document.createElement('button');
        minusBtn.type = 'button';
        minusBtn.className = 'ctrl-nudgebtn';
        minusBtn.textContent = '\u2212';
        minusBtn.title = `\u2212 ${step}`;
        minusBtn.addEventListener('click', () => commit(value - step));
        item.appendChild(minusBtn);

        input.addEventListener('change', () => {
          const v = Number(input.value);
          if (!Number.isFinite(v)) { input.value = formatVal(value); return; }
          commit(v);
        });
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
        });
        item.appendChild(input);

        const plusBtn = document.createElement('button');
        plusBtn.type = 'button';
        plusBtn.className = 'ctrl-nudgebtn';
        plusBtn.textContent = '+';
        plusBtn.title = `+ ${step}`;
        plusBtn.addEventListener('click', () => commit(value + step));
        item.appendChild(plusBtn);

        controlElements.sliders[el.id] = { setValue: (v) => applyLocal(v, false) };
        if (fmt) controlElements.displayFormats[el.id] = fmt;
        return item;
      }

      function buildSliderWidget({ min, max, step, initial, commit, applyLocal, hasMin, hasMax }) {
        // HTML range inputs can't represent unbounded values, so fall back
        // to sane defaults when the user omits min/max on a slider.
        const rangeMin = hasMin ? min : 0;
        const rangeMax = hasMax ? max : 1;
        const range = document.createElement('input');
        range.type = 'range';
        range.className = 'ctrl-rangeinput';
        range.min = rangeMin;
        range.max = rangeMax;
        range.step = step;
        range.value = initial;
        // Live preview: update the number box (and any other mirrors) on every
        // drag tick, but only actually send the value to Python on release.
        range.addEventListener('input', () => applyLocal(Number(range.value), true));
        range.addEventListener('change', () => commit(Number(range.value), true));
        return {
          node: range,
          setValue: (v, fromDrag) => { range.value = v; },
        };
      }

      function buildDialWidget({ min, max, initial, commit, applyLocal, sensitivity, hasMin, hasMax }) {
        const svgNS = 'http://www.w3.org/2000/svg';
        const size = 100;
        const svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
        svg.setAttribute('width', size);
        svg.setAttribute('height', size);
        svg.classList.add('ctrl-dial');
        const cx = size / 2, cy = size / 2, r = size / 2 - 8;

        const track = document.createElementNS(svgNS, 'circle');
        track.setAttribute('cx', cx);
        track.setAttribute('cy', cy);
        track.setAttribute('r', r);
        track.classList.add('dial-track');
        svg.appendChild(track);

        // Up/down arrows as drag-direction hints, inside the circle at the
        // 12 and 6 o'clock positions. Drawn as polygons (rather than text
        // glyphs) so they scale with the SVG viewBox when the dial is
        // resized via the `height` multiplier.
        const mkArrow = (pointsUp, y) => {
          const p = document.createElementNS(svgNS, 'polygon');
          const w = 7, h = 6;
          const pts = pointsUp
            ? `${cx},${y - h / 2} ${cx - w / 2},${y + h / 2} ${cx + w / 2},${y + h / 2}`
            : `${cx - w / 2},${y - h / 2} ${cx + w / 2},${y - h / 2} ${cx},${y + h / 2}`;
          p.setAttribute('points', pts);
          p.classList.add('dial-arrow');
          return p;
        };
        svg.appendChild(mkArrow(true,  cy - r + 9));
        svg.appendChild(mkArrow(false, cy + r - 9));

        const indicator = document.createElementNS(svgNS, 'line');
        indicator.classList.add('dial-indicator');
        svg.appendChild(indicator);

        // Unified rotation math: the indicator advances by 2π radians for
        // every `valuePerRotation` units of value change, in either
        // direction. Hardstops fall out naturally — when value clamps,
        // the per-tick delta is 0 and the indicator stops. sensitivity
        // sets how much of the value range one rotation covers:
        //   bounded:   valuePerRotation = (max - min) * sensitivity
        //              sensitivity=1    -> 1 rotation per range
        //              sensitivity=0.2  -> 5 rotations per range
        //   unbounded: valuePerRotation = sensitivity directly
        //              (raw value units per rotation)
        const bothBounded = hasMin && hasMax;
        const refRange = bothBounded ? (max - min) : 1;
        const valuePerRotation = refRange * sensitivity;
        const PX_PER_ROTATION = 100;
        const BASE_ANGLE = (-135 * Math.PI) / 180;

        let currentValue = initial;
        let currentAngle = BASE_ANGLE;

        function drawIndicator() {
          const x2 = cx + (r - 4) * Math.sin(currentAngle);
          const y2 = cy - (r - 4) * Math.cos(currentAngle);
          indicator.setAttribute('x1', cx);
          indicator.setAttribute('y1', cy);
          indicator.setAttribute('x2', x2);
          indicator.setAttribute('y2', y2);
        }
        drawIndicator();

        // Vertical drag: drag up = value increases. 100 px of drag =
        // one full indicator rotation = valuePerRotation units of value
        // change. When value is pinned at a hardstop, delta = 0 and the
        // indicator stops too.
        svg.addEventListener('pointerdown', (e) => {
          const startY = e.clientY;
          const startV = currentValue;
          svg.classList.add('ctrl-dial-dragging');

          const onMove = (em) => {
            const dy = startY - em.clientY;  // positive when dragging up
            const target = startV + (dy / PX_PER_ROTATION) * valuePerRotation;
            applyLocal(target, true);
          };
          const onUp = () => {
            document.removeEventListener('pointermove', onMove);
            document.removeEventListener('pointerup', onUp);
            svg.classList.remove('ctrl-dial-dragging');
            commit(currentValue, true);
          };
          document.addEventListener('pointermove', onMove);
          document.addEventListener('pointerup', onUp, { once: true });
          try { svg.setPointerCapture(e.pointerId); } catch (err) {}
          e.preventDefault();
        });

        return {
          node: svg,
          setValue: (v, fromDrag) => {
            if (fromDrag) {
              // Incremental update during a drag: rotate the indicator by
              // the delta since the last set, which implicitly pins it
              // when value clamps at a hardstop.
              const delta = v - currentValue;
              currentAngle += (delta / valuePerRotation) * 2 * Math.PI;
            } else {
              // External update (e.g. seeded server value on reconnect):
              // snap back to the base angle so we have a known starting
              // point for the next drag.
              currentAngle = BASE_ANGLE;
            }
            currentValue = v;
            drawIndicator();
          },
        };
      }

      function buildControlElement(el) {
        const item = document.createElement('div');
        item.className = 'ctrl-item';
        if (el.type === 'button') {
          const b = document.createElement('button');
          b.className = 'ctrl-btn';
          b.textContent = el.label || el.id;
          b.addEventListener('click', () => sendCtrl({ type: 'control_button', id: el.id }));
          item.appendChild(b);
        } else if (el.type === 'slider') {
          return makeScalarControl(el, buildSliderWidget);
        } else if (el.type === 'dial') {
          return makeScalarControl(el, buildDialWidget);
        } else if (el.type === 'display') {
          item.classList.add('ctrl-display');
          if (el.label) {
            const lbl = document.createElement('label');
            lbl.textContent = el.label;
            item.appendChild(lbl);
          }
          const val = document.createElement('span');
          val.className = 'ctrl-val';
          val.textContent = '--';
          item.appendChild(val);
          controlElements.displays[el.id] = val;
          controlElements.displayKinds[el.id] = 'numeric';
          const fmt = parseDisplayFormat(el.format);
          if (fmt) controlElements.displayFormats[el.id] = fmt;
        } else if (el.type === 'text') {
          item.classList.add('ctrl-text', 'flex');
          if (el.label) {
            const lbl = document.createElement('label');
            lbl.textContent = el.label;
            item.appendChild(lbl);
          }
          const val = document.createElement('span');
          val.className = 'ctrl-val ctrl-textval';
          val.textContent = el.value || '--';
          item.appendChild(val);
          controlElements.displays[el.id] = val;
          controlElements.displayKinds[el.id] = 'text';
        }
        return item;
      }

      function applyElementSize(item, el) {
        // height: per-element multiplier on the standard row height. Lets
        // users declare e.g. `{"type":"button","height":2}` to get a bigger
        // click target, or `{"type":"dial","height":2}` to get a bigger
        // knob. Values other than 1 set a min-height on the wrapper and,
        // for buttons, make the button stretch to fill it. For dials the
        // nested SVG itself is resized so the knob actually grows.
        const h = Number(el.height);
        if (Number.isFinite(h) && h > 0 && h !== 1) {
          item.style.minHeight = `calc(var(--ctrl-unit-h) * ${h})`;
          if (h > 1) item.classList.add('ctrl-item-tall');
          const dial = item.querySelector('.ctrl-dial');
          if (dial) {
            const base = Number(dial.getAttribute('width')) || 100;
            const newSize = Math.round(base * h);
            dial.setAttribute('width', newSize);
            dial.setAttribute('height', newSize);
          }
        }
      }

      function buildControlRow(row) {
        const div = document.createElement('div');
        div.className = 'ctrl-row';
        row.forEach(el => {
          const item = buildControlElement(el);
          applyElementSize(item, el);
          div.appendChild(item);
        });
        return div;
      }

      function applySliderValues(values) {
        if (!values) return;
        for (const [id, val] of Object.entries(values)) {
          const s = controlElements.sliders[id];
          if (s && typeof s.setValue === 'function') s.setValue(val);
        }
      }

      function applyDisplayValues(values) {
        if (!values) return;
        for (const [id, val] of Object.entries(values)) {
          const node = controlElements.displays[id];
          if (node) node.textContent = formatDisplay(id, val);
        }
      }

      function destroyPlots() {
        plots.forEach(p => { try { p.uplot.destroy(); } catch (e) {} });
        plots = [];
        plotsDiv.innerHTML = '';
        totalTraces = 0;
        controlElements.displays = {};
        controlElements.displayFormats = {};
        controlElements.displayKinds = {};
        controlElements.sliders = {};
      }

      function buildOnePlot(pcfg, rowLayout, traceOffset) {
        const xrange = pcfg.xrange || 200;
        const xs = new Float64Array(xrange);
        for (let i = 0; i < xrange; i++) xs[i] = i;

        const traceCount = pcfg.names.length;
        const colors = pcfg.colors || DEFAULT_COLORS;
        const widths = pcfg.line_width || [];
        const styles = pcfg.line_style || [];

        const series = [{}];
        for (let t = 0; t < traceCount; t++) {
          const dash = (styles[t] === '-') ? [10, 5] : null;
          series.push({
            label: pcfg.names[t],
            stroke: resolveColor(colors[t]),
            width: widths[t] || 1,
            dash: dash || undefined,
            points: { show: false },
            spanGaps: true,
          });
        }

        const baseHeight = rowLayout ? 260 : 320;
        const heightMul = Number(pcfg.height);
        const plotHeight = (Number.isFinite(heightMul) && heightMul > 0)
          ? Math.round(baseHeight * heightMul)
          : baseHeight;
        const opts = {
          width: Math.max(640, plotsDiv.clientWidth - 40),
          height: plotHeight,
          title: pcfg.title || '',
          scales: {
            x: { time: false, range: [0, xrange - 1] },
            y: pcfg.yrange ? { range: [pcfg.yrange[0], pcfg.yrange[1]] } : {},
          },
          axes: [
            { label: pcfg.xlabel || '' },
            { label: pcfg.ylabel || '' },
          ],
          series: series,
          legend: { show: true },
          cursor: { drag: { x: false, y: false } },
        };

        const wrap = document.createElement('div');
        wrap.className = 'plot-wrap';
        plotsDiv.appendChild(wrap);

        const buffers = [];
        for (let t = 0; t < traceCount; t++) {
          const buf = new Float32Array(xrange);
          buf.fill(NaN);
          buffers.push(buf);
        }

        const initialData = [xs];
        for (let t = 0; t < traceCount; t++) initialData.push(buffers[t]);

        const u = new uPlot(opts, initialData, wrap);
        plots.push({
          uplot: u,
          xs: xs,
          traceCount: traceCount,
          startIdx: traceOffset,
          xrange: xrange,
          buffers: buffers,
          height: opts.height,
        });
        return traceCount;
      }

      function buildPlots(cfg) {
        destroyPlots();
        plotsDiv.classList.toggle('row', cfg.row_layout);
        plotsDiv.classList.toggle('col', !cfg.row_layout);

        const controls = cfg.controls || [];
        const layout = (cfg.layout && cfg.layout.length)
          ? cfg.layout
          : cfg.plots.map((_, idx) => ({ kind: 'plot', index: idx }))
              .concat(controls.map((_, idx) => ({ kind: 'controls', index: idx })));

        let traceOffset = 0;
        layout.forEach(entry => {
          if (entry.kind === 'plot') {
            const pcfg = cfg.plots[entry.index];
            if (!pcfg) return;
            traceOffset += buildOnePlot(pcfg, cfg.row_layout, traceOffset);
          } else if (entry.kind === 'controls') {
            const row = controls[entry.index];
            if (!row) return;
            plotsDiv.appendChild(buildControlRow(row));
          }
        });
        totalTraces = traceOffset;
        applySliderValues(cfg.slider_values);
        applyDisplayValues(cfg.display_values);
        applyVisibleSamples();
        scheduleRender();
      }

      // Track render-FPS with a 1-second moving window so the status bar
      // can show both the data rate (from the server) and the actual
      // browser repaint rate.
      let renderFrameCount = 0;
      let renderFpsLastCheck = performance.now();
      let renderFps = 0;

      let lastRenderTime = 0;
      function _doRender() {
        pendingFrame = false;
        // Update the render-FPS counter every repaint.
        renderFrameCount += 1;
        const now = performance.now();
        if (now - renderFpsLastCheck >= 1000) {
          renderFps = renderFrameCount * 1000 / (now - renderFpsLastCheck);
          renderFrameCount = 0;
          renderFpsLastCheck = now;
          lastStatus.dirty = true;
        }
        lastRenderTime = now;
        plots.forEach(p => {
          const data = [p.xs];
          for (let t = 0; t < p.traceCount; t++) data.push(p.buffers[t]);
          // Default resetScales=true so y-axis auto-fits when no yrange
          // was supplied. With explicit yrange, uPlot pins the scale and
          // this is essentially a no-op.
          p.uplot.setData(data);
        });
        if (lastStatus.dirty) {
          const txt =
            `Data ${lastStatus.fps.toFixed(0)} Hz  ·  Render ${renderFps.toFixed(0)} Hz` +
            (lastStatus.nonPlot > 0 ? `  ·  non-plot ${lastStatus.nonPlot}` : '');
          statusDiv.textContent = txt;
          statusDiv.className = lastStatus.statusByte === 1 ? 'red' : 'green';
          lastStatus.dirty = false;
        }
      }

      function scheduleRender() {
        if (pendingFrame) return;
        pendingFrame = true;
        requestAnimationFrame(() => {
          // FPS cap: if the user set a maxFps in the hamburger menu and
          // we're within 1000/maxFps ms of the last actual repaint,
          // reschedule ourselves a bit later via setTimeout instead of
          // running the render now. This spaces repaints out without
          // losing any data (the ring buffers keep accumulating).
          const cap = Number(settings.maxFps) || 0;
          if (cap > 0) {
            const minInterval = 1000 / cap;
            const now = performance.now();
            const wait = minInterval - (now - lastRenderTime);
            if (wait > 1) {
              pendingFrame = false;
              setTimeout(scheduleRender, wait);
              return;
            }
          }
          _doRender();
        });
      }

      function applyBinary(buf) {
        if (!plots.length) return;
        const view = new DataView(buf);
        const msgType = view.getUint8(0);
        const status = view.getUint8(1);
        const nonPlot = view.getUint8(2);
        const numTraces = view.getUint32(4, true);
        const numSamples = view.getUint32(8, true);
        const fps = view.getFloat32(12, true);
        if (numTraces !== totalTraces || numSamples === 0) return;

        // Float32Array view directly over the WS payload — no copy.
        const data = new Float32Array(buf, HEADER_SIZE, numTraces * numSamples);

        if (msgType === MSG_SNAPSHOT) {
          plots.forEach(p => {
            for (let t = 0; t < p.traceCount; t++) {
              const traceRow = p.startIdx + t;
              const offset = traceRow * numSamples;
              const buf32 = p.buffers[t];
              if (numSamples >= p.xrange) {
                buf32.set(data.subarray(offset + numSamples - p.xrange, offset + numSamples));
              } else {
                buf32.fill(0);
                buf32.set(data.subarray(offset, offset + numSamples), p.xrange - numSamples);
              }
            }
          });
        } else if (msgType === MSG_DELTA) {
          const n = numSamples;
          plots.forEach(p => {
            for (let t = 0; t < p.traceCount; t++) {
              const traceRow = p.startIdx + t;
              const buf32 = p.buffers[t];
              if (n < buf32.length) {
                buf32.copyWithin(0, n);
                const offset = traceRow * n;
                buf32.set(data.subarray(offset, offset + n), buf32.length - n);
              } else {
                const offset = traceRow * n + (n - buf32.length);
                buf32.set(data.subarray(offset, offset + buf32.length));
              }
            }
          });
        } else {
          return;
        }

        if (lastStatus.fps !== fps || lastStatus.statusByte !== status || lastStatus.nonPlot !== nonPlot) {
          lastStatus.fps = fps;
          lastStatus.statusByte = status;
          lastStatus.nonPlot = nonPlot;
          lastStatus.dirty = true;
        }
        scheduleRender();
      }

      function setZmqMode(mode, target) {
        if (mode === 'connect') {
          zmqMode.textContent = `ZMQ → ${target}`;
        } else if (mode === 'bind') {
          zmqMode.textContent = `ZMQ bind ${target || '*:5555'}`;
        } else {
          zmqMode.textContent = 'ZMQ: --';
        }
        // Color-code the two mode buttons: the currently-active mode is
        // green and non-clickable (clicking it again would be a no-op);
        // the other is plain white and clickable so users can see at a
        // glance which action is available.
        bindBtn.classList.remove('zmq-active', 'zmq-disabled');
        connectBtn.classList.remove('zmq-active', 'zmq-disabled');
        if (mode === 'bind') {
          bindBtn.classList.add('zmq-active');
          // Clear the IP field so the user can type a fresh target
          // without having to manually erase the old value.
          ipInput.value = '';
        } else if (mode === 'connect') {
          connectBtn.classList.add('zmq-active');
        }
      }

      function connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        socket = new WebSocket(proto + '//' + location.host + '/ws');
        socket.binaryType = 'arraybuffer';
        socket.onopen = () => { wsStatus.textContent = 'connected'; };
        socket.onclose = () => {
          wsStatus.textContent = 'disconnected, retrying...';
          setTimeout(connect, 1000);
        };
        socket.onerror = () => { wsStatus.textContent = 'error'; };
        socket.onmessage = (ev) => {
          if (typeof ev.data === 'string') {
            let msg;
            try { msg = JSON.parse(ev.data); } catch (e) { return; }
            if (msg.type === 'config') {
              buildPlots(msg);
            } else if (msg.type === 'zmq_status') {
              setZmqMode(msg.mode, msg.target);
              if (msg.mode === 'connect' && msg.target) {
                ipInput.value = msg.target;
              }
            } else if (msg.type === 'display_update') {
              applyDisplayValues(msg.values);
            }
          } else {
            applyBinary(ev.data);
          }
        };
      }

      saveBtn.addEventListener('click', () => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'save' }));
        }
      });

      connectBtn.addEventListener('click', () => {
        // Already in connect mode — clicking again is a no-op unless
        // the user has typed a DIFFERENT IP into the input.
        const ip = ipInput.value.trim();
        if (!ip) { ipInput.focus(); return; }
        if (connectBtn.classList.contains('zmq-active')) {
          // Allow re-connecting to a different host while already in
          // connect mode (retarget). Fall through to send the message.
        }
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'configure_ip', ip: ip }));
        }
      });

      ipInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') connectBtn.click();
      });

      bindBtn.addEventListener('click', () => {
        // Binding twice is a no-op; skip the WS round trip.
        if (bindBtn.classList.contains('zmq-active')) return;
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'bind' }));
        }
      });

      window.addEventListener('resize', () => {
        plots.forEach(p => {
          p.uplot.setSize({
            width: Math.max(640, plotsDiv.clientWidth - 40),
            height: p.height,
          });
        });
      });

      connect();
    })();
  </script>
</body>
</html>
"""


async def handle_index(request):
    return web.Response(
        text=INDEX_HTML,
        content_type="text/html",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


# ------------------------------------------------------------------ snapshot
# GET /snapshot.html returns a self-contained static HTML file that
# reproduces the current plot visually without needing any server
# connection. uPlot's JS + CSS are inlined, the visible buffer and
# per-plot config are embedded as JSON, and a small bootstrap script
# calls `new uPlot(opts, data, container)` on page load. Pass
# ?animate=1 to also embed a setInterval loop that keeps scrolling
# the data so the plot looks alive.
#
# Example scripts use this via client.save_snapshot("path.html"), so
# they can commit a reproducible static preview alongside the code.

def _read_static_asset(name: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "static", name)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


# Loaded once at module import so per-request cost is just JSON + format.
try:
    _UPLOT_JS = _read_static_asset("uPlot.iife.min.js")
    _UPLOT_CSS = _read_static_asset("uPlot.min.css")
except Exception as _exc:  # noqa: BLE001
    _UPLOT_JS = f"/* uPlot load failed: {_exc} */"
    _UPLOT_CSS = ""


_SNAPSHOT_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>rtplot snapshot</title>
<style>__UPLOT_CSS__</style>
<style>
  html, body { margin: 0; padding: 0; background: #fafafa; color: #222;
               font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  #plots { display: flex; flex-direction: column; gap: 12px;
           max-width: 900px; margin: 0 auto; padding: 20px 16px; }
  .plot-wrap { background: #fff; border: 1px solid #ddd; border-radius: 4px; padding: 8px; }
  .snap-footer { text-align: center; font-size: 12px; color: #999; padding: 8px 0 20px; }
  .snap-footer a { color: #2a5db0; text-decoration: none; }
  .snap-footer a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div id="plots"></div>
<p class="snap-footer">
  static snapshot from
  <a href="https://github.com/jmontp/rtplot">rtplot</a>
  &middot; drag to zoom, double-click to reset
</p>
<script>__UPLOT_JS__</script>
<script>
(function () {
  const SNAP = __SNAPSHOT_JSON__;
  const plotsDiv = document.getElementById('plots');
  const COLOR_MAP = { r:'rgb(255,0,0)', g:'rgb(0,200,0)', b:'rgb(0,0,255)',
                      c:'rgb(0,200,200)', m:'rgb(200,0,200)',
                      y:'rgb(200,200,0)', k:'rgb(0,0,0)' };
  const DEFAULT_COLORS = ['r','g','b','c','m','y'];
  function resolveColor(c) {
    if (c == null) return 'rgb(0,0,0)';
    if (Array.isArray(c) && c.length >= 3) return `rgb(${c[0]},${c[1]},${c[2]})`;
    if (typeof c === 'string') return COLOR_MAP[c] || c;
    return 'rgb(0,0,0)';
  }
  const plots = [];
  let traceOffset = 0;
  SNAP.plots.forEach(function (pcfg) {
    const xrange = SNAP.num_samples;
    const xs = new Float64Array(xrange);
    for (let i = 0; i < xrange; i++) xs[i] = i;
    const traceCount = pcfg.names.length;
    const colors = pcfg.colors || DEFAULT_COLORS;
    const widths = pcfg.line_width || [];
    const styles = pcfg.line_style || [];
    const series = [{}];
    for (let t = 0; t < traceCount; t++) {
      series.push({
        label: pcfg.names[t],
        stroke: resolveColor(colors[t]),
        width: widths[t] || 1,
        dash: (styles[t] === '-') ? [10, 5] : undefined,
        points: { show: false },
      });
    }
    const wrap = document.createElement('div');
    wrap.className = 'plot-wrap';
    plotsDiv.appendChild(wrap);
    const data = [xs];
    for (let t = 0; t < traceCount; t++) {
      const src = SNAP.trace_data[traceOffset + t];
      data.push(Float64Array.from(src));
    }
    const opts = {
      width: Math.max(640, plotsDiv.clientWidth - 40),
      height: 260,
      title: pcfg.title || '',
      scales: {
        x: { time: false, range: [0, xrange - 1] },
        y: pcfg.yrange ? { range: [pcfg.yrange[0], pcfg.yrange[1]] } : {},
      },
      axes: [{ label: pcfg.xlabel || '' }, { label: pcfg.ylabel || '' }],
      series: series,
      legend: { show: true },
      cursor: { drag: { x: true, y: false } },
    };
    const u = new uPlot(opts, data, wrap);
    plots.push({ uplot: u, data: data, xs: xs, xrange: xrange,
                 traceCount: traceCount, startIdx: traceOffset });
    traceOffset += traceCount;
  });
  // Tier-2 animated replay: keep rolling the ring buffer so the plot
  // looks "live". Disabled unless the /snapshot.html?animate=1 query
  // was set at save time.
  if (SNAP.animate) {
    let phase = 0;
    setInterval(function () {
      phase = (phase + 1) % SNAP.num_samples;
      plots.forEach(function (p) {
        const nd = [p.xs];
        for (let t = 0; t < p.traceCount; t++) {
          const src = SNAP.trace_data[p.startIdx + t];
          const out = new Float64Array(p.xrange);
          for (let i = 0; i < p.xrange; i++) {
            out[i] = src[(i + phase) % p.xrange];
          }
          nd.push(out);
        }
        p.uplot.setData(nd);
      });
    }, 33);
  }
  window.addEventListener('resize', function () {
    plots.forEach(function (p) {
      p.uplot.setSize({
        width: Math.max(640, plotsDiv.clientWidth - 40),
        height: 260,
      });
    });
  });
})();
</script>
</body>
</html>
"""


def _build_snapshot_html(animate: bool) -> str:
    """Serialize the current plot state into a static snapshot HTML document."""
    # Determine the visible window in the ring buffer. If no data has
    # arrived yet, return an "empty" snapshot with a helpful note.
    li = state.get("li", 0)
    num_points = state.get("num_datapoints_in_plot", DEFAULT_NUM_DATAPOINTS_IN_PLOT)
    num_traces = state.get("num_traces", 0)
    if num_traces == 0 or not state.get("initialized", False):
        return (
            "<!doctype html><html><body style='font-family:sans-serif;padding:32px'>"
            "<h1>rtplot snapshot</h1>"
            "<p>No plot has been initialized yet — start your client and "
            "call <code>initialize_plots()</code> first, then hit "
            "<code>/snapshot.html</code> again.</p></body></html>"
        )
    lo = max(0, li - num_points)
    hi = li

    # Rebuild the per-plot configs from the OrderedDict the user sent.
    plots = []
    cfg = state.get("config_dict") or OrderedDict()
    for key, plot_description in cfg.items():
        if "non_plot_labels" in plot_description or "controls" in plot_description:
            continue
        plots.append({
            "key": key,
            "names": plot_description.get("names", []),
            "colors": plot_description.get("colors"),
            "line_style": plot_description.get("line_style"),
            "line_width": plot_description.get("line_width"),
            "title": plot_description.get("title"),
            "xlabel": plot_description.get("xlabel"),
            "ylabel": plot_description.get("ylabel"),
            "yrange": plot_description.get("yrange"),
        })

    # Extract the last `num_points` samples for each plotted trace.
    trace_data = []
    arr = local_storage_buffer[:num_traces, lo:hi]
    for i in range(num_traces):
        trace_data.append([float(v) for v in arr[i]])

    payload = {
        "plots": plots,
        "num_samples": int(hi - lo),
        "trace_data": trace_data,
        "animate": bool(animate),
    }

    # Use a placeholder-replace strategy instead of .format() so the
    # uPlot minified JS's {} braces don't need to be escaped.
    html = _SNAPSHOT_TEMPLATE
    html = html.replace("__UPLOT_CSS__", _UPLOT_CSS)
    html = html.replace("__UPLOT_JS__", _UPLOT_JS)
    html = html.replace("__SNAPSHOT_JSON__", json.dumps(payload))
    return html


async def handle_snapshot(request):
    animate = request.query.get("animate") == "1"
    html = _build_snapshot_html(animate=animate)
    return web.Response(
        text=html,
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


async def handle_ws(request):
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(request)
    ws_clients.add(ws)
    try:
        await ws.send_str(
            json.dumps(
                {
                    "type": "zmq_status",
                    "mode": zmq_status["mode"],
                    "target": zmq_status["target"],
                }
            )
        )
        if state["config_message"] is not None:
            await ws.send_str(json.dumps(state["config_message"]))
            if state["display_values"]:
                await ws.send_str(
                    json.dumps(
                        {
                            "type": "display_update",
                            "values": dict(state["display_values"]),
                        }
                    )
                )
            snap = make_snapshot_message()
            if snap is not None:
                await ws.send_bytes(snap)
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                ptype = payload.get("type")
                if ptype == "save":
                    try:
                        save_current_plot(payload.get("name"))
                    except Exception as exc:  # noqa: BLE001
                        print(f"[rtplot] save_current_plot failed: {exc}")
                elif ptype == "configure_ip":
                    ip = payload.get("ip")
                    if ip:
                        try:
                            await reconfigure_zmq(request.app, connect_ip=ip)
                        except Exception as exc:  # noqa: BLE001
                            print(f"[rtplot] configure_ip failed: {exc}")
                elif ptype == "bind":
                    try:
                        await reconfigure_zmq(request.app, connect_ip=None)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[rtplot] bind failed: {exc}")
                elif ptype == "control_button":
                    btn_id = payload.get("id")
                    if btn_id:
                        await send_control_event({"type": "button", "id": btn_id})
                elif ptype == "control_slider":
                    sid = payload.get("id")
                    try:
                        value = float(payload.get("value", 0.0))
                    except (TypeError, ValueError):
                        value = 0.0
                    if sid:
                        state["slider_values"][sid] = value
                        await send_control_event(
                            {"type": "slider", "id": sid, "value": value}
                        )
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        ws_clients.discard(ws)
    return ws


async def on_startup(app):
    app["zmq_task"] = asyncio.create_task(zmq_receiver())
    app["ws_task"] = asyncio.create_task(ws_pusher())
    app["display_task"] = asyncio.create_task(display_pusher())


async def on_cleanup(app):
    for key in ("zmq_task", "ws_task", "display_task"):
        task = app.get(key)
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    for ws in list(ws_clients):
        await ws.close()
    zmq_socket.close(0)
    if control_push_socket is not None:
        control_push_socket.close(0)
    zmq_ctx.term()


def build_app():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/ws", handle_ws)
    app.router.add_get("/snapshot.html", handle_snapshot)
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    app.router.add_static("/static/", static_dir)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def _detect_lan_ips():
    """Return likely-reachable IPs (LAN + WSL) for the connect-here hint."""
    ips = []
    try:
        import socket as _s

        hostname = _s.gethostname()
        for info in _s.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ip and ip not in ips and not ip.startswith("127.") and ":" not in ip:
                ips.append(ip)
    except Exception:  # noqa: BLE001
        pass
    return ips


def main():
    app = build_app()
    print(f"rtplot browser server listening on http://localhost:{args.port}")
    for ip in _detect_lan_ips():
        print(f"  also reachable at  http://{ip}:{args.port}")
    is_wsl = "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ
    if is_wsl:
        print(
            "  (WSL detected: open the URL above in your Windows browser;"
            " if localhost doesn't work, use one of the LAN IPs)"
        )
    # webbrowser.open() shells out to xdg-settings/xdg-open, which can hang
    # indefinitely under WSL waiting on D-Bus. Skip it on WSL entirely, and
    # always run it in a daemon thread so a stuck child can never block
    # web.run_app from binding the HTTP port.
    if not args.no_browser and not is_wsl:
        import threading

        def _open():
            try:
                webbrowser.open(f"http://localhost:{args.port}")
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_open, daemon=True).start()
    # Bind to 0.0.0.0 explicitly so WSL2 / LAN clients can reach us.
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
