# Grid picker controls

Requires **better-rtplot 0.8.0 or later on both client and browser server**
(capability `grid_picker_v1`). The Qt server does not support browser controls.
This page documents the generic control; the [requirements](grid-picker-requirements.html)
describe the controller-bank experiment that motivated it.

A grid picker displays one discrete coordinate pair. rtplot never interprets the
coordinates: the application maps `(method, x, y)` (or any other context) to a
checkpoint, decides whether to switch, and confirms the result. Clicking a cell
**requests** it; the highlighted cell changes only after the application confirms.

```python
from rtplot import client
from rtplot.client import ControlsRow, Dropdown, GridPicker

client.initialize_plots([ControlsRow([
    Dropdown('method', 'Anti-shake method', ['M', 'D', 'E']),
    GridPicker('weights', 'Training weights',
               x_options=[{'value': 'j1', 'label': 'J1: 1e-4'}, {'value': 'j2', 'label': 'J2: 1e-3'}],
               y_options=[{'value': 'w1', 'label': 'W1: ×0.5'}, {'value': 'w2', 'label': 'W2: ×1'}],
               x_label='Jerk weight', y_label='Anti-shake weight multiplier', value=('j2', 'w2')),
])])

state = client.poll_controls()
for request in state.grid_requests:          # GridRequest(id, x, y, request_id)
    ...                                      # validate, load, then confirm or reject
client.set_grid_picker('weights', 'j1', 'w2', request_id=request.request_id,
                       values={'method': 'D'})
```

Equivalent dictionary control:

```python
{'type': 'grid_picker', 'id': 'weights', 'label': 'Training weights',
 'x_label': 'Jerk weight', 'y_label': 'Anti-shake weight multiplier',
 'x_options': [{'value': 'j1', 'label': 'J1: 1e-4'}, {'value': 'j2', 'label': 'J2: 1e-3'}],
 'y_options': [{'value': 'w1', 'label': 'W1: ×0.5'}, {'value': 'w2', 'label': 'W2: ×1'}],
 'value': {'x': 'j2', 'y': 'w2'}}
```

## Declaration

- `x_options` and `y_options` are non-empty lists of strings or
  `{'value', 'label'}` dictionaries. Values are stable, non-empty IDs, unique per
  axis; labels may change meaning only through a new layout. Axes may have any
  finite length.
- X increases left to right. **`y_options[0]` is the bottom row**, so rows
  increase from bottom to top. Column and row labels show the option labels;
  put exact values there (for example `J2: 1e-3`).
- `value` is the application-declared default confirmed pair; omitted, it is the
  first X and first Y option. `active=False` declares it as remembered but not
  active. Invalid IDs raise `ValueError`.
- Cells are equal-sized buttons of at least 44 × 44 CSS px. Many columns scroll
  horizontally inside the control instead of widening the page.

## Requests

`poll_controls()` returns `ControlState(values, buttons)` with an additional
`grid_requests` attribute: a list of `GridRequest(id, x, y, request_id)` received
since the previous poll, in arrival order, drained once per poll.
`ControlState` still unpacks as `(values, buttons)`.

- Only click/tap or Enter/Space on a cell sends a request. Focus, hover, arrow
  keys, resizing, presentation updates, reconnects and initialization send none.
- The server assigns each request a unique `request_id`, validates the declared
  coordinates, control and section availability, and the cell's `enabled`
  override, and drops requests from superseded layouts or sources. The client
  drops stale-generation and stale-source requests, as for buttons.
- Requests are not selections. Double clicks produce two requests; the
  application deduplicates them (for example, a request for the active
  checkpoint is acknowledged without a switch).

Method dropdowns stay ordinary dropdowns. When a method change and a grid request
arrive in the same poll, resolve one explicit final pair, e.g. the latest
dropdown value with the last grid request, and switch at most once. A method
change alone resolves at the last **confirmed** coordinates. Handle requests
sequentially; while a load is in progress keep only the latest resolved choice.

## Confirmation, rejection and pending state

```python
client.set_grid_picker(control_id, x, y, *, active=True, cells=None, message=None,
                       request_id=None, values=None, ui_state=None)
client.reject_grid_request(control_id, request_id, reason, *, values=None, ui_state=None)
client.grid_selection(control_id)       # -> (x, y, active) as last confirmed here
client.grid_cell_state(control_id, x, y)
client.server_capabilities()            # frozenset acknowledged at initialization
```

