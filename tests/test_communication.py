"""End-to-end tests for the rtplot browser server.

Each test class spawns a fresh server subprocess on the default ports
(8050 HTTP, 5555/5556 ZMQ) and drives it via the live WebSocket protocol
so the test is faithful to what a real browser sees. Tests run
sequentially; a stale server from one test would block the next, so we
poll for port-availability before declaring a test class ready.

Run:
    python3 -m unittest tests.test_communication -v

Or with pytest:
    pytest tests/test_communication.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from collections import OrderedDict

import aiohttp
import numpy as np
import zmq


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
HTTP_PORT = 8050
ZMQ_DATA_PORT = 5555
ZMQ_CTRL_PORT = 5556


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_port(host: str, port: int, timeout: float = 6.0, want_open: bool = True):
    """Block until the TCP port is open (or closed if want_open=False)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                if want_open:
                    return True
        except OSError:
            if not want_open:
                return True
        time.sleep(0.1)
    return False


def _kill_listeners_on(port: int):
    """Best-effort cleanup of any straggler holding ``port``.

    Tests are sequential, but if a prior failed run left a server alive
    we'd block forever waiting for ports. Try fuser; ignore if missing.
    """
    if shutil.which("fuser"):
        subprocess.run(
            ["fuser", "-k", f"{port}/tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


class ServerProcess:
    """Starts and stops the rtplot browser server as a subprocess."""

    def __init__(self, *, password: str | None = None, tabs_file: str | None = None):
        self.password = password
        self.tabs_file = tabs_file
        self.proc: subprocess.Popen | None = None
        self.log_file = tempfile.NamedTemporaryFile(
            prefix="rtplot-test-", suffix=".log", delete=False
        )

    def start(self):
        # Port-handoff hardening: previous test class may have just freed
        # 8050 and the kernel may need a beat. We only fuser-kill the
        # HTTP port — never the ZMQ ones, since some tests intentionally
        # hold 5555 in this same process to test bind-failure paths, and
        # fuser would kill us instead of the imaginary stragglers.
        if _wait_for_port("127.0.0.1", HTTP_PORT, timeout=0.05):
            _kill_listeners_on(HTTP_PORT)
            _wait_for_port("127.0.0.1", HTTP_PORT, timeout=4.0, want_open=False)
        for port in (ZMQ_DATA_PORT, ZMQ_CTRL_PORT):
            _wait_for_port("127.0.0.1", port, timeout=2.0, want_open=False)

        env = os.environ.copy()
        env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        # Force unbuffered stdio so tests that grep the server log see
        # print() output without waiting for the process to exit.
        env["PYTHONUNBUFFERED"] = "1"
        if self.password is not None:
            env["RTPLOT_PASSWORD"] = self.password
        else:
            env.pop("RTPLOT_PASSWORD", None)
        # Redirect the persisted-tabs file via env var so tests don't
        # need to override HOME (which would also evict ~/.local
        # site-packages and break stdlib imports like numpy).
        if self.tabs_file is not None:
            env["RTPLOT_TABS_FILE"] = self.tabs_file
        else:
            env.pop("RTPLOT_TABS_FILE", None)

        self.proc = subprocess.Popen(
            [sys.executable, "-m", "rtplot.server_browser", "--no-browser",
             "--port", str(HTTP_PORT)],
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
            cwd=REPO_ROOT,
            env=env,
        )
        if not _wait_for_port("127.0.0.1", HTTP_PORT, timeout=15.0):
            self.stop()
            log_tail = "\n".join(self.log_text().splitlines()[-30:])
            raise RuntimeError(
                f"server did not bind {HTTP_PORT} within 15 s.\n"
                f"--- tail of server log ---\n{log_tail}"
            )

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
        # Give the OS a moment to release the bound ports so the next
        # test class doesn't race us.
        for port in (HTTP_PORT, ZMQ_DATA_PORT, ZMQ_CTRL_PORT):
            _wait_for_port("127.0.0.1", port, timeout=4.0, want_open=False)
        self.log_file.close()

    def log_text(self) -> str:
        try:
            with open(self.log_file.name, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""


class ZmqTestClient:
    """Minimal stand-in for rtplot.client running in the test process.

    We don't import rtplot.client directly because it grabs the default
    bind address at import time and can't easily be torn down between
    tests. Speaking the wire protocol by hand is shorter and clearer.
    """

    def __init__(self):
        self.ctx = zmq.Context.instance()
        self.pub = self.ctx.socket(zmq.PUB)
        self.pub.connect(f"tcp://127.0.0.1:{ZMQ_DATA_PORT}")
        self.pull = self.ctx.socket(zmq.PULL)
        self.pull.setsockopt(zmq.RCVHWM, 1000)
        self.pull.connect(f"tcp://127.0.0.1:{ZMQ_CTRL_PORT}")
        # Slow-joiner guard: PUB drops messages until the SUB has finished
        # subscribing. 300 ms is empirical — the server's SUB has been up
        # since startup, but the local PUB connect handshake still races.
        time.sleep(0.3)

    def send_config(self, cfg_dict):
        self.pub.send_string("0", flags=zmq.SNDMORE)
        self.pub.send_json(cfg_dict)

    def send_data(self, arr: np.ndarray):
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        md = {"dtype": str(arr.dtype), "shape": list(arr.shape)}
        self.pub.send_string("1", flags=zmq.SNDMORE)
        self.pub.send_json(md, flags=zmq.SNDMORE)
        self.pub.send(arr.tobytes())

    def send_display(self, did: str, value):
        self.pub.send_string("4", flags=zmq.SNDMORE)
        self.pub.send_json({"id": did, "value": value})

    def poll_one(self, timeout: float = 1.0):
        """Drain one control event with a timeout. Returns dict or None."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                return self.pull.recv_json(flags=zmq.NOBLOCK)
            except zmq.Again:
                time.sleep(0.02)
        return None

    def close(self):
        try: self.pub.close(0)
        except Exception: pass
        try: self.pull.close(0)
        except Exception: pass


async def _drain_until(ws, predicate, timeout=4.0):
    """Read WS messages until ``predicate(msg_dict_or_bytes)`` returns truthy.

    Returns the matching message, or None on timeout.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        remaining = deadline - asyncio.get_event_loop().time()
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=max(0.05, remaining))
        except asyncio.TimeoutError:
            return None
        if msg.type == aiohttp.WSMsgType.TEXT:
            d = json.loads(msg.data)
            if predicate(d):
                return d
        elif msg.type == aiohttp.WSMsgType.BINARY:
            if predicate(msg.data):
                return msg.data
        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            return None
    return None


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class _ServerTest(unittest.TestCase):
    """Base: each subclass gets a fresh server with an isolated tabs file.

    Without isolation, tests that create connect tabs would persist them
    to the user's real ~/.rtplot/tabs.json and the next test class would
    inherit a polluted tab list.
    """
    server: ServerProcess
    _tabs_dir: str

    SERVER_KWARGS: dict = {}

    @classmethod
    def setUpClass(cls):
        cls._tabs_dir = tempfile.mkdtemp(prefix="rtplot-tabs-")
        kwargs = dict(cls.SERVER_KWARGS)
        kwargs.setdefault("tabs_file", os.path.join(cls._tabs_dir, "tabs.json"))
        cls.server = ServerProcess(**kwargs)
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        shutil.rmtree(cls._tabs_dir, ignore_errors=True)

    def run_async(self, coro, timeout=15.0):
        return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


class TestInitialState(_ServerTest):
    def test_only_bind_me_at_startup(self):
        async def go():
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                    msg = await _drain_until(ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs")
                    self.assertIsNotNone(msg)
                    ids = [t["id"] for t in msg["tabs"]]
                    self.assertEqual(ids, ["bind_me"])
                    self.assertEqual(msg["tabs"][0]["name"], "Shared - Bind to me")
                    self.assertEqual(msg["tabs"][0]["mode"], "bind")
        self.run_async(go())


class TestBindModeRoundtrip(_ServerTest):
    def test_config_and_data_reach_browser(self):
        async def go():
            zc = ZmqTestClient()
            try:
                cfg = OrderedDict([("p0", {"names": ["x", "y"], "title": "RT", "xrange": 200})])
                zc.send_config(cfg)
                # Send a few data frames
                for _ in range(5):
                    zc.send_data(np.random.randn(2, 50).astype(np.float64))
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await ws.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                        cfg_msg = await _drain_until(
                            ws, lambda d: isinstance(d, dict) and d.get("type") == "config"
                        )
                        self.assertIsNotNone(cfg_msg, "no config msg")
                        self.assertEqual(cfg_msg["plots"][0]["title"], "RT")
                        self.assertEqual(cfg_msg["plots"][0]["names"], ["x", "y"])
                        # And a binary data frame
                        bin_msg = await _drain_until(
                            ws, lambda d: isinstance(d, (bytes, bytearray))
                        )
                        self.assertIsNotNone(bin_msg, "no binary frame")
                        self.assertGreater(len(bin_msg), 16)
            finally:
                zc.close()
        self.run_async(go())


class TestTabCRUD(_ServerTest):
    def test_create_rename_delete(self):
        async def go():
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                    await _drain_until(ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs")
                    # CREATE
                    await ws.send_str(json.dumps({
                        "type": "tab_create", "name": "MyDevice", "endpoint": "127.0.0.1:5599"
                    }))
                    new_tab = None
                    msg = await _drain_until(
                        ws,
                        lambda d: isinstance(d, dict) and d.get("type") == "tabs"
                                  and any(t["id"] != "bind_me" for t in d["tabs"]),
                    )
                    self.assertIsNotNone(msg)
                    for t in msg["tabs"]:
                        if t["id"] != "bind_me":
                            new_tab = t["id"]
                    self.assertIsNotNone(new_tab)

                    # RENAME
                    await ws.send_str(json.dumps({
                        "type": "tab_rename", "id": new_tab, "name": "Renamed"
                    }))
                    upd = await _drain_until(
                        ws,
                        lambda d: isinstance(d, dict) and d.get("type") == "tab"
                                  and d["tab"]["id"] == new_tab and d["tab"]["name"] == "Renamed",
                    )
                    self.assertIsNotNone(upd)

                    # DELETE
                    await ws.send_str(json.dumps({"type": "tab_delete", "id": new_tab}))
                    rem = await _drain_until(
                        ws,
                        lambda d: isinstance(d, dict) and d.get("type") == "tab_removed"
                                  and d["id"] == new_tab,
                    )
                    self.assertIsNotNone(rem)

                    # bind_me should be unaffected by attempted delete
                    await ws.send_str(json.dumps({"type": "tab_delete", "id": "bind_me"}))
                    await asyncio.sleep(0.3)
                    await ws.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                    sub_ack = await _drain_until(
                        ws,
                        lambda d: isinstance(d, dict) and d.get("type") in ("zmq_status", "no_config"),
                    )
                    self.assertIsNotNone(sub_ack, "bind_me was wrongly deletable")
        self.run_async(go())


class TestTabPersistence(unittest.TestCase):
    """Server restart should restore user-created connect tabs."""

    def test_persisted_tab_survives_restart(self):
        tmp_dir = tempfile.mkdtemp(prefix="rtplot-tabs-")
        tabs_file = os.path.join(tmp_dir, "tabs.json")
        try:
            # 1) Start server, create a tab.
            srv = ServerProcess(tabs_file=tabs_file)
            srv.start()
            try:
                async def create():
                    async with aiohttp.ClientSession() as s:
                        async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                            await _drain_until(ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs")
                            await ws.send_str(json.dumps({
                                "type": "tab_create", "name": "Persisty", "endpoint": "127.0.0.1:5599"
                            }))
                            await _drain_until(
                                ws,
                                lambda d: isinstance(d, dict) and d.get("type") == "tabs"
                                          and any(t.get("name") == "Persisty" for t in d["tabs"]),
                            )
                asyncio.run(asyncio.wait_for(create(), timeout=10.0))
            finally:
                srv.stop()

            # tabs.json should exist where we asked.
            self.assertTrue(os.path.exists(tabs_file), f"tabs.json not at {tabs_file}")
            with open(tabs_file) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "Persisty")

            # 2) Restart server, confirm the tab returns.
            srv2 = ServerProcess(tabs_file=tabs_file)
            srv2.start()
            try:
                async def verify():
                    async with aiohttp.ClientSession() as s:
                        async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                            msg = await _drain_until(
                                ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs"
                            )
                            names = sorted(t["name"] for t in msg["tabs"])
                            self.assertEqual(names, ["Persisty", "Shared - Bind to me"])
                asyncio.run(asyncio.wait_for(verify(), timeout=10.0))
            finally:
                srv2.stop()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestInvalidConfig(_ServerTest):
    def test_bad_config_sets_error_and_clears_on_good(self):
        async def go():
            zc = ZmqTestClient()
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await ws.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                        await _drain_until(
                            ws, lambda d: isinstance(d, dict) and d.get("type") in ("no_config", "config")
                        )
                        # Send a bad config (missing 'names').
                        zc.send_config(OrderedDict([("p0", {"title": "broken", "xrange": 200})]))
                        bad = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict)
                                      and d.get("type") == "tab"
                                      and d["tab"]["id"] == "bind_me"
                                      and d["tab"].get("last_config_error"),
                        )
                        self.assertIsNotNone(bad)
                        err = bad["tab"]["last_config_error"]
                        self.assertIn("KeyError", err["message"])
                        self.assertGreater(err["timestamp"], time.time() - 60)
                        # A good config clears it.
                        zc.send_config(OrderedDict([("p0", {"names": ["x"]})]))
                        cleared = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict)
                                      and d.get("type") == "tab"
                                      and d["tab"]["id"] == "bind_me"
                                      and d["tab"].get("last_config_error") is None,
                        )
                        self.assertIsNotNone(cleared)
            finally:
                zc.close()
        self.run_async(go())


