from test_presentation import TestPresentation as _PresentationBase, SIZES
from test_sections import Publisher
from playwright.sync_api import sync_playwright


class TestDropdown(_PresentationBase):
    # Reuse presentation checks with a dropdown present in the layout.
    def setUp(self):
        self.pub = Publisher(script='dropdown_publisher.py')
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch()
        self.errors = []

    def test_selection_sync_validation_and_reconnection(self):
        page = self.page()
        other = self.page()
        select = page.get_by_role('combobox', name='Signal mode')
        select.select_option('smooth')
        other.wait_for_function("document.querySelector('select').value === 'smooth'")
        self.assertEqual(self.pub.command('values')['result']['mode'], 'smooth')
        self.pub.command('set', value='raw')
        page.wait_for_function("document.querySelector('select').value === 'raw'")
        select.focus()
        self.pub.command('patch', patch={'controls': {'mode': {'busy': True, 'selected': True}}})
        page.wait_for_timeout(100)
        self.assertTrue(select.evaluate('e => e === document.activeElement'))
        self.assertEqual(select.input_value(), 'raw')
        self.pub.command('patch', patch={'controls': {'mode': {'enabled': False, 'reason': 'Source unavailable'}}})
        page.wait_for_function("document.querySelector('select').disabled")
        self.assertTrue(page.get_by_text('Source unavailable', exact=True).is_visible())
        count = page.evaluate('window.__sent.length')
        select.dispatch_event('change')
        self.assertEqual(page.evaluate('window.__sent.length'), count)
        # Bypass the DOM: server rejects disabled or invalid selection events.
        page.evaluate("window.__ws.send(JSON.stringify({type:'control_text',id:'mode',value:'smooth'}))")
        page.wait_for_timeout(100)
        self.assertEqual(self.pub.command('values')['result']['mode'], 'raw')
        self.pub.command('patch', patch={'controls': {'mode': None}})
        page.wait_for_function("!document.querySelector('select').disabled")
        page.evaluate("window.__ws.send(JSON.stringify({type:'control_text',id:'mode',value:'bogus'}))")
        page.wait_for_timeout(100)
        self.assertEqual(self.pub.command('values')['result']['mode'], 'raw')
        self.pub.command('set', value='smooth')
        page.wait_for_function("document.querySelector('select').value === 'smooth'")
        self.pub.command('stale')
        page.wait_for_timeout(100)
        self.assertEqual(self.pub.command('values')['result']['mode'], 'smooth')
        self.pub.command('patch', patch={'controls': {'mode': {'visible': False}}})
        select.wait_for(state='hidden')
        self.pub.command('patch', patch={'controls': {'mode': {'visible': True}}})
        select.wait_for(state='visible')
        self.assertEqual(select.input_value(), 'smooth')
        self.assertEqual(page.evaluate('[window.__plots.length, window.__destroyed]'), [3, 0])
        page.reload()
        page.wait_for_function("document.querySelector('select')?.value === 'smooth'")
        self.assertEqual(page.evaluate('window.__destroyed'), 0)

    def test_native_dropdown_geometry(self):
        for width, height in SIZES:
            page = self.page(width, height)
            select = page.get_by_role('combobox', name='Signal mode')
            r = select.bounding_box()
            self.assertGreaterEqual(r['height'], 44)
            self.assertLessEqual(r['x'] + r['width'], width)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
            page.context.close()
