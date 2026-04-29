"""Browser-based rtplot server with multi-tab routing.

The ZMQ protocol exposed to clients is identical to the original server,
so existing client code keeps working unchanged. Each tab owns its own
ZMQ socket pair so one server process can host several senders at once:

  * ``bind_me`` — a fixed, shared tab that binds ``tcp://*:5555`` (data)
    and ``tcp://*:5556`` (controls). Any sender that connects to this
    server's LAN IP ends up here. Not renameable, not deletable.

  * ``tab_<id>`` — user-created tabs that dial out to a specific device
    (``host:port``). Browsers switch between tabs via the tab bar at the
    top of the UI.

Each browser WebSocket is bound to exactly one tab at a time. Switching
tabs is just a ``tab_subscribe`` message — the server immediately pushes
that tab's config + buffer snapshot. Control events are routed to the
subscribed tab's PUSH socket.
"""

import argparse
import asyncio
import dataclasses
import json
import os
import socket
import subprocess
import struct
import sys
import time
import uuid
import webbrowser
from collections import OrderedDict
from dataclasses import dataclass, field
from time import perf_counter
from typing import Optional

import numpy as np
import zmq
import zmq.asyncio
from zmq.utils.monitor import recv_monitor_message

# pyzmq's asyncio integration needs event_loop.add_reader(), which the
# Windows-default ProactorEventLoop (Python 3.8+) does not implement.
# Without this policy override, zmq receives throw on first recv, the
# task dies silently, and any data the client pushes after that gets
# dropped — the browser plot stays blank with no visible error.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    from aiohttp import WSMsgType, web
except ImportError as _exc:
    _missing = getattr(_exc, "name", None) or "aiohttp"
    sys.stderr.write(
        "\n[rtplot] Cannot import '{m}'. The browser server needs the\n"
        "'browser' extra (just aiohttp these days).\n"
        "\n"
        "Install it with:\n"
        "    pip install 'better-rtplot[browser]'\n"
        "\n".format(m=_missing)
    )
    sys.exit(1)

try:  # Optional: resources panel falls back gracefully if missing.
    import psutil  # type: ignore
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore
    _PSUTIL_AVAILABLE = False


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
        "If supplied, create an extra tab at startup that connects outbound"
        " to that host[:port]. The default 'Shared - Bind to me' tab still"
        " binds locally."
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

parser.add_argument(
    "--password",
    help=(
        "Gate the whole UI behind a shared password (HTTP Basic). Any"
        " username is accepted. Can also be set via RTPLOT_PASSWORD env"
        " var; the flag wins if both are given. Leave unset to serve"
        " without auth."
    ),
    action="store",
    type=str,
    default=None,
)

args = parser.parse_args()

NEW_SUBPLOT_IN_ROW = args.column
DEBUG_TEXT_ENABLED = args.debug
SKIP_PLOT_DATAPOINTS = args.skip
ADAPT_SKIP_PLOT_DATAPOINTS = args.adaptable
AUTH_PASSWORD = args.password if args.password is not None else os.environ.get("RTPLOT_PASSWORD")


###############################
# Local storage configuration #
###############################

DEFAULT_NUM_DATAPOINTS_IN_PLOT = 200
MAX_LOCAL_STORAGE = 10_000_000
INITIAL_NUM_TRACES = 50

# Binary frame pushed to browsers (plot data):
#   uint8  msg_type   (0 = snapshot, 1 = delta)
#   uint8  status     (0 = green,    1 = red)
#   uint8  reserved   (was non-plot trace count, kept for wire compat)
#   uint8  pad
#   uint32 num_traces
#   uint32 num_samples
#   float32 fps
#   float32[num_traces * num_samples]  data, row-major
HEADER_FMT = "<BBBxIIf"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MSG_SNAPSHOT = 0
MSG_DELTA = 1

ZMQ_DEFAULT_PORT = 5555
ZMQ_CONTROL_PORT = ZMQ_DEFAULT_PORT + 1
TCP_PROBE_TIMEOUT = 0.5

RECEIVED_PLOT_UPDATE = 0
RECEIVED_DATA = 1
SAVE_PLOT = 3
RECEIVED_DISPLAY = 4

BIND_ME_ID = "bind_me"
BIND_ME_NAME = "Shared - Bind to me"

# Path to the persisted tabs JSON. Honors RTPLOT_TABS_FILE so tests
# (and operators with multi-user setups) can override without symlinking
# their HOME directory or losing access to ~/.local site-packages.
TABS_FILE = os.environ.get(
    "RTPLOT_TABS_FILE",
    os.path.join(os.path.expanduser("~"), ".rtplot", "tabs.json"),
)

zmq_ctx = zmq.asyncio.Context()


###############################
# Endpoint-parsing helpers #
###############################

def _normalize_connect_target(ip, port=ZMQ_DEFAULT_PORT):
    """Return ``(tcp://...endpoint, host:port label)`` for a user-supplied IP."""
    ip = ip.strip()
    if ip.startswith("tcp://"):
        endpoint = ip
        label = ip[len("tcp://"):]
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


def _host_port_from_endpoint(endpoint, default_port=ZMQ_DEFAULT_PORT):
    """Parse ``tcp://host:port`` or ``host[:port]`` into ``(host, port)``."""
    raw = endpoint.strip()
    if raw.startswith("tcp://"):
        raw = raw[len("tcp://"):]
    if raw.count(":") >= 1:
        host, port_str = raw.rsplit(":", 1)
    else:
        host, port_str = raw, str(default_port)
    try:
        port = int(port_str)
    except ValueError:
        port = default_port
    return host, port


def _probe_tcp_endpoint(endpoint, timeout=TCP_PROBE_TIMEOUT):
    """Return ``(open, reachable, error)`` for a TCP endpoint.

    ``Connection refused`` still proves the host answered at the network
    layer, so it is reachable even though that particular port is closed.
    """
    host, port = _host_port_from_endpoint(endpoint)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, True, None
    except ConnectionRefusedError as exc:
        return False, True, str(exc)
    except OSError as exc:
        return False, False, str(exc)


