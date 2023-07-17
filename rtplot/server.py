# Import communication
import zmq

# Import plotting
from pyqtgraph.Qt import QtGui, QtCore, QtWidgets
import pyqtgraph as pg

# Common imports
import numpy as np
import pandas as pd
import os
import time

# Get timer to calculate fps
from time import perf_counter

# Import argparse to handle different configurations
# of the plotter
import argparse

# Import date_time to save timestamps
import datetime

############################
# Command Line Arguments #
###########################

# Create command line arguments
parser = argparse.ArgumentParser(
    # help=("Plotter for real time data. By default it will accept plots, however"
    # "" )
)

# Add argument to enable bigger fonts
parser.add_argument(
    "-p",
    "--pi_ip",
    help=(
        "The IP address for the pi, if you don't add"
        " this it will default to 10.0.0.200"
    ),
    action="store",
    type=str,
)

# Add argument to enable bigger fonts
parser.add_argument(
    "-b",
    "--bigscreen",
    help="Increase fonts to print in the big screen",
    action="store_true",
)

# Add argument to create subplots in separate columns instead of rows
parser.add_argument(
    "-c",
    "--column",
    help="Create new plots in separate columns",
    action="store_false",
)

# Add argument to enable bigger fonts
parser.add_argument(
    "-d", "--debug", help="Add debug text output", action="store_true"
)

# Add argument to show user the options in the plotter
parser.add_argument(
    "-t",
    "--plot_config",
    help="Detail all the options that the plotter accepts",
    action="store_true",
)

# Add argument to skip every n datapoints
parser.add_argument(
    "-n",
    "--skip",
    help="Skip every n datapoints",
    action="store",
    type=int,
    default=1,
)

# Read in the arguments
args = parser.parse_args()

if args.plot_config is True:
    help_text = (
        "You can control the following things when calling"
        " client.initialize_plots() by passing in a dictionary:"
        "\n\r"
        "\n\r'names' - This defines the names of the traces."
        "The plot will have as many traces as names."
        "\n\r"
        "\n\r'colors' - Defines the colors for each trace. Follow"
        " documentation on how to specify color. Should have at least the same"
        " length as the number of traces."
        "\n\r"
        "\n\r'line_style' - Defines wheter or not a trace is dashed or not."
        "\n\r\t'-' - represents dashed line"
        "\n\r\t'' - emptry string (or any other string) represents a"
        "normal line"
        "\n\r"
        "\n\r'line_width' - Defines the width of the line. Expects an integer"
        "\n\r"
        "\n\r'title' - Sets the title to the plot"
        "\n\r"
        "\n\r'ylabel' - Sets the y label of the plot"
        "\n\r"
        "\n\r'xlabel' - Sets the x label of the plot"
        "\n\r"
        "\n\r'yrange' - Sets the range of values of y."
        " This provides a performance boost to the plotter"
        "\n\r\tExpects values as a iterable in the order [min, max]."
        " Example: [-2,2]"
        "\n\r"
        "\n\r'xrange' - Sets the number of datapoints that will be"
        " in the real time plotter at a given time. Expects values as a"
        " integer that describes how many datapoints are in the subplot."
        " Default is 200 datapoints"
        "\n\r"
        "\n\rYou only need to specify the things that you want, if the"
        " dictionary element is left out then the default value is used."
        "\n\r"
        
    )

    print(help_text)
    exit()

# If big screen mode is on, set font sizes big
if args.bigscreen:
    axis_label_style = {"font-size": "20pt"}
    title_style = {"size": "25pt"}
    # Accepts parameters into LegendItem constructor
    legend_style = {"labelTextSize": "14pt"}
    tick_size = 25

# Else set to normal size
else:
    axis_label_style = {"font-size": "10pt"}
    title_style = {"size": "14pt"}
    legend_style = {"labelTextSize": "8pt"}
    tick_size = 12

# Define if a new subplot is placed in a
# new row or columns
NEW_SUBPLOT_IN_ROW = args.column

# Define if debug text output is set on
DEBUG_TEXT_ENABLED = args.debug

# Define how many datapoints are skipped
SKIP_PLOT_DATAPOINTS = args.skip

###################
# ZMQ Networking #
##################

# Create connection layer
context = zmq.Context()