class TestReconnectResendsConfig(_ServerTest):
    """The user's reported bug: clicking Reconnect should ask the still-
    running client to re-send its initialize_plots() payload so the plot
    recovers without a script restart."""

    def test_reconnect_triggers_resend(self):
        async def go():
            zc = ZmqTestClient()
            try:
                # 1) Initial config + a poll loop in the background to drain
                #    the PULL socket like a real client would.
                cfg = OrderedDict([("p0", {"names": ["sig"], "title": "RECON", "xrange": 200})])
                zc.send_config(cfg)

                stop = asyncio.Event()
                async def pull_loop():
                    while not stop.is_set():
                        ev = await asyncio.get_event_loop().run_in_executor(
                            None, zc.poll_one, 0.1
                        )
                        if ev and ev.get("type") == "resend_config":
                            zc.send_config(cfg)
                pull_task = asyncio.create_task(pull_loop())

                try:
                    async with aiohttp.ClientSession() as s:
                        async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                            await ws.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                            first = await _drain_until(
                                ws,
                                lambda d: isinstance(d, dict) and d.get("type") == "config"
                                          and d.get("plots", [{}])[0].get("title") == "RECON",
                                timeout=5,
                            )
                            self.assertIsNotNone(first, "no initial config delivered")

                            # Click Reconnect
                            await ws.send_str(json.dumps({"type": "tab_reconnect", "id": "bind_me"}))

                            second = await _drain_until(
                                ws,
                                lambda d: isinstance(d, dict) and d.get("type") == "config"
                                          and d.get("plots", [{}])[0].get("title") == "RECON",
                                timeout=12,  # generous for the retry schedule
                            )
                            self.assertIsNotNone(
                                second,
                                "config did not return after Reconnect — resend handshake failed",
                            )
                finally:
                    stop.set()
                    await asyncio.sleep(0.2)
                    pull_task.cancel()
                    try: await pull_task
                    except asyncio.CancelledError: pass
            finally:
                zc.close()
        self.run_async(go(), timeout=30.0)