def _ping_host(host):
    """Best-effort host reachability fallback for firewalled TCP ports."""
    if not host or host == "*":
        return False
    if sys.platform == "win32":
        cmd = ["ping", "-n", "1", "-w", "700", host]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", host]
    try:
        return subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.5,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _probe_connect_target(endpoint):
    """Classify a connect-mode target for the browser status dot.

    Returns ``(host_reachable, rtplot_ports_open, error)``. A reachable host
    with closed rtplot ports is still a usable tab: ZeroMQ can connect now and
    auto-complete the connection later when the sender starts listening.
    """
    host, data_port = _host_port_from_endpoint(endpoint)
    data_open, data_reachable, data_err = _probe_tcp_endpoint(endpoint)
    ctrl_endpoint = _control_target_from_data(endpoint)
    ctrl_open, ctrl_reachable, ctrl_err = _probe_tcp_endpoint(
        ctrl_endpoint, timeout=TCP_PROBE_TIMEOUT
    )
    host_reachable = data_reachable or ctrl_reachable
    if not host_reachable and _ping_host(host):
        host_reachable = True
    if not host_reachable:
        return (
            False,
            False,
            f"{host} unreachable (data {data_port}: {data_err}; "
            f"control {data_port + 1}: {ctrl_err})",
        )
    return True, bool(data_open and ctrl_open), None


###############################
# Tab model #
###############################

@dataclass
class Tab:
    """One logical data source: bind (incoming) or connect (outbound)."""

    id: str
    name: str
    mode: str                 # "bind" or "connect"
    endpoint: str             # user-visible label, e.g. "*:5555" or "pi1:5555"
    status: str = "idle"      # idle | connecting | connected | streaming | error
    error: Optional[str] = None

    # Plot state
    config_dict: Optional["OrderedDict"] = None
    config_message: Optional[dict] = None
    initialized: bool = False
    num_datapoints_in_plot: int = DEFAULT_NUM_DATAPOINTS_IN_PLOT
    li: int = DEFAULT_NUM_DATAPOINTS_IN_PLOT
    buffer_bounds: np.ndarray = field(
        default_factory=lambda: np.array([0, DEFAULT_NUM_DATAPOINTS_IN_PLOT])
    )
    num_traces: int = 0
    traces_per_plot: list = field(default_factory=list)
    trace_labels: list = field(default_factory=list)
    last_pushed_li: int = DEFAULT_NUM_DATAPOINTS_IN_PLOT
    layout: list = field(default_factory=list)
    control_rows: list = field(default_factory=list)
    slider_values: dict = field(default_factory=dict)
    display_values: dict = field(default_factory=dict)
    display_dirty: set = field(default_factory=set)
    fps: float = 0.0
    title_color: str = "green"

    # ZMQ sockets + receiver task
    data_sock: Optional[zmq.Socket] = None
    ctrl_sock: Optional[zmq.Socket] = None
    receiver_task: Optional[asyncio.Task] = None
    monitor_task: Optional[asyncio.Task] = None

    # Data buffer, lazy-allocated on first use (roughly 4 GB virtual,
    # but pages in only when written on Linux/Windows — a single tab
    # typically touches a few MB worth of pages).
    buffer: Optional[np.ndarray] = None

    # Used by the resources panel so operators can see which tab is busy.
    data_rate_hz: float = 0.0
    _last_rx_ts: float = 0.0

    # When the most recent client-supplied config failed to parse we
    # stash the reason + a unix timestamp so the browser can surface
    # "your last config was rejected at HH:MM:SS" instead of just
    # silently rendering nothing. Cleared on the next successful parse.
    last_config_error: Optional[dict] = None

    def ensure_buffer(self):
        if self.buffer is None:
            self.buffer = np.zeros((INITIAL_NUM_TRACES, MAX_LOCAL_STORAGE))

    def reset_buffer_state(self, num_datapoints_in_plot, num_traces):
        """Reset the buffer indices when a new plot config arrives."""
        self.ensure_buffer()
        self.num_datapoints_in_plot = num_datapoints_in_plot
        self.li = num_datapoints_in_plot
        self.buffer_bounds = np.array([0, num_datapoints_in_plot])
        self.num_traces = num_traces
        self.last_pushed_li = num_datapoints_in_plot
        self.buffer[:num_traces, :num_datapoints_in_plot] = 0


###############################
# Tab registry #
###############################

# id -> Tab. Always contains BIND_ME_ID.
tabs: "OrderedDict[str, Tab]" = OrderedDict()

# ws -> tab id the browser is currently viewing.
ws_tab: "dict[web.WebSocketResponse, str]" = {}

# set of all currently open WebSocketResponse instances.
ws_clients: set = set()


def tab_public(t: Tab) -> dict:
    """Tab summary that's safe to send to browsers."""
    return {
        "id": t.id,
        "name": t.name,
        "mode": t.mode,
        "endpoint": t.endpoint,
        "status": t.status,
        "error": t.error,
        "last_config_error": t.last_config_error,
    }


def tabs_public() -> list:
    return [tab_public(t) for t in tabs.values()]


def viewers_of(tab_id: str) -> list:
    return [ws for ws, tid in ws_tab.items() if tid == tab_id]


###############################
# Tab persistence #
###############################

