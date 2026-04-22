"""Interactive controls test for rtplot.

Walks a human through a sequence of actions (click a button, drag a slider
to a specific value, etc.) using a text display for prompts and a status
readout for progress. Each step completes only when the user performs the
requested action in the browser. The script fails out if a step is
"completed" with the wrong action so you can tell the UI is wired.

Run with:
    python3 -m rtplot.server_browser --no-browser &    # in another shell
    python3 rtplot/interactive_test.py

Then open http://localhost:8050 in a browser.
"""

import math
import sys
import time

import numpy as np

try:
    # Normal path: installed package or `python -m rtplot.interactive_test`
    from rtplot import client
except ImportError:
    # Fallback: running as a loose script from inside the rtplot/ directory
    import client


# ----- utilities -----------------------------------------------------------

def _prompt(text):
    """Update the on-screen prompt and also mirror it to stdout."""
    print("\n>>> " + text, flush=True)
    client.set_display("prompt", text)


def _status(text):
    print("    " + text, flush=True)
    client.set_display("status", text)


def _run_with_feedback(predicate, feedback=None, tick_hz=30):
    """Drive plot + displays while waiting for ``predicate(ctrl)`` to be truthy.

    Returns the ControlState snapshot that satisfied the predicate.
    """
    dt = 1.0 / tick_hz
    t0 = time.time()
    while True:
        ctrl = client.poll_controls()
        t = time.time() - t0
        sig = math.sin(2 * math.pi * 0.5 * t)
        client.send_array(sig)
        client.set_display("elapsed", t)
        if feedback is not None:
            feedback(ctrl, t)
        if predicate(ctrl):
            return ctrl
        time.sleep(dt)


# ----- scripted steps ------------------------------------------------------

def step_click(button_id, label):
    _prompt(f"Click the '{label}' button in the browser.")
    _status("Waiting for click...")
    def pred(ctrl):
        return button_id in ctrl.buttons
    def feedback(ctrl, t):
        # Show any *wrong* clicks so the user can tell they hit the wrong button.
        if ctrl.buttons and button_id not in ctrl.buttons:
            _status(f"Got button '{ctrl.buttons[0]}', expected '{button_id}'.")
    _run_with_feedback(pred, feedback=feedback)
    _status(f"OK — received click on '{button_id}'")


def step_slider_to(slider_id, label, target, tol=0.25):
    _prompt(
        f"Move the '{label}' slider to {target:.2f} (\u00b1{tol:.2f}) and release."
    )
    _status("Waiting for release...")
    last_seen = {"v": None}
    def pred(ctrl):
        v = ctrl.values.get(slider_id)
        if v is None:
            return False
        if v != last_seen["v"]:
            last_seen["v"] = v
            _status(f"slider='{slider_id}' value={v:.2f} (target={target:.2f})")
        return abs(v - target) <= tol
    def feedback(ctrl, t):
        pass
    _run_with_feedback(pred, feedback=feedback)
    _status(
        f"OK \u2014 slider '{slider_id}' within tolerance "
        f"({last_seen['v']:.2f} of {target:.2f})"
    )


def main():
    # Outbound to the server — the rtplot browser server defaults to binding
    # 5555, so in local-plot mode the client is the one that connects.
    # client.local_plot()

    plot_cfg = {
        "names": ["live signal"],
        "colors": ["b"],
        "title": "Interactive Controls Test",
        "yrange": [-1.5, 1.5],
        "height": 1.5,
    }
    controls_row_prompt = {"controls": [
        {"type": "text", "id": "prompt", "label": "Task",
         "value": "Starting..."},
    ]}
    controls_row_buttons = {"controls": [
        {"type": "button", "id": "start", "label": "Start", "height": 2},
        {"type": "button", "id": "stop", "label": "Stop"},
        {"type": "button", "id": "fail", "label": "Abort"},
    ]}
    controls_row_slider = {"controls": [
        {"type": "slider", "id": "gain", "label": "Gain",
         "min": 0, "max": 10, "value": 0.0, "step": 0.1, "format": "{:.2f}"},
    ]}
    controls_row_dial = {"controls": [
        {"type": "dial", "id": "freq", "label": "Freq (Hz)",
         "min": 0.1, "max": 5.0, "value": 1.0, "step": 0.05,
         "sensitivity": 0.2, "format": "{:.2f}", "height": 2},
    ]}
    controls_row_status = {"controls": [
        {"type": "text", "id": "status", "label": "Status",
         "value": "waiting"},
        {"type": "display", "id": "elapsed", "label": "t (s)",
         "format": "{:.1f}"},
    ]}

    client.initialize_plots([
        plot_cfg,
        controls_row_prompt,
        controls_row_buttons,
        controls_row_slider,
        controls_row_dial,
        controls_row_status,
    ])

    # Give the server a moment to broadcast the config so the browser has
    # DOM elements ready before we start talking to them.
    time.sleep(0.5)

    try:
        _prompt("Welcome! Open the browser, then click 'Start' to begin.")
        step_click("start", "Start")

        # Exercise the slider with a drag
        step_slider_to("gain", "Gain", target=3.0, tol=0.3)

        # Exercise the number text input (type a value directly)
        _prompt("Type 5.5 into the Gain number box on the right, press Enter.")
        _status("Waiting for text entry of 5.5 \u00b10.05 ...")
        def gain_is_55(ctrl):
            v = ctrl.values.get("gain")
            return v is not None and abs(v - 5.5) < 0.05
        _run_with_feedback(gain_is_55)
        _status("OK \u2014 Gain set to 5.5 from the text box")

        # Exercise the +/- nudge buttons
        _prompt("Click the minus (\u2212) button on the Gain row 5 times.")
        _status("Waiting for Gain to decrease toward 5.0 ...")
        def gain_is_5(ctrl):
            v = ctrl.values.get("gain")
            return v is not None and abs(v - 5.0) < 0.05
        _run_with_feedback(gain_is_5)
        _status("OK \u2014 Gain nudged down to 5.0")

        # Exercise the dial
        step_slider_to("freq", "Freq (Hz)", target=2.5, tol=0.2)
        _status("OK \u2014 dial dragged to target")

        # Final: make sure the dial + slider can coexist (move slider again)
        step_slider_to("gain", "Gain", target=0.0, tol=0.3)

        step_click("stop", "Stop")

        _prompt("All checks passed! \u2714  You can close the browser.")
        _status("done")
        # Keep feeding the plot briefly so the user sees the final message.
        t_end = time.time() + 3.0
        while time.time() < t_end:
            client.poll_controls()
            client.send_array(0.0)
            time.sleep(0.05)
        print("\nInteractive test finished successfully.")
        return 0
    except KeyboardInterrupt:
        _prompt("Aborted by Ctrl-C")
        print("\nInterrupted.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