class TestControlButtonRouting(_ServerTest):
    def test_browser_button_arrives_at_client(self):
        async def go():
            zc = ZmqTestClient()
            try:
                # Declare a controls row with a button.
                cfg = OrderedDict([
                    ("p0", {"names": ["x"]}),
                    ("ctrl0", {"controls": [{"type": "button", "id": "go", "label": "Go"}]}),
                ])
                zc.send_config(cfg)
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await ws.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                        await _drain_until(
                            ws, lambda d: isinstance(d, dict) and d.get("type") == "config"
                        )
                        # Send a button click from the "browser".
                        await ws.send_str(json.dumps({"type": "control_button", "id": "go"}))
                # Client should see it on its PULL socket. Skip past any
                # config_ack / seeded slider events emitted on parse.
                got = None
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    ev = zc.poll_one(timeout=0.3)
                    if ev is None: continue
                    if ev.get("type") == "button":
                        got = ev; break
                self.assertIsNotNone(got, "client never received the button event")
                self.assertEqual(got.get("id"), "go")
            finally:
                zc.close()
        self.run_async(go())


class TestControlSliderRouting(_ServerTest):
    def test_slider_value_round_trips(self):
        async def go():
            zc = ZmqTestClient()
            try:
                cfg = OrderedDict([
                    ("p0", {"names": ["x"]}),
                    ("ctrl0", {"controls": [
                        {"type": "slider", "id": "k", "label": "k",
                         "min": 0, "max": 10, "value": 3.0},
                    ]}),
                ])
                zc.send_config(cfg)
                # On parse, server emits config_ack + the seeded slider
                # value. Drain until we pick out the seeded slider.
                seed = None
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    ev = zc.poll_one(timeout=0.3)
                    if ev is None: continue
                    if ev.get("type") == "slider" and ev.get("id") == "k":
                        seed = ev; break
                self.assertIsNotNone(seed, "server didn't echo seeded slider")
                self.assertAlmostEqual(seed.get("value"), 3.0)

                # Now drag from a "browser".
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await ws.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                        await _drain_until(
                            ws, lambda d: isinstance(d, dict) and d.get("type") == "config"
                        )
                        await ws.send_str(json.dumps({
                            "type": "control_slider", "id": "k", "value": 7.5
                        }))
                drag = None
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    ev = zc.poll_one(timeout=0.3)
                    if ev is None: continue
                    if ev.get("type") == "slider" and ev.get("id") == "k" \
                            and abs(ev.get("value", 0) - 7.5) < 1e-6:
                        drag = ev; break
                self.assertIsNotNone(drag, "client never saw the dragged slider value")
            finally:
                zc.close()
        self.run_async(go())


class TestControlTextRouting(_ServerTest):
    def test_text_value_round_trips(self):
        async def go():
            zc = ZmqTestClient()
            try:
                cfg = OrderedDict([
                    ("p0", {"names": ["x"]}),
                    ("ctrl0", {"controls": [
                        {
                            "type": "text_input",
                            "id": "log_name",
                            "label": "Log Name",
                            "value": "",
                            "placeholder": "walk_fast_01",
                            "max_length": 80,
                        },
                    ]}),
                ])
                zc.send_config(cfg)
                seed = None
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    ev = zc.poll_one(timeout=0.3)
                    if ev is None:
                        continue
                    if ev.get("type") == "text" and ev.get("id") == "log_name":
                        seed = ev
                        break
                self.assertIsNotNone(seed, "server didn't echo seeded text input")
                self.assertEqual(seed.get("value"), "")

                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await ws.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                        cfg_msg = await _drain_until(
                            ws, lambda d: isinstance(d, dict) and d.get("type") == "config"
                        )
                        self.assertIsNotNone(cfg_msg)
                        self.assertEqual(
                            cfg_msg.get("text_values", {}).get("log_name"),
                            "",
                        )
                        await ws.send_str(json.dumps({
                            "type": "control_text",
                            "id": "log_name",
                            "value": "walk_fast_01",
                        }))
                typed = None
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    ev = zc.poll_one(timeout=0.3)
                    if ev is None:
                        continue
                    if ev.get("type") == "text" and ev.get("id") == "log_name":
                        if ev.get("value") == "walk_fast_01":
                            typed = ev
                            break
                self.assertIsNotNone(typed, "client never saw the text input update")
            finally:
                zc.close()
        self.run_async(go())


