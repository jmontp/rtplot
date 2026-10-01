"""Typed configuration for the signal and FFT example."""
from rtplot.client import Plot, PlotRow
from run import run


if __name__ == '__main__':
    run([PlotRow([
        Plot(names=['signal'], title='Live signal', xrange=1024,
             xlabel='Sample in rolling window', ylabel='Amplitude', yrange=(-1.5, 1.5)),
        Plot(names=['magnitude'], id='spectrum', mode='xy', xscale='log',
             title='FFT spectrum', xlabel='Frequency (Hz)', ylabel='Amplitude (dB re 1)',
             yrange=(-100, 5)),
    ], columns=2)])
