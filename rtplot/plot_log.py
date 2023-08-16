# Common imports
import numpy as np 
import pandas as pd

# File dialog impots
import tkinter as tk
from tkinter import filedialog

# Import plotting
import matplotlib.pyplot as plt

# Get file path to numpy plot
root = tk.Tk()
root.withdraw()
file_path = filedialog.askopenfilename()

# Read in the dataframe
data = pd.read_parquet(file_path)

# print the columns in the data
print(f"Columns of data in the file: {list(data.columns)}")

# We store the subplots in the last columns
subplots = data.values[-1,:]
num_subplots = int(np.max(subplots))
fig,axs = plt.subplots(num_subplots,1,sharex=True)

# Convert axis
if isinstance(axs, np.ndarray) != True:
	axs = [axs]

time = data['Time(s)'][:-1]

# Create the legend handles for each subplot
legend_handles = {i:[] for i in range(num_subplots)}

# Plot the data
for col_name in data.columns:
     #Skip the time column
    if col_name == 'Time(s)':
        continue
    # Get the subplot index
    subplot_idx = int(data[col_name].values[-1])
    # If we are non-plot data don't plot
    if subplot_idx == -1:
        continue
    handle, = axs[subplot_idx].plot(time,data[col_name][:-1],label=col_name)
    # Comment this line in if you want to have the x-axis be the index
    # handle, = axs[subplot_idx].plot(data[col_name][:-1],label=col_name)

    # Add the legend handle
    legend_handles[subplot_idx].append(handle)

# Add the x label
axs[-1].set_xlabel('Time (s)')

# Add each legend
plt.legend()
for ii in range(num_subplots):
    axs[ii].legend(handles=legend_handles[ii])

#Show the plot
plt.show()

