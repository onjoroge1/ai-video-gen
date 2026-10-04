from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
import threading,json
from playwright.sync_api import sync_playwright
repo=Path(__file__).resolve().parents[2]
root=repo/'static'
output=repo/'integrations/video_engines/runtime/reports/browser'
output.mkdir(parents=True,exist_ok=True)
server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(root)))
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
  page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(f'http://127.0.0.1:{server.server_port}/video-engine-workbench.html');page.wait_for_selector('.engine')
  assert page.locator('.engine').count()==4
  assert page.locator('.shot').count()==2
  assert 'Browser checks passed' in page.locator('#status').inner_text()
  page.locator('#title').fill('Edited storyboard')
  with page.expect_download() as download:
   page.get_by_role('button',name='Export draft JSON').click()
  download.value.save_as(str(output/'workbench-export.json'))
  assert json.loads(Path(str(output/'workbench-export.json')).read_text())['title']=='Edited storyboard'
  page.locator('#flow').select_option('repurpose')
  assert 'source span' in page.locator('#status').inner_text()
  page.locator('#flow').select_option('motion_scene')
  page.screenshot(path=str(output/'workbench-desktop.png'),full_page=True)
  page.set_viewport_size({'width':390,'height':844})
  page.screenshot(path=str(output/'workbench-mobile.png'),full_page=True)
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
  assert not errors,errors
  browser.close();print('UI PASS: 4 capabilities, 2 shots, edit/export, source-span error, mobile no-overflow, zero page errors')
finally:server.shutdown()
