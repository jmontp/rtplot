"""Exercise the shipped dropdown renderer without touching any server ports."""
from pathlib import Path

from playwright.sync_api import sync_playwright


def test_filtered_dropdown_preserves_selection_and_emits_no_input():
    static = Path(__file__).resolve().parents[1] / 'rtplot/static'
    html = (static/'index.html').read_text()
    renderer = html.split("} else if (el.type === 'dropdown') {", 1)[1].split("} else if (el.type === 'grid_picker') {", 1)[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content('<div id="fixture"></div>')
        page.add_script_tag(content=(static/'dropdown-filter.js').read_text())
        page.evaluate('''renderer => {
            window.events = [];
            window.controlElements = {textInputs:{}};
            window.sendCtrl = event => { events.push(event); return true; };
            window.item = document.querySelector('#fixture');
            window.el = {id:'model',label:'Controller',options:[
              {value:'a',label:'Model A'}, {value:'b',label:'Model B'}, {value:'c',label:'Model C'}],value:'a'};
            new Function(renderer)();
        }''', renderer)
        select = page.get_by_role('combobox', name='Controller')
        page.evaluate("item.rtplotUpdate({visible_options:['b']})")
        assert select.input_value() == 'a'
        assert select.locator('option').all_text_contents() == ['Model A (current · outside filter)', 'Model B']
        assert page.evaluate('events.length') == 0
        page.evaluate("controlElements.textInputs.model.setServerValue('c')")
        assert select.input_value() == 'c'
        assert select.locator('option').all_text_contents() == ['Model B', 'Model C (current · outside filter)']
        page.evaluate("item.rtplotUpdate({visible_options:[]})")
        assert select.input_value() == 'c' and select.locator('option').count() == 1
        page.evaluate('item.rtplotUpdate({})')
        assert select.input_value() == 'c' and select.locator('option').count() == 3
        assert page.evaluate('events.length') == 0
        select.select_option('b')
        assert page.evaluate('events') == [{'type':'control_text', 'id':'model', 'value':'b'}]
        browser.close()
