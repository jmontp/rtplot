from pathlib import Path

from rtplot.client import Plot


def test_plot_serializes_initial_trace_visibility():
    assert Plot(names=["primary", "comparison"], show=[True, False]).to_dict()["show"] == [True, False]


def test_browser_applies_initial_trace_visibility():
    source = (Path(__file__).parents[1] / "rtplot" / "static" / "index.html").read_text()
    assert "show: shows[t] !== false" in source