# Using the pub - sub paradigm
socket = context.socket(zmq.SUB)

# Current default is to connect to the neurobionics pi hotspot
# since that is the current use case
if args.pi_ip is not None:
    # Connect to the supplied IP address
    
    #If you have a colon, then the user indicated a port
    if args.pi_ip.count(":")  == 1:
        connect_string = f"tcp://{args.pi_ip}"    
    else:
        connect_string = f"tcp://{args.pi_ip}:5555"
    
    #Connect to that socket
    socket.connect(connect_string)
    print(f"Connected to {connect_string}")

# Default behavior, wait for people to connect to you
else:
    # Bind so that you can get more
    socket.bind("tcp://*:5555")
    print("Bounded every ip address on port :5555")

# Initialize subscriber
socket.setsockopt_string(zmq.SUBSCRIBE, "")


###############################
# Local Storage Configuration #
###############################

# Width of the window displaying the curve
# NUM_DATAPOINTS_IN_PLOT = 200
DEFAULT_NUM_DATAPOINTS_IN_PLOT = 200

# Num of entry buffers
MAX_LOCAL_STORAGE = 10000000

# Initial number of traces
INITIAL_NUM_TRACES = 50

# Storage buffer - This will take around 3.73 GB of ram
# Should last for 27 hours running at 100 Hz
local_storage_buffer = np.zeros((INITIAL_NUM_TRACES, MAX_LOCAL_STORAGE))

# Create an index to keep track where we are in the local storage buffer
li = DEFAULT_NUM_DATAPOINTS_IN_PLOT

# Set how many traces we have
local_storage_buffer_num_trace = 1

# Configure save path
PLOT_SAVE_PATH = "saved_plots/"

# We are going to use the traces per plot do add info to saved plots
# since this is set below, initialize to none
traces_per_plot = None
trace_labels = None
non_plot_labels = None

# Create button callback method
def save_current_plot(log_name=None):
    """
    Save the plot locally

    Keywork arguments
    log_name -- Name of the file that will be saved. If left None, the current
            time stamp will be used
    """

    # Set which trace goes in which plot on the last element of the column
    num_subplots = 0
    trace_names = []
    for i, (trace_name, subplot_index) in enumerate(trace_labels):
        # Add subplot index to last column
        local_storage_buffer[i, li] = subplot_index
        # Get the number of subplots
        num_subplots = max(subplot_index, num_subplots)
        # Add trace name
        trace_names.append(trace_name)
    
    # Set the non-plot labels to have a index of -1
    

    # Assign a new subplot for time
    num_traces = len(trace_labels)
    trace_names.append("Time(s)")
    local_storage_buffer[num_traces, li] = num_subplots + 1

    #Set the log name if it is not provided
    if log_name is None or log_name is False:

        # Set the plot name as the current time
        log_name = datetime.datetime.now()
        #Remove spaces for underscores for no real reason
        log_name = str(log_name).replace(" ", "_")
        # Remove colons from timestamp for windows file name compatibility
        log_name = log_name.replace(":", "-")

    #Add to the save path for the datafiles
    total_name = os.path.join(
        PLOT_SAVE_PATH, log_name + ".parquet"
    )
    
    # Create the dataframe object so that we can add info about the subplot
    #  names
    df = pd.DataFrame(
        local_storage_buffer[
            :local_storage_buffer_num_trace + len(non_plot_labels),
            num_datapoints_in_plot : li + 1
        ].T,
        columns=trace_names + non_plot_labels,
    )
    df.to_parquet(total_name)

    # Output text confirming we saved
    print(f"Saved the plot as {total_name}")


###########################
# PyQTgraph Configuration #
###########################

# START QtApp
# You MUST do this once to initialize pyqtgraph
# app = QtWidgets.QApplication([])
app = QtWidgets.QApplication([])


# Window title
WINDOW_TITLE = "Real Time Plotter"

# Set background white
pg.setConfigOption("background", "w")
pg.setConfigOption("foreground", "k")

# Define the window object for the plot
win = pg.GraphicsLayoutWidget(title=WINDOW_TITLE, show=False)

# Create button to save plots
save_button = QtWidgets.QPushButton("Save Plot")

