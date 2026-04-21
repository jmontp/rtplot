import zmq
import numpy as np
import time
from collections import OrderedDict, namedtuple
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

###################
# ZMQ Networking #
##################

#Get the context for networking setup
context = zmq.Context()

#Socket to talk to server
#Using the pub - sub paradigm to communicate
socket = context.socket(zmq.PUB)

#Return channel socket: the server PUSHes control events (button clicks and
# slider values) to us over a second ZMQ socket whose endpoint tracks the
# main data socket (default port = data port + 1).
control_socket = context.socket(zmq.PULL)
control_socket.setsockopt(zmq.RCVHWM, 1000)
#Non-blocking local state for controls, drained on each poll_controls() call
_control_slider_values = {}
_control_button_events = []

# Cached payload of the most recent initialize_plots() call. The server
# uses this to recover from its own crashes: when its tab loses the
# config, it pushes a "resend_config" control event over the return
# channel, and poll_controls() re-PUBs this dict so the plot reattaches
# without the user restarting their script. None until first call.
plot_desc_dict = None

#Global variable to keep track of last connected address
# default is fixed publisher mode, therefore you don't connect
# to an address
prev_address = None

#This address will be used to bind any incoming subscriber on port 5555
# to the publisher
bind_address = "tcp://*:5555"
#Matching bind address for the return (control) channel, default port+1.
control_bind_address = "tcp://*:5556"
#Current data port, so configure_port / configure_ip can derive the control port.
current_data_port = 5555

# The subscriber or the publisher must be fixed
# set which is which here
known_pi_address_prev = True
# Add flag to indicate if we ever failed to bind
failed_bind = False

## Define the default behaviour of the pi

# Assume that you know the ip address of the pi
if known_pi_address_prev:

    try:
        #Attempt to bind to incoming addresses on the port
        socket.bind(bind_address)
        control_socket.bind(control_bind_address)

        #Sleep so that the subscriber can join
        time.sleep(0.2)

    #If you cannot connect to the socket, alert user and continue
    except zmq.error.ZMQError as e:
        failed_bind = True

        print("rtplot.client: Could not connect to default address '{}'".format(e))
        print("               There might be another client running")
        print("               This is fine if doing local plots")

# Secondary default behavior is that you know the ip address
# of the computer that will plot
else:
    #Connect to the computer that will plot information
    socket.connect(prev_address)


############################
# PyQTgraph Configuration #
###########################

#Create definitions for categories. "3" used to be SAVE_PLOT (parquet
#output); that feature has been removed. The numeric value is reserved
#so the server still recognizes it and quietly ignores messages sent
#by any pre-0.3 client still in the wild.
SENDING_PLOT_UPDATE = "0"
SENDING_DATA = "1"
SENDING_DISPLAY = "4"

#Lightweight result type returned by poll_controls()
ControlState = namedtuple("ControlState", ["values", "buttons"])


##########################################
# Typed plot / controls configuration API #
##########################################
#
# These dataclasses are an alternative to the dict-based configuration
# accepted by initialize_plots(). Both APIs coexist — the typed form
# serializes to the exact same on-the-wire dict, so the server is
# unaware of which one the caller used.
#
#   client.initialize_plots([
#       client.Plot(names=["signal"], yrange=(-6, 6), title="demo"),
#       client.ControlsRow([client.Button("reset", "Reset")]),
#   ])
#
# is equivalent to the classic:
#
#   client.initialize_plots([
#       {"names": ["signal"], "yrange": [-6, 6], "title": "demo"},
#       {"controls": [{"type": "button", "id": "reset", "label": "Reset"}]},
#   ])


def _drop_none(d):
    # Wire format treats missing keys as "use default"; None would
    # JSON-serialize to null which the server wouldn't handle.
    return {k: v for k, v in d.items() if v is not None}


def _range_to_list(r):
    # yrange/xrange go over the wire as JSON lists.
    return list(r) if r is not None else None


@dataclass
class Plot:
    """A single plot with optional styling.

    All fields beyond ``names`` are optional and mirror the styled-plot
    dict keys documented in ``docs/api.md``.
    """
    names: List[str]
    colors: Optional[List[str]] = None
    line_style: Optional[List[str]] = None
    line_width: Optional[float] = None
    title: Optional[str] = None
    xlabel: Optional[str] = None
    ylabel: Optional[str] = None
    yrange: Optional[Tuple[float, float]] = None
    xrange: Optional[int] = None
    height: Optional[float] = None

    def to_dict(self):
        return _drop_none({
            "names": list(self.names),
            "colors": list(self.colors) if self.colors is not None else None,
            "line_style": list(self.line_style) if self.line_style is not None else None,
            "line_width": self.line_width,
            "title": self.title,
            "xlabel": self.xlabel,
            "ylabel": self.ylabel,
            "yrange": _range_to_list(self.yrange),
            "xrange": self.xrange,
            "height": self.height,
        })


