"""Sections, runtime state and synthetic recovery; no hardware required."""
import argparse
import math
import time

from rtplot import client
from rtplot.client import Button, ControlsRow, Plot, PlotRow, Section, Slider, Text, TextInput, View


def configuration():
    # Declaration/stream order deliberately differs from visual section order.
    rows = [
        Plot(names=["detail"], title="Detail signal", xrange=400, section="advanced"),
        ControlsRow([Text("status", "Status", "Setup required"), Button("stop", "Stop"),
                     Button("pause", "Simulate interruption")], section="status"),
        ControlsRow([Button("prepare", "Prepare source"), Button("start", "Start work"),
                     TextInput("note", "Notes", value="Edit while streaming")], section="setup"),
        PlotRow([Plot(names=["signal"], title="Synthetic signal", xrange=400),
                 Plot(names=["reference"], title="Reference", xrange=400)], columns=2, section="work"),
        ControlsRow([Slider("gain", "Gain", 0, 2, value=1), Button("raw", "Raw"),
                     Button("smooth", "Smooth")], section="advanced"),
    ]
    view = View([Section("status", "Status"), Section("setup", "Setup"),
                 Section("work", "Active work"),
                 Section("advanced", "Advanced", "Optional display settings", collapsible=True, collapsed=True)],
                persistent_section="status")
    return rows, view


def run(make_configuration=configuration):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auto', action='store_true', help='Run setup, work, completion, and a stale/recovery cycle automatically')
    parser.add_argument('--seconds', type=float, default=0, help='Exit after this many seconds (0 runs until Ctrl-C)')
    args = parser.parse_args()
    client.local_plot()
    rows, view = make_configuration()
    client.initialize_plots(rows, view=view, ui_state={
        'controls': {'start': {'enabled': False, 'reason': 'Prepare the synthetic source first'},
                     'stop': {'enabled': False, 'reason': 'No active work'}, 'raw': {'selected': True}},
        'sections': {'setup': {'status': 'ready'}, 'work': {'status': 'idle'}},
    })
    ready, working, smooth = False, False, False
    started = time.monotonic()
    work_started = 0
    auto_done = set()
    print('Open http://localhost:8050. Prepare source, then Start work. Ctrl-C exits.')
    try:
        while not args.seconds or time.monotonic() - started < args.seconds:
            elapsed = time.monotonic() - started
            controls = client.poll_controls()  # Also maintains liveness while idle.
            actions = list(controls.buttons)
            if args.auto:
                for when, action in [(1, 'prepare'), (2, 'start'), (8, 'pause')]:
                    if elapsed >= when and action not in auto_done:
                        auto_done.add(action); actions.append(action)
            for action in actions:
                # Application validates every action against its own state.
                if action == 'prepare' and not working:
                    ready = True
                    client.set_display('status', 'Synthetic source ready')
                    client.set_ui_state({'controls': {'start': {'enabled': True, 'reason': None}},
                                         'sections': {'setup': {'status': 'complete', 'message': 'Source ready'},
                                                      'work': {'status': 'ready'}}})
                elif action == 'start' and ready and not working:
                    working, work_started = True, time.monotonic()
                    client.set_display('status', 'Working')
                    client.set_ui_state({'controls': {'start': {'enabled': False, 'busy': True, 'reason': 'Work is active'},
                                                      'prepare': {'enabled': False}, 'stop': {'enabled': True, 'reason': None}},
                                         'sections': {'work': {'status': 'busy', 'message': 'Generating synthetic data'}}})
                elif action == 'stop' and working:
                    working = False
                    client.set_display('status', 'Stopped by the example application')
                    client.set_ui_state({'controls': {'start': None, 'prepare': None,
                                                      'stop': {'enabled': False, 'reason': 'No active work'}},
                                         'sections': {'work': {'status': 'ready', 'message': 'Stopped'}}})
                elif action in ('raw', 'smooth'):
                    smooth = action == 'smooth'
                    client.set_ui_state({'controls': {'raw': {'selected': not smooth}, 'smooth': {'selected': smooth}}})
                elif action == 'pause':
                    print('Pausing samples and heartbeats for 7 seconds; the browser will show stale, then recover.')
                    time.sleep(7)
                    client.poll_controls()
            if working and time.monotonic() - work_started >= 4:
                working = False
                client.set_display('status', 'Complete')
                client.set_ui_state({'controls': {'start': None, 'prepare': None,
                                                  'stop': {'enabled': False, 'reason': 'Work complete'}},
                                     'sections': {'work': {'status': 'complete', 'message': 'Synthetic work finished'}}})
            gain = controls.values.get('gain', 1)
            reference = math.sin(elapsed)
            signal = gain * reference + (0 if smooth else .1 * math.sin(15 * elapsed))
            client.send_array([math.cos(3 * elapsed), signal, reference])
            time.sleep(.02)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    run()
