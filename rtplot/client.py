import zmq
import numpy as np
import time
from collections import OrderedDict, namedtuple
import csv
from typing import List

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
# Local plot save config #
###########################
local_log_file = None
csv_writer = None

############################
# PyQTgraph Configuration #
###########################

#Create definitions for categories
SENDING_PLOT_UPDATE = "0"
SENDING_DATA = "1"
SAVE_PLOT = "3"
SENDING_DISPLAY = "4"

#Lightweight result type returned by poll_controls()
ControlState = namedtuple("ControlState", ["values", "buttons"])

def local_plot():
    """Send data to a plot in the same computer"""

    local_address = "tcp://127.0.0.1:5555"
    configure_ip(ip = local_address)

def plot_to_neurobionics_tv():
    """Send data to a plot in the same computer"""

    tv_computer_address = "tcp://141.212.77.23:5555"
    configure_ip(ip = tv_computer_address)
    

def configure_port(new_port:int):
    """Change the port

    Keyword Arguments:
    new_port -- int four digit number that represents the port

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

def create_local_log(plot_desc_dict:List[dict], log_name:str=None):
    """Create a current log file based on the data that is sent"""
    global local_log_file
    global csv_writer
    
    #If we have a local log file, then delete it
    if local_log_file is not None:
        local_log_file.close()
        local_log_file = None

    # Create a new log file with a csv writter object which uses the log_name
    # argument in conjunction with the timestamp to create a unique log file
    local_log_file = open(f"{log_name}_{time.time()}.csv", 'w', newline='')
    csv_writer = csv.writer(local_log_file, delimiter=',',
                             quotechar='"', quoting=csv.QUOTE_MINIMAL)

    # Add the header to the csv file based on the plot description
    csv_writer.writerow(["Time"] + [name for plot in plot_desc_dict.values() for name in plot["names"]])
    


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
    
    #If we have a local log file, then save the data
    if local_log_file is not None:
        csv_writer.writerow([time.time()] + A.flatten().tolist())


def initialize_plots(plot_descriptions=1, log_name=None):
    """Send a json description of desired plot
    Inputs
    ------
    plot_description: list of names or list of plot descriptions dictionaries
        list of names - the names of the plots that you want to create
        list of plot descriptions - the dictionary of the plot descriptions
    log_name: string, name of the file that will be stored locally
    """
    
    global local_log_file
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
        
        #Process list of dics
        elif isinstance(plot_descriptions[0],dict):
            plot_desc_dict = OrderedDict()
            for i,plot_desc in enumerate(plot_descriptions):
                plot_desc_dict["plot{}".format(i)] = plot_desc
    
    #Throw error
    else:
        raise TypeError("Incorrect usage of initialize_plots, verify github for usage")
    
    #Send the category
    socket.send_string(SENDING_PLOT_UPDATE)

    #Send the description
    socket.send_json(plot_desc_dict)

    #If we have a log name, then save the log
    if log_name is not None:
        create_local_log(log_name)


def save_plot(log_name):
    """
    Tell the server to store the data that has been sent for the latest
    plot configuration

    Keyword Arguments
    log_name -- string, name of the file that will be stored

    """
    # Indicate that we will send a plot save requset
    socket.send_string(SAVE_PLOT)

    # Send the save plot name
    socket.send_string(log_name)

    # Flush the file to ensure that all data is written
    local_log_file.flush()


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