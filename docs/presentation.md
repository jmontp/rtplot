# Responsive presentation

The browser UI in **rtplot 0.6.0+** uses native device-width sizing, permits
browser zoom, and adapts the existing layout without rebuilding plots or controls.
Old configurations require no changes. New options are available in typed
builders and dictionaries; use both client and browser server 0.6.0+ to adopt
them. A client warns when a server does not acknowledge `presentation_v1`.
The existing runtime UI-state API remains unchanged.

## Essential actions and state

```python
from rtplot import client
from rtplot.client import Button, ControlsRow, Section, Text, View

client.initialize_plots([
    ControlsRow([
        Text('hardware', 'Hardware', 'Ready', appearance='state'),
        Button('stop', 'Stop', appearance='danger'),
    ], section='status'),
], view=View(
    sections=[Section('status', 'Status', density='compact', show_heading=False)],
    persistent_section='status',
    essential_controls=['hardware', 'stop'],
))
```

`essential_controls` names existing control IDs. Their **existing elements** move
once at initialization into an unclipped strip under the header, outside all
internally scrolling panels. They retain declaration order, IDs, values, and
event payloads; the list designates membership rather than a new order.
Resizing never reparents or duplicates them.

Essentials remain available when their original section collapses or becomes
hidden. Their own `visible` and `enabled` overrides, source availability, and
disabled reasons still apply. This rule is also enforced by the server. The
application decides which actions matter and validates every command: a label
such as “Stop” never assigns meaning, styling, or success behavior.

The optional `persistent_section` retains its original behavior for other
controls, using a bounded scrolling area. Essential controls are outside that
area. Keep the essential set small (typically a short state readout and one or
two actions). At default font scale, the persistent header/strip targets are
144 px desktop, 180 px portrait phone, and 120 px short landscape. Extra or long
essentials wrap instead of disappearing or being clipped; these are design
budgets, not limits that hide content. Browser zoom and larger font settings can
also increase their height.

## Sections and navigation

`Section` adds these optional properties:

| Property | Default | Behavior |
|---|---|---|
| `navigation` | `"primary"` | `"primary"` links appear directly; `"secondary"` links appear under More. |
| `density` | `"normal"` | `"compact"` reduces section spacing without shrinking touch targets. |
| `show_heading` | `True` | `False` visually omits the heading; its accessible heading/name remains available. |

The navigation is compact on phones and stays in page flow so it does not consume
the essential strip's height budget. Links display the application's section
status with text/symbols. There are no inferred completion rules. Navigation
reveals collapsed sections, closes More, and focuses the heading below persistent
regions. Collapse and navigation remain local to each browser.

Connection health stays in the compact header. Open Settings to see endpoint
details, performance statistics, and server resources; the panel opens below the
persistent strip. Escape closes it and restores focus. Source tabs remain
keyboard accessible and wrap instead of creating page-level overflow.

## Explicit semantic styling and groups

`Button`, `Text`, and `Display` accept `appearance=`; dictionaries use the same
key. The styles are `default`, `help`, `state`, `primary`, `choice`, `warning`,
and `danger`. Help/readout styles suit Text/Display, and action styles suit
buttons. Help messages have no individual border. State readouts use a distinct
surface and a screen-reader status region. An explicit appearance chooses its semantic palette instead of the legacy custom
button `color`; omit appearance to keep that custom color. Warning/danger/primary actions differ
visually; their labels still need to explain their action.

```python
ControlsRow([
    Button('raw', 'Raw', appearance='choice'),
    Button('smooth', 'Smoothed', appearance='choice'),
], section='advanced', title='Source', exclusive=True)
```

`title` labels a group. `exclusive=True` requires button-only contents and
constrains the **authoritative selected state**, without changing click payloads.
Selecting one member through `set_ui_state()` removes the other members'
selected overrides. A patch that selects two members at once is rejected
atomically. Clearing the selected member with `None` leaves the group with no
selection. Other properties, such as reasons and enabled states, are preserved.

```python
# Called by the application only after accepting the requested choice:
client.set_ui_state({'controls': {'smooth': {'selected': True}}})
```

Clicking a choice emits its existing button event. The browser does not select
it optimistically. Buttons remain keyboard accessible with Tab and Enter/Space;
selection is exposed through `aria-pressed` and a compact check mark. Groups wrap
in declaration order.

Equivalent dictionary options:

```python
{'controls': [
    {'type': 'button', 'id': 'raw', 'label': 'Raw', 'appearance': 'choice'},
    {'type': 'button', 'id': 'smooth', 'label': 'Smoothed', 'appearance': 'choice'},
], 'title': 'Source', 'exclusive': True, 'section': 'advanced'}
```

The existing `enabled`, `visible`, `busy`, `selected`, `reason`, section
`status`/`message`, `set_display()`, and `set_text_input()` APIs still work.
Busy never implicitly disables an action. Disabled explanations remain visible
and linked with `aria-describedby`. Moving from an edited text input into
navigation, section headers, or settings preserves its draft without submitting
it. Enter or an ordinary application-area blur retains the text input's commit
behavior.

## Charts and responsive rows

Rows keep the sender's requested column count at widths of **1024 px and above**,
cap it at two columns at **640–1023 px**, and use one column **below 640 px**.
Control groups wrap in the same order. Resizing preserves uPlot instances, trace
mapping, buffered history, zoom, legend selections, runtime state, and input focus.

`Plot(..., min_height=220)` sets a minimum chart height in CSS pixels (an integer
of at least 160). Existing `height`, `colors`, and `line_width` options remain
supported. Line styles accept `solid`, `dashed`, `dotted`, and `dashdot`; the
existing `"-"` dashed shorthand still works. Legends wrap, and their trace toggles
are keyboard accessible. A single-trace title identical to its legend label is
shown once; the legend retains its accessible name and toggle.

The visual design uses consistent spacing, readable typography, subtle chart
surfaces, visible focus rings, and at least 44 × 44 CSS px interactive targets.
Reduced-motion preferences disable incidental animation.

## Examples, screenshots, and checks

Run the [synthetic presentation example](../examples/07_presentation/README.md)
in dictionary or typed form. See the [before/after screenshots](presentation-screenshots/README.md)
for 1440×900, 1024×768, 390×844, 320×568, and 844×390.

```bash
python -m pytest tests/test_presentation_client.py tests/test_sections_client.py tests/test_ui_state.py tests/test_plot_rows.py tests/test_plot_visibility.py -q
python -m pytest tests/test_communication.py tests/test_sections.py tests/test_presentation.py -q
```

Run client unit tests separately from server tests because importing the client
opens its default ZMQ sockets. Browser tests check geometry, native phone width,
target sizes, persistent height budgets, focus placement, draft preservation,
exclusive state, disabled reasons, and zero application commands from navigation,
collapse, settings, and resizing. Existing streaming/reconnection tests remain
part of the regression run.

Validation for this change: **35 client/schema tests and 44 communication/browser
tests passed**. The typed demo also passed an end-to-end prepare/start/stop and
source-choice check. Wheel and source distribution builds passed metadata checks.