def load_persisted_tabs() -> list:
    """Load user-created connect tabs from disk. Returns [] on any failure."""
    try:
        with open(TABS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [
            {
                "id": str(e.get("id")),
                "name": str(e.get("name", "")),
                "endpoint": str(e.get("endpoint", "")),
            }
            for e in data
            if e.get("id") and e.get("endpoint")
            and str(e.get("id")) != BIND_ME_ID
        ]
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def save_persisted_tabs():
    """Persist all connect tabs to ~/.rtplot/tabs.json."""
    entries = [
        {"id": t.id, "name": t.name, "endpoint": t.endpoint}
        for t in tabs.values()
        if t.mode == "connect"
    ]
    try:
        os.makedirs(os.path.dirname(TABS_FILE), exist_ok=True)
        with open(TABS_FILE, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)
    except OSError as exc:
        print(f"[rtplot] Could not save tabs.json: {exc}")


###############################
# Config parsing (per tab) #
###############################

def parse_config(tab: Tab, json_config):
    """Translate a client plot config into the tab's buffer/trace metadata."""
    traces_per_plot = []
    trace_info = []
    control_rows = []
    slider_values = {}
    layout = []
    num_datapoints_in_plot = DEFAULT_NUM_DATAPOINTS_IN_PLOT

    plot_counter = 0
    for plot_description in json_config.values():
        # Legacy non_plot_labels rows — save-to-parquet is gone, but we
        # accept the shape so old client scripts don't crash.
        if "non_plot_labels" in plot_description:
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

    tab.traces_per_plot = traces_per_plot
    tab.trace_labels = trace_info
    tab.control_rows = control_rows
    # Preserve display values across re-init when the same ids are reused;
    # drop ids that are no longer declared so stale data doesn't linger.
    active_display_ids = {
        el["id"]
        for row in control_rows
        for el in row
        if el.get("type") == "display"
    }
    tab.display_values = {
        k: v for k, v in tab.display_values.items() if k in active_display_ids
    }
    tab.display_dirty = {d for d in tab.display_dirty if d in active_display_ids}
    tab.slider_values = slider_values
    tab.layout = layout

    num_traces = sum(traces_per_plot)
    tab.reset_buffer_state(num_datapoints_in_plot, num_traces)

    print(f"[{tab.id}] Initialized plot                 ")
    return num_datapoints_in_plot


def build_config_message(tab: Tab, config_dict) -> dict:
    """Convert the client-supplied OrderedDict into a JSON-friendly message."""
    plots = []
    for key, plot_description in config_dict.items():
        if "non_plot_labels" in plot_description:
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
        "tab": tab.id,
        "plots": plots,
        "controls": tab.control_rows,
        "layout": tab.layout,
        "slider_values": dict(tab.slider_values),
        "display_values": dict(tab.display_values),
        "row_layout": bool(NEW_SUBPLOT_IN_ROW),
    }


###############################
# Binary payload construction #
###############################

def make_data_message(tab: Tab, msg_type, lo, hi):
    """Pack a binary delta/snapshot message for ``tab.buffer[:, lo:hi]``."""
    num_traces = tab.num_traces
    n_samples = hi - lo
    if n_samples <= 0 or num_traces <= 0 or tab.buffer is None:
        return None
    status_int = 1 if tab.title_color == "red" else 0
    fps = float(tab.fps) if tab.fps else 0.0
    header = struct.pack(
        HEADER_FMT, msg_type, status_int, 0, num_traces, n_samples, fps
    )
    payload = np.ascontiguousarray(
        tab.buffer[:num_traces, lo:hi], dtype=np.float32
    )
    return header + payload.tobytes()


def make_snapshot_message(tab: Tab):
    if tab.buffer is None:
        return None
    lo, hi = int(tab.buffer_bounds[0]), int(tab.buffer_bounds[1])
    return make_data_message(tab, MSG_SNAPSHOT, lo, hi)


###############################
# WebSocket broadcasts #
###############################

async def ws_send_text(ws, message):
    try:
        await ws.send_str(json.dumps(message))
        return True
    except (ConnectionResetError, RuntimeError):
        return False


async def ws_send_bytes(ws, payload):
    try:
        await ws.send_bytes(payload)
        return True
    except (ConnectionResetError, RuntimeError):
        return False


async def broadcast_text_all(message):
    """Send a JSON dict to every connected client."""
    if not ws_clients:
        return
    dead = []
    for ws in list(ws_clients):
        if not await ws_send_text(ws, message):
            dead.append(ws)
    for ws in dead:
        _remove_ws(ws)


async def broadcast_text_tab(tab_id, message):
    """Send a JSON dict only to browsers currently viewing ``tab_id``."""
    for ws in viewers_of(tab_id):
        await ws_send_text(ws, message)


async def broadcast_bytes_tab(tab_id, payload):
    if payload is None:
        return
    for ws in viewers_of(tab_id):
        await ws_send_bytes(ws, payload)


async def broadcast_tab_list():
    await broadcast_text_all({"type": "tabs", "tabs": tabs_public()})


async def broadcast_tab(tab_id):
    t = tabs.get(tab_id)
    if t is None:
        return
    await broadcast_text_all({"type": "tab", "tab": tab_public(t)})


async def broadcast_peer_count():
    """Tell every browser how many browsers are connected in total."""
    await broadcast_text_all({"type": "peer_count", "count": len(ws_clients)})


def _remove_ws(ws):
    ws_clients.discard(ws)
    ws_tab.pop(ws, None)


###############################
# ZMQ socket plumbing #
###############################

