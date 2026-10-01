"""Shared X/Y plot validation and binary payloads (no networking)."""
import json
import struct

import numpy as np


SENDING_XY = "7"
MSG_XY = 2


def xy_declarations(config):
    """Validate optional plot modes and return X/Y plots keyed by public ID."""
    plots, ids = {}, set()
    for row in config.values():
        if "controls" in row or "non_plot_labels" in row:
            continue
        for plot in row.get("plots", [row]):
            mode = plot.get("mode", "stream")
            if mode not in ("stream", "xy"):
                raise ValueError("Plot mode must be 'stream' or 'xy'")
            pid = plot.get("id")
            if pid is not None:
                if not isinstance(pid, str) or not pid or pid in ids:
                    raise ValueError("Plot IDs must be unique non-empty strings")
                ids.add(pid)
            scale = plot.get("xscale", "linear")
            if scale not in ("linear", "log"):
                raise ValueError("Plot xscale must be 'linear' or 'log'")
            if mode == "xy":
                if pid is None:
                    raise ValueError("X/Y plots require a unique non-empty id")
                if not isinstance(plot.get("names"), list) or not plot["names"]:
                    raise ValueError("X/Y plots require at least one trace name")
                if "xrange" in plot:
                    raise ValueError("xrange is only supported for scrolling plots")
                plots[pid] = plot
            elif scale != "linear":
                raise ValueError("Logarithmic X requires mode='xy'")
    return plots


def normalize_xy(x, y, plot):
    """Return contiguous little-endian float64 X and float32 trace rows."""
    x, y = np.asarray(x), np.asarray(y)
    if x.ndim != 1:
        raise ValueError("X must be a one-dimensional array")
    if x.dtype.kind not in "iuf" or y.dtype.kind not in "iuf":
        raise ValueError("X/Y values must be real numeric values")
    count = len(plot["names"])
    if y.ndim == 1 and count == 1:
        y = y.reshape(1, -1)
    if y.shape != (count, x.size):
        raise ValueError(f"Y must have shape ({count}, {x.size}) matching the plot traces and X")
    with np.errstate(over="ignore", invalid="ignore"):
        x = np.ascontiguousarray(x, dtype="<f8")
        y = np.ascontiguousarray(y, dtype="<f4")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("X/Y values must be finite and representable as float64 X / float32 Y")
    if np.any(x[1:] <= x[:-1]):
        raise ValueError("X coordinates must be strictly increasing")
    if plot.get("xscale", "linear") == "log" and np.any(x <= 0):
        raise ValueError("Logarithmic X coordinates must be positive")
    return x, y


def decode_xy_arrays(meta, x_bytes, y_bytes, plot):
    """Validate sizes before interpreting an incoming ZMQ replacement."""
    n, count = meta.get("num_samples"), meta.get("num_traces")
    if type(n) is not int or n < 0 or type(count) is not int or count != len(plot["names"]):
        raise ValueError("Invalid X/Y sample or trace count")
    if len(x_bytes) != n * 8 or len(y_bytes) != count * n * 4:
        raise ValueError("X/Y payload size does not match its metadata")
    return normalize_xy(np.frombuffer(x_bytes, dtype="<f8"),
                        np.frombuffer(y_bytes, dtype="<f4").reshape(count, n), plot)


def pack_xy_message(meta, x, y):
    """WebSocket type 2: <B3xI JSON length>, JSON padded to 8, f64 X, f32 Y.

    Metadata identifies tab, session, generation, plot ID and array sizes.
    Padding keeps both typed arrays aligned without copying in the browser.
    """
    encoded = json.dumps({**meta, "num_samples": x.size, "num_traces": y.shape[0]}).encode("utf-8")
    return (struct.pack("<B3xI", MSG_XY, len(encoded)) + encoded
            + bytes((-len(encoded)) % 8) + x.tobytes() + y.tobytes())