class TestControlTextUI(_ServerTest):
    def test_browser_text_input_renders_and_sends_updates(self):
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            self.skipTest(f"playwright unavailable: {exc}")

        zc = ZmqTestClient()
        try:
            cfg = OrderedDict([
                ("p0", {"names": ["x"], "title": "TEXT_UI"}),
                ("ctrl0", {"controls": [
                    {
                        "type": "text_input",
                        "id": "log_name",
                        "label": "Log Name",
                        "value": "",
                        "placeholder": "walk_fast_01",
                        "max_length": 80,
                    },
                ]}),
            ])
            zc.send_config(cfg)

            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True)
                except PlaywrightError as exc:
                    self.skipTest(f"playwright browser unavailable: {exc}")
                try:
                    page = browser.new_page()
                    page.goto(f"http://localhost:{HTTP_PORT}/", wait_until="domcontentloaded")
                    text_input = page.locator("input.ctrl-textinput")
                    text_input.wait_for(state="visible", timeout=4000)
                    self.assertEqual(text_input.get_attribute("placeholder"), "walk_fast_01")
                    self.assertEqual(text_input.get_attribute("maxlength"), "80")

                    text_input.fill("walk_fast_01")
                    text_input.press("Enter")

                    enter_event = None
                    deadline = time.time() + 3.0
                    while time.time() < deadline:
                        ev = zc.poll_one(timeout=0.3)
                        if ev is None:
                            continue
                        if ev.get("type") == "text" and ev.get("id") == "log_name":
                            if ev.get("value") == "walk_fast_01":
                                enter_event = ev
                                break
                    self.assertIsNotNone(enter_event, "Enter did not send the text input value")

                    text_input.fill("walk_fast_02")
                    page.locator("#status").click()

                    blur_event = None
                    deadline = time.time() + 3.0
                    while time.time() < deadline:
                        ev = zc.poll_one(timeout=0.3)
                        if ev is None:
                            continue
                        if ev.get("type") == "text" and ev.get("id") == "log_name":
                            if ev.get("value") == "walk_fast_02":
                                blur_event = ev
                                break
                    self.assertIsNotNone(blur_event, "Blur did not send the updated text input value")
                finally:
                    browser.close()
        finally:
            zc.close()


class TestDisplayUpdate(_ServerTest):
    def test_display_value_reaches_browser(self):
        async def go():
            zc = ZmqTestClient()
            try:
                cfg = OrderedDict([
                    ("p0", {"names": ["x"]}),
                    ("ctrl0", {"controls": [
                        {"type": "display", "id": "n", "label": "samples", "format": "{:.0f}"},
                    ]}),
                ])
                zc.send_config(cfg)
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await ws.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                        await _drain_until(
                            ws, lambda d: isinstance(d, dict) and d.get("type") == "config"
                        )
                        # Push a display update from the client.
                        zc.send_display("n", 42.0)
                        upd = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict) and d.get("type") == "display_update"
                                      and d.get("values", {}).get("n") == 42.0,
                            timeout=3.0,
                        )
                        self.assertIsNotNone(upd, "display_update never broadcast")
            finally:
                zc.close()
        self.run_async(go())


class TestAuthGate(unittest.TestCase):
    """Cookie-based password gate: anon → 302 /login, login → cookie, WS → 401 without."""

    SERVER_PASSWORD = "hunter2"

    @classmethod
    def setUpClass(cls):
        cls.server = ServerProcess(password=cls.SERVER_PASSWORD)
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_login_flow(self):
        async def go():
            jar = aiohttp.CookieJar(unsafe=True)
            async with aiohttp.ClientSession(cookie_jar=jar) as s:
                # Anon → redirect
                async with s.get(f"http://localhost:{HTTP_PORT}/", allow_redirects=False) as r:
                    self.assertEqual(r.status, 302)
                    self.assertIn("/login", r.headers["Location"])

                # Wrong password
                async with s.post(
                    f"http://localhost:{HTTP_PORT}/login",
                    data={"password": "nope"}, allow_redirects=False,
                ) as r:
                    self.assertEqual(r.status, 401)

                # Right password
                async with s.post(
                    f"http://localhost:{HTTP_PORT}/login",
                    data={"password": self.SERVER_PASSWORD}, allow_redirects=False,
                ) as r:
                    self.assertEqual(r.status, 302)
                    self.assertEqual(r.headers["Location"], "/")
                    self.assertIn("rtplot_session", r.cookies)

                # With cookie → 200 on /
                async with s.get(f"http://localhost:{HTTP_PORT}/", allow_redirects=False) as r:
                    self.assertEqual(r.status, 200)

                # WS without cookie → 401
                async with aiohttp.ClientSession() as s2:
                    with self.assertRaises(aiohttp.WSServerHandshakeError) as cm:
                        async with s2.ws_connect(f"http://localhost:{HTTP_PORT}/ws"):
                            pass
                    self.assertEqual(cm.exception.status, 401)

                # WS with cookie → opens
                async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                    msg = await _drain_until(
                        ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs"
                    )
                    self.assertIsNotNone(msg)
        asyncio.run(asyncio.wait_for(go(), timeout=10.0))


# ---------------------------------------------------------------------------
# Real-client / multi-viewer / connect-mode tests
# ---------------------------------------------------------------------------

# Script we shove into a child process so it runs the actual rtplot.client
# module — not a hand-rolled stand-in. Communicates back via stdout.
# Lines prefixed with "EVT:" are protocol observations the test parses.
_REAL_CLIENT_SCRIPT = """\
import sys, time, json, os
sys.path.insert(0, {repo!r})
from rtplot import client
client.local_plot()
client.initialize_plots({{"names": ["sig"], "title": "REAL", "xrange": 200}})
print("EVT:READY", flush=True)
i = 0
last_btn_count = 0
while True:
    client.send_array(float(i % 100))
    state = client.poll_controls()
    for bid in state.buttons:
        print(f"EVT:BUTTON:{{bid}}", flush=True)
    for sid, sval in state.values.items():
        print(f"EVT:SLIDER:{{sid}}:{{sval}}", flush=True)
    i += 1
    time.sleep(0.05)
"""

_REAL_CLIENT_MIXED_CONTROLS_SCRIPT = """\
import sys, time, json, os
sys.path.insert(0, {repo!r})
from rtplot import client
client.local_plot()
client.initialize_plots([
    {{"names": ["sig"], "title": "REAL_MIXED", "xrange": 200}},
    {{"controls": [
        {{"type": "slider", "id": "torque_cutoff_hz", "label": "Cutoff", "min": 0, "max": 50, "value": 15.0}},
        {{"type": "text_input", "id": "log_name", "label": "Log Name", "value": "", "placeholder": "walk_fast_01", "max_length": 80}},
    ]}},
])
print("EVT:READY", flush=True)
i = 0
while True:
    client.send_array(float(i % 100))
    state = client.poll_controls()
    if "torque_cutoff_hz" in state.values and "log_name" in state.values:
        print("EVT:MIXED:" + json.dumps(state.values, sort_keys=True), flush=True)
    i += 1
    time.sleep(0.05)
"""


def _start_real_client(script=_REAL_CLIENT_SCRIPT):
    """Spawn the real rtplot.client in a subprocess and wait for READY."""
    code = script.format(repo=REPO_ROOT)
    p = subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    deadline = time.time() + 6.0
    while time.time() < deadline:
        line = p.stdout.readline()
        if not line:
            break
        if "EVT:READY" in line:
            return p
    p.terminate(); p.wait(timeout=2)
    raise RuntimeError("real client did not become ready")


