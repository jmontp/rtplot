"""X/Y acceptance tests through the real Python client, server and Chromium."""
from pathlib import Path
import tempfile

import numpy as np
from playwright.sync_api import sync_playwright

from test_communication import _ServerTest
from test_sections import Publisher, INSTRUMENT


class TestXYBrowser(_ServerTest):
    def setUp(self):
        self.pub = Publisher(script='xy_publisher.py')
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=True)
        self.errors = []

    def tearDown(self):
        self.browser.close()
        self.pw.stop()
        self.pub.stop()
        self.assertEqual(self.errors, [])

    def page(self, expected=4):
        page = self.browser.new_page(viewport={'width': 1280, 'height': 1000})
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.add_init_script(INSTRUMENT)
        page.goto('http://localhost:8050/')
        page.wait_for_function(f'window.__plots.length === {expected}')
        return page

    def spectrum(self, x=(1, 10, 100), y=((2, 5, 3), (4, 7, 6))):
        self.pub.command('xy', id='spectrum', x=list(x), y=list(y))

    def test_mixed_offsets_replacement_scales_and_clearing(self):
        page = self.page()
        self.spectrum()
        self.pub.command('xy', id='curve', x=[-2, 0, 4], y=[30, 20, 10])
        self.pub.command('stream', y=[[11, 12], [111, 112]])
        page.wait_for_function('window.__plots[2].data[1].at(-1) === 112 && window.__plots[1].data[0].length === 3')
        self.assertEqual(page.evaluate('window.__plots.map(p => Array.from(p.data[1]).slice(-3))'),
                         [[0, 11, 12], [2, 5, 3], [0, 111, 112], [30, 20, 10]])
        positions = page.evaluate('[1,10,100].map(x => window.__plots[1].valToPos(x,"x"))')
        self.assertAlmostEqual(positions[1] - positions[0], positions[2] - positions[1], places=6)
        self.assertFalse(page.evaluate('window.__plots[1].series[2].show'))
        page.evaluate("document.querySelector('#menu-xrange').value='8';document.querySelector('#menu-xrange').dispatchEvent(new Event('change'))")
        self.assertEqual(page.evaluate('[window.__plots[0].scales.x.min,window.__plots[1].scales.x.min,window.__plots[1].scales.x.max]'), [24, 1, 100])
        before = page.evaluate('window.__plots[1].__renders')
        self.pub.command('stream', y=[[13], [113]])
        page.wait_for_function('window.__plots[2].data[1].at(-1) === 113')
        self.assertEqual(page.evaluate('window.__plots[1].__renders'), before)
        self.spectrum([2, 200], [[8, 9], [10, 11]])
        page.wait_for_function('window.__plots[1].data[0].length === 2')
        self.assertEqual(page.evaluate('Array.from(window.__plots[1].data[0])'), [2, 200])
        self.assertFalse(page.evaluate('window.__plots[1].series[2].show'))
        self.assertEqual(page.evaluate('window.__plots[2].data[1].at(-1)'), 113)
        self.spectrum([], [[], []])
        page.wait_for_function('window.__plots[1].data[0].length === 0')
        self.spectrum([10], [[12], [13]])
        page.wait_for_function('window.__plots[1].data[1][0] === 12')
        self.assertTrue(page.evaluate('Number.isFinite(window.__plots[1].valToPos(10,"x"))'))

    def test_hidden_section_latest_curve_and_viewer_reconnect(self):
        page = self.page()
        self.spectrum()
        page.wait_for_function('window.__plots[1].data[0].length === 3')
        toggle = page.locator('[data-section=plots] button[aria-expanded]')
        toggle.click()
        page.wait_for_timeout(100)
        renders = page.evaluate('window.__plots[1].__renders')
        self.spectrum([10, 100, 1000], [[7, 8, 9], [10, 11, 12]])
        page.wait_for_timeout(150)
        self.assertEqual(page.evaluate('window.__plots[1].__renders'), renders)
        toggle.click()
        page.wait_for_function('window.__plots[1].data[0].at(-1) === 1000')
        self.assertEqual(page.evaluate('[window.__plots[1].scales.x.min,window.__plots[1].scales.x.max]'), [10, 1000])
        fresh = self.page()
        fresh.wait_for_function('window.__plots[1].data[1][0] === 7')
        page.evaluate('window.__plots[1].setSeries(1,{show:false});window.__ws.close()')
        page.wait_for_function('window.__ws.readyState === WebSocket.OPEN')
        page.wait_for_timeout(150)
        self.assertFalse(page.evaluate('window.__plots[1].series[1].show'))
        self.assertEqual(page.evaluate('window.__destroyed'), 0)

    def test_xy_only_reinitialization_and_precision(self):
        self.spectrum()
        self.pub.command('replace', xy_only=True)
        page = self.page(expected=2)
        self.assertEqual(page.evaluate('window.__plots.map(p => p.data[0].length)'), [0, 0])
        self.pub.command('xy', id='curve', x=[1e12, 1e12 + .25], y=[1, 2])
        self.spectrum()
        page.wait_for_function('window.__plots[1].data[0].length === 2 && window.__plots[0].data[0].length === 3')
        self.assertEqual(page.evaluate('window.__plots[1].data[0][1]-window.__plots[1].data[0][0]'), .25)
        fresh = self.page(expected=2)
        fresh.wait_for_function('window.__plots[0].data[0].length === 3')
        snapshot = self.browser.new_page()
        snapshot.on('pageerror', lambda error: self.errors.append(str(error)))
        snapshot.add_init_script(INSTRUMENT)
        snapshot.goto('http://localhost:8050/snapshot.html?animate=1')
        snapshot.wait_for_function('window.__plots?.length === 2')
        self.assertEqual(snapshot.evaluate('Array.from(window.__plots[0].data[0])'), [1, 10, 100])

    def test_malformed_and_stale_updates_preserve_data_and_receiver(self):
        page = self.page()
        self.spectrum()
        page.wait_for_function('window.__plots[1].data[0].length === 3')
        for kwargs in ({'bad_size': True}, {'bad_json': True}, {'extra_frame': True},
                       {'meta': {'id': 'missing'}}, {'meta': {'session': 'stale'}},
                       {'meta': {'generation': self.pub.ready['generation'] - 1}},
                       {'meta': {'num_traces': 1}}, {'x': [0]}, {'x': [-1]},
                       {'y': [[float('nan')], [1]]},
                       {'meta': {'num_samples': 2}, 'x': [2, 1], 'y': [[1, 2], [3, 4]]}):
            self.pub.command('raw', **kwargs)
        self.pub.command('stream', y=[[123], [456]])
        page.wait_for_function('window.__plots[2].data[1].at(-1) === 456')
        self.assertEqual(page.evaluate('Array.from(window.__plots[1].data[1])'), [2, 5, 3])
        self.spectrum([5, 50], [[90, 91], [92, 93]])
        page.wait_for_function('window.__plots[1].data[1][0] === 90')

    def test_tab_switches_restore_independent_latest_curves(self):
        page = self.page()
        page.evaluate('window.__active = () => window.__plots.filter(p => p.root.isConnected)')
        self.spectrum()
        page.evaluate("window.__ws.send(JSON.stringify({type:'tab_create',name:'Other spectrum',endpoint:'127.0.0.1:5560'}))")
        page.get_by_role('button', name='View Other spectrum', exact=True).wait_for()
        other = Publisher(port=5560, script='xy_publisher.py')
        try:
            other.command('replace', xy_only=True)
            other.command('xy', id='spectrum', x=[2, 20], y=[[70, 80], [90, 100]])
            page.get_by_role('button', name='View Other spectrum', exact=True).click()
            page.wait_for_function('window.__active().length === 2 && window.__active()[0].data[1][0] === 70')
            self.spectrum([10, 100, 1000], [[7, 8, 9], [10, 11, 12]])
            page.wait_for_timeout(100)
            self.assertEqual(page.evaluate('Array.from(window.__active()[0].data[0])'), [2, 20])
            page.locator('[data-tab-id=bind_me] .tab-select').click()
            page.wait_for_function('window.__active().length === 4 && window.__active()[1].data[0].at(-1) === 1000')
            other.command('xy', id='spectrum', x=[20, 200], y=[[71, 81], [91, 101]])
            page.get_by_role('button', name='View Other spectrum', exact=True).click()
            page.wait_for_function('window.__active().length === 2 && window.__active()[0].data[1][0] === 71')
        finally:
            page.evaluate("window.__ws.send(JSON.stringify({type:'tab_delete',id:window.__tabs.find(t=>t.name==='Other spectrum').id}))")
            other.stop()

    def test_known_fft_peak_and_offline_animated_snapshot(self):
        page = self.page()
        fs, n, frequency = 1024, 1024, 64
        signal = np.sin(2 * np.pi * frequency * np.arange(n) / fs)
        magnitude = 2 * np.abs(np.fft.rfft(signal)) / n
        frequencies = np.fft.rfftfreq(n, 1 / fs)
        self.spectrum(frequencies[1:].tolist(), [magnitude[1:].tolist(), magnitude[1:].tolist()])
        self.pub.command('stream', y=[signal[-32:].tolist(), (signal[-32:] + 10).tolist()])
        page.wait_for_function('window.__plots[1].data[0].length === 512 && window.__plots[2].data[1].at(-1) > 9')
        peak = '(()=>{const [x,y]=window.__plots[1].data;return x[y.indexOf(Math.max(...y))]})()'
        self.assertEqual(page.evaluate(peak), frequency)
        html = page.request.get('http://localhost:8050/snapshot.html?animate=1').text()
        with tempfile.TemporaryDirectory(prefix='rtplot-xy-snapshot-') as tmp:
            path = Path(tmp) / 'snapshot.html'
            path.write_text(html)
            snapshot = self.browser.new_page()
            snapshot.on('pageerror', lambda error: self.errors.append(str(error)))
            snapshot.add_init_script(INSTRUMENT)
            snapshot.route('http://**/*', lambda route: route.abort())
            snapshot.route('https://**/*', lambda route: route.abort())
            snapshot.goto(path.as_uri())
            snapshot.wait_for_function('window.__plots.length === 4 && window.__plots[0].__renders > 2')
            self.assertEqual(snapshot.evaluate(peak), frequency)
            self.assertEqual(snapshot.evaluate('window.__plots[1].scales.x.distr'), 3)
            self.assertEqual(snapshot.evaluate('window.__plots[1].__renders'), 0)
            self.assertFalse(snapshot.evaluate('window.__plots[1].series[2].show'))
            snapshot.close()
