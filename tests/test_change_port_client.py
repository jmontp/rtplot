"""
This file is meant to verify that the client can change ports when the 
server is connecting to it

Run the server with this line of code first

python3 server.py -p 127.0.0.1:1234
"""

import numpy as np 

from rtplot import client

client.configure_port(1234)
client.initialize_plots(1)

for i in range(1000):
    client.send_array(np.random.randn())