def _drain_client_lines(p, predicate, timeout):
    """Read stdout lines from the client subprocess until predicate matches.

    Runs in a thread because Popen.stdout.readline() blocks. Returns the
    matching line or None on timeout.
    """
    import threading, queue
    q: queue.Queue[str] = queue.Queue()

    def reader():
        try:
            for line in p.stdout:
                q.put(line)
        except Exception:
            pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            line = q.get(timeout=max(0.05, deadline - time.time()))
        except queue.Empty:
            continue
        if predicate(line):
            return line
    return None


class TestRealClientPollControls(_ServerTest):
    """Drive the actual rtplot.client.poll_controls() in a subprocess.

    Catches client-side regressions the hand-rolled ZmqTestClient stand-in
    can't see — e.g. a bug in poll_controls()'s drain loop, or in the
    resend_config handler.
    """

    def test_button_round_trip_through_real_client(self):
        proc = _start_real_client()
        try:
            async def go():
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await ws.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                        await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict) and d.get("type") == "config"
                                      and d.get("plots", [{}])[0].get("title") == "REAL",
                            timeout=4,
                        )
                        await ws.send_str(json.dumps({"type": "control_button", "id": "go"}))
            self.run_async(go(), timeout=10)
            line = _drain_client_lines(proc, lambda l: "EVT:BUTTON:go" in l, timeout=4.0)
            self.assertIsNotNone(line, "real client never observed the button event")
        finally:
            proc.terminate(); proc.wait(timeout=2)

    def test_resend_config_through_real_client(self):
        proc = _start_real_client()
        try:
            async def go():
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await ws.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                        first = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict) and d.get("type") == "config"
                                      and d.get("plots", [{}])[0].get("title") == "REAL",
                            timeout=4,
                        )
                        self.assertIsNotNone(first)
                        await ws.send_str(json.dumps({"type": "tab_reconnect", "id": "bind_me"}))
                        # Real client's poll_controls() should pick up
                        # resend_config and re-publish; we should see the
                        # config arrive a second time over WS.
                        second = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict) and d.get("type") == "config"
                                      and d.get("plots", [{}])[0].get("title") == "REAL",
                            timeout=12,
                        )
                        self.assertIsNotNone(
                            second,
                            "real client did not re-publish config after Reconnect",
                        )
            self.run_async(go(), timeout=20)
        finally:
            proc.terminate(); proc.wait(timeout=2)

    def test_mixed_slider_and_text_values_through_real_client(self):
        proc = _start_real_client(_REAL_CLIENT_MIXED_CONTROLS_SCRIPT)
        try:
            async def go():
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await ws.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                        cfg = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict) and d.get("type") == "config"
                                      and d.get("plots", [{}])[0].get("title") == "REAL_MIXED",
                            timeout=4,
                        )
                        self.assertIsNotNone(cfg)
                        self.assertEqual(cfg.get("text_values", {}).get("log_name"), "")
                        await ws.send_str(json.dumps({
                            "type": "control_slider",
                            "id": "torque_cutoff_hz",
                            "value": 15.0,
                        }))
                        await ws.send_str(json.dumps({
                            "type": "control_text",
                            "id": "log_name",
                            "value": "walk_fast_01",
                        }))
            self.run_async(go(), timeout=10)
            line = _drain_client_lines(
                proc,
                lambda l: '"log_name": "walk_fast_01"' in l,
                timeout=4.0,
            )
            self.assertIsNotNone(line, "real client never reported mixed control values")
            payload = json.loads(line.split("EVT:MIXED:", 1)[1].strip())
            self.assertEqual(payload.get("log_name"), "walk_fast_01")
            self.assertIsInstance(payload.get("log_name"), str)
            self.assertEqual(payload.get("torque_cutoff_hz"), 15.0)
            self.assertIsInstance(payload.get("torque_cutoff_hz"), float)
        finally:
            proc.terminate(); proc.wait(timeout=2)


