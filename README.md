![Logo of the project](https://github.com/jmontp/rtplot/blob/master/.images/signature-stationery.png)

# Real Time Plotting with pyqtgraph and ZMQ

The point of this module is to be able to plot data in python in real time either from a script running locally in your computer or a script that is on a remote computer that sends data over a network (e.g. from a raspberry pi)

The rtplot library consist of two modules: a server, which acts like a standalone script which opens a window that waits to recieve plots and data, and a client which is used to modify your code to send the data to the server.


The main highlight in this plotter are the following:
* **Fast Performance**. Can do 500+ fps on one trace using an i7-9750H processor
* **Remote Plot Customizability**. The plot configuration is defined by the provider of the data. E.g. if you are using a pi to collect data, the plot configuration is also stored on the pi so you only have to change code in one location 
* **Save data**. Once you plot the data, you can save it locally by clicking one button.


# Install 
To install just the client (can only send data)

```pip install better-rtplot```

To install the client and the dependencies for the server. This is not recommended for smaller devices since some dependencies are large.

```pip install better-rtplot[server]```

If you are using WSL, you need to install an xorg server such as [vcXsrv](https://sourceforge.net/projects/vcxsrv/) to see the plot. However, this should run in a native windows install of python.

# How to use
The general steps to use the plotter are as follows:

1. Run the server.py script on the computer that will be used to visualize the data
2. Import the client library to (lightly) modify your code so that it can send data to the server

In more detail:

## Step 1: Run the program that visualizes the data (server.py)

To run the server script, you can run the following code in the command line 
```python3 -m rtplot.server```

This will open a window which will wait for plots that are sent by a client. This is a convenient setup if you know the IP address of the computer that is running the server. However, if you don't know the IP address, you can specify the ip address of the computer that is sending data (e.g. the client) with the following line:

 ``` python3 -m rtplot server.py -p 192.168.1.1```
  
Where the"192.168.1.1" represents the IP address of the computer you want to connect to (note, you must be on the same network).
   
## Step 2: Modify your code to send data (use "client" library)

You only need to follow a few steps to update your code to send data to a server

Step 0: Import client library
Step 1: (Optional) Set the IP address of the server
Step 2: Send the plot configuration to the server
Step 3: Send data to the server

Here is a small example to get your started. This will create a plot with one trace and send the number 5 to it:

```python
# Step 0: Load plotting library
from rtplot import client 

# Step 1: Configure the IP address
# Point to the same comptuer
client.local_plot()

# Step 2: Initialize the plots
# Initialize one plot with 1 traces
client.initialize_plots(1)

#Send 1000 datapoints
for i in range(1000):

    # Step 3: Send the data
    # Send the number 5 a thousand times
    client.send_array(5)
```

Here is a more detailed explanation of every step

### Code changes 1: (Optional) Set the IP address of the server

There are three function calls that will allow you to configure the IP address of the plotter

```client.configure_ip(ip)```

This is the most common function you will use. The ip address is a string in the normal format. For example ```client.configure_ip(192.168.1.1)``` will connect to the computer addressed at 192.168.1.1 on port 5555 by default. You can also specify the port by adding it with a colon. Therefore, ```client.configure_ip(192.168.1.1:1234)``` connects to IP address 192.168.1.1 on port 1234.

```client.local_plot()```

This will indicate that the server is running in the same machine. It is a shorthand for ```client.configure_ip(127.0.0.1)```

```client.plot_to_neurobionics_tv()```

This will send data to the TV in the rehab lab bigscreen TV.


 ### Code changes 2: Send the plot configuration to the server

The client specifies what the plot looks like. Therefore, that has to be added to where you send the data. The only function that you need to call is ```client.initialize_plots()```. This function can take in many different arguments to define the look and feel. At the most basic level you can have one plot with one or more traces. However, you can add multiple sub-plots with different amounts of traces in each. Therefore the different ways that you can call ```client.initialize_plots(plot_layout)``` are:

- No argument
  
This will intialize the plot to have one subplot with one trace

- Integer
  
This will configure one subplot to have the a

- String
  
This will configure the plots to have one subplot with a trace named the same as the string

- List of strings
  
One subplot with as many traces as names in the list, each with the corresponding name.

- List that contains lists of strings
  
Same as above, but now with as many subplots as sublists

- Dictionary
  
One subplot with a more advanced configuration

- List of dictionaries
  
Many subplots, each with an advanced configuration


### :cherry_blossom: Make pretty plots :cherry_blossom:

You can control the look and feel of the plots by sending a dictionary that contains specific strings as the keys. These are as follows


- 'names' - This defines the names of the traces. The plot will have as many traces as names.

- 'colors' - Defines the colors for each trace. [Follow documentation on how to specify color](https://pyqtgraph.readthedocs.io/en/latest/style.html). Should have at least the same length as the number of traces.

- 'line_style' - Defines wheter or not a trace is dashed or not. 
    * '-' - represents dashed line
    * "" - emptry string (or any other string) represents a normal line

- 'line_width' - Defines how thick the plot lines are. Expects an integer

- 'title' - Sets the title to the plot

- 'ylabel' - Sets the y label of the plot

- 'xlabel' - Sets the x label of the plot

- 'yrange' - Sets the range of values of y. This provides a performance boost to the plotter
   * Expects values as a iterable in the order [min, max]. Example: [-2,2]

- 'xrange' - Sets the number of datapoints that will be in the real time plotter at a given time.
   * Expects values as a integer that describes how many datapoints are in the subplot. Default is 200 datapoints

You only need to specify the things that you want, if the dictionary element is left out then the default value is used. 

You can see the [example code](https://github.com/jmontp/rtplot/blob/master/rtplot/example_code.py) to see how these are used.

### Code changes 3: How to send data

To send data to the server, you use the ```client.send_array(arr)``` function. Similar to initialize plots, this function also takes in multiple different argument types:

- Float
When there is only one trace

- List of float
The length of the list has to equal the total number of traces that are configured for the plot

- 1-d Numpy array
The size of the numpy array has to be equal to the total number of traces that are configured for the plot

- 2-d Numpy array
The number of rows must equal the total number of traces. The column can vary in length. The sever will plot as many datapoints as you send in. E.g. the plot will be updated with 10 new points if you have 10 columns. This can make the plot looks less smooth but it will increase performance. More on improving performance later.

# Saving plots

The server is also capable of saving the data that has been sent since the latest plot has been initialized (if a new plot configuration is sent, the existing data will be wiped). To do this, you can either press the botton at the end of the server that says 'save plot', or trigger the save with the client using the ```client.save_plot(log_name)``` function. 

By default, the server will save the plot in the directory where the server was run. A relative file path can be supplied to the server with the -sd flag
````python3 -m rtplot.server -sd ./saved_plots``
And the file name can also be modified using the -sn flag
````python3 -m rtplot.server -sn test_plot``
Note that a timestamp will be appended to the end of the plot name to be able to determine which plot is the newest. 

## Save data without plotting it
You can have data that is not displayed in the screen but is still transmitted to the server and saved. To achieve this, you need to add a special dictionary configuration that only has one key called ```'non_plot_labels'``` that indicates what names the data that you are storing have. Example: 
```python
non_plot_dict = {'non_plot_labels':['data0','data1','data2']}
```
This example will expect you to send three additional datapoints to the ones displayed that will be saved when the save plot is triggered. By convention, you should add this dictonary to the end of the list of dictionaries that are sent to the server.
```python
plots = [plot_config_0, plot_config_1,non_plot_dict]
client.initialize_plots(plots)
```
 
# Additional networking details

There are two main ways that you can connect to transmit information. Either the computer that runs the server knows what IP the client is (server connects to client), or the client knows which IP the server has (server connects to client). For either option, follow the steps bellow:

## Server connects to client
This is accomplished by running the server with the IP address of the pi as an argument.

```
python3 server.py -p xxx.xxx.xxx.xxx
```

Where xxx.xxx.xxx.xxx is the IP address of the pi. No additional configuration is needed on the client side.


## Client connects to server
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

Even though the plotter is built to be fast, if you have enough traces in the screen it can cause it to slow down. The bottleneck in the code is redrawing the traces. In particular, the amount of pixels it has to redraw will close it down (weird bottleneck, I know). To get around this you can do serveral things to improve the frames per second of the plotter. 

- Fix y range. The easiest way to get a significant increase in frames per second is to set the 'yrange' configuration of the plot. If you are having slower than desired performance this is the first step I would take. 

- Plot multiple points at the same time. You can redraw the plot after multiple datapoints instead of updating every single data point. This will cause the plotter to look un-smooth if too many points are sent at the same time. This can be done in one of two ways:
  * Pass in the '-s' flag along with an integer to the server. This will cause the server to skip datapoints between plot refreshing. For example,
  ```python3 -m rtplot.server -s 5```
  will refresh the plot once it receives 5 transmissions of data. If you set the -a flag in the server, it will automatically update the skip rate. This is only good to experiment to find the skip rate that works for you and bad if you want the time data to have the correct timestamps since the rate at which you consume data will change. The adapted rate is printed to the terminal
  
  * Send a batch of data from the client. Using a 2-d numpy array, the first axis will represent the amount of traces in the plot configuration and the second axis will determine how many datapoints you want to send. The server will automatically determine how much data you are sending. This stacks with the server's '-s' flag. 

- Reduce the amount of pixels that you have to plot. If you reduce the size of the plotter window, or reduce the resolution of the monitor. 

- Reduce the line width of the traces. There is an option in the plotter configuration dictionary to increase the line width of each trace. While this makes the lots much easier to read it also makes it much slower. Therefore, keeping the line width at a minimum helps to keep the speed up. 



# [Example Code](https://github.com/jmontp/rtplot/blob/master/rtplot/example_code.py)


# Example Image
![alt text](https://github.com/jmontp/rtplot/blob/master/.images/rtplot_example1.png "Example 1")

![alt text](https://github.com/jmontp/rtplot/blob/master/.images/rtplot_example2.png "Example 2")
