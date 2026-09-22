/** Render one immutable JSON job with a version-pinned, preinstalled browser. */
import {createServer} from 'vite';
import motionCanvasModule from '@motion-canvas/vite-plugin';
import {copyFile, mkdir, readFile, symlink} from 'node:fs/promises';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const project = dirname(fileURLToPath(import.meta.url));
process.env.PLAYWRIGHT_BROWSERS_PATH = join(project, '.browsers');
const {chromium} = await import('playwright');
let browser, server;
try {
  browser = await chromium.launch({headless:true});
  if (process.argv[2] === '--check') {
    console.log('Installed Chromium launch verified');
  } else {
    const payload = resolve(process.argv[2]);
    const output = resolve(process.argv[3]);
    const data = JSON.parse(await readFile(payload,'utf8'));
    const board = data.request.storyboard;
    const frames = Math.round(board.shots.at(-1).end * 24);
    if (!Array.isArray(board.shots) || frames < 24 || frames > 2160) throw Error('Invalid motion job size');
    const root = join(dirname(output), 'motion-project');
    await mkdir(join(root,'src'),{recursive:true});
    await mkdir(output,{recursive:true});
    for (const f of ['render.html','src/job-project.ts','src/job-render.ts','src/job-scene.tsx']) {
      await copyFile(join(project,f),join(root,f));
    }
    await symlink(join(project,'node_modules'),join(root,'node_modules'),'dir');
    const motionCanvas = motionCanvasModule.default ?? motionCanvasModule;
    server = await createServer({configFile:false,root,logLevel:'error',
      plugins:[motionCanvas({project:join(root,'src/job-project.ts'),output})],
      server:{host:'127.0.0.1',port:0,fs:{strict:true,allow:[root,join(project,'node_modules')]}}});
    await server.listen();
    const port = server.httpServer.address().port;
    const origin = `http://127.0.0.1:${port}`;
    const page = await browser.newPage();
    await page.route('**/*',route=>{
      const url=new URL(route.request().url());
      if (url.origin===origin || ['data:','blob:'].includes(url.protocol)) return route.continue();
      return route.abort();
    });
    const errors=[]; page.on('pageerror',error=>errors.push(error.message));
    await page.goto(`${origin}/render.html`);
    await page.waitForFunction(()=>typeof window.renderEngineJob==='function',{},{timeout:30000});
    await page.evaluate(data=>window.renderEngineJob(data),
      {shots:board.shots,portrait:data.request.aspect_ratio==='9:16',frames});
    if(errors.length)throw Error(errors.join('; '));
    console.log(JSON.stringify({frames,output,renderer:'motion_canvas',version:'3.17.2'}));
  }
} finally {
  if(browser)await browser.close();
  if(server)await server.close();
}