@dataclass
class Button:
    id: str
    label: str
    color: Optional[str] = None
    height: Optional[float] = None

    def to_dict(self):
        return _drop_none({
            "type": "button", "id": self.id, "label": self.label,
            "color": self.color, "height": self.height,
        })


@dataclass
class Slider:
    id: str
    label: str
    min: float
    max: float
    value: float = 0.0
    step: Optional[float] = None
    format: Optional[str] = None
    color: Optional[str] = None
    height: Optional[float] = None

    def to_dict(self):
        return _drop_none({
            "type": "slider", "id": self.id, "label": self.label,
            "min": self.min, "max": self.max, "value": self.value,
            "step": self.step, "format": self.format,
            "color": self.color, "height": self.height,
        })


@dataclass
class Dial:
    id: str
    label: str
    min: float
    max: float
    value: float = 0.0
    step: Optional[float] = None
    sensitivity: Optional[float] = None
    format: Optional[str] = None
    color: Optional[str] = None
    height: Optional[float] = None

    def to_dict(self):
        return _drop_none({
            "type": "dial", "id": self.id, "label": self.label,
            "min": self.min, "max": self.max, "value": self.value,
            "step": self.step, "sensitivity": self.sensitivity,
            "format": self.format, "color": self.color,
            "height": self.height,
        })


@dataclass
class Display:
    id: str
    label: str
    format: Optional[str] = None
    height: Optional[float] = None

    def to_dict(self):
        return _drop_none({
            "type": "display", "id": self.id, "label": self.label,
            "format": self.format, "height": self.height,
        })


@dataclass
class Text:
    id: str
    label: str
    value: str = ""
    height: Optional[float] = None

    def to_dict(self):
        return _drop_none({
            "type": "text", "id": self.id, "label": self.label,
            "value": self.value, "height": self.height,
        })


@dataclass
class ControlsRow:
    """A row of control widgets, rendered in place of a plot."""
    controls: List[Union[Button, Slider, Dial, Display, Text, dict]] = field(default_factory=list)

    def to_dict(self):
        return {"controls": [
            c.to_dict() if hasattr(c, "to_dict") else c
            for c in self.controls
        ]}


def local_plot():
    """Send data to a plot in the same computer"""

    local_address = "tcp://127.0.0.1:5555"
    configure_ip(ip = local_address)

def configure_port(new_port:int):
    """Rebind the local publisher on ``new_port`` (bind mode only).

    This only affects the *bind* path — it re-opens the client's PUB
    socket on a new local port and expects the server to connect
    inbound. If you're in the usual "client connects to a remote
    server" mode, use ``configure_ip(host_or_ip, ...)`` with the
    ``host:port`` form instead; ``configure_port`` has no effect on
    the connect target.

    Keyword Arguments:
    new_port -- int, the local port to bind the data PUB socket on.
                The control return channel automatically uses the next
                port (``new_port + 1``).
    """
    #Create the new bind address
    new_bind_address = f"tcp://*:{new_port}"

    #Run the ip configuration
    configure_ip(known_pi_address=True, new_bind_address=new_bind_address)


def _parse_host_port(address, default_port=5555):
    """Split a 'tcp://host:port' or 'host[:port]' string into (host, port)."""
    s = address
    if s.startswith("tcp://"):
        s = s[len("tcp://"):]
    if s.startswith("*:"):
        host = "*"
        port_str = s[2:]
    elif ":" in s:
        host, port_str = s.rsplit(":", 1)
    else:
        host, port_str = s, str(default_port)
    try:
        port = int(port_str)
    except ValueError:
        port = default_port
    return host, port


