# 04 – Typed configuration

Same runtime behavior as [example 03](../03_interactive_controls/),
rewritten against the **typed** configuration API. rtplot accepts two
equivalent ways to describe a layout:

| Form | Example 03 uses | Example 04 uses |
|---|---|---|
| **Dict-based** | ✅ | — |
| **Typed dataclasses** | — | ✅ |

Both serialize to the same JSON on the wire, so pick whichever feels
better. The typed form trades a few more imports for autocomplete, type
checking, and better error messages on typos.

## Run it

```bash
# terminal 1
python -m rtplot.server_browser

# terminal 2
python run.py
```

## What changed vs. example 03

Same plot, same controls, same loop. Only the `initialize_plots` call
differs:

```python
from rtplot.client import Plot, ControlsRow, Button, Slider, Dial, Display, Text

client.initialize_plots([
    Plot(
        names=["signal"],
        colors=["b"],
        yrange=(-6, 6),
        title="Interactive controls (typed API)",
        ylabel="amplitude",
    ),
    ControlsRow([Button("reset", "Reset"), Button("pause", "Pause")]),
    ControlsRow([Slider("gain", "Gain", min=0, max=5, value=1.0,
                        step=0.1, format="{:.2f}")]),
    ControlsRow([Dial("freq", "Freq (Hz)", min=0.1, max=5.0, value=1.0,
                      step=0.05, sensitivity=0.5, format="{:.2f}")]),
    ControlsRow([
        Text("status", "Status", value="running"),
        Display("elapsed", "t (s)", format="{:.1f}"),
    ]),
])
```

Things you get for free:

- **Autocomplete** — your editor lists every valid field on `Plot`,
  `Slider`, etc.
- **Typo catches** — `Plot(namse=[...])` fails immediately with
  `TypeError`, instead of silently sending an ignored `namse` key.
- **Required fields enforced** — `Slider(min=0, max=5)` raises if you
  forget `id` or `label`.

## Mix and match

The dispatch is duck-typed on `.to_dict()`, so you can mix typed and
dict items freely while migrating:

```python
client.initialize_plots([
    Plot(names=["signal"], yrange=(-6, 6)),
    {"controls": [{"type": "button", "id": "reset", "label": "Reset"}]},
])
```

See [`docs/api.md`](../../docs/api.md#plot-configuration) for the full
field reference (keys on dicts == fields on the dataclasses).