class TestConnectModeTab(_ServerTest):
    """Server dials OUT to a sender that bound the data port itself."""

    OUT_DATA_PORT = 5599
    OUT_CTRL_PORT = 5600
    EMPTY_DATA_PORT = 5611
    HEALTH_DATA_PORT = 5613
    HEALTH_CTRL_PORT = 5614
    RESTART_DATA_PORT = 5615
    RESTART_CTRL_PORT = 5616
    UI_MISSING_PORT = 5617
    UI_HEALTH_DATA_PORT = 5619
    UI_HEALTH_CTRL_PORT = 5620
    AUTO_DATA_PORT = 5621
    AUTO_CTRL_PORT = 5622

    def test_connect_tab_closed_rtplot_ports_is_gray(self):
        async def go():
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                    await _drain_until(ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs")
                    await ws.send_str(json.dumps({
                        "type": "tab_create",
                        "name": "ReachableNoRtplot",
                        "endpoint": f"127.0.0.1:{self.EMPTY_DATA_PORT}",
                    }))
                    listing = await _drain_until(
                        ws,
                        lambda d: isinstance(d, dict) and d.get("type") == "tabs"
                                  and any(
                                      t["id"] != "bind_me"
                                      and t["name"] == "ReachableNoRtplot"
                                      and t["status"] == "idle"
                                      for t in d["tabs"]
                                  ),
                        timeout=4,
                    )
                    self.assertIsNotNone(listing, "closed rtplot ports were not marked idle")
                    missing = next(t for t in listing["tabs"] if t.get("name") == "ReachableNoRtplot")
                    self.assertIsNone(missing.get("error"))
        self.run_async(go(), timeout=10)

    def test_connect_tab_unreachable_host_is_red(self):
        async def go():
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                    await _drain_until(ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs")
                    await ws.send_str(json.dumps({
                        "type": "tab_create",
                        "name": "NoSuchHost",
                        "endpoint": "no-such-host.invalid:5555",
                    }))
                    listing = await _drain_until(
                        ws,
                        lambda d: isinstance(d, dict) and d.get("type") == "tabs"
                                  and any(
                                      t["id"] != "bind_me"
                                      and t["name"] == "NoSuchHost"
                                      and t["status"] == "error"
                                      for t in d["tabs"]
                                  ),
                        timeout=4,
                    )
                    self.assertIsNotNone(listing, "unreachable host was not marked error")
                    missing = next(t for t in listing["tabs"] if t.get("name") == "NoSuchHost")
                    self.assertIn("unreachable", missing.get("error") or "")
        self.run_async(go(), timeout=10)

    def test_reconnect_reaches_zmq_connected_before_data(self):
        ctx = zmq.Context.instance()
        pub = ctx.socket(zmq.PUB)
        pub.bind(f"tcp://127.0.0.1:{self.HEALTH_DATA_PORT}")
        pull = ctx.socket(zmq.PULL)
        pull.bind(f"tcp://127.0.0.1:{self.HEALTH_CTRL_PORT}")
        try:
            async def go():
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await _drain_until(ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs")
                        await ws.send_str(json.dumps({
                            "type": "tab_create",
                            "name": "BootedPi",
                            "endpoint": f"127.0.0.1:{self.HEALTH_DATA_PORT}",
                        }))
                        listing = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict) and d.get("type") == "tabs"
                                      and any(t["id"] != "bind_me" and t["name"] == "BootedPi"
                                              for t in d["tabs"]),
                            timeout=4,
                        )
                        tab_id = next(t["id"] for t in listing["tabs"] if t.get("name") == "BootedPi")
                        upd = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict)
                                      and d.get("type") == "tab"
                                      and d["tab"]["id"] == tab_id
                                      and d["tab"]["status"] == "connected",
                            timeout=4,
                        )
                        self.assertIsNotNone(upd, "reachable peer did not become ZMQ-connected")
                        self.assertIsNone(upd["tab"]["error"])
            self.run_async(go(), timeout=12)
        finally:
            pub.close(0); pull.close(0)

    def test_gray_tab_auto_promotes_when_peer_starts(self):
        ctx = zmq.Context.instance()
        pub = None
        pull = None
        try:
            async def go():
                nonlocal pub, pull
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await _drain_until(ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs")
                        await ws.send_str(json.dumps({
                            "type": "tab_create",
                            "name": "StartsLater",
                            "endpoint": f"127.0.0.1:{self.AUTO_DATA_PORT}",
                        }))
                        listing = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict) and d.get("type") == "tabs"
                                      and any(t["id"] != "bind_me" and t["name"] == "StartsLater"
                                              and t["status"] == "idle"
                                              for t in d["tabs"]),
                            timeout=4,
                        )
                        self.assertIsNotNone(listing, "closed ports did not create an idle tab")
                        tab_id = next(t["id"] for t in listing["tabs"] if t.get("name") == "StartsLater")

                        pub = ctx.socket(zmq.PUB)
                        pub.bind(f"tcp://127.0.0.1:{self.AUTO_DATA_PORT}")
                        pull = ctx.socket(zmq.PULL)
                        pull.bind(f"tcp://127.0.0.1:{self.AUTO_CTRL_PORT}")

                        promoted = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict)
                                      and d.get("type") == "tab"
                                      and d["tab"]["id"] == tab_id
                                      and d["tab"]["status"] == "connected",
                            timeout=8,
                        )
                        self.assertIsNotNone(
                            promoted,
                            "idle tab did not auto-promote to connected when peer started",
                        )
            self.run_async(go(), timeout=15)
        finally:
            if pub is not None:
                pub.close(0)
            if pull is not None:
                pull.close(0)

    def test_peer_disconnect_goes_gray_then_reconnect_goes_connected(self):
        ctx = zmq.Context.instance()

        def bind_peer():
            pub = ctx.socket(zmq.PUB)
            pub.bind(f"tcp://127.0.0.1:{self.RESTART_DATA_PORT}")
            pull = ctx.socket(zmq.PULL)
            pull.bind(f"tcp://127.0.0.1:{self.RESTART_CTRL_PORT}")
            return pub, pull

        pub, pull = bind_peer()
        try:
            async def go():
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await _drain_until(ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs")
                        await ws.send_str(json.dumps({
                            "type": "tab_create",
                            "name": "RestartingPi",
                            "endpoint": f"127.0.0.1:{self.RESTART_DATA_PORT}",
                        }))
                        listing = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict) and d.get("type") == "tabs"
                                      and any(t["id"] != "bind_me" and t["name"] == "RestartingPi"
                                              for t in d["tabs"]),
                            timeout=4,
                        )
                        tab_id = next(t["id"] for t in listing["tabs"] if t.get("name") == "RestartingPi")
                        connected = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict)
                                      and d.get("type") == "tab"
                                      and d["tab"]["id"] == tab_id
                                      and d["tab"]["status"] == "connected",
                            timeout=4,
                        )
                        self.assertIsNotNone(connected, "peer did not reach connected before shutdown")

                        nonlocal pub, pull
                        pub.close(0); pull.close(0)
                        pub = pull = None
                        went_gray = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict)
                                      and d.get("type") == "tab"
                                      and d["tab"]["id"] == tab_id
                                      and d["tab"]["status"] == "idle",
                            timeout=5,
                        )
                        self.assertIsNotNone(went_gray, "peer disconnect did not return tab to idle")

                        pub, pull = bind_peer()
                        await ws.send_str(json.dumps({"type": "tab_reconnect", "id": tab_id}))
                        recovered = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict)
                                      and d.get("type") == "tab"
                                      and d["tab"]["id"] == tab_id
                                      and d["tab"]["status"] == "connected",
                            timeout=5,
                        )
                        self.assertIsNotNone(recovered, "Reconnect did not restore connected status")
                        self.assertIsNone(recovered["tab"]["error"])
            self.run_async(go(), timeout=20)
        finally:
            if pub is not None:
                pub.close(0)
            if pull is not None:
                pull.close(0)

    def test_browser_status_dots_reflect_connect_tab_health(self):
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            self.skipTest(f"playwright unavailable: {exc}")

        ctx = zmq.Context.instance()
        pub = ctx.socket(zmq.PUB)
        pub.bind(f"tcp://127.0.0.1:{self.UI_HEALTH_DATA_PORT}")
        pull = ctx.socket(zmq.PULL)
        pull.bind(f"tcp://127.0.0.1:{self.UI_HEALTH_CTRL_PORT}")
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True)
                except PlaywrightError as exc:
                    self.skipTest(f"playwright browser unavailable: {exc}")
                try:
                    page = browser.new_page()
                    page.goto(f"http://localhost:{HTTP_PORT}/", wait_until="domcontentloaded")
                    page.locator(".tab-add").click(force=True)
                    page.locator("#tab-create .name-in").fill("ClosedPortsUi")
                    page.locator("#tab-create .ep-in").fill(f"127.0.0.1:{self.UI_MISSING_PORT}")
                    page.locator("#tab-create .tab-create-ok").click(force=True)
                    missing_dot = page.locator(".tab", has_text="ClosedPortsUi").locator(".tab-dot")
                    missing_dot.wait_for(state="visible", timeout=4000)
                    page.wait_for_function(
                        "(el) => el.classList.contains('idle')",
                        arg=missing_dot.element_handle(),
                        timeout=4000,
                    )
                    self.assertEqual(
                        missing_dot.get_attribute("title"),
                        "Host reachable; rtplot ports are not connected",
                    )

                    page.locator(".tab-add").click(force=True)
                    page.locator("#tab-create .name-in").fill("BootedUi")
                    page.locator("#tab-create .ep-in").fill(f"127.0.0.1:{self.UI_HEALTH_DATA_PORT}")
                    page.locator("#tab-create .tab-create-ok").click(force=True)
                    booted_dot = page.locator(".tab", has_text="BootedUi").locator(".tab-dot")
                    booted_dot.wait_for(state="visible", timeout=4000)
                    page.wait_for_function(
                        "(el) => el.classList.contains('connected')",
                        arg=booted_dot.element_handle(),
                        timeout=5000,
                    )
                    self.assertEqual(
                        booted_dot.get_attribute("title"),
                        "ZMQ connected; waiting for plot config/data",
                    )
                finally:
                    browser.close()
        finally:
            pub.close(0); pull.close(0)

    def test_connect_mode_data_inbound(self):
        # Stand up a fake "remote sender" that binds the data port and
        # publishes a config + a few frames; the server-side connect tab
        # dials into us.
        ctx = zmq.Context.instance()
        pub = ctx.socket(zmq.PUB)
        pub.bind(f"tcp://127.0.0.1:{self.OUT_DATA_PORT}")
        pull = ctx.socket(zmq.PULL)
        pull.bind(f"tcp://127.0.0.1:{self.OUT_CTRL_PORT}")
        try:
            async def go():
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await _drain_until(ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs")
                        await ws.send_str(json.dumps({
                            "type": "tab_create",
                            "name": "RemoteDevice",
                            "endpoint": f"127.0.0.1:{self.OUT_DATA_PORT}",
                        }))
                        # Find the new tab id.
                        new_id = None
                        listing = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict) and d.get("type") == "tabs"
                                      and any(t["id"] != "bind_me" for t in d["tabs"]),
                        )
                        for t in listing["tabs"]:
                            if t["id"] != "bind_me":
                                new_id = t["id"]
                        self.assertIsNotNone(new_id)
                        await ws.send_str(json.dumps({"type": "tab_subscribe", "id": new_id}))
                        # Brief pause for the server SUB to finish handshake
                        # before our PUB starts sending — otherwise the
                        # config gets dropped on the slow-joiner race.
                        await asyncio.sleep(0.4)
                        cfg = OrderedDict([("p0", {"names": ["v"], "title": "REMOTE", "xrange": 100})])
                        pub.send_string("0", flags=zmq.SNDMORE); pub.send_json(cfg)
                        for _ in range(3):
                            arr = np.random.randn(1, 25).astype(np.float64)
                            md = {"dtype": "float64", "shape": list(arr.shape)}
                            pub.send_string("1", flags=zmq.SNDMORE)
                            pub.send_json(md, flags=zmq.SNDMORE)
                            pub.send(arr.tobytes())
                            await asyncio.sleep(0.02)
                        cfg_msg = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict) and d.get("type") == "config"
                                      and d.get("plots", [{}])[0].get("title") == "REMOTE",
                            timeout=5,
                        )
                        self.assertIsNotNone(cfg_msg, "connect-tab config never reached browser")
                        bin_msg = await _drain_until(
                            ws, lambda d: isinstance(d, (bytes, bytearray)), timeout=3
                        )
                        self.assertIsNotNone(bin_msg, "connect-tab data never reached browser")
            self.run_async(go(), timeout=20)
        finally:
            pub.close(0); pull.close(0)