def configure_ip(ip = None, known_pi_address = False, new_bind_address = None):
    """Connect to a subscriber at a specific IP address

    Inputs
    ------
    ip: Ip address or string formated to protocol:address:port
    known_pi_address: bool, if true, the plot server will connect to the client
    """

    ## Get the current address
    global prev_address
    global known_pi_address_prev
    global bind_address
    global control_bind_address
    global current_data_port

    ## Disconnect from the previous configuration
    # if known_pi_address_prev and not failed_bind:
    #     socket.unbind(bind_address)
    # elif prev_address is not None:
    #     socket.disconnect(prev_address)

    ## Format the incomming string
    #If you just get the ip address and no port, format correctly
    connect_address = None
    control_connect_address = None

    if ip is not None:
        num_colons = ip.count(':')

        #You only got the ip address
        if num_colons == 0:
            connect_address = "tcp://{}:5555".format(ip)
        #You got ip address and port
        elif num_colons == 1:
            connect_address = "tcp://{}".format(ip)
        #You got everything
        else:
            connect_address = ip

        host, data_port = _parse_host_port(connect_address)
        control_connect_address = f"tcp://{host}:{data_port + 1}"


    ## Connect to new configuration
    if(known_pi_address):

        if(new_bind_address is not None):
            print(f"rtplot.client: Connecting to address {new_bind_address}")
            socket.bind(new_bind_address)
            _, data_port = _parse_host_port(new_bind_address)
            new_control_bind = f"tcp://*:{data_port + 1}"
            control_socket.bind(new_control_bind)
            bind_address = new_bind_address
            control_bind_address = new_control_bind
            current_data_port = data_port
        else:
            #Bind incomming computers to the pi
            print(f"rtplot.client: Connecting to address {bind_address}")
            socket.bind(bind_address)
            control_socket.bind(control_bind_address)

        prev_address = None

    else:
        #Connect to the computer that will do the plotting
        print(f"rtplot.client: Connecting to address {connect_address}")
        socket.connect(connect_address)
        if control_connect_address is not None:
            control_socket.connect(control_connect_address)
        prev_address = connect_address

    #Remember the last configuration you had
    known_pi_address_prev = known_pi_address

    #Sleep so that the connection can be established
    time.sleep(1)

def send_array(A, flags=0, copy=True, track=False):
    """send a numpy array with metadata
    Inputs
    ------
    A: (subplots,dim) np array to transmit
        subplots - the amount of subplots that are
                   defined in the current plot
        dim - the amount of data that you want to plot.
              This is not fixed
    """
    #If you get a float value, convert it to a numpy array
    if(isinstance(A,float) or isinstance(A,list)):
        A = np.array(A).reshape(-1,1)
    #If array is one dimensional, reshape to two dimensions
    if(len(A.shape) ==1):
        A = A.reshape(-1,1)
    #Create dict to reconstruct array
    md = dict(
        dtype = str(A.dtype),
        shape = A.shape,
    )

    #Send category
    socket.send_string(SENDING_DATA)
    #Send json description
    socket.send_json(md, flags | zmq.SNDMORE)
    #Send array
    socket.send(A, flags, copy=copy, track=track)


def initialize_plots(plot_descriptions=1):
    """Send a json description of desired plot.

    Inputs
    ------
    plot_description:
        - int N: one plot with N anonymous traces
        - str: one plot with a single named trace
        - dict: one plot with full styling
        - list of str: one plot, one trace per name
        - list of list of str: one plot per sublist
        - list of dict: multiple plots, each with full styling
    """
    global plot_desc_dict

    #Process int inputs
    if isinstance(plot_descriptions,int):
        plot_desc_dict = OrderedDict()
        plot_desc_dict["plot0"] = {"names":["Trace {}".format(i) for i in range (plot_descriptions)]}

    #Process string inputs
    elif isinstance(plot_descriptions, str):
        plot_desc_dict = OrderedDict()
        plot_desc_dict["plot0"] = {"names":[plot_descriptions]}

    #Process dictionary inputs
    elif isinstance(plot_descriptions, dict):
        plot_desc_dict = OrderedDict()
        plot_desc_dict["plot0"] = plot_descriptions

    #Process typed inputs (Plot / ControlsRow) passed alone
    elif hasattr(plot_descriptions, "to_dict"):
        plot_desc_dict = OrderedDict()
        plot_desc_dict["plot0"] = plot_descriptions.to_dict()

    #Process lists of things
    elif isinstance(plot_descriptions, list):

        #Process list of strings
        if isinstance(plot_descriptions[0],str):
            plot_desc_dict = OrderedDict()
            plot_desc_dict["plot0"] = {"names":plot_descriptions}

        # Prcoess list with lists
        if isinstance(plot_descriptions[0],list):
            plot_desc_dict = OrderedDict()
            for i,plot_desc in enumerate(plot_descriptions):
                plot_desc_dict["plot{}".format(i)] = {"names":plot_desc}

        #Process list of dicts or typed objects (Plot / ControlsRow),
        # including mixed lists — anything exposing .to_dict() is normalized
        # to the wire dict form.
        elif isinstance(plot_descriptions[0],dict) or hasattr(plot_descriptions[0], "to_dict"):
            plot_desc_dict = OrderedDict()
            for i,plot_desc in enumerate(plot_descriptions):
                if hasattr(plot_desc, "to_dict"):
                    plot_desc = plot_desc.to_dict()
                plot_desc_dict["plot{}".format(i)] = plot_desc

    #Throw error
    else:
        raise TypeError("Incorrect usage of initialize_plots, verify github for usage")

    #Send the category
    socket.send_string(SENDING_PLOT_UPDATE)

    #Send the description
    socket.send_json(plot_desc_dict)


