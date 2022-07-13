#Common imports
import numpy as np 
import pandas as pd

#File dialog impots
import tkinter as tk
from tkinter import filedialog

#Import plotting
import matplotlib.pyplot as plt

#Get file path to numpy plot
root = tk.Tk()
root.withdraw()
file_path = filedialog.askopenfilename()

#Read in the dataframe
data = pd.read_parquet(file_path)

#We store the subplots in the last columns
subplots = data.values[-1,:-1]
num_subplots = int(np.max(subplots))+1
fig,axs = plt.subplots(num_subplots,1,sharex=True)

#Convert axis
if isinstance(axs, np.ndarray) != True:
	axs = [axs]

time = data['Time(s)'][:-1]

#Get the trace names from the columns
trace_names = data.columns

#Plot the data
#Set which trace goes in which plot
legend_handles = [[] for i in range(num_subplots)]
for i,subplot in enumerate(subplots):
    k = int(subplot)
    handel, = axs[k].plot(time,data.values[:-1,i], label=trace_names[i])
    legend_handles[k].append(handel)

#Add each legend
for ii in range(num_subplots):
    axs[ii].legend(handles=legend_handles[ii])

#Show the plot
plt.show()
