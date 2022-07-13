import client
import numpy as np
import time


#The first section is dedicated to configuring IP
# You do NOT need to do this if the server.py is connecting to the pi
# Uncomment "client.local_plot()" if you want to plot locally 

#--------------------------------------------------------------------------------------------------
#Change the ip address that you are going to send data to
# In this example we configure it to plot locally (127.0.0.1 is the address of the local host)
# client.configure_ip("127.0.0.1")

#Can also specify port, default is 5555
# client.configure_ip("127.0.0.1:5555")
# client.plot_to_neurobionics_tv()

#If you want to plot locally, there is already a function that is equivalent to the above
client.local_plot()
#--------------------------------------------------------------------------------------------------


#--------------------------------------------------------------------------------------------------
#Initialize one plot with one trace
client.initialize_plots()


#Send 1000 data points
for i in range(1000):

    #Send data
    client.send_array(np.random.randn())

    time.sleep(0.01)
#--------------------------------------------------------------------------------------------------





time.sleep(2)





#--------------------------------------------------------------------------------------------------
#Initialize one plot with 5 traces
client.initialize_plots(5)


#Send 1000 data points
for i in range(1000):

    #Send data
    client.send_array(np.random.randn(5,1))
#--------------------------------------------------------------------------------------------------





time.sleep(2)





#--------------------------------------------------------------------------------------------------
#Initialize one plot with oen trace named 'test_trace'
client.initialize_plots('test_trace')


#Send 1000 data points
for i in range(1000):

    #Send data
    client.send_array(np.random.randn(1,1))
#--------------------------------------------------------------------------------------------------





time.sleep(2)






#--------------------------------------------------------------------------------------------------
#Initialize one plot with three traces
client.initialize_plots(['test 1', 'test2', 'test 5'])


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

#--------------------------------------------------------------------------------------------------





time.sleep(2)





#--------------------------------------------------------------------------------------------------
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
#--------------------------------------------------------------------------------------------------



time.sleep(2)



#--------------------------------------------------------------------------------------------------
#Initialize with more complex configuration

#The only required field is 'names' 

plot_config1 = {'names' : ['plot1_trace1', 'plot1_trace2'],
                'colors' : ['r','b'],
                'line_style': ['','-'],
                'title' : "Plot 1 Title",
                'ylabel': "Plot 1 y label",
                'xlabel': "Plot 1 x label",
                'yrange': [-1,1]
                }

plot_config2 = {'names' : ['plot2_trace1'],
                'colors' : ['r','b'],
                'line_style': ['-',''],
                'title' : "Plot 2 Title",
                'ylabel': "Plot 2 y label",
                'xlabel': "Plot 2 x label",
                'yrange': [-1,1]
                }

client.initialize_plots([plot_config1, plot_config2])


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
#--------------------------------------------------------------------------------------------------


#--------------------------------------------------------------------------------------------------
#Initialize with more complex configuration

#The only required field is 'names' 

plot_config1 = {'names' : ['plot1_trace1', 'plot1_trace2'],
                'colors' : ['r','b'],
                'line_style': ['','-'],
                'title' : "Plot 1 Title",
                'ylabel': "Plot 1 y label",
                'xlabel': "Plot 1 x label",
                'yrange': [-1,1]
                }

plot_config2 = {'names' : ['plot2_trace1'],
                'colors' : ['r','b'],
                'line_style': ['-',''],
                'title' : "Plot 2 Title",
                'ylabel': "Plot 2 y label",
                'xlabel': "Plot 2 x label",
                'yrange': [-1,1],
                'xrange':500
                }

client.initialize_plots([plot_config1, plot_config2])


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
#--------------------------------------------------------------------------------------------------
