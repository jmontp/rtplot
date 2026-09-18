"""Acceptance tests for sections, streaming integrity and UI state recovery."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from playwright.sync_api import sync_playwright
from test_communication import _ServerTest, REPO_ROOT


class Publisher:
    def __init__(self, port=None):
        env = os.environ.copy()
        env['PYTHONPATH'] = REPO_ROOT
        self.messages = []
        self.serial = 0
        self.proc = subprocess.Popen([sys.executable, '-u', str(Path(REPO_ROOT) / 'tests/section_publisher.py'),
                                      *([] if port is None else [str(port)])],
                                     cwd=REPO_ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True)
        def read():
            for line in self.proc.stdout:
                try: self.messages.append(json.loads(line))
                except ValueError: pass
        threading.Thread(target=read, daemon=True).start()
        self.ready = self.wait(lambda m: m.get('ready'))

    def wait(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for message in self.messages:
                if predicate(message): return message
            if self.proc.poll() is not None: raise AssertionError(f'Publisher exited: {self.proc.returncode}')
            time.sleep(.01)
        raise AssertionError(f'Publisher response timeout; messages: {self.messages[-5:]}')

    def command(self, op, **kwargs):
        self.serial += 1
        self.proc.stdin.write(json.dumps({'op': op, 'serial': self.serial, **kwargs}) + '\n')
        self.proc.stdin.flush()
        return self.wait(lambda m: m.get('command') == self.serial)

    def stop(self):
        self.proc.terminate()
        try: self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired: self.proc.kill(); self.proc.wait()
        self.proc.stdin.close(); self.proc.stdout.close()


INSTRUMENT = r"""
window.__tabs = []; window.__uiMessages = 0; window.__plots = []; window.__destroyed = 0; window.__sent = []; window.__frames = 0; window.__maxFrames = 0;
const raf = window.requestAnimationFrame;
window.requestAnimationFrame = fn => {
  window.__frames++; window.__maxFrames = Math.max(window.__maxFrames, window.__frames);
  return raf(t => { window.__frames--; fn(t); });
};
let ctor;
Object.defineProperty(window, 'uPlot', {configurable:true, get:()=>ctor, set:Original=> {
  ctor = function(...args) {
    const u = new Original(...args); u.__renders = 0;
    const set = u.setData; u.setData = (...args) => { u.__renders++; return set(...args); };
    const destroy = u.destroy; u.destroy = () => { window.__destroyed++; destroy(); };
    window.__plots.push(u); return u;
  };
  Object.setPrototypeOf(ctor, Original); ctor.prototype = Original.prototype;
}});
const WS = window.WebSocket;
window.WebSocket = class extends WS {
  constructor(...args) {
    super(...args); window.__ws = this;
    this.addEventListener('message', e => {
      if (typeof e.data !== 'string') return;
      const m = JSON.parse(e.data);
      if (m.type === 'tabs') window.__tabs = m.tabs;
      if (m.type === 'ui_state') window.__uiMessages++;
    });
  }
  send(s) { try { const m=JSON.parse(s); if(m.type.startsWith('control_')) window.__sent.push(m); } catch (_) {} super.send(s); }
};
"""


class TestSections(_ServerTest):
    def setUp(self):
        self.pub = Publisher()
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        self.errors = []

    def tearDown(self):
        self.browser.close(); self.playwright.stop(); self.pub.stop()
        self.assertEqual(self.errors, [])

    def page(self, height=900):
        page = self.browser.new_page(viewport={'width': 1280, 'height': height})
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.add_init_script(INSTRUMENT)
        page.goto('http://localhost:8050/')
        page.wait_for_function('window.__plots.length === 2')
        page.wait_for_function("document.querySelector('[data-control-id=record] button')?.disabled === false")
        return page

    def test_layout_state_focus_navigation_and_persistent_controls(self):
        page = self.page(height=500)
        other = self.page()
        train = page.locator('[data-control-id=train] button')
        self.assertTrue(train.is_disabled())
        self.assertTrue(page.get_by_text('Record first', exact=True).is_visible())
        train.dispatch_event('click')
        train.dispatch_event('keydown', {'key': 'Enter'})
        self.assertEqual(page.evaluate('window.__sent.length'), 0)
        note = page.locator('[data-control-id=note] input')
        note.fill('unfinished edit')
        self.pub.command('patch', patch={'controls': {'source_raw': {'selected': True}, 'record': {'busy': True}},
                                         'sections': {'setup': {'status': 'complete', 'message': 'Sensors ready'}}})
        page.wait_for_function("document.querySelector('[data-control-id=source_raw] button').getAttribute('aria-pressed') === 'true'")
        self.assertTrue(page.locator('[data-control-id=record] button').is_enabled())
        self.assertTrue(page.locator('[data-control-id=record] .ctrl-busy').is_visible())
        self.assertEqual(note.input_value(), 'unfinished edit')
        self.assertTrue(note.evaluate('(el)=>el===document.activeElement'))
        self.assertEqual(page.locator('[data-control-id=gain] input[type=number]').input_value(), '2')
        self.assertEqual(page.locator('[data-section=advanced] button[aria-expanded]').get_attribute('aria-expanded'), 'false')
        page.locator('.section-nav a').filter(has_text='Advanced').click()
        page.wait_for_function("!document.querySelector('[data-section=advanced] .section-body').hidden")
        self.assertEqual(other.locator('[data-section=advanced] button[aria-expanded]').get_attribute('aria-expanded'), 'false')
        self.assertEqual(other.locator('[data-control-id=source_raw] button').get_attribute('aria-pressed'), 'true')
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        self.assertTrue(page.locator('[data-control-id=stop] button').is_visible())
        box = page.locator('[data-control-id=stop]').bounding_box()
        self.assertGreaterEqual(box['y'], 0); self.assertLess(box['y'], 500)
        self.pub.command('patch', patch={'sections': {'advanced': {'status': 'warning', 'message': 'Still visible'}}})
        page.wait_for_timeout(100)
        self.assertEqual(page.locator('[data-section=advanced] button[aria-expanded]').get_attribute('aria-expanded'), 'true')
        self.pub.command('patch', patch={'controls': {'note': {'visible': False}}})
        page.wait_for_function("document.querySelector('[data-control-id=note]').hidden")
        self.assertEqual(note.input_value(), 'unfinished edit')
        self.pub.command('patch', patch={'controls': {'note': {'visible': None}}})
        page.wait_for_function("!document.querySelector('[data-control-id=note]').hidden")
        self.assertEqual(note.input_value(), 'unfinished edit')

    def test_stream_mapping_history_zoom_instances_and_recovery(self):
        page = self.page()
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate('window.__plots[0].__renders'), 0)
        self.assertGreater(page.evaluate('window.__plots[1].__renders'), 1)
        page.locator('[data-section=advanced] button[aria-expanded]').click()
        page.wait_for_function('window.__plots[0].__renders > 0')
        self.assertEqual(page.evaluate('window.__plots[1].data[1].at(-1)-window.__plots[0].data[1].at(-1)'), 1000)
        page.evaluate('window.__plots[0].setScale("x",{min:20,max:40}); window.__plots[0].setSeries(1,{show:false})')
        page.wait_for_timeout(100)
        for _ in range(3):
            page.locator('[data-section=advanced] button[aria-expanded]').click()
            page.wait_for_timeout(100)
            page.locator('[data-section=advanced] button[aria-expanded]').click()
            self.pub.command('patch', patch={'controls': {'record': {'selected': True}}})
        page.wait_for_timeout(150)
        self.assertEqual(page.evaluate('[window.__plots.length,window.__destroyed]'), [2, 0])
        self.assertEqual(page.evaluate('[window.__plots[0].scales.x.min,window.__plots[0].scales.x.max,window.__plots[0].series[1].show]'), [20, 40, False])
        self.pub.command('patch', patch={'sections': {'advanced': {'visible': False}}})
        page.wait_for_function("document.querySelector('[data-section=advanced]').hidden")
        renders = page.evaluate('window.__plots[0].__renders')
        page.wait_for_timeout(150)
        self.assertEqual(page.evaluate('window.__plots[0].__renders'), renders)
        self.pub.command('patch', patch={'sections': {'advanced': {'visible': None}}})
        page.wait_for_function("!document.querySelector('[data-section=advanced]').hidden")
        page.wait_for_timeout(100)
        self.assertEqual(page.evaluate('[window.__plots[0].scales.x.min,window.__plots[0].scales.x.max]'), [20,40])
        before = page.evaluate('window.__plots[0].data[1].at(-1)')
        self.pub.command('resend')
        page.wait_for_timeout(150)
        self.assertGreater(page.evaluate('window.__plots[0].data[1].at(-1)'), before)
        self.assertEqual(page.evaluate('[window.__plots.length,window.__destroyed]'), [2, 0])
        page.evaluate('window.__ws.close()')
        page.wait_for_function("document.querySelector('[data-control-id=record] button').disabled")
        page.wait_for_function("document.querySelector('[data-control-id=record] button').disabled === false")
        self.assertEqual(page.evaluate('[window.__plots.length,window.__destroyed]'), [2, 0])
        self.assertEqual(page.locator('[data-section=advanced] button[aria-expanded]').get_attribute('aria-expanded'), 'true')
        fresh = self.page()
        self.assertGreater(fresh.evaluate('window.__plots[1].data[1].at(-1)'), 2000)
        self.assertEqual(fresh.locator('[data-control-id=record] button').get_attribute('aria-pressed'), 'true')
        self.pub.command('disconnect')
        page.wait_for_function("document.querySelector('[data-control-id=record] button').disabled")
        page.locator('[data-control-id=record] button').dispatch_event('click')
        self.assertTrue(page.locator('.ui-source-status').is_visible())
        self.pub.command('reconnect')
        page.wait_for_function("document.querySelector('[data-control-id=record] button').disabled === false")
        page.wait_for_timeout(300)
        self.assertFalse(any(m.get('buttons') for m in self.pub.messages))
        self.assertEqual(page.evaluate('[window.__plots.length,window.__destroyed]'), [2, 0])

    def test_stale_revisions_generations_and_backend_enforcement(self):
        page = self.page()
        self.pub.command('patch', patch={'controls': {'record': {'enabled': False, 'reason': 'Unavailable'}}})
        page.wait_for_function("document.querySelector('[data-control-id=record] button').disabled")
        for payload in ({'revision': 0, 'state': {}}, {'session': 'other', 'revision': 999, 'state': {}},
                        {'generation': 999, 'revision': 999, 'state': {}}):
            self.pub.command('raw', payload=payload)
        page.wait_for_timeout(100)
        self.assertTrue(page.locator('[data-control-id=record] button').is_disabled())
        packet = {'type': 'control_button', 'id': 'record', **{k:self.pub.ready[k] for k in ('session','generation')}}
        page.evaluate('p => window.__ws.send(JSON.stringify(p))', packet)
        page.wait_for_timeout(100)
        self.assertFalse(any(m.get('buttons') for m in self.pub.messages))
        self.pub.command('patch', patch={'controls': {'record': {'enabled': None, 'reason': None}}})
        page.wait_for_function("document.querySelector('[data-control-id=record] button').disabled === false")
        page.locator('[data-control-id=record] button').click()
        self.pub.wait(lambda m: m.get('buttons') == ['record'])
        result = self.pub.command('replace')
        page.wait_for_function('window.__plots.length === 4')
        self.pub.command('raw', payload={'generation': result['generation'] - 1, 'revision': 999,
                                        'state': {'controls': {'train': {'enabled': True}}}})
        page.wait_for_timeout(100)
        self.assertTrue(page.locator('[data-control-id=train] button').is_disabled())

    def test_source_isolation_and_stale_recovery(self):
        page = self.page()
        page.evaluate("window.__ws.send(JSON.stringify({type:'tab_create',name:'Second source',endpoint:'127.0.0.1:5597'}))")
        page.wait_for_function("window.__tabs.some(t => t.name === 'Second source')")
        second_id = page.evaluate("window.__tabs.find(t => t.name === 'Second source').id")
        second = Publisher(port=5597)
        try:
            other = self.browser.new_page()
            other.add_init_script(INSTRUMENT)
            other.goto('http://localhost:8050/')
            other.wait_for_function('window.__ws?.readyState === 1')
            # Select via the actual tab UI so the browser's active source changes.
            other.get_by_text('Second source', exact=True).click()
            other.wait_for_function("document.querySelector('[data-control-id=record] button')?.disabled === false")
            second.command('patch', patch={'controls': {'record': {'enabled': False, 'reason': 'Second only'}}})
            other.wait_for_function("document.querySelector('[data-control-id=record] button').disabled")
            self.assertTrue(page.locator('[data-control-id=record] button').is_enabled())
            self.pub.command('pause', value=True)
            # This click reaches PULL before the server knows the source is stale.
            page.locator('[data-control-id=record] button').click()
            page.wait_for_function("document.querySelector('[data-control-id=record] button').disabled", timeout=8000)
            self.assertIn('stale', page.locator('.ui-source-status').inner_text())
            self.pub.command('pause', value=False)
            page.wait_for_function("document.querySelector('[data-control-id=record] button').disabled === false")
            self.assertTrue(other.locator('[data-control-id=record] button').is_disabled())
            page.wait_for_timeout(1100)
            self.assertFalse(any(m.get('buttons') for m in self.pub.messages))
            self.assertEqual(page.evaluate('[window.__plots.length,window.__destroyed]'), [2, 0])
        finally:
            second.stop()
            page.evaluate("id => window.__ws.send(JSON.stringify({type:'tab_delete',id}))", second_id)

    def test_render_work_memory_and_coalescing(self):
        page = self.page()
        cdp = page.context.new_cdp_session(page)
        page.wait_for_timeout(300)
        cdp.send('HeapProfiler.collectGarbage')
        before_heap = cdp.send('Runtime.getHeapUsage')['usedSize']
        before_nodes = cdp.send('Memory.getDOMCounters')['nodes']
        before = page.evaluate('[window.__plots[0].__renders, window.__plots[1].__renders, window.__plots[1].data[1].at(-1), window.__uiMessages]')
        rounds = int(os.environ.get('RTPLOT_STRESS_ROUNDS', '4'))
        for _ in range(rounds):
            self.pub.command('burst', count=400)
            page.wait_for_timeout(250)
        page.wait_for_timeout(100)
        hidden = page.evaluate('[window.__plots[0].__renders, window.__plots[1].__renders, window.__plots[1].data[1].at(-1), window.__uiMessages]')
        self.assertEqual(hidden[0], before[0])
        self.assertGreater(hidden[1], before[1])
        self.assertGreater(hidden[2], before[2] + 20)
        self.assertLess(hidden[3] - before[3], rounds * 25)  # Bounded/coalesced forwarding.
        result = self.pub.command('patch', patch={'controls': {'record': {'selected': True}}})
        self.assertFalse(result['result'])  # Last burst already selected it.
        page.locator('[data-section=advanced] button[aria-expanded]').click()
        page.wait_for_timeout(300 * rounds)
        visible = page.evaluate('[window.__plots[0].__renders, window.__plots[1].__renders]')
        self.assertGreater(visible[0], hidden[0] + 10)
        self.assertEqual(page.evaluate('window.__plots[1].data[1].at(-1)-window.__plots[0].data[1].at(-1)'), 1000)
        cdp.send('HeapProfiler.collectGarbage')
        after_heap = cdp.send('Runtime.getHeapUsage')['usedSize']
        self.assertLess(after_heap - before_heap, 2_000_000)
        self.assertLessEqual(cdp.send('Memory.getDOMCounters')['nodes'] - before_nodes, 12)  # Labels created on first reveal.
        self.assertLessEqual(page.evaluate('window.__maxFrames'), 5)
        self.assertEqual(page.evaluate('[window.__plots.length,window.__destroyed]'), [2, 0])
        print({'hidden_plot_renders': hidden[0]-before[0], 'visible_plot_renders': hidden[1]-before[1],
               'revealed_plot_renders': visible[0]-hidden[0], 'patches': 400 * rounds, 'ui_messages': hidden[3]-before[3],
               'heap_growth_bytes': after_heap-before_heap, 'max_pending_frames': page.evaluate('window.__maxFrames')})