def set_display(display_id: str, value):
    """Push a single display box value to the browser.

    Display boxes are read-only UI elements declared via a 'controls' row in
    initialize_plots(). Call this method from your loop to update their
    displayed value; the server rebroadcasts dirty values to all connected
    browsers at ~30 Hz.

    Accepts either numeric values (for 'display' elements) or strings
    (for 'text' elements). Everything else is coerced to str().
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        payload_value = float(value)
    else:
        payload_value = str(value)
    socket.send_string(SENDING_DISPLAY, zmq.SNDMORE)
    socket.send_json({"id": str(display_id), "value": payload_value})


def poll_controls():
    """Drain the return channel non-blocking and return current control state.

    Returns a ControlState(values, buttons) where:
      - values: dict of {slider_id: float} with the latest value of every
        slider the server has told us about since process start.
      - buttons: list of button ids that fired since the previous poll
        (cleared after this call).

    Call this from your tight loop before computing the next sample.

    Also transparently handles ``resend_config`` requests from the server:
    if the server crashed and reconnected (or the user clicked the
    Reconnect button on a tab), it asks us to re-publish the cached
    initialize_plots() payload so the plot rewires without the user
    restarting their script. The request is consumed silently — the
    returned ControlState only ever contains slider/button events.
    """
    global _control_button_events
    while True:
        try:
            event = control_socket.recv_json(flags=zmq.NOBLOCK)
        except zmq.Again:
            break
        except zmq.ZMQError:
            break
        evtype = event.get("type")
        if evtype == "button":
            _control_button_events.append(event.get("id"))
        elif evtype == "slider":
            _control_slider_values[event.get("id")] = float(event.get("value", 0.0))
        elif evtype == "resend_config":
            if plot_desc_dict is not None:
                socket.send_string(SENDING_PLOT_UPDATE)
                socket.send_json(plot_desc_dict)
                # Surface a one-line confirmation so the user can see in
                # their script log that the recovery handshake worked.
                # If they never see this after clicking Reconnect, the
                # PUSH/PULL channel back from the server isn't wired —
                # check that poll_controls() is actually being called.
                print("rtplot.client: resent cached initialize_plots() config")

    buttons = _control_button_events
    _control_button_events = []
    return ControlState(values=dict(_control_slider_values), buttons=buttons)


def save_snapshot(path, server_url=None, animate=False, timeout=5.0):
    """Download a static HTML snapshot of the current plot to ``path``.

    The server exposes a ``/snapshot.html`` endpoint that renders the
    current plot state as a self-contained HTML file with uPlot's JS +
    CSS inlined plus the most recent window of trace data. The result
    opens in any browser offline and looks pixel-identical to what the
    live tab was showing. Ideal for committing reproducible example
    previews to a repo or emailing a static "here's what I was seeing"
    artifact.

    Parameters
    ----------
    path : str
        Local filename to write the HTML to (e.g. ``"snapshot.html"``).
    server_url : str, optional
        Base URL of the rtplot browser server. Defaults to
        ``http://localhost:8050`` — adjust if you started the server
        with a non-default ``--port`` or you're snapshotting a remote
        server. Accepts with or without scheme / trailing slash.
    animate : bool, optional
        If True, the snapshot HTML also embeds a small replay loop so
        the plot keeps scrolling smoothly in the browser (useful for
        gallery previews that benefit from visible motion).
    timeout : float, optional
        Seconds to wait for the HTTP GET to complete. Default 5.0.

    Returns
    -------
    str
        The absolute path the snapshot was written to.
    """
    import os as _os
    from urllib.request import urlopen as _urlopen

    base = server_url or "http://localhost:8050"
    base = base.strip().rstrip("/")
    if not base.lower().startswith(("http://", "https://")):
        base = "http://" + base
    url = base + "/snapshot.html" + ("?animate=1" if animate else "")

    with _urlopen(url, timeout=timeout) as resp:  # noqa: S310 — local HTTP to our own server
        body = resp.read()
    abs_path = _os.path.abspath(path)
    with open(abs_path, "wb") as fh:
        fh.write(body)
    return abs_path