class TestTabSwitchMidStream(_ServerTest):
    """Subscribing to a different tab should stop data from the previous one."""

    EXTRA_DATA_PORT = 5599

    def test_switch_routes_data_correctly(self):
        # Active sender on bind_me + an empty connect tab to switch to.
        zc = ZmqTestClient()
        try:
            cfg = OrderedDict([("p0", {"names": ["x"], "title": "BIND_ME"})])
            zc.send_config(cfg)

            async def go():
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                        await _drain_until(ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs")
                        # Create the empty connect tab.
                        await ws.send_str(json.dumps({
                            "type": "tab_create", "name": "Empty",
                            "endpoint": f"127.0.0.1:{self.EXTRA_DATA_PORT}",
                        }))
                        listing = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict) and d.get("type") == "tabs"
                                      and any(t["id"] != "bind_me" for t in d["tabs"]),
                        )
                        empty_id = next(t["id"] for t in listing["tabs"] if t["id"] != "bind_me")

                        # Subscribe to bind_me, send some data, expect binary.
                        await ws.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                        await _drain_until(
                            ws, lambda d: isinstance(d, dict) and d.get("type") == "config"
                        )
                        for _ in range(5):
                            zc.send_data(np.random.randn(1, 30).astype(np.float64))
                            await asyncio.sleep(0.02)
                        before = await _drain_until(
                            ws, lambda d: isinstance(d, (bytes, bytearray)), timeout=3
                        )
                        self.assertIsNotNone(before, "no binary while subscribed to bind_me")

                        # Switch to Empty tab.
                        await ws.send_str(json.dumps({"type": "tab_subscribe", "id": empty_id}))
                        # Server should answer with no_config (no client behind Empty).
                        ack = await _drain_until(
                            ws,
                            lambda d: isinstance(d, dict)
                                      and d.get("type") in ("no_config", "config")
                                      and d.get("tab") == empty_id,
                            timeout=3,
                        )
                        self.assertIsNotNone(ack)

                        # Keep sending bind_me data; we must NOT see any
                        # binary frames now (we're not subscribed there).
                        for _ in range(10):
                            zc.send_data(np.random.randn(1, 30).astype(np.float64))
                            await asyncio.sleep(0.02)
                        leaked = await _drain_until(
                            ws, lambda d: isinstance(d, (bytes, bytearray)), timeout=1.5
                        )
                        self.assertIsNone(leaked, "binary frame leaked from unsubscribed tab")
            self.run_async(go(), timeout=20)
        finally:
            zc.close()


class TestMultipleViewers(_ServerTest):
    def test_two_viewers_both_get_data_and_peer_count(self):
        zc = ZmqTestClient()
        try:
            cfg = OrderedDict([("p0", {"names": ["x"], "title": "MULTI"})])
            zc.send_config(cfg)

            async def go():
                async with aiohttp.ClientSession() as s1, aiohttp.ClientSession() as s2:
                    async with s1.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as w1, \
                               s2.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as w2:
                        # Both subscribe to bind_me.
                        await w1.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))
                        await w2.send_str(json.dumps({"type": "tab_subscribe", "id": "bind_me"}))

                        # Each receives a config.
                        c1 = await _drain_until(
                            w1, lambda d: isinstance(d, dict) and d.get("type") == "config"
                        )
                        c2 = await _drain_until(
                            w2, lambda d: isinstance(d, dict) and d.get("type") == "config"
                        )
                        self.assertIsNotNone(c1); self.assertIsNotNone(c2)

                        # Send some data; both viewers see binary.
                        for _ in range(5):
                            zc.send_data(np.random.randn(1, 25).astype(np.float64))
                            await asyncio.sleep(0.02)
                        b1 = await _drain_until(
                            w1, lambda d: isinstance(d, (bytes, bytearray)), timeout=3
                        )
                        b2 = await _drain_until(
                            w2, lambda d: isinstance(d, (bytes, bytearray)), timeout=3
                        )
                        self.assertIsNotNone(b1); self.assertIsNotNone(b2)

                        # peer_count for at least one viewer should report 2.
                        # We may have already drained that message earlier;
                        # close one viewer to force a new broadcast and then
                        # the surviving viewer should see count=1.
                        await w2.close()
                        pc = await _drain_until(
                            w1,
                            lambda d: isinstance(d, dict) and d.get("type") == "peer_count"
                                      and d.get("count") == 1,
                            timeout=3,
                        )
                        self.assertIsNotNone(pc, "peer_count=1 not seen after one viewer left")
            self.run_async(go(), timeout=20)
        finally:
            zc.close()


