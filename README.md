![Logo of the project](https://github.com/jmontp/prosthetic_adaptation/blob/master/.images/signature-stationery.png)

# Real Time Plotting with pyqtgraph and ZMQ

The point of this module is to be able to plot remotely over socket protocols using the [ZMQ library](https://zeromq.org/). The use cases that I have in mind is plotting information from the raspberry pi to a host computer so that they can plot the data. This is very useful for setting up real time plots given pyqtgraph's performance. This can also be used to plot local information in real time by using the localhost as the address to publish/subscribe data from. 

The main highlight in this plotter are the following:
* **Fast Performance**. Can do 500+ fps on one trace using an i7-9750H processor
* **Remote Plot Customizability**. The plot configuration is defined by the provider of the data. E.g. if you are using a pi to collect data, the plot configuration is also stored on the pi so you only have to change code in one location 

# Dependencies
[PyZMQ](https://zeromq.org/languages/python/)

[pyqtgraph](https://pyqtgraph.readthedocs.io/en/latest/installation.html)

# How to use

* Step 1

   ``` python3 server.py```

   Or, if you are on a big TV

   ```python3 server.py --bigscreen```

* Step 2
   
   Send data to the server


The first step to plot is to execute the server.py file in the computer that you want to plot. This will wait for a configuration from the publisher and then plot the subsequent data that is sent over as numpy arrays. If a new plot configuration is sent, the plot will automatically update the plot and keep plotting data in the new format. 


In order to use this library, you must import the rtplot.client module into your code. The first step is to define the configuration. There are two ways of doing this

## Simplest client plot configuration and data transfer

In the simplest plot configuration, you only need to indicate the amount of traces that you want (if you leave it empty, it will default to 1 trace). Then you need to send the data. The data must be a one or two dimensional numpy array (more info on this later).  

```
from rtplot import client

#Initialize one plot with 5 traces
client.initialize_plots(5)


for i in range(1000):

    #Send data
    client.send_array(np.random.randn(5,1))
```

More examples can be seen in simplest_test.py.


## Complex plot configuration

Additional elements of the plot can be configured from the client side. To do this, you can define a dictionary that contains the configuration of the plot with special keys. Currently, the keys that are supported are the following: 


* 'names' - This defines the names of the traces. Same as how using just the simple plot configuration using lists works.

* 'colors' - Defines the colors for each trace. Should have at least the same length as the number of traces.

* 'line_style' - Defines wheter or not a trace is dotted or not. 
    * '-' - represents dotted line
    * '' - or anything else represents a normal line


* 'title' - Sets the title to the plot
* 'ylabel' - Sets the y label of the plot
* 'xlabel' - Sets the x label of the plot
* 'yrange' - Sets the range of values of y. This provides a performance boost to the plotter
   * Expects values as a iterable in the order [min, max]. Example: [-2,2]


You only need to specify the things that you want, if the dictionary element is left out then the default value is used. Some example code of how to use this is as follows (it can also be executed by running client.py)

```
from rtplot import client 

#Define a dictionary of items for each plot
plot_1_config = {'names': ['phase', 'phase_dot', 'stride_length'],
                    'title': "Phase, Phase Dot, Stride Length",
                    'ylabel': "reading (unitless)",
                    'xlabel': 'test 1'}
                   
#Anything not specified gets defaulted 

plot_2_config = {'names': [f"gf{i+1}" for i in range(5)],
                    'colors' : ['w' for i in range(5)],
                    'line_style' : ['-','','-','','-'],
                    'title': "Phase, Phase Dot, Stride Length",
                    'ylabel': "reading (unitless)",
                    'xlabel': 'test 2'}

#Aggregate into list  
plot_config = [plot_1_config,plot_2_config]


#Tell the server to initialize the plot
client.initialize_plots(plot_config)
```

## How to send data

Once the plot has been configured, the data is sent as a numpy array. The order of the data in the array is very important and it MUST be sent where the rows have data that corresponds to the same order that the trace names were defined in. For example, in the simple plot configuration code snipet, the traces were defined as follows

```
#Define a list of names for every plot
plot1_traces = ['phase', 'phase_dot']
plot2_traces = ['ramp','stride_length']
```

The corresponding numpy arraw that would be sent would look like




<!-- $$
\begin{equation*}
    \text{data} = 
        \begin{bmatrix} 
            phase_0 & \dots & phase_{n-1} \\
            phase\_dot_0 & \dots & phase\_dot_{n-1} \\
            ramp_0 & \dots & ramp_{n-1} \\
            stride_0 & \dots & stride_{n-1}
    
        \end{bmatrix}
\end{equation*}
$$ --> 

<div align="center"><img style="background: white;" src="https://render.githubusercontent.com/render/math?math=%5Cbegin%7Bequation*%7D%0A%20%20%20%20%5Ctext%7Bdata%7D%20%3D%20%0A%20%20%20%20%20%20%20%20%5Cbegin%7Bbmatrix%7D%20%0A%20%20%20%20%20%20%20%20%20%20%20%20phase_0%20%26%20%5Cdots%20%26%20phase_%7Bn-1%7D%20%5C%5C%0A%20%20%20%20%20%20%20%20%20%20%20%20phase%5C_dot_0%20%26%20%5Cdots%20%26%20phase%5C_dot_%7Bn-1%7D%20%5C%5C%0A%20%20%20%20%20%20%20%20%20%20%20%20ramp_0%20%26%20%5Cdots%20%26%20ramp_%7Bn-1%7D%20%5C%5C%0A%20%20%20%20%20%20%20%20%20%20%20%20stride_0%20%26%20%5Cdots%20%26%20stride_%7Bn-1%7D%0A%20%20%20%20%0A%20%20%20%20%20%20%20%20%5Cend%7Bbmatrix%7D%0A%5Cend%7Bequation*%7D"></div>
 
Were n is the amount of columns of data that we send over. Note that the rows each correspond to the labels as they are defined and that we do not specify the width of the data block in the plot configuration. This means that we can send over as many columns of information as we want as long as it does not exceed the window width (WINDOW_WIDTH in server.py).

Similarly, for the example in the complex configuration, the data would take the following shape: 

```
#Define a dictionary of items for each plot
plot_1_config = {'names': ['phase', 'phase_dot', 'stride_length'],
                    'title': "Phase, Phase Dot, Stride Length",
                    'ylabel': "reading (unitless)",
                    'xlabel': 'test 1'}

#rest of dict obviated since it does not make a difference
plot_2_config = {'names': [f"gf{i+1}" for i in range(5)]} 
```

<!-- $$
\begin{equation*}
    \text{data} = 
        \begin{bmatrix} 
            phase_0 & \dots & phase_{n-1} \\
            phase\_dot_0 & \dots & phase\_dot_{n-1} \\
            stride_0 & \dots & stride_{n-1}\\
            gf_{1_0} & \dots & gf_{1_{n-1}} \\
            gf_{2_0} & \dots & gf_{2_{n-1}} \\
            gf_{3_0} & \dots & gf_{3_{n-1}} \\
            gf_{4_0} & \dots & gf_{4_{n-1}} \\
            gf_{5_0} & \dots & gf_{5_{n-1}}           
          
        \end{bmatrix}
\end{equation*}
$$ --> 

<div align="center"><img style="background: white;" src="https://render.githubusercontent.com/render/math?math=%5Cbegin%7Bequation*%7D%0A%20%20%20%20%5Ctext%7Bdata%7D%20%3D%20%0A%20%20%20%20%20%20%20%20%5Cbegin%7Bbmatrix%7D%20%0A%20%20%20%20%20%20%20%20%20%20%20%20phase_0%20%26%20%5Cdots%20%26%20phase_n%20%5C%5C%0A%20%20%20%20%20%20%20%20%20%20%20%20phase%5C_dot_0%20%26%20%5Cdots%20%26%20phase%5C_dot_n%20%5C%5C%0A%20%20%20%20%20%20%20%20%20%20%20%20stride_0%20%26%20%5Cdots%20%26%20stride_%7Bn-1%7D%5C%5C%0A%20%20%20%20%20%20%20%20%20%20%20%20gf_%7B1_0%7D%20%26%20%5Cdots%20%26%20gf_%7B1_%7Bn-1%7D%7D%20%5C%5C%0A%20%20%20%20%20%20%20%20%20%20%20%20gf_%7B2_0%7D%20%26%20%5Cdots%20%26%20gf_%7B2_%7Bn-1%7D%7D%20%5C%5C%0A%20%20%20%20%20%20%20%20%20%20%20%20gf_%7B3_0%7D%20%26%20%5Cdots%20%26%20gf_%7B3_%7Bn-1%7D%7D%20%5C%5C%0A%20%20%20%20%20%20%20%20%20%20%20%20gf_%7B4_0%7D%20%26%20%5Cdots%20%26%20gf_%7B4_%7Bn-1%7D%7D%20%5C%5C%0A%20%20%20%20%20%20%20%20%20%20%20%20gf_%7B5_0%7D%20%26%20%5Cdots%20%26%20gf_%7B5_%7Bn-1%7D%7D%20%20%20%20%20%20%20%20%20%20%20%0A%20%20%20%20%20%20%20%20%20%20%0A%20%20%20%20%20%20%20%20%5Cend%7Bbmatrix%7D%0A%5Cend%7Bequation*%7D"></div>

 

 Once the data is formatted appropriately, it is sent to the client by 

 ```
from rtplot import client 

#Initialize plot
client.initialize_plots()

#Format the data as explained above
data = ... 

#Send data to server to plot
client.send_array(data)
 ```
 
# A note on performance

The performance of the plotter is mostly impacted by the amount of traces that you want to plot (this is due to multiple calls to the line drawing algorithms in pyqtgraph). However, sending over multiple datapoints to plot at once is not expensive since there is essentially only the added overhead of receiving the data (the plotter redraws the entire line anyways). Therefore to get the most performance you should have as little traces as possible and send over as much datapoints at once before the plot updates look ugly.

To get the most performance out of the system, you want to set the 'yrange' configuration of the plot. This has resulted in a 100FPS increase for my testing. 



# Examples

[simplest_test.py](https://github.com/jmontp/prosthetic_adaptation/blob/master/rtplot/simplest_test.py) Contains many great examples on how to setup the client-side code. 

![alt text](https://github.com/jmontp/prosthetic_adaptation/blob/master/.images/rtplot_example2.png "Example 1")

![alt text](https://github.com/jmontp/prosthetic_adaptation/blob/master/.images/rtplot_example1.png "Example 2")

simulate_ekf.py contains example code. Look for calls to client. 


# Todo

* Rename 'server' and 'client' to 'subscriber' and 'publisher' to better indicate the communication pattern. 
* Make the x-axis represent time.
* Have a way to store entire datasets directly from the plotter (e.g. button of some sort).
* Add performance vs number of traces and array size surface. Include performance by varying yrange and other terms.
