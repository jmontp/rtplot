"""Grid picker acceptance checks with real Chromium and the example controller bank."""
from playwright.sync_api import sync_playwright
from test_communication import _ServerTest
from test_presentation import SIZES
from test_sections import Publisher, INSTRUMENT

CELL = '.grid-cell[data-x={}][data-y={}]'


class TestGridPicker(_ServerTest):
    def setUp(self):
        self.pub = Publisher(script='grid_publisher.py')
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch()
        self.errors = []

    def tearDown(self):
        self.browser.close(); self.pw.stop(); self.pub.stop()
        self.assertEqual(self.errors, [])

    def page(self, width=1280, height=900):
        context = self.browser.new_context(viewport={'width': width, 'height': height},
                                           is_mobile=width < 640, has_touch=width < 640)
        page = context.new_page()
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.add_init_script(INSTRUMENT)
        page.goto('http://localhost:8050/')
        page.wait_for_function('window.__plots.length === 1')
        page.wait_for_function("document.querySelector('.grid-cell[aria-pressed=true]')?.disabled === false")
        page.wait_for_function("document.querySelector('.grid-cell').textContent.includes('c=')")
        return page

    def state(self):
        return self.pub.command('state')['result']

    def wait_state(self, predicate, timeout=6):
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.state()
            if predicate(state):
                return state
            time.sleep(.05)
        raise AssertionError(f'State not reached: {self.state()}')

    def active(self, page):
        return page.evaluate("[...document.querySelectorAll('.grid-cell[aria-pressed=true]')].map(c => [c.dataset.x, c.dataset.y])")

    def wait_active(self, page, x, y, method=None):
        page.wait_for_function(f"(() => {{ const c = document.querySelectorAll('.grid-cell[aria-pressed=true]');"
                               f" return c.length === 1 && c[0].dataset.x === '{x}' && c[0].dataset.y === '{y}'"
                               f" && !document.querySelector('.grid-cell.pending')"
                               + (f" && c[0].textContent.startsWith('{method} ·')" if method else '') + "; })()")

    def readout(self, page):
        return page.locator('[data-control-id=active_model] .ctrl-textval').inner_text()

    def test_method_changes_preserve_coordinates_and_reference_returns(self):
        page, other = self.page(), self.page()
        page.locator(CELL.format('j2', 'w3')).click()
        # A request is pending, not selected, until the application confirms it.
        page.wait_for_selector(CELL.format('j2', 'w3') + '.pending')
        self.assertEqual(page.locator(CELL.format('j2', 'w3')).get_attribute('aria-pressed'), 'false')
        self.assertIn('awaiting confirmation', page.locator('.grid-status').inner_text())
        for p in (page, other):
            self.wait_active(p, 'j2', 'w3', 'M')
        select = page.get_by_role('combobox', name='Anti-shake method')
        for method in ('D', 'E'):
            select.select_option(method)
            self.wait_state(lambda s: s['method'] == method and not s['loading'])
            for p in (page, other):
                self.wait_active(p, 'j2', 'w3', method)
            other.wait_for_function(f"document.querySelector('select').value === '{method}'")
            self.assertTrue(self.readout(page).startswith({'D': 'Active damping', 'E': 'Positive energy'}[method]))
        page.get_by_role('button', name='Reference at this jerk').click()
        self.wait_state(lambda s: s['reference'] and not s['loading'])
        for p in (page, other):
            p.wait_for_function("!document.querySelector('.grid-cell[aria-pressed=true]') && "
                                "document.querySelector('.grid-cell.remembered')?.dataset.x === 'j2'")
            p.wait_for_function("document.querySelector('[data-control-id=active_model] .ctrl-textval').textContent.startsWith('Reference · J2')")
        self.assertEqual(page.locator(CELL.format('j2', 'w3')).get_attribute('class').split().count('remembered'), 1)
        self.assertIn('No cell active', page.locator('.grid-status').inner_text())
        self.assertEqual(page.locator('[data-control-id=reference] button').get_attribute('aria-pressed'), 'true')
        page.locator(CELL.format('j2', 'w3')).click()
        self.wait_state(lambda s: not s['reference'] and not s['loading'])
        self.wait_active(page, 'j2', 'w3', 'E')
        state = self.state()
        self.assertEqual(state['switches'], [['M', 'j2', 'w3'], ['D', 'j2', 'w3'], ['E', 'j2', 'w3'],
                                             ['REF', 'j2', None], ['E', 'j2', 'w3']])
        self.assertEqual(page.evaluate('[window.__plots.length, window.__destroyed]'), [1, 0])
        self.assertEqual(other.evaluate('[window.__plots.length, window.__destroyed]'), [1, 0])

    def test_unavailable_cells_and_rejections_keep_selection(self):
        page = self.page()
        select = page.get_by_role('combobox', name='Anti-shake method')
        select.select_option('D')
        self.wait_state(lambda s: s['method'] == 'D' and not s['loading'])
        cell = page.locator(CELL.format('j1', 'w1'))
        page.wait_for_function(f"document.querySelector('{CELL.format('j1', 'w1')}').getAttribute('aria-disabled') === 'true'")
        self.assertIn('Hash mismatch', cell.inner_text())
        reason_id = cell.get_attribute('aria-describedby')
        self.assertEqual(page.locator(f'#{reason_id}').inner_text(), 'Hash mismatch')
        sent = page.evaluate('window.__sent.length')
        cell.dispatch_event('click')
        cell.focus(); page.keyboard.press('Enter')
        self.assertEqual(page.evaluate('window.__sent.length'), sent)
        # Bypass the DOM: the server enforces unavailable cells and declared coordinates.
        requests = len(self.state()['requests'])
        for x, y in (('j1', 'w1'), ('j9', 'w1'), ('j1', None)):
            page.evaluate('p => window.__ws.send(JSON.stringify(p))',
                          {'type': 'control_grid', 'id': 'weights', 'x': x, 'y': y})
        page.wait_for_timeout(200)
        self.assertEqual(len(self.state()['requests']), requests)
        # Unavailable corresponding cell on a method change: reject, keep model and X/Y.
        page.locator(CELL.format('j3', 'w3')).click()
        self.wait_state(lambda s: (s['x'], s['y']) == ('j3', 'w3') and not s['loading'])
        switches = len(self.state()['switches'])
        select.select_option('E')
        page.wait_for_function("document.querySelector('.grid-message').textContent.includes('Not exported')")
        page.wait_for_function("document.querySelector('select').value === 'D'")
        state = self.state()
        self.assertEqual((state['method'], state['x'], state['y'], len(state['switches'])), ('D', 'j3', 'w3', switches))
        self.wait_active(page, 'j3', 'w3', 'D')

    def test_torque_on_disables_and_repeated_rejections_clear_pending(self):
        page = self.page()
        enable = page.get_by_role('button', name='Enable torque')
        page.wait_for_function("!document.querySelector('[data-control-id=enable] button').disabled")
        enable.click()
        self.wait_state(lambda s: s['torque_on'])
        page.wait_for_function("document.querySelector('.grid-cell').disabled")
        self.assertTrue(page.get_by_text('Stop torque before switching controllers').first.is_visible())
        self.assertTrue(page.locator('select').is_disabled())
        requests = len(self.state()['requests'])
        page.evaluate("window.__ws.send(JSON.stringify({type:'control_grid', id:'weights', x:'j1', y:'w1'}))")
        page.wait_for_timeout(200)
        self.assertEqual(len(self.state()['requests']), requests)
        for attempt in range(2):
            # Force the grid enabled so requests reach the application, which rejects
            # them and re-locks the grid because torque is still on.
            self.pub.command('patch', patch={'controls': {'weights': {'enabled': None, 'reason': None}}})
            page.wait_for_function("!document.querySelector('.grid-cell').disabled")
            page.locator(CELL.format('j1', 'w1')).click()
            self.wait_state(lambda s: len(s['requests']) == requests + attempt + 1)
            page.wait_for_function("!document.querySelector('.grid-cell.pending') && "
                                   "document.querySelector('.grid-message').textContent.includes('stop torque')")
            self.wait_active(page, 'j2', 'w2', 'M')
            page.wait_for_function("document.querySelector('.grid-cell').disabled")
        self.assertEqual(self.state()['switches'], [])
        page.get_by_role('button', name='Stop torque').click()
        self.wait_state(lambda s: not s['torque_on'])
        page.locator(CELL.format('j1', 'w1')).click()
        self.wait_state(lambda s: s['switches'] == [['M', 'j1', 'w1']] and not s['loading'])
        self.wait_active(page, 'j1', 'w1', 'M')
        self.assertFalse(self.state()['torque_on'])  # a switch never enables torque

    def test_keyboard_reconnect_and_presentation_send_nothing(self):
        page = self.page()
        page.locator(CELL.format('j2', 'w2')).focus()
        for key, expected in (('ArrowRight', ('j3', 'w2')), ('ArrowUp', ('j3', 'w3')), ('ArrowUp', ('j3', 'w3')),
                              ('Home', ('j1', 'w3')), ('ArrowDown', ('j1', 'w2'))):
            page.keyboard.press(key)
            self.assertEqual(page.evaluate("[document.activeElement.dataset.x, document.activeElement.dataset.y]"), list(expected))
        self.assertEqual(page.evaluate("document.querySelectorAll('.grid-cell[tabindex=\"0\"]').length"), 1)
        self.assertEqual(page.evaluate('window.__sent.length'), 0)
        page.keyboard.press('Enter')
        self.wait_state(lambda s: (s['x'], s['y']) == ('j1', 'w2') and not s['loading'])
        page.keyboard.press('ArrowRight'); page.keyboard.press(' ')
        self.wait_state(lambda s: (s['x'], s['y']) == ('j2', 'w2') and not s['loading'])
        self.assertEqual([m['type'] for m in page.evaluate('window.__sent')], ['control_grid', 'control_grid'])
        self.wait_active(page, 'j2', 'w2', 'M')
        before = self.state()
        # Presentation changes and reconnects emit no requests and do not reset history.
        self.pub.command('patch', patch={'sections': {'controller': {'status': 'warning', 'message': 'Check'}},
                                         'controls': {'weights': {'busy': True}}})
        page.wait_for_function("document.querySelector('[data-control-id=weights]').getAttribute('aria-busy') === 'true'")
        page.set_viewport_size({'width': 390, 'height': 844}); page.wait_for_timeout(150)
        page.set_viewport_size({'width': 1280, 'height': 900}); page.wait_for_timeout(150)
        self.assertEqual(page.evaluate('[window.__sent.length, window.__destroyed]'), [2, 0])
        page.reload()
        page.wait_for_function('window.__plots.length === 1')
        self.wait_active(page, 'j2', 'w2', 'M')
        page.wait_for_timeout(300)
        after = self.state()
        self.assertEqual((after['requests'], after['switches']), (before['requests'], before['switches']))
        # A request carrying a superseded layout generation is rejected by the server.
        page.evaluate("window.__ws.send(JSON.stringify({type:'control_grid', id:'weights', x:'j3', y:'w3', session:'old', generation:0}))")
        page.wait_for_timeout(200)
        self.assertEqual(self.state()['requests'], before['requests'])

    def test_phone_geometry(self):
        for width, height in [*SIZES, (360, 780)]:
            with self.subTest(size=(width, height)):
                page = self.page(width, height)
                page.locator('.grid-picker').scroll_into_view_if_needed()
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                boxes = page.locator('.grid-cell').evaluate_all('cs => cs.map(c => c.getBoundingClientRect().toJSON())')
                self.assertEqual(len(boxes), 9)
                for box in boxes:
                    self.assertGreaterEqual(box['width'], 44)
                    self.assertGreaterEqual(box['height'], 44)
                    self.assertLessEqual(box['right'], width)
                widths = {round(b['width']) for b in boxes}
                self.assertLessEqual(max(widths) - min(widths), 1)  # equal-sized cells
                page.context.close()


