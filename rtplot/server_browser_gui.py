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
import io
import json
import os
import queue
import sys
import tempfile
import threading
import traceback
import webbrowser
from datetime import datetime


# ---- persistent settings -------------------------------------------------
#
# Settings live in rtplot-settings.json next to the exe (portable) so a
# user can move the exe + its settings between machines on a thumb drive
# and not lose anything. If that directory turns out to be read-only
# (e.g. exe dropped in Program Files), we fall back to
# %APPDATA%\rtplot\rtplot-settings.json.

def _exe_dir():
    """Directory the exe (or dev script) is launched from."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.getcwd())


def _appdata_rtplot_dir():
    base = os.environ.get("APPDATA") or tempfile.gettempdir()
    return os.path.join(base, "rtplot")


def _settings_path():
    """Return the best-effort writable path for the settings JSON."""
    candidate = os.path.join(_exe_dir(), "rtplot-settings.json")
    probe = candidate + ".write-probe"
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("")
        os.remove(probe)
        return candidate
    except Exception:  # noqa: BLE001
        try:
            os.makedirs(_appdata_rtplot_dir(), exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        return os.path.join(_appdata_rtplot_dir(), "rtplot-settings.json")


DEFAULT_SETTINGS = {
    # Most recent demo-sender targets, newest first, capped at 8.
    "recent_hosts": [],
}

MAX_RECENT_HOSTS = 8


def _load_settings():
    try:
        with open(_settings_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        return merged
    except FileNotFoundError:
        return dict(DEFAULT_SETTINGS)
    except Exception as exc:  # noqa: BLE001
        _log(f"failed to load settings: {exc}")
        return dict(DEFAULT_SETTINGS)


def _save_settings(settings):
    try:
        with open(_settings_path(), "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
    except Exception as exc:  # noqa: BLE001
        _log(f"failed to save settings: {exc}")


def _remember_host(settings, host):
    if not host:
        return
    lst = [h for h in settings.get("recent_hosts", []) if h and h != host]
    lst.insert(0, host)
    settings["recent_hosts"] = lst[:MAX_RECENT_HOSTS]
    _save_settings(settings)


class _TkLogRedirect(io.TextIOBase):
    """Thread-safe sys.stdout / sys.stderr replacement.

    Writes are buffered in a queue and mirrored to the persistent log
    file, then drained onto the Tk log panel by a periodic pump running
    on the main thread. Installing this before importing
    rtplot.server_browser captures the server's startup prints too.
    """

    def __init__(self):
        self.queue: "queue.Queue[str]" = queue.Queue()

    def writable(self):
        return True

    def write(self, s):
        if not s:
            return 0
        try:
            self.queue.put_nowait(s)
        except Exception:  # noqa: BLE001
            pass
        for line in s.splitlines():
            if line.strip():
                _log("OUT " + line.rstrip())
        return len(s)

    def flush(self):
        pass

# Everything the GUI wrapper does gets mirrored to a log file in the
# user's TEMP directory. This is the only reliable way to diagnose a
# failed double-click on Windows — the console window closes
# instantly on exit, so stderr tracebacks are invisible.
LOG_FILE = os.path.join(tempfile.gettempdir(), "rtplot-server.log")


def _log(message: str) -> None:
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n")
    except Exception:  # noqa: BLE001
        pass


def _show_error_dialog(title: str, message: str) -> None:
    """Show a modal error dialog. Best-effort — falls back to stderr."""
    _log(f"ERROR {title}: {message}")
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:  # noqa: BLE001
        sys.stderr.write(f"\n{title}\n{message}\n")


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
    parser.add_argument(
        "--test-client",
        dest="test_client",
        default=None,
        metavar="TARGET",
        help=(
            "Run the exe as a demo data sender instead of a server. "
            "TARGET is the 'host' or 'host:port' of the machine running "
            "the rtplot server you want to test connectivity with. "
            "Useful for verifying cross-PC networking from a second "
            "machine that only has the exe (no Python install)."
        ),
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


def _demo_sender_loop(rtp_client, stop_event, stats):
    """Shared sine-wave sender used by both --test-client mode and the
    "Demo sender" button inside the server window.

    Writes progress into the stats dict under the keys ``count`` and
    ``elapsed``; puts a string on ``error`` if anything raises. Stops
    as soon as stop_event is set.
    """
    import math
    import time

    t0 = time.time()
    i = 0
    try:
        while not stop_event.is_set():
            t = time.time() - t0
            rtp_client.send_array(math.sin(2 * math.pi * 1.5 * t))
            rtp_client.set_display("count", float(i))
            i += 1
            stats["count"] = i
            stats["elapsed"] = t
            time.sleep(0.02)
    except Exception as exc:  # noqa: BLE001
        stats["error"] = str(exc)
        _log("demo sender loop crashed: " + traceback.format_exc())


def _normalize_demo_target(raw: str):
    """Normalize a user-entered target host string into a ZMQ-friendly form.

    The most common mistake is pasting the browser URL from the server
    status window (e.g. ``http://192.168.1.42:8050``) into the target
    field. That hands ``http://...:8050`` to pyzmq, which rejects the
    scheme and, on a retry, connects to the aiohttp HTTP port instead
    of the real ZMQ SUB port 5555 — data goes into the void with no
    visible error.

    Returns ``(cleaned, warning)`` where ``warning`` is None if no
    auto-correction was applied, or a short human-readable explanation
    of what was fixed otherwise.
    """
    import re

    warnings = []
    s = raw.strip().rstrip("/")

    # 1. Strip http:// or https:// prefix
    if s.lower().startswith("http://"):
        s = s[len("http://"):]
        warnings.append("stripped 'http://' prefix")
    elif s.lower().startswith("https://"):
        s = s[len("https://"):]
        warnings.append("stripped 'https://' prefix")

    # 2. Strip any path after the host (e.g. http://host:8050/index)
    if "/" in s:
        s = s.split("/", 1)[0]

    # 3. If the port is obviously the HTTP port, retarget to the ZMQ port.
    #    The rtplot server's default HTTP port is 8050; the default ZMQ
    #    data port is 5555.
    m = re.match(r"^(.+):(\d+)$", s)
    if m:
        host, port_str = m.group(1), m.group(2)
        try:
            port = int(port_str)
        except ValueError:
            port = -1
        if port in (80, 443, 8050, 8051, 8080, 8000):
            s = host
            warnings.append(f"dropped HTTP port :{port} (ZMQ defaults to 5555)")

    warning = "; ".join(warnings) if warnings else None
    return s, warning


def _configure_demo_sender(rtp_client, target: str, source_label: str):
    """Configure rtplot.client for ``target`` and push the demo layout.

    Returns None on success, an error string on failure.

    Sends the config TWICE with a small delay in between as a slow-joiner
    guard. ZMQ PUB/SUB drops messages that are sent before the subscriber
    has finished handshaking, and ``configure_ip`` only sleeps 1 second —
    which can still be too short on Windows loopback once in a while.
    The server's ``parse_config`` path is idempotent, so resending the
    same config is harmless in the common case where the first message
    already landed.
    """
    import time

    _log(f"demo sender: configure_ip({target!r})")
    try:
        rtp_client.configure_ip(target)
    except Exception as exc:  # noqa: BLE001
        _log("configure_ip failed: " + traceback.format_exc())
        return f"configure_ip({target}): {exc}"
    plot_cfg = {
        "names": ["demo-signal"],
        "colors": ["b"],
        "yrange": [-1.5, 1.5],
        "title": "rtplot demo sender",
        "xrange": 500,
    }
    controls_row = {
        "controls": [
            {"type": "text", "id": "src", "label": "From", "value": source_label},
            {"type": "display", "id": "count", "label": "sent", "format": "{:.0f}"},
        ],
    }
    layout = [plot_cfg, controls_row]
    _log("demo sender: sending initialize_plots (first pass)")
    try:
        rtp_client.initialize_plots(layout)
    except Exception as exc:  # noqa: BLE001
        _log("initialize_plots (1st) failed: " + traceback.format_exc())
        return f"initialize_plots: {exc}"
    # Slow-joiner guard — sleep + resend. See docstring above.
    time.sleep(0.4)
    _log("demo sender: re-sending initialize_plots (slow-joiner guard)")
    try:
        rtp_client.initialize_plots(layout)
    except Exception as exc:  # noqa: BLE001
        _log("initialize_plots (2nd) failed: " + traceback.format_exc())
        return f"initialize_plots (resend): {exc}"
    _log("demo sender: initialize_plots ok")
    return None


def _port_conflict_message(exc: Exception, args) -> str:
    return (
        f"rtplot-server could not start:\n\n{exc}\n\n"
        f"The most common cause is another process already using one of:\n"
        f"  • TCP {args.port} (HTTP)\n"
        f"  • TCP 5555 (ZMQ data)\n"
        f"  • TCP 5556 (ZMQ control)\n\n"
        "Check Task Manager for a stray rtplot-server.exe, or shut down\n"
        "any WSL/other Python process hosting an rtplot server.\n\n"
        f"A detailed log has been written to:\n{LOG_FILE}"
    )


def _run_with_gui(args, rest):
    import asyncio
    import tkinter as tk
    from tkinter import ttk
    from aiohttp import web

    _log(f"starting GUI mode port={args.port} host={args.host} pi_ip={args.pi_ip}")

    # Install the log redirect BEFORE importing server_browser so the
    # module-level prints ("ZMQ: bound on tcp://*:5555", etc.) land in
    # our buffer and eventually on the collapsable log panel.
    log_redirect = _TkLogRedirect()
    sys.stdout = log_redirect
    sys.stderr = log_redirect

    settings = _load_settings()

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

    # server_browser binds ZMQ sockets at import time. If those binds
    # fail (port already in use) the import itself throws and we never
    # get to the Tk window. Catch it and pop up a dialog explaining
    # what happened instead of silently closing the console.
    try:
        from rtplot import server_browser as sb  # noqa: E402
    except Exception as exc:  # noqa: BLE001
        _log("server_browser import failed: " + traceback.format_exc())
        _show_error_dialog("rtplot-server", _port_conflict_message(exc, args))
        return

    # Start the aiohttp server in a background thread with its own event
    # loop. web.run_app() can't be called off the main thread because it
    # installs signal handlers, so we drop down to AppRunner + TCPSite.
    server_ready = threading.Event()
    startup_error = {"value": None}

    def _server_thread():
        # On Windows the default event loop policy is ProactorEventLoop,
        # which pyzmq's asyncio integration cannot use (no add_reader).
        # Force Selector before creating the loop so zmq_receiver() works.
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            app = sb.build_app()
            runner = web.AppRunner(app)
            loop.run_until_complete(runner.setup())
            site = web.TCPSite(runner, args.host, args.port)
            loop.run_until_complete(site.start())
            print(f"http listening on {args.host}:{args.port}")
            server_ready.set()
            loop.run_forever()
        except Exception as exc:  # noqa: BLE001
            _log("server thread crashed: " + traceback.format_exc())
            startup_error["value"] = exc
            server_ready.set()

    thread = threading.Thread(target=_server_thread, daemon=True)
    thread.start()
    server_ready.wait(timeout=8)
    if startup_error["value"] is not None:
        _show_error_dialog(
            "rtplot-server", _port_conflict_message(startup_error["value"], args)
        )
        return
    if not server_ready.is_set():
        _show_error_dialog(
            "rtplot-server",
            "rtplot-server did not become ready within 8 seconds.\n\n"
            f"See the log at:\n{LOG_FILE}",
        )
        return

    # ---------------------------------------------------------------- UI
    # Layout philosophy: the user downloaded an exe and double-clicked it.
    # They want to know (1) is it running? (2) how do I see my plots?
    # Everything else — demo sender, save path, server logs — is hidden
    # behind a single "Show advanced options" collapse so the main screen
    # stays light and unintimidating.
    root = tk.Tk()
    root.title("rtplot server")
    # Width stays fixed, height is user-resizable so they always have
    # an escape hatch if auto-sizing ever undercounts on a weird DPI.
    root.resizable(False, True)

    try:
        style = ttk.Style()
        style.theme_use("vista" if "vista" in style.theme_names() else "clam")
    except tk.TclError:
        pass

    BG = "#f7f7f7"
    try:
        root.configure(bg=BG)
    except tk.TclError:
        pass

    # Custom ttk styles for the hero + helpers
    try:
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG)
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG)
        style.configure(
            "Hero.TLabel",
            font=("Segoe UI", 15, "bold"),
            foreground="#186a18",
            background=BG,
        )
        style.configure(
            "Subhead.TLabel",
            font=("Segoe UI", 10),
            foreground="#555",
            background=BG,
        )
        style.configure(
            "Muted.TLabel",
            font=("Segoe UI", 9),
            foreground="#777",
            background=BG,
        )
        style.configure(
            "Mono.TLabel",
            font=("Consolas", 9),
            foreground="#555",
            background=BG,
        )
        style.configure(
            "Section.TLabel",
            font=("Segoe UI", 10, "bold"),
            foreground="#333",
            background=BG,
        )
        style.configure(
            "Help.TLabel",
            font=("Segoe UI", 9),
            foreground="#888",
            background=BG,
        )
        style.configure(
            "Primary.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(14, 7),
        )
        style.configure(
            "Link.TButton",
            foreground="#2a5db0",
            background=BG,
            borderwidth=0,
            padding=(0, 2),
            font=("Segoe UI", 9),
        )
        style.map(
            "Link.TButton",
            foreground=[("active", "#1a3d80")],
            background=[("active", BG)],
        )
    except tk.TclError:
        pass

    def _selectable_label(parent, text, font=("Consolas", 9), fg="#555"):
        """A borderless tk.Entry styled to look like a Label but with
        OS-selectable text. Used for URLs and any other string the user
        might want to copy."""
        e = tk.Entry(
            parent,
            font=font,
            bg=BG,
            fg=fg,
            bd=0,
            relief="flat",
            readonlybackground=BG,
            highlightthickness=0,
            takefocus=0,
            cursor="xterm",
        )
        e.insert(0, text)
        e.configure(state="readonly")
        return e

    main = ttk.Frame(root, padding=(24, 20, 24, 0))
    main.pack(fill="both", expand=True)

    # ---- Hero: running indicator + one-sentence instruction ----
    ttk.Label(
        main,
        text="\u2713  Your rtplot server is running",
        style="Hero.TLabel",
    ).pack(anchor="w")
    ttk.Label(
        main,
        text="Open this address in any browser to see your plots:",
        style="Subhead.TLabel",
    ).pack(anchor="w", pady=(4, 10))

    # ---- Big URL display (clickable, copy-able) ----
    url = f"http://localhost:{args.port}"
    url_var = tk.StringVar(value=url)
    url_entry = tk.Entry(
        main,
        textvariable=url_var,
        font=("Consolas", 13),
        bg="#ffffff",
        fg="#222",
        relief="solid",
        bd=1,
        readonlybackground="#ffffff",
        state="readonly",
        cursor="hand2",
        justify="center",
    )
    url_entry.pack(fill="x", ipady=8)

    def _open_browser(_event=None):
        webbrowser.open(url)

    url_entry.bind("<Button-1>", _open_browser)

    # ---- Primary / secondary action buttons ----
    copy_feedback_var = tk.StringVar(value="")

    def _on_copy():
        root.clipboard_clear()
        root.clipboard_append(url)
        copy_feedback_var.set("copied \u2713")
        root.after(1500, lambda: copy_feedback_var.set(""))

    btn_row = ttk.Frame(main)
    btn_row.pack(fill="x", pady=(12, 4))
    ttk.Button(
        btn_row,
        text="\u25B6  Open in browser",
        style="Primary.TButton",
        command=_open_browser,
    ).pack(side="left")
    ttk.Button(btn_row, text="Copy link", command=_on_copy).pack(
        side="left", padx=(8, 0)
    )
    ttk.Label(btn_row, textvariable=copy_feedback_var, style="Muted.TLabel").pack(
        side="left", padx=(10, 0)
    )

    # ---- LAN IPs as muted helper text (selectable so users can copy) ----
    lan_ips = _lan_ips()
    if lan_ips:
        ttk.Label(
            main,
            text="Also reachable from other devices on your network at:",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(14, 2))
        for ip in lan_ips:
            _selectable_label(
                main,
                text=f"  http://{ip}:{args.port}",
                font=("Consolas", 9),
            ).pack(anchor="w", fill="x")

    # ---- Advanced collapse toggle ----
    advanced_expanded = {"value": False}
    advanced_toggle_var = tk.StringVar(value="\u25B8  Show advanced options")
    advanced_frame = ttk.Frame(main)

    def _relayout_window():
        # Compute the real requested height from Tk instead of hardcoding
        # numbers that undercount on Windows/HiDPI. update_idletasks()
        # forces pending pack/grid work to finish so winfo_reqheight()
        # returns the "natural" height after the most recent toggle.
        root.update_idletasks()
        # Width is still fixed — pick it based on whether the wide log
        # panel is visible, since that's the only thing that really
        # needs more horizontal space.
        if advanced_expanded["value"] and log_state["expanded"]:
            target_w = 600
        elif advanced_expanded["value"]:
            target_w = 520
        else:
            target_w = 480
        req_h = root.winfo_reqheight()
        # A small pad stops children from looking cramped against the
        # bottom of the window on themes that underreport their size.
        target_h = max(req_h + 8, 240)
        root.geometry(f"{target_w}x{target_h}")

    def _toggle_advanced():
        advanced_expanded["value"] = not advanced_expanded["value"]
        if advanced_expanded["value"]:
            advanced_toggle_var.set("\u25BE  Hide advanced options")
            advanced_frame.pack(fill="x", expand=False, pady=(4, 0))
        else:
            advanced_toggle_var.set("\u25B8  Show advanced options")
            advanced_frame.pack_forget()
        _relayout_window()

    ttk.Button(
        main,
        textvariable=advanced_toggle_var,
        command=_toggle_advanced,
        style="Link.TButton",
    ).pack(anchor="w", pady=(18, 0))

    # ==================================================================
    # Advanced section (hidden by default)
    # ==================================================================

    # --- Test sender sub-section ---
    ttk.Separator(advanced_frame, orient="horizontal").pack(fill="x", pady=(12, 10))
    ttk.Label(advanced_frame, text="Test with sample data", style="Section.TLabel").pack(
        anchor="w"
    )
    ttk.Label(
        advanced_frame,
        text="Stream a demo sine wave at the server so you can confirm end-to-end.",
        style="Help.TLabel",
    ).pack(anchor="w", pady=(2, 6))

    demo_state = {
        "running": False,
        "thread": None,
        "stop": None,
        "stats": {"count": 0, "elapsed": 0.0, "error": None},
        "client": None,
    }
    demo_btn_var = tk.StringVar(value="\u25B6 Start demo sender")
    demo_status_var = tk.StringVar(value="")

    target_expanded = {"value": False}
    target_toggle_var = tk.StringVar(value="\u25B8 Send to another PC\u2026")
    target_var = tk.StringVar(value="")

    def _start_demo():
        if demo_state["running"]:
            return
        target_raw = target_var.get().strip()

        if target_raw:
            target, warn = _normalize_demo_target(target_raw)
            if not target:
                target = "127.0.0.1"
            if warn:
                _log(
                    f"demo sender: target normalized: {target_raw!r} -> {target!r} ({warn})"
                )
                target_var.set(target)
        else:
            target = "127.0.0.1"

        demo_status_var.set("importing rtplot.client\u2026")
        _log(f"demo sender: start requested, target={target}")
        try:
            if demo_state["client"] is None:
                from rtplot import client as rtp_client  # noqa: E402
                demo_state["client"] = rtp_client
            rtp_client = demo_state["client"]
        except Exception as exc:  # noqa: BLE001
            _log("demo sender: client import failed: " + traceback.format_exc())
            demo_status_var.set(f"error: {exc}")
            return

        demo_status_var.set(f"connecting to {target}\u2026")
        root.update_idletasks()

        source_label = (
            "demo sender -> localhost"
            if not target_raw
            else f"demo sender -> {target}"
        )
        err = _configure_demo_sender(rtp_client, target, source_label)
        if err is not None:
            _log(f"demo sender: config failed: {err}")
            demo_status_var.set(f"error: {err}")
            return

        if target_raw:
            _remember_host(settings, target)
            target_entry.configure(values=settings.get("recent_hosts", []))

        _log("demo sender: starting sender thread")
        demo_state["stats"] = {"count": 0, "elapsed": 0.0, "error": None}
        demo_state["stop"] = threading.Event()
        demo_state["thread"] = threading.Thread(
            target=_demo_sender_loop,
            args=(rtp_client, demo_state["stop"], demo_state["stats"]),
            daemon=True,
        )
        demo_state["thread"].start()
        demo_state["running"] = True
        demo_btn_var.set("\u25A0 Stop demo sender")
        target_entry.configure(state="disabled")

    def _stop_demo():
        if not demo_state["running"]:
            return
        if demo_state["stop"]:
            demo_state["stop"].set()
        if demo_state["thread"]:
            try:
                demo_state["thread"].join(timeout=1)
            except Exception:  # noqa: BLE001
                pass
        demo_state["running"] = False
        demo_btn_var.set("\u25B6 Start demo sender")
        target_entry.configure(state="normal")

    def _toggle_demo():
        if demo_state["running"]:
            _stop_demo()
        else:
            _start_demo()

    ttk.Button(advanced_frame, textvariable=demo_btn_var, command=_toggle_demo).pack(
        anchor="w"
    )
    ttk.Label(advanced_frame, textvariable=demo_status_var, style="Muted.TLabel").pack(
        anchor="w", pady=(4, 0)
    )

    def _toggle_target():
        target_expanded["value"] = not target_expanded["value"]
        if target_expanded["value"]:
            target_row.pack(anchor="w", fill="x", pady=(4, 0))
            target_toggle_var.set("\u25BE Hide target")
        else:
            target_row.pack_forget()
            target_toggle_var.set("\u25B8 Send to another PC\u2026")

    ttk.Button(
        advanced_frame,
        textvariable=target_toggle_var,
        command=_toggle_target,
        style="Link.TButton",
    ).pack(anchor="w", pady=(6, 0))

    target_row = ttk.Frame(advanced_frame)
    target_entry = ttk.Combobox(
        target_row,
        textvariable=target_var,
        values=settings.get("recent_hosts", []),
        width=22,
    )
    target_entry.pack(side="left", padx=(0, 6))
    ttk.Label(
        target_row,
        text="host or host:5555  \u2014  blank = localhost",
        style="Help.TLabel",
    ).pack(side="left")
    # target_row starts hidden

    def poll_demo_stats():
        if demo_state["running"]:
            stats = demo_state["stats"]
            if stats.get("error"):
                demo_status_var.set(f"error: {stats['error']}")
            else:
                demo_status_var.set(
                    f"{stats['count']} samples sent  \u00B7  {stats['elapsed']:.1f} s"
                )
        root.after(250, poll_demo_stats)

    poll_demo_stats()

    # --- Log sub-section (further collapsable inside advanced) ---
    ttk.Separator(advanced_frame, orient="horizontal").pack(fill="x", pady=(14, 10))
    log_state = {"expanded": False}
    log_toggle_var = tk.StringVar(value="\u25B8 Show server log")

    log_frame = ttk.Frame(advanced_frame)
    log_text = tk.Text(
        log_frame,
        height=10,
        width=60,
        wrap="word",
        state="disabled",
        bg="#111",
        fg="#eee",
        insertbackground="#eee",
        font=("Consolas", 9),
        relief="flat",
        padx=6,
        pady=4,
    )
    log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=log_text.yview)
    log_text.configure(yscrollcommand=log_scroll.set)
    log_text.pack(side="left", fill="both", expand=True)
    log_scroll.pack(side="right", fill="y")

    def set_log_expanded(expanded):
        log_state["expanded"] = expanded
        if expanded:
            log_toggle_var.set("\u25BE Hide server log")
            log_frame.pack(fill="both", expand=True, pady=(6, 0))
        else:
            log_toggle_var.set("\u25B8 Show server log")
            log_frame.pack_forget()
        _relayout_window()

    ttk.Button(
        advanced_frame,
        textvariable=log_toggle_var,
        command=lambda: set_log_expanded(not log_state["expanded"]),
        style="Link.TButton",
    ).pack(anchor="w")

    def pump_logs():
        chunks = []
        while True:
            try:
                chunks.append(log_redirect.queue.get_nowait())
            except queue.Empty:
                break
        if chunks:
            log_text.configure(state="normal")
            log_text.insert("end", "".join(chunks))
            num_lines = int(log_text.index("end-1c").split(".")[0])
            if num_lines > 5000:
                log_text.delete("1.0", f"{num_lines - 5000}.0")
            log_text.see("end")
            log_text.configure(state="disabled")
        root.after(250, pump_logs)

    pump_logs()

    # ---- Status bar at the bottom ----
    status_bar_var = tk.StringVar(value="starting\u2026")
    status_bar = tk.Label(
        root,
        textvariable=status_bar_var,
        bg="#e8e8e8",
        fg="#555",
        font=("Segoe UI", 8),
        padx=14,
        pady=4,
        anchor="w",
    )
    status_bar.pack(side="bottom", fill="x")

    def poll_status_bar():
        try:
            zm = getattr(sb, "zmq_status", {}) or {}
            mode = zm.get("mode", "?")
            target = zm.get("target", "")
            state_d = getattr(sb, "state", {}) or {}
            fps = state_d.get("fps", 0) or 0
            num_clients = len(getattr(sb, "ws_clients", set()) or set())
            mode_label = (
                f"ZMQ {mode}" if mode != "connect" else f"ZMQ \u2192 {target}"
            )
            client_word = "browser" if num_clients == 1 else "browsers"
            status_bar_var.set(
                f"{mode_label}   \u00B7   {fps:.0f} Hz   \u00B7   {num_clients} {client_word}"
            )
        except Exception as exc:  # noqa: BLE001
            status_bar_var.set(f"status error: {exc}")
        root.after(500, poll_status_bar)

    poll_status_bar()
    _relayout_window()  # initial sizing

    def on_close():
        if demo_state["running"] and demo_state["stop"]:
            demo_state["stop"].set()
        root.destroy()
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def _run_test_client(args, rest):
    """Send a demo sine wave to a remote rtplot server.

    Provides a zero-Python way to smoke-test cross-PC connectivity:
    on the viewing PC, run the server exe; on the sending PC, run
    ``rtplot-server.exe --test-client <viewing-pc-ip>``. A small Tk
    window appears showing how many samples have been sent so the
    user knows the connection is alive even before they look at the
    server's browser page.
    """
    import tkinter as tk
    from tkinter import ttk

    target_raw = args.test_client
    target, warn = _normalize_demo_target(target_raw)
    if not target:
        target = "127.0.0.1"
    if warn:
        _log(f"test-client target normalized: {target_raw!r} -> {target!r} ({warn})")
    _log(f"starting test-client mode target={target}")

    log_redirect = _TkLogRedirect()
    sys.stdout = log_redirect
    sys.stderr = log_redirect

    try:
        from rtplot import client as rtp_client
    except Exception as exc:  # noqa: BLE001
        _log("client import failed: " + traceback.format_exc())
        _show_error_dialog(
            "rtplot test client",
            f"Failed to import rtplot.client:\n\n{exc}\n\nSee {LOG_FILE}",
        )
        return

    err = _configure_demo_sender(rtp_client, target, f"test client -> {target}")
    if err is not None:
        _show_error_dialog(
            "rtplot test client",
            f"{err}\n\nCheck the host is reachable (ping it) and that the\n"
            "rtplot-server is running there on the default ZMQ port (5555).",
        )
        return
    print(f"initialized remote plot on {target}")

    root = tk.Tk()
    root.title("rtplot test client")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame, text="rtplot test client", font=("Segoe UI", 13, "bold")
    ).pack(anchor="w")
    ttk.Label(
        frame, text=f"Sending demo data to  {target}", foreground="#555"
    ).pack(anchor="w", pady=(0, 10))
    ttk.Label(
        frame,
        text=(
            "Open the rtplot server's browser on the target machine\n"
            "— you should see a 1.5 Hz sine wave streaming in."
        ),
        foreground="#555",
    ).pack(anchor="w", pady=(0, 10))

    count_var = tk.StringVar(value="0 samples sent")
    elapsed_var = tk.StringVar(value="elapsed 0.0 s")
    ttk.Label(frame, textvariable=count_var).pack(anchor="w")
    ttk.Label(frame, textvariable=elapsed_var).pack(anchor="w", pady=(0, 12))

    stop_event = threading.Event()
    stats = {"count": 0, "elapsed": 0.0, "error": None}

    sender_thread = threading.Thread(
        target=_demo_sender_loop,
        args=(rtp_client, stop_event, stats),
        daemon=True,
    )
    sender_thread.start()

    def poll_stats():
        if stats["error"] is not None:
            count_var.set(f"ERROR: {stats['error']}")
        else:
            count_var.set(f"{stats['count']} samples sent")
            elapsed_var.set(f"elapsed {stats['elapsed']:.1f} s")
        root.after(200, poll_stats)

    poll_stats()

    def on_stop():
        stop_event.set()
        try:
            sender_thread.join(timeout=1)
        except Exception:  # noqa: BLE001
            pass
        root.destroy()
        os._exit(0)

    ttk.Button(frame, text="Stop and close", command=on_stop).pack(anchor="w")
    root.protocol("WM_DELETE_WINDOW", on_stop)
    root.mainloop()


def main():
    _log("=" * 60)
    _log(f"rtplot-server started argv={sys.argv}")
    try:
        args, rest = _parse_wrapper_args(sys.argv[1:])
        if args.test_client:
            _run_test_client(args, rest)
        elif args.no_gui:
            _run_headless(args, rest)
        else:
            _run_with_gui(args, rest)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _log("unhandled error: " + traceback.format_exc())
        _show_error_dialog(
            "rtplot-server",
            f"Unexpected error:\n\n{exc}\n\nA log has been written to:\n{LOG_FILE}",
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
