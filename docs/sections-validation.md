# Sections validation

Run from the checkout with browser dependencies, pytest, and Playwright Chromium
installed. Run client unit tests separately because importing the client opens
its default ZMQ sockets; communication tests start real servers on those ports.

```bash
python -m pip install -e '.[browser]' pytest playwright build
python -m playwright install chromium
python -m pytest tests/test_plot_rows.py tests/test_plot_visibility.py tests/test_sections_client.py tests/test_ui_state.py -q
python -m pytest tests/test_communication.py tests/test_sections.py -q
```

The first command group covers 26 validation/client tests. The communication
and browser group covers 39 tests, including legacy layouts and protocols.
New acceptance coverage uses a real synthetic publisher and Chromium:

- Typed/dictionary equivalence, capability warnings, patch validation, defaults,
  revisions and layout generations.
- Disabled mouse/keyboard actions and server rejection, visible reasons, selected
  and busy state, preserved editing focus and control values.
- Persistent controls, independent navigation/collapse in two viewers, and
  authoritative presentation state.
- Distinct traces declared in a different order from their visual sections;
  collapse, runtime visibility, reveal, zoom/legend retention, and fixed history
  buffers without recreating uPlot instances.
- Browser reconnect/new-viewer snapshots, source disconnect/stale recovery,
  explicit config resend, separate source tabs, and no replay of clicks buffered
  before an application pauses long enough to become stale.

## Rendering and memory check

For a longer local performance comparison:

```bash
RTPLOT_STRESS_ROUNDS=40 python -m pytest tests/test_sections.py::TestSections::test_render_work_memory_and_coalescing -q -s
```

A local Linux/Chromium run (2026-09-18) used two 50 Hz synthetic traces with
80-sample browser windows, 16,000 alternating presentation patches during the
collapsed phase, then revealed the hidden plot. Total test time was 25.45 seconds.

| Measurement | Observed |
|---|---:|
| Collapsed plot `setData` calls | 0 |
| Visible peer `setData` calls during the same phase | 507 |
| Previously hidden plot `setData` calls after reveal | 593 |
| Forwarded UI snapshots for 16,000 patches | 63 |
| Maximum outstanding instrumented animation frames | 3 |
| Retained JS heap increase after garbage collection | 943,776 bytes |
| uPlot instances destroyed by presentation updates | 0 |

Streaming continued through the bursts, both traces retained their expected
1,000-unit difference, DOM node growth stayed within the first-reveal label
allowance, and the retained-heap increase stayed below the test's 2 MB bound.
This is a short regression check, not a long-duration memory guarantee or a
cross-platform benchmark. Increase `RTPLOT_STRESS_ROUNDS` for a longer run.

Both user-facing example forms were also run; the automated typed example
completed setup/work/completion and a seven-second pause followed by recovery.
The wheel and source distribution build include the new protocol module and
browser assets. The existing binary workflow packages the entire static folder.
