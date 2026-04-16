# 01 – Hello, sine wave

The smallest useful rtplot script: stream a single 1 Hz sine wave from
your Python code to a live browser plot.

[**▶ View the snapshot**](snapshot.html)

## Run it

Open two terminals. In the first:

```bash
python -m rtplot.server_browser
```

That prints a URL like `http://localhost:8050` — open it in a browser.

In the second terminal:

```bash
python run.py
```

You'll see the sine wave rolling through the browser tab for 8 seconds.
When the script ends it writes `snapshot.html` alongside itself, a
static HTML file you can open offline and that reproduces the plot
exactly as it looked when the script finished.

## The three client calls

```python
from rtplot import client

client.local_plot()                # point at server on localhost
client.initialize_plots([...])     # describe the plot layout
client.send_array(value)           # push one sample
```

Everything else in the script is styling and the snapshot save at the
end.

- `client.local_plot()` is shorthand for `client.configure_ip("127.0.0.1")`. If your server lives on another machine, pass its IP instead.
- `client.initialize_plots([{"names": ["signal"], ...}])` declares a single plot with one trace called `signal`. The `names` list is the only required field; `colors`, `title`, `yrange`, `xlabel`, `ylabel`, `line_width`, `line_style`, `xrange` are all optional styling — see the main README for the full schema.
- `client.send_array(value)` accepts a float, a list of floats, a 1-D numpy array, or a 2-D numpy array. The call is non-blocking, ~microsecond cost, safe to call from a tight loop.

## What `save_snapshot` does

`client.save_snapshot("snapshot.html", animate=True)` does an HTTP GET
against the server's `/snapshot.html` endpoint and writes the response
to disk. The file is ~65 KB: inlined uPlot JS + CSS, embedded JSON with
the most recent window of trace data, and a ~30-line bootstrap that
calls `new uPlot(opts, data, container)` on page load. With
`animate=True` the snapshot also embeds a small replay loop so the plot
keeps scrolling, which looks nicer in a gallery.
