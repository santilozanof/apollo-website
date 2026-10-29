/* Synthetic connection states only; no real Google account is accessed. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const origin = process.env.APOLLO_TEST_URL || 'http://127.0.0.1:8891';

(async () => {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    for (const viewport of [{width:1440,height:900},{width:390,height:844}]) {
      const mobile = viewport.width < 500;
      const context = await browser.newContext({viewport, isMobile:mobile, hasTouch:mobile});
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      let gmailConnected = true, disconnects = 0;
      await page.route('**/api/connections**', route => route.fulfill({status:200, contentType:'application/json',
        body:JSON.stringify({integrations:[
          {id:'gmail',name:'Gmail',description:'Search, summarize, and draft email replies in Apollo chat.',
            status:gmailConnected?'connected':'disconnected',connected:gmailConnected,
            actions:gmailConnected?[{id:'reconnect',label:'Reconnect',method:'GET',url:'/api/gmail/connect'},
              {id:'disconnect',label:'Disconnect',method:'POST',url:'/api/gmail/disconnect',confirm:'Disconnect Gmail?'}]:
              [{id:'connect',label:'Connect',method:'GET',url:'/api/gmail/connect'}]},
          {id:'google_calendar',name:'Google Calendar',description:'Schedules and events.',status:'connected',
            connected:true,actions:[]}
        ]})}));
      await page.route('**/api/gmail/disconnect', route => {disconnects++; gmailConnected=false;
        return route.fulfill({status:200, contentType:'application/json',body:'{"status":"disconnected","connected":false}'});
      });
      await page.goto(origin, {waitUntil:'domcontentloaded'});
      await page.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
      await page.evaluate(() => window.openSettings());
      const gmail = page.locator('[data-connection-id="gmail"]');
      await gmail.waitFor();
      assert.equal(await gmail.locator('.apollo-connection-status').innerText(), 'Connected');
      assert.equal(await gmail.getByRole('link', {name:'Reconnect'}).getAttribute('href'), '/api/gmail/connect');
      assert.equal(await page.locator('[data-connection-id="google_calendar"] .apollo-connection-status').innerText(), 'Connected');
      await page.evaluate(() => {window.apolloConfirm = async () => true;});
      await gmail.getByRole('button', {name:'Disconnect'}).click();
      await page.waitForFunction(() => document.querySelector('[data-connection-id="gmail"] .apollo-connection-status')?.textContent?.includes('Disconnected'));
      assert.equal(disconnects, 1);
      assert.equal(await gmail.getByRole('link', {name:'Connect'}).getAttribute('href'), '/api/gmail/connect');
      assert.equal(await page.locator('[data-connection-id="google_calendar"] .apollo-connection-status').innerText(), 'Connected');
      await page.evaluate(() => document.documentElement.setAttribute('data-theme','light'));
      assert.equal(await gmail.isVisible(), true);
      await page.evaluate(() => document.documentElement.setAttribute('data-theme','dark'));
      await page.goto(origin + '/?gmail=connected', {waitUntil:'domcontentloaded'});
      await page.locator('#settingsView.active').waitFor();
      assert.equal(new URL(page.url()).searchParams.has('gmail'), false);
      assert.deepEqual(errors, []);
      console.log(`${mobile?'iPhone':'desktop'} Gmail connection controls and Calendar preservation passed`);
      await context.close();
    }
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exit(1);});
