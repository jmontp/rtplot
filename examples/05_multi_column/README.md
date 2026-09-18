# 05 – Multi-column layout

The sender declares a different column count for each row. Start the
server normally, then run either sender (client and server 0.4.16+):

```bash
# Terminal 1 (or use ./rtplot-server)
python -m rtplot.server_browser

# Terminal 2
python examples/05_multi_column/run.py
```

Open http://localhost:8050. Six plots appear in three rows: two columns,
one full-width plot, then three columns. Change a row's `columns` in the
sender and rerun it; the server stays running. On narrow windows, rows
scroll horizontally to keep individual plots readable.

`run.py` uses `{"columns": 2, "plots": [...]}` dictionaries. `run_typed.py`
uses `PlotRow([...], columns=2)` and sends the same signals. Each row's
plots fill from left to right; `send_array` follows that order through
all rows. Both scripts save a snapshot in this folder that preserves the
mixed layout.

Rows with more plots than columns wrap onto another line within that
group. Ordinary `Plot` entries and `ControlsRow` entries can still be
mixed with `PlotRow` entries at the top level.
