# 05 – Multi-column layout

Start the server with two plot columns, then run either sender:

```bash
# Terminal 1 (or use ./rtplot-server --columns 2)
python -m rtplot.server_browser --columns 2

# Terminal 2
python examples/05_multi_column/run.py
```

Open http://localhost:8050. Four plots appear in a 2 × 2 grid. To get
three columns, restart the server with `--columns 3`; no sender code change
is needed. `-c` is shorthand for two columns. The browser scrolls
horizontally when the window is too narrow to fit all columns.

`run.py` uses dictionaries. `run_typed.py` uses `Plot` objects and sends
the same signals. Both save a snapshot in this folder so you can check
that the downloaded HTML preserves the two-column layout.
