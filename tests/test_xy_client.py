import json
import struct

import numpy as np
import pytest

from rtplot import client
from rtplot.ui_state import CAPABILITIES
from rtplot.xy import decode_xy_arrays, normalize_xy, pack_xy_message, xy_declarations


def acknowledge(monkeypatch):
    monkeypatch.setattr(client, "_send_initialize_with_handshake",
                        lambda *_: client._accept_ack({"capabilities": CAPABILITIES}))
    monkeypatch.setattr(client, "_publish_ui_if_due", lambda *a, **k: None)


def test_typed_dict_mixed_layout_and_replacement_wire(monkeypatch):
    acknowledge(monkeypatch)
    xy = client.Plot(names=["a", "b"], id="spectrum", mode="xy", xscale="log")
    assert client.Plot(names=["legacy"]).to_dict() == {"names": ["legacy"]}
    assert xy.to_dict() == {"names": ["a", "b"], "id": "spectrum", "mode": "xy", "xscale": "log"}
    for description in (xy, xy.to_dict()):
        client.initialize_plots([client.Plot(names=["before"]),
                                 client.PlotRow([description, client.Plot(names=["after"])], columns=2)])
        assert list(client._xy_plots) == ["spectrum"]
    sent = []
    class Socket:
        def send_multipart(self, frames): sent.append(frames)
    monkeypatch.setattr(client, "socket", Socket())
    # Non-contiguous arrays, multiple rows, and changing sizes.
    for n in (6, 2, 0):
        x = np.arange(1, n * 2 + 1, dtype=float)[::2]
        y = np.arange(n * 4).reshape(2, n * 2)[:, ::2]
        client.send_xy("spectrum", x, y)
        category, header, xb, yb = sent[-1]
        meta = json.loads(header)
        assert category == b"7"
        assert (meta["session"], meta["generation"]) == (client._session, client._generation)
        dx, dy = decode_xy_arrays(meta, xb, yb, xy.to_dict())
        np.testing.assert_array_equal(dx, x)
        np.testing.assert_array_equal(dy, y)
    with pytest.raises(ValueError, match="Unknown"):
        client.send_xy("missing", [], [])
    assert len(sent) == 3


def test_capability_required_and_old_layouts_work(monkeypatch):
    monkeypatch.setattr(client, "_send_initialize_with_handshake", lambda *_: None)
    client.initialize_plots("legacy", handshake_timeout=0)
    with pytest.raises(RuntimeError, match="xy_v1"):
        client.initialize_plots(client.Plot(names=["a"], id="a", mode="xy"))
    with pytest.raises(RuntimeError, match="xy_v1"):
        client.send_xy("a", [1], [2])


@pytest.mark.parametrize("fields", [
    {"mode": "unknown"}, {"mode": "xy"}, {"mode": "xy", "id": ""},
    {"mode": "xy", "id": 1}, {"mode": "xy", "id": "a", "xrange": 200},
    {"mode": "xy", "id": "a", "names": []},
    {"mode": "xy", "id": "a", "xscale": "unknown"}, {"xscale": "log"},
])
def test_invalid_declarations(fields):
    with pytest.raises(ValueError):
        xy_declarations({"plot": {"names": ["a"], **fields}})


def test_duplicate_ids_across_rows():
    with pytest.raises(ValueError, match="unique"):
        xy_declarations({"first": {"names": ["a"], "id": "a"},
                         "row": {"plots": [{"names": ["b"], "mode": "xy", "id": "a"}]}})


@pytest.mark.parametrize("x,y,scale", [
    ([[1]], [1], "linear"), ([1, 2], [1], "linear"),
    ([1], [[1], [2]], "linear"), ([2, 1], [1, 2], "linear"),
    ([1, 1], [1, 2], "linear"), ([np.nan], [1], "linear"),
    ([np.inf], [1], "linear"), ([1], [np.nan], "linear"),
    ([1], [1e40], "linear"), ([1j], [1], "linear"),
    ([1], [1j], "linear"), (["1"], [1], "linear"),
    ([True], [1], "linear"), ([0], [1], "log"), ([-1], [1], "log"),
])
def test_invalid_coordinates(x, y, scale):
    with pytest.raises(ValueError):
        normalize_xy(x, y, {"names": ["a"], "xscale": scale})


def test_single_trace_empty_negative_and_precise_coordinates():
    plot = {"names": ["a"]}
    x, y = normalize_xy([], [], plot)
    assert x.shape == (0,) and y.shape == (1, 0)
    x, y = normalize_xy([-1, 0, 1], [1, 2, 3], plot)
    assert x.tolist() == [-1, 0, 1]
    x, y = normalize_xy([1e12, 1e12 + .25], [4, 5], plot)
    packet = pack_xy_message({"id": "frequency-θ"}, x, y)
    kind, length = struct.unpack("<B3xI", packet[:8])
    assert kind == 2
    meta = json.loads(packet[8:8 + length])
    offset = 8 + (length + 7) // 8 * 8
    dx, dy = decode_xy_arrays(meta, packet[offset:offset + 16], packet[offset + 16:], plot)
    np.testing.assert_array_equal(dx, x)
    np.testing.assert_array_equal(dy, y)


@pytest.mark.parametrize("meta,xb,yb", [
    ({"num_samples": -1, "num_traces": 1}, b"", b""),
    ({"num_samples": True, "num_traces": 1}, b"", b""),
    ({"num_samples": 0, "num_traces": 2}, b"", b""),
    ({"num_samples": 1, "num_traces": 1}, b"", b""),
    ({"num_samples": 0, "num_traces": 1}, b"extra", b""),
])
def test_bad_wire_sizes(meta, xb, yb):
    with pytest.raises(ValueError):
        decode_xy_arrays(meta, xb, yb, {"names": ["a"]})
