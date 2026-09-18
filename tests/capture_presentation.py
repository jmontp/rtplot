"""Save an acceptance screenshot set; run with the local test ports available."""
import argparse
import json
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from test_communication import ServerProcess, REPO_ROOT
from test_sections import Publisher
from test_presentation import SIZES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label',default='after')
    parser.add_argument('--output',type=Path,default=Path(REPO_ROOT)/'docs/presentation-screenshots')
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        server=ServerProcess(tabs_file=tmp+'/tabs.json');server.start()
        publisher=None
        try:
            publisher=Publisher(script='presentation_publisher.py')
            with sync_playwright() as p:
                browser=p.chromium.launch();metrics=[]
                for w,h in SIZES:
                    context=browser.new_context(viewport={'width':w,'height':h},is_mobile=w<640,has_touch=w<640)
                    page=context.new_page(); page.goto('http://localhost:8050/')
                    page.wait_for_selector('.uplot'); page.wait_for_timeout(300)
                    page.screenshot(path=str(args.output/f'{args.label}-{w}x{h}.png'))
                    record={'viewport':[w,h],**page.evaluate('''({innerWidth,scrollWidth:document.documentElement.scrollWidth,
                        persistentHeight:document.querySelector('#header').getBoundingClientRect().height+document.querySelector('.ui-sticky').getBoundingClientRect().height})''')}
                    if page.locator('.section-more').count():
                        page.locator('.section-more summary').click(); page.locator('.secondary-links a').click()
                        page.wait_for_timeout(100)
                        page.screenshot(path=str(args.output/f'{args.label}-advanced-{w}x{h}.png'))
                        record['expandedScrollWidth']=page.evaluate('document.documentElement.scrollWidth')
                    metrics.append(record);context.close()
                browser.close()
                (args.output/f'{args.label}-metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
        finally:
            if publisher: publisher.stop()
            server.stop()


if __name__=='__main__':
    main()