`set_grid_picker()` publishes the confirmed selection without producing input
events or rebuilding plots. Its parts reach every viewer in **one update**, so a
viewer never sees a new cell with an old readout:

- `values`: dropdown, text, text input or display values that change with the
  selection, such as `{'method': 'D', 'active_model': 'D · J2 · W3'}`. Linked
  dropdown values also update the application's own `poll_controls().values`.
- `ui_state`: an additional `set_ui_state()` patch (for example, marking a
  reference button `selected`).
- `cells`: a full replacement of per-cell overrides, as `{(x, y): {...}}` or
  `{x: {y: {...}}}` with `enabled`, `busy`, `reason` and `label`. `None` keeps
  the current overrides. Cell labels and availability change without layout
  initialization; coordinate IDs stay stable.
- `message`: status text under the grid (for example a rejection reason);
  `None` keeps it, `''` clears it.
- `request_id`: the request this update resolves.

After a request, every viewer shows the cell as **◌ Requested** with
“awaiting confirmation” until an update carries that `request_id` (accepted or
rejected), the confirmed active pair equals the requested pair, a newer request
replaces it, or the source/layout changes. Every call is a new revision, so
repeated identical rejections still resolve their requests.

`reject_grid_request()` keeps the confirmed pair and active flag, shows `reason`,
and resolves the request. Pass `values` to restore a dropdown the user changed,
for example `values={'method': confirmed_method}`. Never substitute another
checkpoint or reset coordinates on rejection.

`active=False` keeps the coordinates as **○ Remembered** without marking any cell
active, for example while a matched reference is active. A later grid request or
method change can return to the remembered coordinates.

Grid properties are ordinary UI state: `set_ui_state({'controls': {'weights':
{'busy': True, 'message': 'Loading…'}}})` works, and `None` restores the
declared default. All existing control properties apply. Control-wide
`enabled=False` disables every cell and links its `reason`; `busy` alone
disables nothing. A cell with `enabled=False` remains focusable, is exposed with
`aria-disabled`, and shows its reason inside the cell (linked with
`aria-describedby`); clicks and keyboard activation do nothing and the server
rejects bypassing requests.

## Keyboard and screen readers

Tab enters the grid at the focused or confirmed cell (roving tab stop). Arrow keys
move focus (Up moves to a higher row), Home/End move to the first/last column,
and Enter/Space request the focused cell. Each cell's accessible name includes
both axis labels and option labels, the cell label, and its state (active,
remembered, requested, busy, unavailable). A status line announces the active
or remembered pair and any outstanding request.

## Viewers, reconnects and recovery

The browser server keeps the confirmed state, pending requests and linked values
per source. All viewers converge on them, including after reloads or WebSocket
reconnects, and no request is replayed. The client republishes its state with the
UI-state heartbeat; a restarted server restores the confirmed selection and
linked values. A new layout or source starts from the declared defaults.

## Older servers

`initialize_plots()` raises `RuntimeError` when a layout declares a grid picker
and the server does not acknowledge `grid_picker_v1` (including when the
handshake is skipped or times out). An older server would not enforce cell
availability or confirmed selection. Fall back explicitly, for example to a flat
dropdown with full labels:

```python
try:
    client.initialize_plots(grid_layout)
except RuntimeError:
    client.initialize_plots(flat_dropdown_layout)
```

`set_grid_picker()` also raises `RuntimeError` without the capability.

## Example

[`examples/10_grid_picker`](../examples/10_grid_picker/run.py)
([typed](../examples/10_grid_picker/run_typed.py)) implements a synthetic bank of
27 candidates (three methods × three jerk levels × three anti-shake multipliers)
plus three matched references. It demonstrates method changes that keep X–Y,
“Reference at this jerk”, unavailable cells, switches accepted only with torque
off, loading and warmup, separate Enable, a combined readout, a switch log, and
the flat-dropdown fallback. Its manifest, coefficients and torque are
placeholders, not trained controllers. Start `rtplot-server`, then run
`python examples/10_grid_picker/run.py`.

Hardware policy (torque-off switching, warmup, enable, checkpoint hashes and
logging) belongs to the application; rtplot is the UI transport.

```bash
python -m pytest tests/test_grid_picker_client.py -q
python -m pytest tests/test_grid_picker.py -q
```