# Attach Callback
save_button.clicked.connect(save_current_plot)


# Create the GUI
window = QtWidgets.QWidget()
hbox = QtWidgets.QVBoxLayout()
hbox.addWidget(win)
hbox.addWidget(save_button)
window.setLayout(hbox)
window.show()

# Close view when exiting
app.aboutToQuit.connect(window.close)

# Create the plot from the json file that is passed in
def initialize_plot(json_config, subplots_to_remove=None):
    """Initializes the plots and returns many handles to plot items

    Inputs
    ------

    json_config: Python dictionary with relevant plot configuration
    subplots_to_remove: Previous plot subplot items that will be removed
                        from the window. This is meant for internal use.
                        Leave as None.
    only_log_traces: list of trace names that will only be logged and not 
        displayed

    Returns
    -------
    traces_per_plot: num of traces per each subplot
    subplots_traces: Object that is used to update the traces
    subplots: Handle to subplots used to delete the subplots uppon
              re-initialization
    num_plots: Number of subplots
    top_plot: Reference to top plot object to update title of
    top_plot_title: Reference to top plot title string to add on FPS
    trace_labels: Array of trace names with subplot number attached to it
    num_datapoints_in_plot: defines the x-axis width number of datapoints
    non_plot_labels: Array of trace names that will not be plotted
    """

    # If there are old subplots, remove them
    if subplots_to_remove is not None:
        for subplot in subplots_to_remove:
            win.removeItem(subplot)

    # Initialize arrays of number per plot and array of pointer to
    # plots and traces
    traces_per_plot = []
    subplots_traces = []
    subplots = []
    trace_info = []
    non_plot_labels = []

    # Initialize the top plot to None so that we can grab it
    top_plot = None

    # Initialize top plot title in case the user does not provide a title
    top_plot_title = ""

    # Generate each subplot
    for plot_num, plot_description in enumerate(json_config.values()):

        # If the non_plot attribute is set to true, ignore the traces in this
        # plot
        if 'non_plot_labels' in plot_description:
            non_plot_labels = plot_description['non_plot_labels']
            continue
        
        # Get the trace names for this plot
        trace_names = plot_description["names"]

        # Count how many traces we want
        num_traces = len(trace_names)

        # Add the indices in the numpy array
        traces_per_plot.append(num_traces)

        # Initialize the new plot
        new_plot = win.addPlot()

        # Move to the next row
        if NEW_SUBPLOT_IN_ROW == True:
            win.nextRow()
        else:
            win.nextCol()

        # Capture the first plot
        if top_plot == None:
            top_plot = new_plot

        # Add the names of the plots to the legend
        new_plot.addLegend(**legend_style)

        # Add the axis info
        if "xlabel" in plot_description:
            new_plot.setLabel(
                "bottom", plot_description["xlabel"], **axis_label_style
            )

        if "ylabel" in plot_description:
            new_plot.setLabel(
                "left", plot_description["ylabel"], **axis_label_style
            )

        # Get the x range information
        if "xrange" in plot_description:
            num_datapoints_in_plot = plot_description["xrange"]
        else:
            num_datapoints_in_plot = DEFAULT_NUM_DATAPOINTS_IN_PLOT

        # Potential performance boost
        new_plot.setXRange(0, num_datapoints_in_plot)

        # Get the y range
        if "yrange" in plot_description:
            new_plot.setYRange(*plot_description["yrange"])

        # Set axis tick mark size
        font = QtGui.QFont()
        font.setPixelSize(tick_size)
        new_plot.getAxis("left").setStyle(tickFont=font)

        font = QtGui.QFont()
        font.setPixelSize(tick_size)
        new_plot.getAxis("bottom").setStyle(tickFont=font)

        # Add title
        if "title" in plot_description:
            new_plot.setTitle(plot_description["title"], **title_style)

            if plot_num == 0:
                top_plot_title = plot_description["title"]

        # If zeroth-plot does not have tittle, add something in blank
        # so fps counter gets style
        elif plot_num == 0:
            new_plot.setTitle("", **title_style)

        # Define default Style
        colors = ["r", "g", "b", "c", "m", "y"]
        if "colors" in plot_description:
            colors = plot_description["colors"]

        line_style = [QtCore.Qt.SolidLine] * num_traces
        if "line_style" in plot_description:
            line_style = [
                QtCore.Qt.DashLine if desc == "-" else QtCore.Qt.SolidLine
                for desc 
                in plot_description["line_style"]
            ]

        line_width = [1] * num_traces
        if "line_width" in plot_description:
            line_width = plot_description["line_width"]

        # Generate all the trace objects
        for i in range(num_traces):
            # Create the pen object that defines the trace style
            pen = pg.mkPen(
                color=colors[i], style=line_style[i], width=line_width[i]
            )
            # Add new curve
            new_curve = pg.PlotCurveItem(name=trace_names[i], pen=pen)
            new_plot.addItem(new_curve)
            # Store pointer to update later
            subplots_traces.append(new_curve)
            # Store the current trace name
            trace_info.append((trace_names[i], plot_num))

        # Add the new subplot
        subplots.append(new_plot)

    print("Initialized Plot!")
    return (
        traces_per_plot,
        subplots_traces,
        subplots,
        top_plot,
        top_plot_title,
        trace_info,
        num_datapoints_in_plot,
        non_plot_labels
    )


