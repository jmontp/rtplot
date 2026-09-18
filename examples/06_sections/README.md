# Sections and live presentation state

Requires both client and browser server **0.5.0+**. No hardware or additional
packages are needed beyond rtplot's browser dependencies.

```bash
python -m rtplot.server_browser
# In another terminal:
python examples/06_sections/run_typed.py
# Dictionary serialization of the same configuration:
python examples/06_sections/run.py
# Automated setup → work → complete → stale → recovery, then exit:
python examples/06_sections/run_typed.py --auto --seconds 18
```

Click **Prepare source**, then **Start work**. Start initially displays a
prerequisite reason and cannot emit actions. Work completes after four seconds;
Stop is enabled only while the application is working. The application validates
actions and publishes the resulting state. A button click alone never reports
success.

The persistent status row stays accessible while scrolling. Expand Advanced,
change gain or source choice, and type notes while samples continue arriving.
Busy and selected states do not reset values or focus. The detail signal is
declared first, but shown last: the transmitted sample order stays detail,
signal, reference regardless of collapse or visibility.

**Simulate interruption** pauses both streaming and polling for seven seconds.
After five seconds the server marks the source stale and disables application
actions. Resuming the same source restores availability without replacing plots
or replaying unavailable clicks. To exercise browser reconnection, temporarily
block its WebSocket connection in browser developer tools or reload the page.
Open two browser tabs to compare independent collapse preferences and shared
application state. Stopping this publisher demonstrates transport disconnection;
restarting the script declares a new layout and therefore resets history.

[run_typed.py](run_typed.py) defines typed builders. [run.py](run.py) declares
the equivalent layout with ordinary dictionaries and uses the same synthetic
application loop. For a literal dictionary declaration and full patch/default,
reconnection, and compatibility semantics, see [the API guide](../../docs/sections.md).
