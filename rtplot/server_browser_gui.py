"""GUI wrapper around the rtplot browser server.

This is the default entry point for the Windows executable. It launches
the aiohttp + ZMQ server in a background thread and shows a tiny Tk
window with the listening URL, ZMQ status, and live FPS / client count.
Users who prefer the plain CLI behavior can pass ``--no-gui`` (or just
run ``python -m rtplot.server_browser`` directly).

We set ``sys.argv`` before importing ``rtplot.server_browser`` because
that module parses CLI flags at import time. The GUI-visible flags
(``--port``, ``-p``) are forwarded; everything else is rewritten so the
server starts with auto-browser-open disabled (the GUI has its own
"Open in browser" button).
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser


def _lan_ips():
    """Return likely-reachable IPv4 addresses so the GUI can show the LAN URL."""
    import socket as _s

    ips = []
    try:
        hostname = _s.gethostname()
        for info in _s.getaddrinfo(hostname, None):
            ip = info[4][0]
            if (
                ip
                and ip not in ips
                and ":" not in ip
                and not ip.startswith("127.")
            ):
                ips.append(ip)
    except Exception:  # noqa: BLE001
        pass
    return ips


def _parse_wrapper_args(argv):
    """Split argv into GUI wrapper options and args forwarded to the server."""
    parser = argparse.ArgumentParser(
        prog="rtplot-server",
        description="rtplot browser server with a small status window",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run headless (no Tk window). Same behavior as python -m rtplot.server_browser.",
    )
    parser.add_argument("--port", type=int, default=8050, help="HTTP port (default 8050)")
    parser.add_argument(
        "-p",
        "--pi-ip",
        dest="pi_ip",
        default=None,
        help="Connect to a sender at this address instead of binding locally.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="HTTP bind interface (default 0.0.0.0)",
    )
    args, rest = parser.parse_known_args(argv)
    return args, rest


def _run_headless(args, rest):
    """Delegate straight to rtplot.server_browser's __main__."""
    import runpy

    forwarded = [sys.argv[0], "--port", str(args.port), "--host", args.host]
    if args.pi_ip:
        forwarded += ["-p", args.pi_ip]
    forwarded += rest
    sys.argv = forwarded
    runpy.run_module("rtplot.server_browser", run_name="__main__")


def _run_with_gui(args, rest):
    import asyncio
    import tkinter as tk
    from tkinter import ttk
    from aiohttp import web

    # Seed sys.argv so server_browser's module-level argparse sees what we
    # want. --no-browser is always forced in GUI mode because the window
    # has its own "Open in browser" button.
    forwarded = [
        sys.argv[0],
        "--no-browser",
        "--port",
        str(args.port),
        "--host",
        args.host,
    ]
    if args.pi_ip:
        forwarded += ["-p", args.pi_ip]
    forwarded += rest
    sys.argv = forwarded

    from rtplot import server_browser as sb  # noqa: E402 — deliberate post-argv import

    # Start the aiohttp server in a background thread with its own event
    # loop. web.run_app() can't be called off the main thread because it
    # installs signal handlers, so we drop down to AppRunner + TCPSite.
    server_ready = threading.Event()
    startup_error = {"value": None}

    def _server_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            app = sb.build_app()
            runner = web.AppRunner(app)
            loop.run_until_complete(runner.setup())
            site = web.TCPSite(runner, args.host, args.port)
            loop.run_until_complete(site.start())
            server_ready.set()
            loop.run_forever()
        except Exception as exc:  # noqa: BLE001
            startup_error["value"] = exc
            server_ready.set()

    thread = threading.Thread(target=_server_thread, daemon=True)
    thread.start()
    server_ready.wait(timeout=8)
    if startup_error["value"] is not None:
        # Fail loudly — a failed bind is the most common cause.
        import traceback

        traceback.print_exception(startup_error["value"])
        sys.stderr.write(f"\nrtplot-server failed to start: {startup_error['value']}\n")
        sys.exit(1)

    # ---------------------------------------------------------------- UI
    root = tk.Tk()
    root.title("rtplot server")
    root.geometry("440x260")
    root.resizable(False, False)

    try:
        style = ttk.Style()
        style.theme_use("vista" if "vista" in style.theme_names() else "clam")
    except tk.TclError:
        pass

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame,
        text="rtplot browser server",
        font=("Segoe UI", 13, "bold"),
    ).pack(anchor="w")

    status_line = ttk.Label(frame, text="● running", foreground="#186a18")
    status_line.pack(anchor="w", pady=(0, 10))

    url = f"http://localhost:{args.port}"
    url_var = tk.StringVar(value=url)
    url_entry = ttk.Entry(frame, textvariable=url_var, width=44)
    url_entry.pack(fill="x")
    url_entry.bind("<Key>", lambda e: "break")  # readonly but still selectable

    def on_open():
        webbrowser.open(url)

    def on_copy():
        root.clipboard_clear()
        root.clipboard_append(url)

    btn_row = ttk.Frame(frame)
    btn_row.pack(fill="x", pady=(8, 12))
    ttk.Button(btn_row, text="Open in browser", command=on_open).pack(
        side="left", padx=(0, 6)
    )
    ttk.Button(btn_row, text="Copy URL", command=on_copy).pack(side="left")

    lan_ips = _lan_ips()
    if lan_ips:
        ttk.Label(
            frame,
            text="LAN: " + ", ".join(f"http://{ip}:{args.port}" for ip in lan_ips),
            foreground="#555",
        ).pack(anchor="w")

    zmq_var = tk.StringVar(value="ZMQ: initializing…")
    ttk.Label(frame, textvariable=zmq_var, foreground="#555").pack(
        anchor="w", pady=(6, 0)
    )
    stats_var = tk.StringVar(value="0 Hz  |  0 browser client(s)")
    ttk.Label(frame, textvariable=stats_var, foreground="#555").pack(anchor="w")

    def poll_status():
        try:
            zm = getattr(sb, "zmq_status", {}) or {}
            mode = zm.get("mode", "?")
            target = zm.get("target", "?")
            zmq_var.set(f"ZMQ: {mode} {target}")
            state = getattr(sb, "state", {}) or {}
            fps = state.get("fps", 0) or 0
            num_clients = len(getattr(sb, "ws_clients", set()) or set())
            stats_var.set(
                f"{fps:.0f} Hz  |  {num_clients} browser client(s) connected"
            )
        except Exception as exc:  # noqa: BLE001
            zmq_var.set(f"status error: {exc}")
        root.after(500, poll_status)

    poll_status()

    def on_close():
        root.destroy()
        # Kill the server thread hard — it's a daemon but aiohttp's
        # event loop may not exit cleanly during process teardown on
        # Windows, and leaving it to interpreter shutdown is slower.
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def main():
    args, rest = _parse_wrapper_args(sys.argv[1:])
    if args.no_gui:
        _run_headless(args, rest)
    else:
        _run_with_gui(args, rest)


if __name__ == "__main__":
    main()
