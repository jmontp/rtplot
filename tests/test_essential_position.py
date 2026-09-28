"""Essential-action geometry without a publisher, network ports, or hardware."""
from pathlib import Path
import re

import pytest
from playwright.sync_api import sync_playwright


STATIC = Path(__file__).resolve().parents[1] / 'rtplot' / 'static'


@pytest.mark.parametrize('width,height', [(1440, 1000), (844, 390), (390, 844), (320, 568)])
def test_essential_position_survives_scroll_collapse_and_status(width, height):
    inline = re.search(r'<style>(.*?)</style>', (STATIC / 'index.html').read_text(), re.S)[1]
    css = (STATIC / 'ui-view.css').read_text() + inline + (STATIC / 'presentation.css').read_text()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': height})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_content(f'''<style>{css}</style>
            <div id="tabbar"><div class="tab"><button class="tab-select">Preview</button></div>
            <button class="tab-add">Add device</button></div><div id="tab-create"></div>
            <div id="header"><h1>rtplot</h1><div id="ws-status">Connected</div>
            <button id="menu-btn" class="btn" aria-label="Settings">&#9776;</button></div><div id="plots"></div>''')
        page.add_script_tag(path=str(STATIC / 'ui-view.js'))
        page.evaluate('''() => {
            const root = document.getElementById('plots');
            window.commands = 0;
            window.view = new RtplotView(root, {tab:'test', view: {
                essential_controls: ['stop','state'], sections: [
                    {id:'controller',title:'Controller',visible:true},
                    {id:'logging',title:'Logging',visible:true,collapsible:true,collapsed:true},
                    {id:'diagnostics',title:'Diagnostics',visible:true,collapsible:true,collapsed:true},
                ]}}, () => {});
            const row = document.createElement('div'); row.className='ctrl-row';
            view.parent('controller').appendChild(row);
            for (const [id, text] of [['stop','Stop torque'],['state','OFF']]) {
                const item = document.createElement('div'); item.className='ctrl-item';
                item.innerHTML = id==='stop' ? '<button class="ctrl-btn">'+text+'</button>' : '<span>'+text+'</span>';
                row.appendChild(item); view.register(id,item,'controller');
                if (id==='stop') item.querySelector('button').onclick=()=>window.commands++;
            }
            for (const id of ['logging','diagnostics']) {
                view.parent(id).innerHTML='<div style="height:900px">Long optional controls</div>';
            }
            const tail=document.createElement('div');tail.style.height='2200px';root.appendChild(tail);
            view.finish();
        }''')
        page.wait_for_timeout(60)
        stop = page.locator('[data-control-id=stop] button')
        initial = stop.bounding_box()
        assert initial['y'] >= 0 and initial['y'] + initial['height'] < height
        for section in ('logging', 'diagnostics'):
            toggle = page.locator(f'[data-section={section}] .section-header button')
            toggle.click()
            page.evaluate('window.scrollTo(0,document.body.scrollHeight)')
            current = stop.bounding_box()
            assert abs(current['x']-initial['x']) < .5
            assert abs(current['y']-initial['y']) < .5
            toggle.click()
        page.evaluate("view.source(false, 'Temporarily disconnected from synthetic source')")
        assert abs(stop.bounding_box()['y'] - initial['y']) < .5
        page.evaluate("view.source(true, '')")
        page.locator('.section-nav a').filter(has_text='Logging').click()
        page.wait_for_timeout(60)
        top = page.locator('[data-section=logging] h2').bounding_box()['y']
        chrome = page.locator('.essential-chrome').bounding_box()
        assert top >= chrome['y'] + chrome['height'] - 1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        assert page.evaluate('window.commands') == 0
        assert page.locator('[data-control-id=stop]').count() == 1
        page.evaluate('view.destroy()')
        assert page.locator('.essential-chrome').count() == 0
        assert page.locator('#header').evaluate('el => el.parentElement === document.body')
        assert not errors
        browser.close()