class TestGridPickerFallback(_ServerTest):
    """The example's explicit flat-dropdown fallback for servers without grid_picker_v1."""

    def setUp(self):
        self.pub = Publisher(port='flat', script='grid_publisher.py')
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch()
        self.errors = []

    def tearDown(self):
        self.browser.close(); self.pw.stop(); self.pub.stop()
        self.assertEqual(self.errors, [])

    def test_flat_dropdown_switches_and_rejects(self):
        page = self.browser.new_page()
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.add_init_script(INSTRUMENT)
        page.goto('http://localhost:8050/')
        select = page.get_by_role('combobox', name='Controller')
        page.wait_for_function("document.querySelector('select')?.disabled === false")
        self.assertEqual(page.locator('.grid-cell').count(), 0)
        self.assertEqual(select.locator('option').count(), 28)  # 30 checkpoints minus 2 unavailable
        readout = page.locator('[data-control-id=active_model] .ctrl-textval')
        select.select_option('D-j1-w3')
        page.wait_for_function("document.querySelector('[data-control-id=active_model] .ctrl-textval').textContent.endsWith('D-j1-w3')")
        self.assertTrue(readout.inner_text().startswith('Active damping · J1'))
        state = TestGridPicker.wait_state(self, lambda s: s['ready'] and not s['loading'])
        self.assertEqual(state['switches'], [['D', 'j1', 'w3']])
        page.get_by_role('button', name='Enable torque').click()
        page.wait_for_function("document.querySelector('select').disabled")
        # Force the dropdown enabled: the application still rejects and restores it.
        self.pub.command('patch', patch={'controls': {'controller': {'enabled': None, 'reason': None}}})
        page.wait_for_function("!document.querySelector('select').disabled")
        select.select_option('E-j2-w2')
        page.wait_for_function("document.querySelector('select').value === 'D-j1-w3'")
        page.get_by_text('Rejected: stop torque before switching controllers').wait_for()
        self.assertEqual(self.state()['switches'], [['D', 'j1', 'w3']])

    state = TestGridPicker.state
