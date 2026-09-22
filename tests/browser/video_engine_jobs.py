"""Browser UI contract with mocked HTTP; real storage/engines have a separate smoke."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import threading
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[2]
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(root/'integrations/motion-canvas/.browsers')
evidence=root/'integrations/video_engines/runtime/reports/jobs/browser'
evidence.mkdir(parents=True,exist_ok=True)
server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(root/'static')))
threading.Thread(target=server.serve_forever,daemon=True).start()
calls=[];saved={}
def handle(route):
    r=route.request;path=r.url.split('/api/',1)[1]
    if path.startswith('finished?'): value={'videos':[{'id':'source','title':'Source fixture'}]}
    elif path=='video-engines':value={'engines':[{'engine':'openshorts','ready_on_this_host':False}]}
    elif r.method=='POST' and path=='video-engines/jobs':
        body=r.post_data_json;calls.append(body);job_id='engine-'+body['request_id'].replace('-','')
        value={'id':job_id,'status':'queued','artifacts':[], 'dispatch_path':f'/api/video-engines/jobs/{job_id}/dispatch'};saved[job_id]=value
    elif path.endswith('/dispatch'):value={'worker_required':True,'message':'Queued for a dedicated engine worker'}
    else:value=saved[path.rsplit('/',1)[-1]]
    route.fulfill(json=value)
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1360,'height':1000});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/api/**',handle)
        url=f'http://127.0.0.1:{server.server_port}/video-engine-jobs.html?source=source'
        page.goto(url);page.wait_for_selector('#source-videos option',state='attached')
        assert page.locator('#source').input_value()=='source'
        page.locator('#title').fill('Reused source')
        page.locator('#end').fill('3');page.locator('#rights').check()
        page.locator('#queue').click();page.wait_for_function("document.querySelector('#message').textContent.includes('dedicated')")
        assert len(calls)==1 and calls[0]['engine']=='openshorts'
        page.locator('#queue').click();page.wait_for_function("document.querySelector('#queue').disabled === false")
        assert len(calls)==2 and calls[0]['request_id']==calls[1]['request_id']
        page.reload();page.wait_for_function("document.querySelector('#job-status').textContent.includes('queued')")
        assert len(calls)==2 # reconnect is read-only
        page.locator('#engine').select_option('moneyprinterturbo')
        assert page.locator('#materials-label').is_visible() and not page.locator('#clip-options').is_visible()
        page.locator('#engine').select_option('motion_canvas')
        assert page.locator('#board-label').is_visible() and page.locator('#silent-label').is_visible()
        page.screenshot(path=str(evidence/'engine-jobs-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(evidence/'engine-jobs-mobile.png'),full_page=True)
        assert not errors,errors
        browser.close()
        (evidence/'browser.json').write_text(json.dumps({'mock_http':True,'source_prefill':True,
            'queue_deduplication':True,'reload_read_only':True,'method_options':True,'mobile_no_overflow':True,
            'page_errors':errors},indent=2))
finally:server.shutdown()
