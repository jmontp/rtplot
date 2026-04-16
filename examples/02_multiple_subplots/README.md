# 02 – Multiple subplots

Show three different signals side by side (stacked vertically) with
per-plot titles, colors, and y-ranges: a sine + cosine pair, a damped
oscillation, and a random walk.

[**▶ View the snapshot**](snapshot.html)

## Run it

```bash
# terminal 1
python -m rtplot.server_browser

# terminal 2
python run.py
```

## What's new vs. the hello-world example

**Multiple plots in one call**: `initialize_plots` takes a *list* of
plot dicts. Each list entry becomes its own subplot.

```python
client.initialize_plots([
    {"names": ["sin", "cos"], ...},        # subplot 1, two traces
    {"names": ["impulse response"], ...},   # subplot 2
    {"names": ["random walk"], ...},        # subplot 3
])
```

**Multiple traces in one plot**: when a plot's `names` list has more than
one entry, each entry is a separate trace rendered on the same axes.

**Single `send_array` covers all plots and all traces**: you pass a flat
list whose length equals the total number of traces across every plot.
In this example there are 4 traces in total (`sin`, `cos`, `impulse
response`, `random walk`) so each call:

```python
client.send_array([sin_v, cos_v, damped, walk])
```

ships one sample for every trace in one shot. rtplot splits the flat
list across the declared plots using the `names` lists as the contract.

**Per-plot styling**: `yrange`, `title`, `ylabel`, `xlabel`, `colors`,
`line_style`, `line_width`, `xrange` are all per-subplot — no global
styling pool.

## Performance note

Pinning a `yrange` on each plot is the biggest single perf win for
high-rate streams, because rtplot can skip the autoscale recomputation
on every frame.
