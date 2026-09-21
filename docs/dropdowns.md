# Dropdown controls

Requires **better-rtplot 0.7.0 or later on both client and browser server**.
Older servers trigger a compatibility warning; dropdown support and disabled-state
handling must not be assumed when support is unconfirmed. The Qt server does not
support browser controls.

```python
from rtplot import client
from rtplot.client import ControlsRow, Dropdown, Plot

client.initialize_plots([
    ControlsRow([Dropdown('source', 'Signal source', [
        'raw', {'value': 'filtered', 'label': 'Filtered signal'},
    ], value='raw')]),
    Plot(names=['Signal']),
])

# In the streaming loop:
source = client.poll_controls().values.get('source', 'raw')

# Application-driven selection, without rebuilding plots:
client.set_dropdown('source', 'filtered')
```

Equivalent dictionary control:

```python
{'type': 'dropdown', 'id': 'source', 'label': 'Signal source',
 'options': ['raw', {'value': 'filtered', 'label': 'Filtered signal'}],
 'value': 'raw'}
```

Options are a non-empty list of strings or dictionaries with a string `value`
and optional string `label`. Values must be unique; labels may repeat. An omitted
initial `value` selects the first option. Explicit values must match an option.
`Dropdown` also accepts optional `height`, like other controls. Options are fixed
for a layout; changing the option list requires full initialization with its usual
history-reset semantics.

Selections are strings in `poll_controls().values`, not button events. Native
keyboard/touch selection sends the usual control event; focus, resizing and
presentation updates send no application commands. The server validates choices,
caches the latest value per source, and synchronizes selections across viewers
and reconnects. A full replacement initializes dropdowns from their declarations.
`set_dropdown()` validates IDs/values and requires confirmed server support; it
uses the existing best-effort string-value channel with layout generation checks.
Invalid or stale application updates are ignored by the server. No success of an
application or hardware operation is implied by selecting an option.

All existing `set_ui_state()` properties apply. `selected` styles the whole control;
it is independent of which option is selected. Disabled controls cannot send
selection events, including from keyboard interaction. `reason` appears beside
the control. Hiding controls preserves selections; `busy` does not disable them.
Existing `set_text_input()` remains for text inputs; use `set_dropdown()` for choices.

Try the [dictionary example](../examples/08_dropdown/run.py) or
[typed example](../examples/08_dropdown/run_typed.py): start `rtplot-server`, then
run `python examples/08_dropdown/run.py` and open the server URL. Choose a waveform
or use Reset waveform to demonstrate an application-driven selection.
