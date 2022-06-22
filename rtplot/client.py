import zmq
import numpy as np
import time
from collections import OrderedDict


###################
# ZMQ Networking #
##################

#Get the context for networking setup
context = zmq.Context()

#Socket to talk to server
#Using the pub - sub paradigm to communicate
socket = context.socket(zmq.PUB)

#Global variable to keep track of last connected address
# default is fixed publisher mode, therefore you don't connect 
# to an address
prev_address = None

#This address will be used to bind any incoming subscriber on port 5555
# to the publisher
bind_address = "tcp://*:5555"

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

        #Sleep so that the subscriber can join
        time.sleep(0.2)
    
    #If you cannot connect to the socket, alert user and continue
    except zmq.error.ZMQError as e:
        failed_bind = True
        print("rtplot.client: Could not connect to default address '{}'".format(e))
        print("               Fine if doing local plots")
   

# Secondary default behavior is that you know the ip address 
# of the computer that will plot
else:
    #Connect to the computer that will plot information
    socket.connect(prev_address)

############################
# PyQTgraph Configuration #
###########################

#Create definitions for categories
SENDING_PLOT_UPDATE = "0"
SENDING_DATA = "1"


def local_plot():
    """Send data to a plot in the same computer"""

    local_address = "tcp://127.0.0.1:5555"
    configure_ip(ip = local_address)

def plot_to_neurobionics_tv():
    """Send data to a plot in the same computer"""

    tv_computer_address = "tcp://141.212.77.109:5555"
    configure_ip(ip = tv_computer_address)
    

def configure_ip(ip=None, known_pi_address = False):
    """Connect to a subscriber at a specific IP address
    
    Inputs
    ------
    ip: Ip address or string formated to protocol:address:port
    fixed_subscriber: bool, defines if either the subscriber of the 
                      publisher has a fixed ip address
    """

    ## Get the current address
    global prev_address
    global known_pi_address_prev
    
    ## Disconnect from the previous configuration
    # if known_pi_address_prev and not failed_bind:
    #     socket.unbind(bind_address)
    # elif prev_address is not None:
    #     socket.disconnect(prev_address)
    
    ## Format the incomming string

    #If you just get the ip address and no port, format correctly
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

    print("rtplot.client: Connecting to address {}".format(connect_address))

    ## Connect to new configuration
    if(known_pi_address):
        #Bind incomming computers to the pi
        socket.bind(bind_address)
        prev_address = None

    else:
        #Connect to the computer that will do the plotting
        socket.connect(connect_address)
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
    return socket.send(A, flags, copy=copy, track=track)


def initialize_plots(plot_descriptions=1):
    """Send a json description of desired plot
    Inputs
    ------
    plot_description: list of names or list of plot descriptions dictionaries
    """

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