# Receive a numpy array
def recv_array(socket, flags=0, copy=True, track=False):
    """recv a numpy array"""
    md = socket.recv_json(flags=flags)
    msg = socket.recv(flags=flags, copy=copy, track=track)
    buf = memoryview(msg)
    A = np.frombuffer(buf, dtype=md["dtype"])
    return A.reshape(md["shape"])


# Create definitions to define when you receive data or new plots
RECEIVED_PLOT_UPDATE = 0
RECEIVED_DATA = 1
NOT_RECEIVED_DATA = 2
SAVE_PLOT = 3

# Variable to store initial time when data was missed
time_when_data_was_missed = None

# This indicates how long should we wait to sleep the cpu after a datapoint
# was missed and no new data arrives
SLEEP_AFTER_X_SECONDS = 10

# This indicates how long to sleep after many datapoints have been missed
SLEEP_X_SECONDS = 0.1

# Define function to detect category
def rec_type():

    # Keep track of the missed datapoints
    global time_when_data_was_missed

    # Sometimes we get miss-aligned data
    # In this case just ignore the data and wait until you have a valid type
    while True:
        try:
            #Receive a string from the user
            received = socket.recv_string(flags=zmq.NOBLOCK)

            #Convert to an int. This can cause a casting value error
            received_type = int(received)

            #Reset timer if valid input was received
            time_when_data_was_missed = None

            return received_type
        
        # If you get a value error, then you got data
        except ValueError:

            if DEBUG_TEXT_ENABLED:
                print(f"Had a value error. Expected int, received: {received}")
            else:
                print(
                    (
                        "Lost synchronization between client and server."
                        " Please restart client"
                    )
                )

        # There is no data currently available
        except zmq.Again as e:

            # if DEBUG_TEXT_ENABLED:
            #     print("ZMQ.Again: No data received")

            time_now = time.time()

            # If its the first time, set original time to now
            if time_when_data_was_missed is None:
                time_when_data_was_missed = time_now

            # Sleep for one second if enough time has passed to save cpu time
            if time_now - time_when_data_was_missed > SLEEP_AFTER_X_SECONDS:
                time.sleep(SLEEP_X_SECONDS)

                if DEBUG_TEXT_ENABLED:
                    print("Sleeping from no data")

            return NOT_RECEIVED_DATA


#####################
# Main code section #
#####################
# Run until you get a keyboard interrupt
# Initialize variables

# Initialize plots expects pointers to the old plots to delete them
# since we have no plots, initialize to None
subplots = None

# Make sure that you don't try to plot data without having a plot
initialized_plot = False

# Create a counter that will be used in case we want to update the plot 
# every X datapoints
data_counter = 0

# Create a counter that will be used to determine if the incoming data is 
# coming in faster than we can process it
data_rate_counter = 0

