# Responsive presentation demo

Requires client and browser server 0.6.0+. This is a synthetic application with
no hardware connections.

```bash
python -m rtplot.server_browser
# In another terminal:
python examples/07_presentation/run.py
# Or the equivalent typed declaration:
python examples/07_presentation/run_typed.py
```

Open the browser and resize it. Hardware state and Stop remain in the essential
strip. Prepare enables Start; the application publishes its synthetic state only
after handling the action. Open More → Advanced to choose a source or inspect
optional settings. Choices change only when the application accepts the click
and publishes selected state. Edit Notes, navigate, and resize to see the draft
and plot history remain intact.

This example shows essential controls, compact sections without visible headings,
primary/secondary navigation, explicit help/state/action styles, labelled and
exclusive groups, and responsive rows with configured trace colors/styles and
minimum heights. The same loop handles both dictionary and typed declarations.

[API guide](../../docs/presentation.md) · [Before/after screenshots](../../docs/presentation-screenshots/README.md)