class TestResendRetriesOnEmpty(_ServerTest):
    """When a Reconnect fires with no client running, the server should
    retry the resend_config nudge on its schedule and eventually log a
    "no config received" hint. We can't tap the wire, but we can prove
    the retry loop is alive by checking the server log after a reconnect
    on a tab whose peer never answers.
    """

    def test_no_peer_logs_hint_after_retries(self):
        async def go():
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                    await _drain_until(ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs")
                    # Reconnect bind_me with no client behind it.
                    await ws.send_str(json.dumps({"type": "tab_reconnect", "id": "bind_me"}))
                    # The retry schedule cumulatively reaches ~10 s. Wait
                    # 11 s and then look for the "no config received" hint
                    # in the server log.
                    await asyncio.sleep(11.5)
        self.run_async(go(), timeout=20)
        log = self.server.log_text()
        self.assertIn(
            "no config received after resend_config nudges",
            log,
            f"server didn't log the resend-failure hint. log tail:\n{log[-1000:]}",
        )


class TestResourcesBroadcast(_ServerTest):
    """The CPU/mem/per-tab Hz broadcast should arrive within ~3 s of WS
    connect (the pusher fires every 2 s).
    """

    def test_resources_message_shape(self):
        async def go():
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                    msg = await _drain_until(
                        ws,
                        lambda d: isinstance(d, dict) and d.get("type") == "resources",
                        timeout=4.0,
                    )
                    self.assertIsNotNone(msg, "no resources broadcast within 4 s")
                    self.assertIn("available", msg)
                    self.assertIn("tabs", msg)
                    self.assertIn("viewers", msg)
                    self.assertIn("rates", msg)
                    self.assertIsInstance(msg["rates"], dict)
                    if msg.get("available"):
                        self.assertIn("cpu", msg)
                        self.assertIn("mem_used_mb", msg)
                        self.assertIn("mem_total_mb", msg)
                        self.assertGreater(msg["mem_total_mb"], 0)
        self.run_async(go(), timeout=10)


class TestBindFailureRecovery(unittest.TestCase):
    """If 5555 is held when the server starts, bind_me should report
    error; freeing the port and clicking Reconnect should clear it.
    """

    def setUp(self):
        # Free anything that might already be on 5555.
        if _wait_for_port("127.0.0.1", ZMQ_DATA_PORT, timeout=0.05):
            _kill_listeners_on(ZMQ_DATA_PORT)
            _wait_for_port("127.0.0.1", ZMQ_DATA_PORT, timeout=4.0, want_open=False)
        self.ctx = zmq.Context.instance()
        self.blocker = self.ctx.socket(zmq.SUB)
        self.blocker.bind(f"tcp://127.0.0.1:{ZMQ_DATA_PORT}")
        self.blocker.setsockopt_string(zmq.SUBSCRIBE, "")
        self.server = ServerProcess()
        self.server.start()

    def tearDown(self):
        try: self.server.stop()
        except Exception: pass
        try: self.blocker.close(0)
        except Exception: pass

    def test_bind_failure_recovers_after_port_free(self):
        async def go():
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://localhost:{HTTP_PORT}/ws") as ws:
                    msg = await _drain_until(
                        ws, lambda d: isinstance(d, dict) and d.get("type") == "tabs"
                    )
                    bm = next(t for t in msg["tabs"] if t["id"] == "bind_me")
                    self.assertEqual(bm["status"], "error", f"unexpected: {bm}")
                    self.assertIsNotNone(bm["error"])

                    # Free the port and reconnect; server should re-bind.
                    self.blocker.close(0)
                    await asyncio.sleep(0.3)
                    await ws.send_str(json.dumps({"type": "tab_reconnect", "id": "bind_me"}))
                    healed = await _drain_until(
                        ws,
                        lambda d: isinstance(d, dict) and d.get("type") == "tab"
                                  and d["tab"]["id"] == "bind_me"
                                  and d["tab"]["status"] != "error",
                        timeout=5,
                    )
                    self.assertIsNotNone(healed, "bind_me did not recover after port freed")
                    self.assertIsNone(healed["tab"]["error"])
        asyncio.run(asyncio.wait_for(go(), timeout=15))


class TestInitializePlotsHandshake(_ServerTest):
    """initialize_plots() should block until the server acks the config.

    Exercises the config_ack round-trip directly and indirectly through
    the real client:
      * The server emits `config_ack` on its PUSH socket after parse.
      * The client's initialize_plots() returns only after that ack
        (or a 2 s warning timeout), so scripts that immediately call
        send_array() don't lose the config to the slow-joiner window.
    """

    def test_server_emits_config_ack(self):
        zc = ZmqTestClient()
        try:
            cfg = OrderedDict([("p0", {"names": ["x"], "xrange": 100})])
            zc.send_config(cfg)
            # Pull the ack off the return channel; it must arrive within
            # a couple of seconds on localhost.
            found = False
            deadline = time.time() + 3.0
            while time.time() < deadline:
                ev = zc.poll_one(timeout=0.5)
                if ev is None:
                    continue
                if ev.get("type") == "config_ack":
                    found = True
                    break
            self.assertTrue(found, "server did not emit config_ack after parse")
        finally:
            zc.close()

    def test_real_client_initialize_plots_blocks_until_ack(self):
        # Run a subprocess that calls initialize_plots and records the
        # wall-clock time it took. If the handshake is wired up, it
        # should return quickly (< 1 s) once the ack comes back.
        code = f"""
import sys, time
sys.path.insert(0, {REPO_ROOT!r})
from rtplot import client
client.local_plot()
t0 = time.monotonic()
client.initialize_plots({{"names":["sig"], "title":"HS"}})
print(f"EVT:DONE:{{time.monotonic() - t0:.3f}}", flush=True)
"""
        p = subprocess.Popen(
            [sys.executable, "-u", "-c", code],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        try:
            line = _drain_client_lines(p, lambda l: "EVT:DONE:" in l, timeout=6.0)
            self.assertIsNotNone(line, "real client never finished initialize_plots()")
            elapsed = float(line.strip().split(":", 2)[2])
            # Must return within the handshake budget + a generous margin.
            # On localhost the ack typically comes back in ~50–300 ms.
            self.assertLess(
                elapsed, 2.5,
                f"initialize_plots() returned in {elapsed:.2f}s, "
                "suggesting the ack never arrived and it hit the 2 s timeout"
            )
        finally:
            p.terminate(); p.wait(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