# Main code loop
while True:
    # Receive the type of information
    category = rec_type()

    # Do not continue unless you have initialized the plot
    if category == RECEIVED_PLOT_UPDATE:

        # Reset the data counter to zero
        data_counter = 0

        # Receive plot configuration
        flags = 0
        plot_configuration = socket.recv_json(flags=flags)

        # Initialize plot
        (
            traces_per_plot,
            subplots_traces,
            subplots,
            top_plot,
            top_plot_title,
            trace_labels,
            num_datapoints_in_plot,
            non_plot_labels,
        ) = initialize_plot(plot_configuration, subplots)

        # Get the number of plots
        num_plots = len(subplots)

        # Get number of traces
        num_traces = sum(traces_per_plot)

        # Get number of traces that will not be plotted
        num_non_plot_traces = len(non_plot_labels)

        # Setup local data buffer
        # Since we save using the index, we just need to update
        # the index and not set the buffer to zero
        li = num_datapoints_in_plot
        buffer_bounds = np.array([0, num_datapoints_in_plot])
        local_storage_buffer_num_trace = num_traces + 1
        local_storage_buffer[:local_storage_buffer_num_trace, :li] = 0

        # You can now plot data
        initialized_plot = True

        # Define fps variable
        fps = None

        # Get last time to estimate fps
        lastTime = perf_counter()

        # Get time to generate time stamps
        firstTime = perf_counter()

    # Read some data and plot it
    elif (category == RECEIVED_DATA) and (initialized_plot == True):

        # Read in numpy array
        receive_np_array = recv_array(socket)
        # Get how many new values are in it
        num_values = receive_np_array.shape[1]

        # Increase the buffer bounds to plot the new data
        buffer_bounds += num_values

        # Remember how much you need to offset per plot
        subplot_offset = 0

        # Estimate fps
        now = perf_counter()
        dt = now - lastTime
        lastTime = now

        if fps is None:
            fps = 1.0 / dt
        else:
            s = np.clip(dt * 3.0, 0, 1)
            fps = fps * (1 - s) + (1.0 / dt) * s

        # Update every subplot
        for plot_index in range(num_plots):

            # Update every trace
            for subplot_index in range(traces_per_plot[plot_index]):

                # Get index to plot
                i = subplot_offset + subplot_index

                # Update the local storage buffer
                local_storage_buffer[
                    i, li : li + num_values
                ] = receive_np_array[i, :]

                # Update the plot
                subplots_traces[i].setData(
                    local_storage_buffer[
                        i, buffer_bounds[0] : buffer_bounds[1]
                    ]
                )

            # Update offset to account for the past loop's traces
            subplot_offset += traces_per_plot[plot_index]

        # Calculate the current time stamp for the local storage buffer
        curr_timestamp = now - firstTime
        local_storage_buffer[
            local_storage_buffer_num_trace - 1, li : li + num_values
        ] = curr_timestamp

        #Add the non-plotting variables
        local_storage_buffer[
            local_storage_buffer_num_trace:local_storage_buffer_num_trace+num_non_plot_traces,
            li : li + num_values
        ] = receive_np_array[
            local_storage_buffer_num_trace:local_storage_buffer_num_trace+num_non_plot_traces,:]

        # Increase the local storage index variable
        li += num_values

        # Update fps in title
        if data_rate_counter < 100:
            color = "green"
        else:
            color = "red"
        top_plot.setTitle(top_plot_title + f" - FPS:{fps:.0f}", color=color)

        # Update the data counter and data_rate counter
        data_counter += 1
        data_rate_counter += 1

        # If you have reached the number of datapoints to update the plot
        # update the plot
        if data_counter % SKIP_PLOT_DATAPOINTS == 0:
            # Indicate you MUST process the plot now
            QtWidgets.QApplication.processEvents()
            # Reset the data counter
            data_counter = 0

    elif category == SAVE_PLOT:
        #Get the log name
        log_name = socket.recv_string()
        #Save the plot with the log name
        save_current_plot(log_name)

    elif category == NOT_RECEIVED_DATA:

        # If we have not received data for a while, set the data rate counter
        # to zero
        data_rate_counter = 0

        # Process other events to make plot responsive
        QtWidgets.QApplication.processEvents()


# References
# ZMQ Example code
# https://zeromq.org/languages/python/

# How to send/receive numpy arrays
# https://pyzmq.readthedocs.io/en/latest/serialization.html

# How to real time plot with pyqtgraph
# https://stackoverflow.com/questions/45046239/python-realtime-plot-using-pyqtgraph
