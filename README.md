![Logo of the project](https://github.com/jmontp/rtplot/blob/master/.images/signature-stationery.png)

# Real Time Plotting with pyqtgraph and ZMQ

The point of this module is to be able to plot remotely over socket protocols using the [ZMQ library](https://zeromq.org/). The use cases that I have in mind is plotting information from the raspberry pi to a host computer so that they can plot the data. This is very useful for setting up real time plots given pyqtgraph's performance. This can also be used to plot local information in real time by using the localhost as the address to publish/subscribe data from. 

The main highlight in this plotter are the following:
* **Fast Performance**. Can do 500+ fps on one trace using an i7-9750H processor
* **Remote Plot Customizability**. The plot configuration is defined by the provider of the data. E.g. if you are using a pi to collect data, the plot configuration is also stored on the pi so you only have to change code in one location 
* **Save data**. Once you plot the data, you can save it locally by clicking one button.


# Install 

Run in the parent folder containing the repo (requires [setuptools](https://pypi.org/project/setuptools/))

> python3 -m pip install -e rtplot/


# Dependencies

| Data-Plotting Computer  | Both Computers|
| ------------- |:-------------:|
| [pyqtgraph](https://pyqtgraph.readthedocs.io/en/latest/installation.html) ```pip3 install pyqtgraph ``` ```pip3 install pyside6``` | [PyZMQ](https://zeromq.org/languages/python/) ```pip3 install pyzmq```  |
| [Pandas](https://pandas.pydata.org/docs/getting_started/install.html) ```pip3 install pandas```      |       |
| [Pyarrow](https://arrow.apache.org/docs/python/install.html) ```pip3 install pyarrow``` |      |

One-liner to install everything:
```pip3 install pyarrow pyqtgraph pyside6 pyzmq pandas```


If you are using WSL, you need to install an xorg server such as [vcXsrv](https://sourceforge.net/projects/vcxsrv/)

# How to use

### Step 1: On the computer that will be used to plot run:

   
  For local plots: ``` python3 server.py -l```
  
  To plot from a raspberry pi: ``` python3 server.py -p xxx.xxx.xxx.xxx```
  
  Where the xxx.xxx.xxx.xxx represents the pi's ip address (note, you must be on the same network) 
   
### Step 2: On the script that provides data, add the plotting library

In order to use this library, you must have installed the library and import the rtplot.client module into your code. The two main steps are to initialize the plotter and then to send data as seen in the following example:

```python
#Load plotting library
from rtplot import client 

#Common import
import numpy as np

#Initialize one plot with 5 traces
client.initialize_plots(5)

#Send 1000 datapoints
for i in range(1000):

    #Send random data
    client.send_array(np.random.randn(5,1))
```

In the simplest plot configuration, you only need to indicate the amount of traces that you want (if you leave it empty, it will default to 1 trace). Then you need to send the data. The data must be either a list or a numpy array. More examples can be seen in the [example code](https://github.com/jmontp/rtplot/blob/master/rtplot/example_code.py)


# :cherry_blossom: Make pretty plots :cherry_blossom:

You can control the following things when calling ```client.initialize_plots()``` by passing in a dictionary:


* 'names' - This defines the names of the traces. The plot will have as many traces as names.

* 'colors' - Defines the colors for each trace. [Follow documentation on how to specify color](https://pyqtgraph.readthedocs.io/en/latest/style.html). Should have at least the same length as the number of traces.

* 'line_style' - Defines wheter or not a trace is dashed or not. 
    * '-' - represents dashed line
    * "" - emptry string (or any other string) represents a normal line
* 'line_width' - Defines how thick the plot lines are. Expects an integer
* 'title' - Sets the title to the plot
* 'ylabel' - Sets the y label of the plot
* 'xlabel' - Sets the x label of the plot
* 'yrange' - Sets the range of values of y. This provides a performance boost to the plotter
   * Expects values as a iterable in the order [min, max]. Example: [-2,2]
* 'xrange' - Sets the number of datapoints that will be in the real time plotter at a given time.
   * Expects values as a integer that describes how many datapoints are in the subplot. Default is 200 datapoints


You only need to specify the things that you want, if the dictionary element is left out then the default value is used. 

### How to send data

Once the plot has been configured, the data is sent as a numpy array. The order of the data in the array is very important and it MUST be sent where the rows have data that corresponds to the same order that the trace names were defined in. 


```python
#Load plotting library
from rtplot import client 

#Common import
import numpy as np

#Let's create two subplots
#First, define a dictionary of items for each plot

#First plot will have three traces: phase, phase_dot, stride_length
plot_1_config = {'names': ['phase', 'phase_dot', 'stride_length'],
                 'title': "Phase, Phase Dot, Stride Length",
                 'ylabel': "reading (unitless)",
                 'xlabel': 'test 1'}

#Second plot will have five traces: gf1, gf2, gf3, gf4, gf5
plot_2_config = {'names': ["gf1","gf2","gf3","gf4","gf5"],
                 'colors' : ["r","b","g","r","b"],
                 'line_style' : ['-','','-','','-'],
                 'title': "Phase, Phase Dot, Stride Length",
                 'ylabel': "reading (unitless)",
                 'xlabel': 'test 2'}

#Aggregate into list  
plot_config = [plot_1_config,plot_2_config]

#Tell the server to initialize the plot
client.initialize_plots(plot_config)

#Create plotter array with random data
plot_data_array = [np.random.randn(), #phase
                   np.random.randn(), #phase_dot
                   np.random.randn(), #stride_length
                   np.random.randn(), #gf1
                   np.random.randn(), #gf2
                   np.random.randn(), #gf3
                   np.random.randn(), #gf4
                   np.random.randn()  #gf5
                   ]

#Send data to server to plot
client.send_array(plot_data_array)
 ```
 
# Additional networking configurations

There are two main ways that you can connect to transmit information. Either the computer that runs the server knows what IP the client is (server connects to client), or the client knows which IP the server has (server connects to client). For either option, follow the steps bellow:

### Server connects to client
This is accomplished by running the server with the IP address of the pi as an argument.

```
python3 server.py -p xxx.xxx.xxx.xxx
```

Where xxx.xxx.xxx.xxx is the IP address of the pi. No additional configuration is needed on the client side.


### Client connects to server
This is done by setting up the server with the static ip flag.

```
python3 server.py -s
```

The client then needs to specify the ip of the plotter by running:
```
client.configure_ip("xxx.xxx.xxx.xxx")
```

Where xxx.xxx.xxx.xxx is the IP address of the server.

 
# Plotter too slow?

The performance of the plotter is mostly impacted by the amount of traces that you want to plot (this is due to multiple calls to the line drawing algorithms in pyqtgraph). However, sending over multiple datapoints to plot at once is not expensive since there is essentially only the added overhead of receiving the data (the plotter redraws the entire line anyways). Therefore to get the most performance you should have as little traces as possible and send over as much datapoints at once before the plot updates look ugly.

### Fix y range
To get the most performance out of the system, you want to set the 'yrange' configuration of the plot. This has resulted in a 100FPS increase for my testing. 


# [Example Code](https://github.com/jmontp/rtplot/blob/master/rtplot/example_code.py)


# Example Image
![alt text](https://github.com/jmontp/rtplot/blob/master/.images/rtplot_example1.png "Example 1")

![alt text](https://github.com/jmontp/rtplot/blob/master/.images/rtplot_example2.png "Example 2")
