# Sections and runtime presentation state

Available in **client and browser server 0.5.0+**. Existing
`initialize_plots(desc)` layouts remain flat. This feature does not add or
remove plots at runtime; replacing the full layout retains its reset behavior.

## Declare a view

```python
from rtplot import client
from rtplot.client import Button, ControlsRow, Plot, PlotRow, Section, Text, View

client.local_plot()
client.initialize_plots([
    ControlsRow([Text("status", "Status", "Waiting"), Button("stop", "Stop")], section="status"),
    ControlsRow([Button("record", "Record"), Button("train", "Train")], section="setup"),
    PlotRow([Plot(names=["angle"]), Plot(names=["reference"])], columns=2, section="check"),
    ControlsRow([Button("source_raw", "Raw source")], section="advanced"),
], view=View([
    Section("status", "Status"),
    Section("setup", "Setup", description="Prepare the synthetic source"),
    Section("check", "Check"),
    Section("advanced", "Advanced", collapsible=True, collapsed=True),
], persistent_section="status"), ui_state={
    "controls": {"train": {"enabled": False, "reason": "Record first"}},
})
```

Equivalent dictionaries use the same keys:

```python
client.initialize_plots([
    {"controls": [{"type": "text", "id": "status", "label": "Status", "value": "Waiting"}], "section": "status"},
    {"names": ["angle", "reference"], "section": "check"},
], view={
    "persistent_section": "status",
    "sections": [{"id": "status", "title": "Status"},
                 {"id": "check", "title": "Check", "collapsible": True}],
})
```

`Section` supports `id`, `title`, `description=""`, `collapsible=False`,
`collapsed=False`, and `visible=True`. IDs must be unique nonempty strings.
Assign `section` to a `Plot`, `PlotRow`, or `ControlsRow`; child plots inside
one `PlotRow` share their row's section. Section order follows `view.sections`;
rows retain their relative declaration order within each section. Unassigned
rows follow the sections. **Samples always follow original plot declaration
order**, even when the visual section order differs.

The optional persistent section accepts only control rows. It cannot collapse;
its sticky area is limited to 35% of the viewport and scrolls internally if
necessary. Keep its contents short. Navigation accounts for its height so
section headings remain visible.

Navigation and collapse never send application commands. Collapse preferences
live in browser `sessionStorage`, per source tab: they survive reloads in that
browser tab and are independent of other viewers. Runtime state does not change
them. Navigating to a collapsed section reveals it; an application-hidden
section has no navigation link.

## Patch existing controls and sections

```python
client.set_ui_state({
    "controls": {
        "train": {"enabled": False, "reason": "Record first"},
        "record": {"enabled": True, "busy": False},
        "source_raw": {"selected": True},
    },
    "sections": {
        "setup": {"status": "complete", "message": "Source ready"},
        "check": {"status": "ready"},
    },
})
```

| Control property | Default | Meaning |
|---|---|---|
| `enabled` | `True` | Allow interaction; disabled controls cannot emit pointer or keyboard actions. |
| `visible` | `True` | Show the existing control; hiding preserves its value. |
| `busy` | `False` | Show a text activity indicator; does not disable interaction. |
| `selected` | `False` | Mark the application's active choice, independent of focus or a click. |
| `reason` | `""` | Visible explanatory text, also linked with `aria-describedby`. |

Sections accept `visible` (default from declaration), `status` (default `idle`),
and `message` (default empty). Status is one of `idle`, `ready`, `busy`,
`complete`, `warning`, `error`; labels include text and symbols as well as
color. Status never navigates or collapses a section.

The API accepts **patches**: omitted properties remain unchanged. Set a property
to `None` to remove its override, or set a control/section ID to `None` to
remove all of its overrides:

```python
client.set_ui_state({"controls": {"train": {"enabled": None, "reason": None}}})
client.set_ui_state({"sections": {"setup": None}})
```

Removing a section's `visible` override restores its declared initial visibility.
Unknown IDs, unsupported properties, incorrect types, and invalid statuses raise
`ValueError` without partially applying a patch. Strings are limited to 4096
characters. `set_ui_state` returns `True` when the merged state changes and
`False` for an unchanged patch. It never updates input values, plot configuration,
or browser focus. Existing `set_display()` and `set_text_input()` retain their
value-update behavior.

## Synchronization and transport

The client merges patches and sends complete presentation snapshots separately
from numerical samples. The server caches one current snapshot per source tab
and forwards changed snapshots at most 30 times per second, coalescing changes
into one pending snapshot per tab. Browser updates touch affected controls and
sections rather than reconstructing control rows or plots. Hidden plots still
buffer samples, skip `setData`, and resize/redraw from their buffers on reveal.

Each initialization carries a random client session ID, an increasing layout
generation, and a monotonic state revision. Old revisions and mismatched layout
updates are ignored. Repeating the same layout generation is idempotent and
does not reset history. Explicit `initialize_plots()` creates a new generation
and retains full-layout reset semantics. Browser reconnection receives the
latest layout, full presentation state, control values, and available plot
history. A reconnect to the same layout reuses existing uPlot instances, zoom,
legend choices, and control elements. A server restart loses in-memory history;
the client's existing config-resend mechanism restores the layout/state.

Call `poll_controls()` regularly, including while the application is idle.
`send_array()` and `poll_controls()` send a presentation heartbeat at most once
per second. A detected transport disconnect, or five seconds without samples
or heartbeat from a modern client, shows a persistent unavailable/stale banner
and disables application controls. Browser-server disconnection does the same.
Data/heartbeat resumption clears the banner. After a polling gap longer than
five seconds, the modern client drains old actions and waits for a fresh epoch
acknowledgment before accepting commands. Legacy clients use transport
disconnection detection because they do not send heartbeats.

Commands remain best-effort ZMQ PUSH/PULL messages, without application-level
acknowledgments or retries. The server rejects unavailable/disabled/hidden
controls, discards pending commands on detected disconnect, and modern commands
carry a source epoch so old-session commands can be rejected. The browser never
queues clicks for reconnection or marks application success when sending one.
Applications must still validate every command and publish their actual state;
rtplot cannot determine whether an action succeeded or undo a command already
received before a disconnection was detected.

## Compatibility and examples

Use both client and browser server **0.5.0 or newer**. Initialization with
sections or initial UI state warns if the server does not acknowledge the
required capability. An older browser server may render rows flat;
**disabled-state enforcement is not available** there. `set_ui_state()` raises
`RuntimeError` until a compatible server acknowledges the layout. A handshake
timeout or `handshake_timeout=0` therefore does not establish support; polling
can subsequently receive the capability acknowledgment. The Qt server does not
implement these browser features.

See [the hardware-free workflow](../examples/06_sections/README.md) for typed
and dictionary forms, synthetic streaming, unavailable actions, completion,
and a deliberate pause/recovery. Static HTML exports remain plot snapshots;
interactive section navigation and application controls belong to the live UI.

For reproducible browser tests and measured rendering behavior, see
[validation and performance checks](sections-validation.md).

Version 0.6.0 adds [responsive presentation, essential controls, semantic styles,
and labelled/exclusive groups](presentation.md), without changing the state API.