def _open_tab_sockets(tab: Tab):
    """Open ``tab``'s data + control sockets according to its mode.

    For bind tabs, the just-closed sockets may leave the OS-level port
    in a transient state for a few hundred ms (especially on Windows /
    WSL). We retry the bind with a small backoff so the user-visible
    Reconnect button doesn't fail spuriously the very first time. On
    sustained failure we set tab.status="error" + tab.error=<reason>;
    the tab stays in the list but won't stream until re-opened.
    """
    # Close any prior sockets first (e.g. on retry).
    _close_tab_sockets(tab)

    connect_label = tab.endpoint
    connect_data_ep = None
    if tab.mode == "connect":
        try:
            connect_data_ep, connect_label = _normalize_connect_target(tab.endpoint)
        except Exception as exc:  # noqa: BLE001
            tab.status = "error"
            tab.error = f"invalid endpoint: {exc}"
            print(f"[{tab.id}] ZMQ open failed: {tab.error}")
            return

        tab.endpoint = connect_label
        tab.status = "connecting"
        tab.error = None
        host_reachable, rtplot_ports_open, peer_err = _probe_connect_target(connect_label)
        if not host_reachable:
            tab.status = "error"
            tab.error = peer_err
            print(f"[{tab.id}] peer probe failed: {peer_err}")
            return
        if not rtplot_ports_open:
            tab.status = "idle"
            tab.error = None
            print(
                f"[{tab.id}] host reachable, rtplot ports closed;"
                f" waiting for ZMQ peer: {connect_label}"
            )

    last_exc: Exception | None = None
    attempts = 4 if tab.mode == "bind" else 1
    for attempt in range(attempts):
        monitor = None
        try:
            data = zmq_ctx.socket(zmq.SUB)
            data.setsockopt_string(zmq.SUBSCRIBE, "")
            data.setsockopt(zmq.LINGER, 0)
            ctrl = zmq_ctx.socket(zmq.PUSH)
            ctrl.setsockopt(zmq.SNDHWM, 1000)
            ctrl.setsockopt(zmq.LINGER, 0)

            if tab.mode == "bind":
                data.bind(f"tcp://*:{ZMQ_DEFAULT_PORT}")
                ctrl.bind(f"tcp://*:{ZMQ_CONTROL_PORT}")
                tab.endpoint = f"*:{ZMQ_DEFAULT_PORT}"
                print(f"[{tab.id}] ZMQ: bound on tcp://*:{ZMQ_DEFAULT_PORT}")
            else:
                monitor = data.get_monitor_socket(
                    zmq.EVENT_CONNECTED
                    | zmq.EVENT_DISCONNECTED
                    | zmq.EVENT_CONNECT_DELAYED
                    | zmq.EVENT_CONNECT_RETRIED
                )
                data.connect(connect_data_ep)
                ctrl_ep, _ = _normalize_connect_target(
                    _control_target_from_data(tab.endpoint), port=ZMQ_CONTROL_PORT
                )
                ctrl.connect(ctrl_ep)
                tab.endpoint = connect_label
                tab.monitor_task = asyncio.create_task(zmq_monitor(tab, monitor))
                print(f"[{tab.id}] ZMQ: connecting to {connect_data_ep} (ctrl {ctrl_ep})")

            tab.data_sock = data
            tab.ctrl_sock = ctrl
            tab.status = "idle"
            tab.error = None
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            # Drop the half-built sockets before retrying so we don't
            # leak descriptors and so the next attempt re-takes the port.
            try: data.close(0)
            except Exception: pass
            try: ctrl.close(0)
            except Exception: pass
            try:
                if monitor is not None:
                    monitor.close(0)
            except Exception:
                pass
            if attempt < attempts - 1:
                wait = 0.15 * (attempt + 1)
                print(
                    f"[{tab.id}] ZMQ open attempt {attempt + 1}/{attempts}"
                    f" failed ({exc}); retrying in {wait:.2f}s"
                )
                time.sleep(wait)

    tab.status = "error"
    tab.error = str(last_exc) if last_exc is not None else "unknown error"
    print(f"[{tab.id}] ZMQ open failed after {attempts} attempts: {last_exc}")
    _close_tab_sockets(tab)


def _close_tab_sockets(tab: Tab):
    for attr in ("data_sock", "ctrl_sock"):
        sock = getattr(tab, attr, None)
        if sock is not None:
            try:
                sock.close(0)
            except Exception:  # noqa: BLE001
                pass
            setattr(tab, attr, None)


async def _cancel_task(task):
    if task is None:
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass


