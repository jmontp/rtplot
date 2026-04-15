import client
import numpy as np
import time


#The first section is dedicated to configuring IP
# You do NOT need to do this if the server.py is connecting to the pi
# Uncomment "client.local_plot()" if you want to plot locally 

#------------------------------------------------------------------------------
#Change the ip address that you are going to send data to
# In this example we configure it to plot locally (127.0.0.1 is the address of
# the local host)
# client.configure_ip("127.0.0.1")

#Can also specify port, default is 5555
# client.configure_ip("127.0.0.1:5555")
# client.plot_to_neurobionics_tv()

#If you want to plot locally, there is already a function that is equivalent 
# to the above
client.local_plot()
#------------------------------------------------------------------------------


#------------------------------------------------------------------------------
#Initialize one plot with one trace
client.initialize_plots()


#Send 1000 data points
for i in range(1000):

    #Send data
    client.send_array(np.random.randn())

    time.sleep(0.01)
#------------------------------------------------------------------------------


time.sleep(2)


#------------------------------------------------------------------------------
#Initialize one plot with 5 traces
client.initialize_plots(5)


#Send 1000 data points
for i in range(1000):

    #Send data
    client.send_array(np.random.randn(5,1))
#------------------------------------------------------------------------------


time.sleep(2)


#------------------------------------------------------------------------------
#Initialize one plot with oen trace named 'test_trace'
client.initialize_plots('test_trace')


#Send 1000 data points
for i in range(1000):

    #Send data
    client.send_array(np.random.randn(1,1))
#------------------------------------------------------------------------------


time.sleep(2)


#------------------------------------------------------------------------------
#Initialize one plot with three traces
client.initialize_plots(['test 1', 'test2', 'test 5'])


#Send 1000 data points
for i in range(10000):

    #Generate Data -> (This would be your code)
    var1 = np.random.randn()
    var2 = np.random.randn()
    var3 = np.random.randn()
    
    #Create array (or numpy array) with data
    data = [var1,var2,var3]

    #Equivalently, send as columns vector
    #data = np.array([[var1],[var2],[var3]])

    #Send data
    client.send_array(data)

    time.sleep(0.001)


#------------------------------------------------------------------------------


time.sleep(2)


#------------------------------------------------------------------------------
#Initialize three subplots with one trace each
client.initialize_plots([['test 1'], ['test2'], ['test 5']])


#Send 1000 data points
for i in range(1000):

    #Generate Data -> (This would be your code)
    var1 = np.random.randn()
    var2 = np.random.randn()
    var3 = np.random.randn()
    
    #Create array (or numpy array) with data
    data = [var1,var2,var3]
    #Equivalently, send as columns vector
    #data = np.array([[var1],[var2],[var3]])

    #Send data
    client.send_array(data)
#------------------------------------------------------------------------------


time.sleep(2)


#------------------------------------------------------------------------------
#Initialize with more complex configuration

#The only required field is 'names' 

plot_config1 = {'names' : ['plot1_trace1', 'plot1_trace2'],
                'colors' : ['r','b'],
                'line_style': ['','-'],
                'title' : "Plot 1 Title",
                'ylabel': "Plot 1 y label",
                'xlabel': "Plot 1 x label",
                'line_width':[2,2],
                'yrange': [-1,1]
                }

plot_config2 = {'names' : ['plot2_trace1'],
                'colors' : ['r','b'],
                'line_style': ['-',''],
                'title' : "Plot 2 Title",
                'ylabel': "Plot 2 y label",
                'xlabel': "Plot 2 x label",
                'line_width':[2],
                'yrange': [-1,1]
                }

client.initialize_plots([plot_config1, plot_config2])


#Send 1000 data points
for i in range(100000):

    #Generate Data -> (This would be your code)
    var1 = np.random.randn()
    var2 = np.random.randn()
    var3 = np.random.randn()

    #Create array (or numpy array) with data
    data = [var1,var2,var3]
    #Equivalently, send as columns vector
    #data = np.array([[var1],[var2],[var3]])

    #Send data
    client.send_array(data)

    time.sleep(1/3000)
