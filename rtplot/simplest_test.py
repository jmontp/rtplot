import client
import numpy as np
import time


#--------------------------------------------------------------------------------------------------
#Change the ip address that you are going to send data to
# In this example we configure it to plot locally (127.0.0.1 is the address of the local host)
client.configure_ip("127.0.0.1")

#Can also specify port, default is 5555
client.configure_ip("127.0.0.1:5555")

#If you want to plot locally, there is already a function that is equivalent to the above
client.local_plot()
#--------------------------------------------------------------------------------------------------


#--------------------------------------------------------------------------------------------------
#Initialize one plot with one trace
client.initialize_plots()


for i in range(1000):

    #Send data
    client.send_array(np.random.randn())
#--------------------------------------------------------------------------------------------------





time.sleep(2)





#--------------------------------------------------------------------------------------------------
#Initialize one plot with 5 traces
client.initialize_plots(5)


for i in range(1000):

    #Send data
    client.send_array(np.random.randn(5,1))
#--------------------------------------------------------------------------------------------------





time.sleep(2)





#--------------------------------------------------------------------------------------------------
#Initialize one plot with oen trace named 'test_trace'
client.initialize_plots('test_trace')


for i in range(1000):

    #Send data
    client.send_array(np.random.randn(1,1))
#--------------------------------------------------------------------------------------------------





time.sleep(2)





#--------------------------------------------------------------------------------------------------
#Initialize one plot with three traces
client.initialize_plots(['test 1', 'test2', 'test 5'])


for i in range(1000):

    #Send data
    client.send_array(np.random.randn(3,1))
#--------------------------------------------------------------------------------------------------





time.sleep(2)





#--------------------------------------------------------------------------------------------------
#Initialize three subplots with one trace each
client.initialize_plots([['test 1'], ['test2'], ['test 5']])


for i in range(1000):

    #Send data
    client.send_array(np.random.randn(3,1))
#--------------------------------------------------------------------------------------------------
