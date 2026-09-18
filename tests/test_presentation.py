"""Responsive presentation acceptance checks using real Chromium and a publisher."""
from playwright.sync_api import sync_playwright
from test_communication import _ServerTest
from test_sections import Publisher, INSTRUMENT

SIZES = [(1440, 900), (1024, 768), (390, 844), (320, 568), (844, 390)]


class TestPresentation(_ServerTest):
    def setUp(self):
        self.pub = Publisher(script='presentation_publisher.py')
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch()
        self.errors = []

    def tearDown(self):
        self.browser.close(); self.pw.stop(); self.pub.stop()
        self.assertEqual(self.errors, [])

    def page(self, width=1440, height=900):
        context = self.browser.new_context(viewport={'width': width, 'height': height},
                                           is_mobile=width < 640, has_touch=width < 640)
        page = context.new_page()
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.add_init_script(INSTRUMENT)
        page.goto('http://localhost:8050/')
        page.wait_for_function('window.__plots.length === 3')
        page.wait_for_function("document.querySelector('[data-control-id=stop] button').disabled === false")
        return page

    def assert_geometry(self, page, width, budget):
        self.assertEqual(page.evaluate('innerWidth'), width)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
        height = page.evaluate("document.querySelector('#header').getBoundingClientRect().height + document.querySelector('.ui-sticky').getBoundingClientRect().height")
        self.assertLessEqual(height, budget)
        # All visible controls fit their row and the viewport, even off-screen vertically.
        bad = page.locator('.ctrl-item').evaluate_all('''items => items.flatMap(item => {
          if (!item.getClientRects().length) return [];
          return Array.from(item.querySelectorAll('button,input,.ctrl-val,.ctrl-reason')).filter(el => {
            if (!el.getClientRects().length) return false;
            const r=el.getBoundingClientRect(); return r.left < -1 || r.right > innerWidth + 1;
          }).map(el => el.outerHTML);
        })''')
        self.assertEqual(bad, [])
        small = page.locator('button,summary,.section-nav a,input,.u-series[role=button]').evaluate_all('''els => els.filter(el => {
          if (!el.getClientRects().length) return false;
          const r=el.getBoundingClientRect(); return r.width < 43.9 || r.height < 43.9;
        }).map(el => ({html:el.outerHTML,rect:el.getBoundingClientRect().toJSON()}))''')
        self.assertEqual(small, [])

    def test_all_requested_viewports_and_presentation_has_no_commands(self):
        for width, height in SIZES:
            with self.subTest(size=(width,height)):
                page = self.page(width, height)
                self.assertIn('width=device-width', page.locator('meta[name=viewport]').get_attribute('content'))
                self.assertNotIn('user-scalable=no', page.locator('meta[name=viewport]').get_attribute('content'))
                budget = 180 if width < 640 else 120 if height < 480 else 144
                self.assert_geometry(page, width, budget)
                note = page.locator('[data-control-id=note] input')
                note.fill('An unfinished edit')
                page.locator('.section-more summary').click()
                page.locator('.secondary-links a').click()
                page.wait_for_timeout(100)
                self.assertEqual(note.input_value(), 'An unfinished edit')
                self.assert_geometry(page, width, budget)
                self.assertTrue(page.locator('[data-section=advanced] h2').evaluate('(e)=>e===document.activeElement'))
                top = page.locator('[data-section=advanced] h2').bounding_box()['y']
                sticky_bottom = page.locator('.ui-sticky').bounding_box()
                self.assertGreaterEqual(top + 1, sticky_bottom['y'] + sticky_bottom['height'])
                page.evaluate('window.scrollTo(0,document.body.scrollHeight)')
                self.assertGreaterEqual(page.locator('#header').bounding_box()['y'], 0)
                self.assertTrue(page.locator('#ws-status').is_visible())
                for cid in ('hardware', 'stop'):
                    el = page.locator(f'.essential-controls [data-control-id={cid}]')
                    r = el.bounding_box()
                    self.assertGreaterEqual(r['y'], 0)
                    self.assertLessEqual(r['y']+r['height'], height)
                    self.assertEqual(el.evaluate("e=>{for(let p=e.parentElement;p;p=p.parentElement){if(/auto|scroll|hidden|clip/.test(getComputedStyle(p).overflowY))return p.className;}return null;}"), None)
                page.locator('[data-section=advanced] button[aria-expanded]').click()
                page.locator('.section-nav > a').filter(has_text='Setup').focus()
                page.keyboard.press('Enter')
                page.locator('#menu-btn').click()
                self.assertTrue(page.locator('#status').is_visible())
                page.keyboard.press('Escape')
                self.assertTrue(page.locator('#menu-btn').evaluate('(e)=>e===document.activeElement'))
                page.locator('[data-control-id=start] button').dispatch_event('click')
                self.assertTrue(page.get_by_text('Prepare the source first', exact=True).is_visible())
                self.assertEqual(page.evaluate('window.__sent'), [])
                self.assertEqual(page.evaluate('[window.__plots.length,window.__destroyed]'), [3,0])
                if height < 480:
                    page.evaluate('window.__ws.close()')
                    page.locator('.ui-source-status').wait_for(state='visible')
                    self.assert_geometry(page, width, budget)
                    self.assertTrue(page.locator('[data-control-id=stop] button').is_disabled())
                page.context.close()
        self.assertFalse(any(m.get('buttons') for m in self.pub.messages))

    def test_resize_retains_instances_values_focus_and_streaming(self):
        page = self.page()
        note = page.locator('[data-control-id=note] input')
        note.fill('Preserved draft')
        order=page.locator('[data-control-id]').evaluate_all('(els)=>els.map(el=>el.dataset.controlId)')
        page.evaluate("window.__plots[0].setScale('x',{min:20,max:50});window.__plots[0].setSeries(1,{show:false})")
        for w,h in SIZES[::-1]:
            page.set_viewport_size({'width':w,'height':h})
            page.wait_for_timeout(120)
            self.assertEqual(note.input_value(),'Preserved draft')
            self.assertEqual(page.locator('[data-control-id]').evaluate_all('(els)=>els.map(el=>el.dataset.controlId)'),order)
            self.assertTrue(note.evaluate('(el)=>el===document.activeElement'))
            self.assertEqual(page.evaluate('[window.__plots.length,window.__destroyed]'), [3,0])
            self.assertEqual(page.evaluate('[window.__plots[0].scales.x.min,window.__plots[0].scales.x.max,window.__plots[0].series[1].show]'), [20,50,False])
            cols = page.locator('.plot-row').evaluate('(el)=>getComputedStyle(el).gridTemplateColumns.split(" ").length')
            self.assertEqual(cols, 1 if w < 640 else 2 if w < 1024 else 3)
            self.assertGreaterEqual(page.evaluate('window.__plots[0].height'), 220)
        legend = page.locator('.u-legend .u-series[role=button]').first
        legend.focus(); page.keyboard.press('Enter')
        self.assertTrue(page.evaluate('window.__plots[0].series[1].show'))
        self.assertEqual(legend.get_attribute('aria-pressed'), 'true')
        self.assertEqual(page.evaluate('window.__sent'), [])
        self.assertGreater(page.evaluate('window.__plots[0].__renders'), 5)

    def test_essential_controls_and_authoritative_exclusive_groups(self):
        page=self.page()
        self.pub.command('patch',patch={'sections':{'status':{'visible':False},'setup':{'status':'warning','message':'Synthetic warning'}},
                                        'controls':{'smooth':{'selected':True}}})
        page.locator('.section-more summary').click()
        page.locator('.secondary-links a').click()
        page.wait_for_function("document.querySelector('[data-control-id=smooth] button').getAttribute('aria-pressed')==='true'")
        self.assertEqual(page.locator('[data-control-id=raw] button').get_attribute('aria-pressed'),'false')
        self.assertIn('Warning',page.locator('.section-nav > a').filter(has_text='Setup').inner_text())
        self.assertTrue(page.locator('.essential-controls [data-control-id=hardware]').is_visible())
        # An explicit control visibility override still wins over essential placement.
        self.pub.command('patch',patch={'controls':{'stop':{'busy':True}}})
        page.wait_for_function("document.querySelector('[data-control-id=stop]').getAttribute('aria-busy')==='true'")
        self.assertTrue(page.locator('[data-control-id=stop] button').is_enabled())
        page.locator('[data-control-id=stop] button').click()
        self.pub.wait(lambda m:m.get('buttons')==['stop'])
        page.locator('[data-control-id=raw] button').click()
        self.pub.wait(lambda m:m.get('buttons')==['raw'])
        # Sending the request does not optimistically select it.
        self.assertEqual(page.locator('[data-control-id=smooth] button').get_attribute('aria-pressed'),'true')

    def test_semantic_contrast_and_focus_style(self):
        page=self.page(390,844)
        page.locator('.section-more summary').click(); page.locator('.secondary-links a').click()
        ratios=page.evaluate(r"""() => {
          const lum = c => {const rgb=c.match(/[\d.]+/g).slice(0,3).map(Number).map(x=>x/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];};
          return ['primary','danger','warning','choice'].map(kind => {
            const el=document.querySelector(`[data-appearance=${kind}] button:not(:disabled)`);
            const s=getComputedStyle(el), a=lum(s.color), b=lum(s.backgroundColor);
            return {kind,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
          });
        }""")
        for result in ratios: self.assertGreaterEqual(result['ratio'],4.5,result)
        page.keyboard.press('Tab')  # Enter keyboard modality for :focus-visible.
        page.locator('[data-control-id=raw] button').focus()
        style=page.locator('[data-control-id=raw] button').evaluate('(e)=>({width:getComputedStyle(e).outlineWidth,style:getComputedStyle(e).outlineStyle})')
        self.assertEqual(style,{'width':'3px','style':'solid'})
        self.assertEqual(page.locator('[data-control-id=help] .ctrl-textval').evaluate('(e)=>getComputedStyle(e).borderWidth'),'0px')

    def test_source_management_keyboard(self):
        page=self.page(320,568)
        page.get_by_role('button',name='Add data source').focus();page.keyboard.press('Enter')
        page.locator('#tab-create .name-in').fill('Keyboard source')
        page.locator('#tab-create .ep-in').fill('127.0.0.1:5599')
        page.locator('.tab-create-ok').press('Enter')
        rename=page.get_by_role('button',name='Rename Keyboard source',exact=True)
        rename.wait_for();rename.focus();page.keyboard.press('Enter')
        page.locator('.tab-name-input').fill('Cancelled edit')
        page.locator('.tab-name-input').press('Escape')
        page.wait_for_timeout(100)
        self.assertTrue(page.get_by_role('button',name='View Keyboard source',exact=True).is_visible())
        self.assertEqual(page.locator('.tab-name-input').count(),0)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),320)
        self.assertEqual(page.evaluate('window.__sent'),[])
        # Keep the shared test server isolated for subsequent tests.
        page.evaluate("window.__ws.send(JSON.stringify({type:'tab_delete',id:window.__tabs.find(t=>t.name==='Keyboard source').id}))")