#------------------------------------------------------------------------------


time.sleep(2)


#------------------------------------------------------------------------------
#Send data that will not be plotted
plot_config1 = {'names' : ['plot1_trace1', 'plot1_trace2'],
                'colors' : ['r','b'],
                'line_style': ['','-'],
                'title' : "Non plot test 1",
                'ylabel': "Plot 1 y label",
                'xlabel': "Plot 1 x label",
                'yrange': [-1,1]
                }

plot_config2 = {'names' : ['plot2_trace1'],
                'colors' : ['r','b'],
                'line_style': ['-',''],
                'title' : "Non plot test 2",
                'ylabel': "Plot 2 y label",
                'xlabel': "Plot 2 x label",
                'yrange': [-1,1],
                'xrange':500
                }

#Add non-plot data labels
non_plot_config = {"non_plot_labels" : ['non_plot_test_data_1',
                                        "non_plot_test_data_2"]}

client.initialize_plots([plot_config1, plot_config2,non_plot_config])


#Send 1000 data points
for i in range(1000):

    #Generate Data -> (This would be your code)
    var1 = np.random.randn()
    var2 = np.random.randn()
    var3 = np.random.randn()
    var4 = np.random.randn()
    var5 = np.random.randn()

    #Create array (or numpy array) with data
    data = [var1,var2,var3,var4,var5]
    #Equivalently, send as columns vector
    #data = np.array([[var1],[var2],[var3]])

    #Send data
    client.send_array(data)
#------------------------------------------------------------------------------


time.sleep(2)


#------------------------------------------------------------------------------
# Configurable UI controls: buttons, sliders, and display boxes.
#
# A 'controls' row goes alongside plot rows in the same initialize_plots call.
# Each row holds a small number of elements. Poll the return channel from
# your loop to read the latest slider values and any button events that
# fired since the previous poll, and push read-only values into the
# display boxes with client.set_display().
plot_config = {
    'names': ['signal'],
    'colors': ['b'],
    'title': 'Controls demo',
    'ylabel': 'amplitude',
    'yrange': [-6, 6],
}

controls_row_1 = {'controls': [
    {'type': 'button', 'id': 'reset', 'label': 'Reset t'},
    {'type': 'button', 'id': 'pause', 'label': 'Pause'},
    {'type': 'slider', 'id': 'gain', 'label': 'Gain',
     'min': 0, 'max': 5, 'value': 1.0, 'step': 0.1, 'format': '{:.2f}'},
]}
controls_row_2 = {'controls': [
    {'type': 'slider', 'id': 'freq', 'label': 'Freq (Hz)',
     'min': 0.1, 'max': 5.0, 'value': 1.0, 'step': 0.1, 'format': '{:.2f}'},
    {'type': 'display', 'id': 't', 'label': 't (s)', 'format': '{:.2f}'},
    {'type': 'display', 'id': 'amp', 'label': 'amp', 'format': '{:.2f}'},
]}

client.initialize_plots([plot_config, controls_row_1, controls_row_2])

running = True
t0 = time.time()
for i in range(5000):
    ctrl = client.poll_controls()
    for btn in ctrl.buttons:
        if btn == 'reset':
            t0 = time.time()
        elif btn == 'pause':
            running = not running

    gain = ctrl.values.get('gain', 1.0)
    freq = ctrl.values.get('freq', 1.0)

    if running:
        t = time.time() - t0
        amp = gain * np.sin(2 * np.pi * freq * t)
    else:
        t = time.time() - t0
        amp = 0.0

    client.set_display('t', t)
    client.set_display('amp', amp)
    client.send_array(amp)

    time.sleep(0.01)
#------------------------------------------------------------------------------


