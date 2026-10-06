"""Native checkboxes use guarded requests and source-confirmed shared state."""
from playwright.sync_api import sync_playwright
from test_communication import _ServerTest
from test_sections import Publisher

class TestCheckbox(_ServerTest):
    def test_source_confirmation_two_browsers_and_disabled_guard(self):
        pub=Publisher(script='checkbox_publisher.py')
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch()
                try:
                    pages=[browser.new_page(),browser.new_page()]
                    for page in pages:
                        page.goto('http://localhost:8050/')
                        page.get_by_role('checkbox',name='Trained filter').wait_for()
                    check=pages[0].get_by_role('checkbox',name='Trained filter')
                    check.click()
                    pages[0].wait_for_timeout(200)
                    assert pub.command('state')['result']==['filter']
                    assert not check.is_checked()
                    pub.command('patch',patch={'controls':{'filter':{'selected':True}}})
                    for page in pages:
                        page.wait_for_function("document.querySelector('input[type=checkbox]').checked")
                    pub.command('patch',patch={'controls':{'filter':{'enabled':False,'reason':'Stop torque first'}}})
                    for page in pages:
                        page.wait_for_function("document.querySelector('input[type=checkbox]').disabled")
                    assert pub.command('state')['result']==['filter']
                finally:
                    browser.close()
        finally:
            pub.stop()

def test_checkbox_declaration():
    from rtplot import client
    assert client.Checkbox('filter','Trained filter').to_dict()=={'type':'checkbox','id':'filter','label':'Trained filter'}
