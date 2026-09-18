import pytest

from rtplot import client
from rtplot.client import Plot, PlotRow


def test_row_serialization_keeps_order_and_legacy_inputs(monkeypatch):
    sent = []
    monkeypatch.setattr(client, "_send_initialize_with_handshake", lambda cfg, timeout: sent.append(cfg))
    client.initialize_plots([
        PlotRow([Plot(names=["a"]), {"names": ["b"]}], columns=2),
        {"plots": [{"names": ["c"]}], "columns": 1},
        Plot(names=["d"]),
    ])
    assert list(sent[-1].values()) == [
        {"plots": [{"names": ["a"]}, {"names": ["b"]}], "columns": 2},
        {"plots": [{"names": ["c"]}], "columns": 1},
        {"names": ["d"]},
    ]
    client.initialize_plots([["a"], ["b", "c"]])
    assert list(sent[-1].values()) == [{"names": ["a"]}, {"names": ["b", "c"]}]


@pytest.mark.parametrize("columns", [0, -1, True, 1.5, "2", None])
def test_invalid_column_counts(columns):
    with pytest.raises(ValueError, match="positive integer"):
        PlotRow([Plot(names=["a"])], columns=columns).to_dict()


@pytest.mark.parametrize("plots", [[], [42], [{"controls": []}], [{"plots": [], "columns": 1}]])
def test_invalid_row_contents(plots):
    with pytest.raises(ValueError):
        PlotRow(plots, columns=1).to_dict()
