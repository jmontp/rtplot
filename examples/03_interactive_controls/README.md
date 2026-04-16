# 03 – Interactive controls

Buttons, sliders, dials, and display boxes that drive your Python
loop live. The user twists a knob in the browser; your script reads
the new value on the next iteration.

[**▶ View the snapshot**](snapshot.html)

> The snapshot captures only the **plot** portion — the control
> widgets need a live server to be interactive, so run the script
> yourself to try them out.

## Run it

```bash
# terminal 1
python -m rtplot.server_browser

# terminal 2
python run.py
```

Open the browser tab and you'll see:

- A **Reset** button that rewinds the elapsed-time display to zero
- A **Pause** button that toggles the output between the active
  signal and a flat zero
- A **Gain** slider (0 → 5) that scales the amplitude in real time
- A **Freq** dial (0.1 → 5 Hz) you can spin to retune the signal
- A **Status** text field that switches between "running" and
  "paused" depending on the button state
- An **elapsed t (s)** numeric display the Python loop pushes into
  every iteration

## The control-row schema

Controls live alongside plots in the same `initialize_plots` call;
you wrap a list of elements in `{"controls": [...]}`:

```python
client.initialize_plots([
    plot_dict,
    {"controls": [
        {"type": "button", "id": "reset",  "label": "Reset"},
        {"type": "button", "id": "pause",  "label": "Pause"},
    ]},
    {"controls": [
        {"type": "slider", "id": "gain",
         "label": "Gain", "min": 0, "max": 5, "value": 1.0},
    ]},
    {"controls": [
        {"type": "dial", "id": "freq",
         "label": "Freq (Hz)", "min": 0.1, "max": 5.0, "value": 1.0,
         "sensitivity": 0.5},
    ]},
    {"controls": [
        {"type": "text",    "id": "status", "label": "Status", "value": "running"},
        {"type": "display", "id": "elapsed", "label": "t (s)", "format": "{:.1f}"},
    ]},
])
```

Each row is rendered as a horizontal group; you can pack more than
one element per row if it fits nicely.

## The poll API

```python
ctrl = client.poll_controls()
```

Returns a `ControlState(values, buttons)` namedtuple:

- `ctrl.values` — dict of `{slider_or_dial_id: current_float_value}`,
  including the `value:` field you declared as the initial.
- `ctrl.buttons` — list of button ids fired since the last poll, in
  order. The list is drained on each call.

`poll_controls()` is non-blocking and cheap to call every loop
iteration. No threads, no callbacks, no missed button events.

## The push API

```python
client.set_display("elapsed", 12.34)   # number → numeric display box
client.set_display("status", "paused") # string → text field
```

`set_display(id, value)` routes to the display element with matching
`id`. Numeric values get formatted via the element's `format` string
(`"{:.1f}"`, `"{:.3f}"`, etc.); strings are shown verbatim in `text`
elements.