async def zmq_monitor(tab: Tab, monitor_sock):
    """Track transport-level ZMQ state for connect-mode tabs."""
    try:
        while True:
            evt = await recv_monitor_message(monitor_sock)
            event = evt.get("event")
            if event == zmq.EVENT_CONNECTED:
                if tab.status in ("connecting", "idle") and not tab.initialized:
                    tab.status = "connected"
                    tab.error = None
                    await broadcast_tab(tab.id)
            elif event == zmq.EVENT_DISCONNECTED:
                if tab.mode == "connect":
                    host_reachable, rtplot_ports_open, peer_err = _probe_connect_target(tab.endpoint)
                    if host_reachable and not rtplot_ports_open:
                        tab.status = "idle"
                        tab.error = None
                    elif host_reachable:
                        tab.status = "idle"
                        tab.error = None
                    else:
                        tab.status = "error"
                        tab.error = peer_err
                    await broadcast_tab(tab.id)
            elif event == zmq.EVENT_CONNECT_RETRIED:
                if tab.mode == "connect" and tab.status == "error":
                    host_reachable, _rtplot_ports_open, peer_err = _probe_connect_target(tab.endpoint)
                    if host_reachable:
                        tab.status = "idle"
                        tab.error = None
                    else:
                        tab.error = peer_err
                    await broadcast_tab(tab.id)
            elif event == zmq.EVENT_CONNECT_DELAYED:
                if tab.mode == "connect" and tab.status == "error":
                    host_reachable, _rtplot_ports_open, peer_err = _probe_connect_target(tab.endpoint)
                    if host_reachable:
                        tab.status = "idle"
                        tab.error = None
                    else:
                        tab.error = peer_err
                    await broadcast_tab(tab.id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        if tab.mode == "connect" and tab.status != "streaming":
            tab.status = "error"
            tab.error = f"ZMQ monitor error: {exc}"
            await broadcast_tab(tab.id)
    finally:
        try:
            monitor_sock.close(0)
        except Exception:  # noqa: BLE001
            pass


async def send_control_event(tab: Tab, event):
    """Forward a control event to the user's Python process, best-effort."""
    if tab.ctrl_sock is None:
        return
    try:
        await tab.ctrl_sock.send_json(event, flags=zmq.DONTWAIT)
    except zmq.Again:
        pass
    except zmq.ZMQError:
        pass


###############################
# Per-tab receiver task #
###############################

async def _recv_array_async(sock):
    md = await sock.recv_json()
    msg = await sock.recv()
    arr = np.frombuffer(memoryview(msg), dtype=md["dtype"])
    return arr.reshape(md["shape"])


async def zmq_receiver(tab: Tab):
    """Drain ``tab.data_sock`` as fast as possible into ``tab.buffer``."""
    last_time = perf_counter()
    fps = None

    while True:
        sock = tab.data_sock
        if sock is None:
            await asyncio.sleep(0.2)
            continue

        try:
            received = await sock.recv_string()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[{tab.id}] ZMQ receive error: {exc}")
            await asyncio.sleep(0.1)
            continue

        try:
            category = int(received)
        except ValueError:
            if DEBUG_TEXT_ENABLED:
                print(f"[{tab.id}] value error, expected int, got: {received}")
            else:
                print(f"[{tab.id}] lost sync with client. Restart client.")
            continue

        now = perf_counter()
        tab._last_rx_ts = now

        if category == RECEIVED_PLOT_UPDATE:
            # Decode + parse are wrapped so a malformed config doesn't kill
            # the receiver task. We stash the failure on the tab so the
            # browser can show "your last config was rejected at HH:MM:SS"
            # instead of looking like nothing happened. Existing valid
            # state (if any) is preserved on parse failure.
            try:
                cfg = await sock.recv_json(object_pairs_hook=OrderedDict)
            except Exception as exc:  # noqa: BLE001
                msg = f"Could not decode config JSON: {type(exc).__name__}: {exc}"
                print(f"[{tab.id}] {msg}")
                tab.last_config_error = {"message": msg, "timestamp": time.time()}
                await broadcast_tab(tab.id)
                continue

            try:
                parse_config(tab, cfg)
            except Exception as exc:  # noqa: BLE001
                msg = f"Configuration rejected: {type(exc).__name__}: {exc}"
                print(f"[{tab.id}] {msg}")
                tab.last_config_error = {"message": msg, "timestamp": time.time()}
                await broadcast_tab(tab.id)
                continue

            tab.last_config_error = None  # clear: this one was good
            tab.config_dict = cfg
            tab.config_message = build_config_message(tab, cfg)
            tab.initialized = True
            fps = None
            tab.fps = 0.0
            last_time = now
            tab.status = "streaming"
            tab.error = None
            # Blocking-handshake ack: tells initialize_plots() on the
            # client side that the config made it past PUB/SUB's
            # slow-joiner window so it can stop resending and return.
            # Old clients ignore unknown event types, so this is safe
            # to emit unconditionally.
            await send_control_event(tab, {"type": "config_ack"})
            await broadcast_text_tab(tab.id, tab.config_message)
            await broadcast_tab(tab.id)
            snap = make_snapshot_message(tab)
            if snap is not None:
                await broadcast_bytes_tab(tab.id, snap)
            # Echo seeded slider defaults back so client's first
            # poll_controls() call already sees the declared initial values.
            for sid, svalue in tab.slider_values.items():
                await send_control_event(
                    tab, {"type": "slider", "id": sid, "value": svalue}
                )

        elif category == RECEIVED_DATA:
            arr = await _recv_array_async(sock)
            if not tab.initialized:
                continue
            tab.ensure_buffer()

            num_values = arr.shape[1]
            li = tab.li
            num_traces = tab.num_traces

            tab.buffer[:num_traces, li:li + num_values] = arr[:num_traces, :]

            dt = now - last_time
            last_time = now
            if dt > 0:
                if fps is None:
                    fps = 1.0 / dt
                else:
                    s = float(np.clip(dt * 3.0, 0, 1))
                    fps = fps * (1 - s) + (1.0 / dt) * s
                tab.fps = fps
                tab.data_rate_hz = fps

            tab.li = li + num_values
            tab.buffer_bounds[0] += num_values
            tab.buffer_bounds[1] += num_values
            tab.title_color = "green"
            if tab.status != "streaming":
                tab.status = "streaming"
                tab.error = None
                await broadcast_tab(tab.id)

        elif category == SAVE_PLOT:
            # Legacy parquet-save; ignored but still drained.
            try:
                await sock.recv_string()
            except Exception:  # noqa: BLE001
                pass

        elif category == RECEIVED_DISPLAY:
            payload = await sock.recv_json()
            display_id = payload.get("id")
            value = payload.get("value")
            if display_id is None:
                continue
            if not isinstance(value, (int, float, str)):
                continue
            if tab.display_values.get(display_id) != value:
                tab.display_values[display_id] = value
                tab.display_dirty.add(display_id)


###############################
# Pusher tasks #
###############################

async def display_pusher():
    """Push any dirty display-box values to viewers at ~30 Hz, per tab."""
    target_dt = 1.0 / 30.0
    while True:
        await asyncio.sleep(target_dt)
        if not ws_clients:
            continue
        for t in list(tabs.values()):
            if not t.display_dirty:
                continue
            values = {k: t.display_values[k] for k in t.display_dirty}
            t.display_dirty = set()
            await broadcast_text_tab(
                t.id, {"type": "display_update", "tab": t.id, "values": values}
            )


async def ws_pusher():
    """Push new samples to viewers as binary delta frames, per tab."""
    target_dt = 1.0 / max(1, args.rate)
    while True:
        await asyncio.sleep(target_dt)
        if not ws_clients:
            continue
        for t in list(tabs.values()):
            if not t.initialized:
                continue
            if not viewers_of(t.id):
                # No browser is watching this tab, skip encoding cost.
                continue

            current_li = t.li
            last_li = t.last_pushed_li
            if current_li <= last_li:
                continue

            num_traces = t.num_traces
            if num_traces == 0:
                continue

            window = t.num_datapoints_in_plot
            n_new = current_li - last_li
            if n_new >= window:
                payload = make_data_message(t, MSG_SNAPSHOT, current_li - window, current_li)
            else:
                payload = make_data_message(t, MSG_DELTA, last_li, current_li)
            t.last_pushed_li = current_li

            if payload is not None:
                await broadcast_bytes_tab(t.id, payload)


async def resources_pusher():
    """Push CPU + memory + per-tab Hz to all browsers every 2 s."""
    target_dt = 2.0
    # First call to cpu_percent() always returns 0.0; prime it so the
    # user's first reading is real.
    if _PSUTIL_AVAILABLE:
        try:
            psutil.cpu_percent(interval=None)
        except Exception:  # noqa: BLE001
            pass

    while True:
        await asyncio.sleep(target_dt)
        if not ws_clients:
            continue
        msg = {
            "type": "resources",
            "available": _PSUTIL_AVAILABLE,
            "tabs": len(tabs),
            "viewers": len(ws_clients),
            "rates": {tid: t.data_rate_hz for tid, t in tabs.items()},
        }
        # Decay the per-tab Hz estimate when a sender goes quiet so the
        # panel doesn't show a stale reading forever.
        now = perf_counter()
        for t in tabs.values():
            if t._last_rx_ts and (now - t._last_rx_ts) > 3.0:
                t.data_rate_hz = 0.0
        if _PSUTIL_AVAILABLE:
            try:
                cpu = psutil.cpu_percent(interval=None)
                vm = psutil.virtual_memory()
                msg["cpu"] = float(cpu)
                msg["mem_used_mb"] = (vm.total - vm.available) / (1024 * 1024)
                msg["mem_total_mb"] = vm.total / (1024 * 1024)
            except Exception as exc:  # noqa: BLE001
                msg["available"] = False
                msg["error"] = str(exc)
        await broadcast_text_all(msg)


###############################
# Tab lifecycle #
###############################

def _new_tab_id() -> str:
    return "tab_" + uuid.uuid4().hex[:8]


async def create_bind_me_tab():
    t = Tab(
        id=BIND_ME_ID,
        name=BIND_ME_NAME,
        mode="bind",
        endpoint=f"*:{ZMQ_DEFAULT_PORT}",
    )
    tabs[t.id] = t
    _open_tab_sockets(t)
    t.receiver_task = asyncio.create_task(zmq_receiver(t))


async def create_connect_tab(
    name: str, endpoint: str, *, tab_id: Optional[str] = None, persist: bool = True
) -> Tab:
    tid = tab_id or _new_tab_id()
    label = endpoint
    try:
        _, label = _normalize_connect_target(endpoint)
    except Exception:  # noqa: BLE001
        pass
    display_name = name.strip() or label
    t = Tab(
        id=tid,
        name=display_name,
        mode="connect",
        endpoint=label,
    )
    tabs[t.id] = t
    _open_tab_sockets(t)
    t.receiver_task = asyncio.create_task(zmq_receiver(t))
    # If the client at the other end is already running and only called
    # initialize_plots() once at its startup, this nudges it to resend
    # the cached config so the new tab populates without a script restart.
    asyncio.create_task(_request_config_resend(t))
    if persist:
        save_persisted_tabs()
    await broadcast_tab_list()
    return t


async def delete_tab(tab_id: str):
    if tab_id == BIND_ME_ID:
        return
    t = tabs.pop(tab_id, None)
    if t is None:
        return
    await _cancel_task(t.receiver_task)
    await _cancel_task(t.monitor_task)
    _close_tab_sockets(t)
    # Move any viewers off this tab back to bind_me on the browser side;
    # server tells them via tab_removed + they re-subscribe.
    for ws in list(ws_tab.keys()):
        if ws_tab.get(ws) == tab_id:
            ws_tab[ws] = BIND_ME_ID
    save_persisted_tabs()
    await broadcast_text_all({"type": "tab_removed", "id": tab_id})


async def rename_tab(tab_id: str, new_name: str):
    if tab_id == BIND_ME_ID:
        # bind_me is fixed; silently ignore.
        return
    t = tabs.get(tab_id)
    if t is None:
        return
    t.name = new_name.strip() or t.endpoint
    save_persisted_tabs()
    await broadcast_tab(tab_id)


async def _request_config_resend(tab: "Tab"):
    """Nudge a still-running client to re-send its initialize_plots() payload.

    The common scenario: the server crashed (or was restarted) mid-session
    and lost the plot config it received the first time the client called
    ``initialize_plots()``. The client is still happily streaming data,
    but the new server has nothing to plot it on. This sends a
    ``{"type": "resend_config"}`` control event over the tab's PUSH
    socket; the client's poll_controls() loop intercepts it and re-sends
    the cached config so the plot picks back up without the user having
    to restart their script.

    Retries over a ~10 s window because:
      * the client's PULL socket may need a moment to auto-reconnect to
        the freshly bound PUSH socket — especially over a WAN/SSH link;
      * a slow user loop may only call poll_controls() once per second,
        so the message can sit unread in the PULL queue for a while;
      * the client may not be running at all (no peer), in which case
        the queued message is just dropped when the next reconnect happens.
    Stops early once tab.initialized flips True (the client answered).
    """
    schedule = (0.3, 0.7, 1.5, 2.5, 5.0)  # cumulative ~10 s
    started_initialized = tab.initialized
    for i, delay in enumerate(schedule):
        await asyncio.sleep(delay)
        if tab.ctrl_sock is None:
            return
        if i > 0 and tab.initialized and not started_initialized:
            return
        try:
            await tab.ctrl_sock.send_json(
                {"type": "resend_config"}, flags=zmq.DONTWAIT
            )
            if DEBUG_TEXT_ENABLED:
                print(f"[{tab.id}] resend_config sent (attempt {i + 1}/{len(schedule)})")
        except (zmq.Again, zmq.ZMQError) as exc:
            if DEBUG_TEXT_ENABLED:
                print(
                    f"[{tab.id}] resend_config attempt {i + 1}/{len(schedule)}"
                    f" failed: {exc} (likely no peer connected yet)"
                )
    # If we asked the client to re-init but nothing came back, surface
    # a hint so the user knows where to look. Common causes: the client
    # is on rtplot < 0.4.6 (no resend_config handler), or its loop never
    # calls poll_controls(), or there's no client running at all.
    if not started_initialized and not tab.initialized:
        print(
            f"[{tab.id}] no config received after resend_config nudges."
            " Is the client running rtplot >= 0.4.6 and calling poll_controls()?"
        )


async def reconnect_tab(tab_id: str):
    """Close and reopen ``tab_id``'s sockets, restart its receiver task.

    The tab's buffer and plot config are preserved — if the sender on
    the other side is still running the same stream we avoid a visible
    flash to empty. After the sockets come back up we ask the (likely
    still-running) client to re-send its plot config so the connection
    recovers cleanly even if the server itself restarted in the
    meantime.
    """
    t = tabs.get(tab_id)
    if t is None:
        return
    await _cancel_task(t.receiver_task)
    await _cancel_task(t.monitor_task)
    t.monitor_task = None
    # _open_tab_sockets closes first, then reopens. Status gets set to
    # "idle" on success or "error" + a message on bind/connect failure.
    _open_tab_sockets(t)
    # Reset the data-rate estimate so a stale Hz doesn't mislead the
    # resources panel until new samples arrive.
    t.data_rate_hz = 0.0
    t._last_rx_ts = 0.0
    t.receiver_task = asyncio.create_task(zmq_receiver(t))
    asyncio.create_task(_request_config_resend(t))
    await broadcast_tab(tab_id)


###############################
# HTTP / WebSocket handlers #
###############################

def _read_static_asset(name: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "static", name)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


# Loaded once at import time so per-request cost is just the send.
_INDEX_HTML = _read_static_asset("index.html")


async def handle_index(request):
    return web.Response(
        text=_INDEX_HTML,
        content_type="text/html",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


async def handle_ws(request):
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(request)
    ws_clients.add(ws)
    ws_tab[ws] = BIND_ME_ID  # default until client sends tab_subscribe
    await broadcast_peer_count()
    try:
        # Initial sync: tab list. The browser picks an active tab and
        # sends a tab_subscribe; we respond with that tab's config.
        await ws_send_text(ws, {"type": "tabs", "tabs": tabs_public()})

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                ptype = payload.get("type")

                if ptype == "tab_subscribe":
                    tid = payload.get("id")
                    if not tid or tid not in tabs:
                        continue
                    ws_tab[ws] = tid
                    t = tabs[tid]
                    await ws_send_text(
                        ws,
                        {
                            "type": "zmq_status",
                            "mode": t.mode,
                            "target": t.endpoint,
                        },
                    )
                    if t.config_message is not None:
                        await ws_send_text(ws, t.config_message)
                        if t.display_values:
                            await ws_send_text(
                                ws,
                                {
                                    "type": "display_update",
                                    "tab": t.id,
                                    "values": dict(t.display_values),
                                },
                            )
                        snap = make_snapshot_message(t)
                        if snap is not None:
                            await ws_send_bytes(ws, snap)
                    else:
                        await ws_send_text(
                            ws, {"type": "no_config", "tab": t.id}
                        )

                elif ptype == "tab_create":
                    name = str(payload.get("name", "")).strip()
                    endpoint = str(payload.get("endpoint", "")).strip()
                    if not endpoint:
                        continue
                    await create_connect_tab(name, endpoint)

                elif ptype == "tab_rename":
                    tid = payload.get("id")
                    new_name = str(payload.get("name", "")).strip()
                    if tid and new_name:
                        await rename_tab(tid, new_name)

                elif ptype == "tab_delete":
                    tid = payload.get("id")
                    if tid and tid != BIND_ME_ID:
                        await delete_tab(tid)

                elif ptype == "tab_reconnect":
                    tid = payload.get("id")
                    if tid:
                        await reconnect_tab(tid)

                elif ptype == "control_button":
                    btn_id = payload.get("id")
                    tid = ws_tab.get(ws, BIND_ME_ID)
                    t = tabs.get(tid)
                    if btn_id and t is not None:
                        await send_control_event(
                            t, {"type": "button", "id": btn_id}
                        )

                elif ptype == "control_slider":
                    sid = payload.get("id")
                    try:
                        value = float(payload.get("value", 0.0))
                    except (TypeError, ValueError):
                        value = 0.0
                    tid = ws_tab.get(ws, BIND_ME_ID)
                    t = tabs.get(tid)
                    if sid and t is not None:
                        t.slider_values[sid] = value
                        await send_control_event(
                            t, {"type": "slider", "id": sid, "value": value}
                        )
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        _remove_ws(ws)
        await broadcast_peer_count()
    return ws


# ------------------------------------------------------------------ snapshot
# GET /snapshot.html returns a self-contained static HTML file that
# reproduces the currently active tab's plot visually.

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


try:
    _UPLOT_JS = _read_static_asset("uPlot.iife.min.js")
    _UPLOT_CSS = _read_static_asset("uPlot.min.css")
except Exception as _exc:  # noqa: BLE001
    _UPLOT_JS = f"/* uPlot load failed: {_exc} */"
    _UPLOT_CSS = ""


def _build_snapshot_html(tab: Tab, animate: bool) -> str:
    """Serialize the given tab's plot state into a static snapshot."""
    num_points = tab.num_datapoints_in_plot
    num_traces = tab.num_traces
    if num_traces == 0 or not tab.initialized or tab.buffer is None:
        return (
            "<!doctype html><html><body style='font-family:sans-serif;padding:32px'>"
            "<h1>rtplot snapshot</h1>"
            f"<p>No plot has been initialized on tab <b>{tab.name}</b> yet"
            " &mdash; start your client and call <code>initialize_plots()</code>"
            " first, then hit <code>/snapshot.html</code> again.</p></body></html>"
        )
    li = tab.li
    lo = max(0, li - num_points)
    hi = li

    plots = []
    cfg = tab.config_dict or OrderedDict()
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

    trace_data = []
    arr = tab.buffer[:num_traces, lo:hi]
    for i in range(num_traces):
        trace_data.append([float(v) for v in arr[i]])

    payload = {
        "plots": plots,
        "num_samples": int(hi - lo),
        "trace_data": trace_data,
        "animate": bool(animate),
    }
    html = _SNAPSHOT_TEMPLATE
    html = html.replace("__UPLOT_CSS__", _UPLOT_CSS)
    html = html.replace("__UPLOT_JS__", _UPLOT_JS)
    html = html.replace("__SNAPSHOT_JSON__", json.dumps(payload))
    return html


async def handle_snapshot(request):
    animate = request.query.get("animate") == "1"
    tid = request.query.get("tab") or BIND_ME_ID
    t = tabs.get(tid) or tabs[BIND_ME_ID]
    html = _build_snapshot_html(t, animate=animate)
    return web.Response(
        text=html,
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


###############################
# Lifecycle #
###############################

async def on_startup(app):
    await create_bind_me_tab()

    # Persisted tabs (user-created connect tabs) from disk.
    for entry in load_persisted_tabs():
        try:
            await create_connect_tab(
                entry["name"], entry["endpoint"], tab_id=entry["id"], persist=False
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[rtplot] could not restore tab {entry.get('id')}: {exc}")

    # -p CLI shortcut: spin up an ephemeral connect tab too.
    if args.pi_ip:
        label = args.pi_ip
        try:
            _, label = _normalize_connect_target(args.pi_ip)
        except Exception:  # noqa: BLE001
            pass
        existing = next(
            (
                t for t in tabs.values()
                if t.mode == "connect" and t.endpoint == label
            ),
            None,
        )
        if existing is None:
            await create_connect_tab(f"CLI {label}", args.pi_ip, persist=False)

    app["ws_task"] = asyncio.create_task(ws_pusher())
    app["display_task"] = asyncio.create_task(display_pusher())
    app["resources_task"] = asyncio.create_task(resources_pusher())


async def on_cleanup(app):
    for key in ("ws_task", "display_task", "resources_task"):
        await _cancel_task(app.get(key))
    for t in list(tabs.values()):
        await _cancel_task(t.receiver_task)
        await _cancel_task(t.monitor_task)
        _close_tab_sockets(t)
    for ws in list(ws_clients):
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
    zmq_ctx.term()


###############################
# Cookie-based password auth #
###############################

# A single shared password unlocks the UI for every browser. We deliberately
# don't model users: the browser's native Basic-Auth popup forces a username
# field, which was confusing — one password is enough for LAN deployments.
# On successful POST /login, the server mints a random session token, stashes
# it in an in-memory set, and drops it as an HttpOnly cookie. All other
# routes (including the WebSocket upgrade) require that cookie.
import hmac as _hmac
import secrets as _secrets

SESSION_COOKIE = "rtplot_session"
_AUTH_REQUIRED = AUTH_PASSWORD is not None
_AUTH_EXPECTED = AUTH_PASSWORD.encode("utf-8") if AUTH_PASSWORD else None
_valid_tokens: set = set()


_LOGIN_HTML = """<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<title>rtplot \u2014 sign in</title>
<style>
  html, body { margin: 0; padding: 0; min-height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #eef1f5; color: #222; }
  body { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  form { background: #fff; border: 1px solid #d2d8e0; border-radius: 8px; padding: 28px 32px; box-shadow: 0 6px 24px rgba(30,40,60,0.08); width: 320px; }
  h1 { margin: 0 0 6px 0; font-size: 20px; color: #1d3566; }
  p { margin: 0 0 18px 0; color: #666; font-size: 13px; }
  label { display: block; font-size: 12px; color: #555; margin-bottom: 6px; }
  input[type=password] { width: 100%; box-sizing: border-box; padding: 9px 10px; font-size: 14px; border: 1px solid #bfc7d2; border-radius: 4px; font-family: inherit; }
  input[type=password]:focus { outline: none; border-color: #2a5db0; box-shadow: 0 0 0 2px rgba(42,93,176,0.15); }
  button { margin-top: 14px; width: 100%; padding: 10px; font-size: 14px; border: none; border-radius: 4px; background: #2a5db0; color: #fff; cursor: pointer; font-weight: 600; }
  button:hover { background: #244f95; }
  .err { background: #fce8e8; color: #a11; border: 1px solid #f0c2c2; padding: 8px 10px; border-radius: 4px; font-size: 13px; margin-bottom: 14px; }
</style>
</head>
<body>
<form method=\"post\" action=\"/login\" autocomplete=\"on\">
  <h1>rtplot</h1>
  <p>Enter the shared password to continue.</p>
  __ERROR_BLOCK__
  <label for=\"pw\">Password</label>
  <input id=\"pw\" type=\"password\" name=\"password\" autofocus required />
  <button type=\"submit\">Sign in</button>
</form>
</body>
</html>
"""


def _render_login_page(error: bool = False) -> str:
    err = '<div class="err">Wrong password. Try again.</div>' if error else ""
    return _LOGIN_HTML.replace("__ERROR_BLOCK__", err)


def _has_valid_session(request) -> bool:
    tok = request.cookies.get(SESSION_COOKIE)
    return bool(tok) and tok in _valid_tokens


async def handle_login(request):
    # GET  /login  -> render form
    # POST /login  -> check password, set cookie on success
    if request.method == "GET":
        if _has_valid_session(request):
            raise web.HTTPFound("/")
        return web.Response(
            text=_render_login_page(),
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    if not _AUTH_REQUIRED:
        raise web.HTTPFound("/")
    data = await request.post()
    supplied = (data.get("password") or "").encode("utf-8")
    if _hmac.compare_digest(supplied, _AUTH_EXPECTED or b""):
        token = _secrets.token_urlsafe(32)
        _valid_tokens.add(token)
        resp = web.HTTPFound("/")
        resp.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,
            samesite="Lax",
            max_age=30 * 24 * 3600,  # 30 days
            path="/",
        )
        raise resp
    return web.Response(
        text=_render_login_page(error=True),
        content_type="text/html",
        status=401,
        headers={"Cache-Control": "no-store"},
    )


async def handle_logout(request):
    tok = request.cookies.get(SESSION_COOKIE)
    if tok:
        _valid_tokens.discard(tok)
    resp = web.HTTPFound("/login")
    resp.del_cookie(SESSION_COOKIE, path="/")
    raise resp


@web.middleware
async def session_auth_middleware(request, handler):
    if not _AUTH_REQUIRED:
        return await handler(request)
    path = request.path
    # Login page and its form post must stay open; the uPlot assets that
    # the main page pulls in are gated too, which is consistent with the
    # rest of the UI.
    if path == "/login" or path == "/logout":
        return await handler(request)
    if _has_valid_session(request):
        return await handler(request)
    # WebSocket upgrade can't follow a redirect — respond with 401 so the
    # browser-side reconnect loop surfaces a clear error.
    if path == "/ws":
        return web.Response(status=401, text="Not signed in.\n")
    raise web.HTTPFound("/login")


def build_app():
    middlewares = [session_auth_middleware] if _AUTH_REQUIRED else []
    app = web.Application(middlewares=middlewares)
    app.router.add_get("/", handle_index)
    app.router.add_get("/login", handle_login)
    app.router.add_post("/login", handle_login)
    app.router.add_get("/logout", handle_logout)
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
    if _AUTH_REQUIRED:
        print("  auth: shared password required (browsers see a login page)")
    else:
        print("  auth: none (set --password or RTPLOT_PASSWORD to gate the UI)")
    for ip in _detect_lan_ips():
        print(f"  also reachable at  http://{ip}:{args.port}")
    is_wsl = "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ
    if is_wsl:
        print(
            "  (WSL detected: open the URL above in your Windows browser;"
            " if localhost doesn't work, use one of the LAN IPs)"
        )
    # webbrowser.open() can hang under WSL on xdg-open / D-Bus; skip there.
    if not args.no_browser and not is_wsl:
        import threading

        def _open():
            try:
                webbrowser.open(f"http://localhost:{args.port}")
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_open, daemon=True).start()
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
