/* Isolated fixture: no real account, operator token, or mailbox is touched. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const origin = process.env.APOLLO_TEST_URL || 'http://127.0.0.1:8895';

(async () => {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    for (const viewport of [{width:1440,height:900},{width:390,height:844}]) {
      const mobile = viewport.width < 500;
      const context = await browser.newContext({viewport, isMobile:mobile, hasTouch:mobile,
        reducedMotion:'reduce'});
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/connections**', route => route.fulfill({status:200, contentType:'application/json',
        body:JSON.stringify({integrations:[
          {id:'gmail',name:'Gmail',description:'Email in Apollo chat',status:'connected',connected:true,
            management_note:'Disconnect leaves Calendar connected.',actions:[{id:'reconnect',label:'Reconnect',method:'GET',url:'/api/gmail/connect'},
              {id:'disconnect',label:'Disconnect',method:'POST',url:'/api/gmail/disconnect',confirm:'Disconnect?'}]},
          {id:'google_calendar',name:'Google Calendar',description:'Calendar events',status:'connected',connected:true,
            management_note:'Calendar has no separate disconnect.',actions:[]},
          {id:'canvas_calendar',name:'Canvas Calendar',description:'Assignments',status:'temporary_error',connected:true,
            last_successful_sync:'2026-10-28T08:00:00Z',actions:[{id:'refresh',label:'Refresh',method:'POST',url:'/api/calendar/subscriptions/canvas/refresh'}]},
          {id:'spotify',name:'Spotify',description:'Listening',status:'connected',connected:true,actions:[]},
          {id:'whoop',name:'WHOOP',description:'Recovery',status:'reconnection_required',connected:false,actions:[{id:'reconnect',label:'Reconnect',method:'GET',url:'/api/whoop/connect'}]}
        ]})}));
      await page.route('**/api/chats', route => route.fulfill({status:200, contentType:'application/json',
        body:JSON.stringify({chats:[
          {id:1,title:'Application planning',updated_at:'2026-10-29 13:00:00',message_count:4},
          {id:2,title:'Error: provider timed out',updated_at:'2026-10-28 12:00:00',message_count:2},
          {id:3,title:'New Chat',updated_at:'2026-10-27 12:00:00',message_count:0}
        ]})}));
      await page.route('**/api/chats/search**', route => route.fulfill({status:200, contentType:'application/json',
        body:JSON.stringify({results:[{id:1,title:'Application planning',updated_at:'2026-10-29 13:00:00',message_count:4,snippet:'application checklist'}]})}));
      await page.goto(origin, {waitUntil:'domcontentloaded'});
      await page.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
      await page.evaluate(() => window.openSettings());
      const disclosure = name => page.locator('.apollo-settings-disclosure').filter({hasText:name}).first();
      for (const name of ['Memory & conversation history','Notifications','Notification history','Privacy & Security · Tab Locks']) {
        const button = disclosure(name);
        await button.waitFor();
        assert.equal(await button.getAttribute('aria-expanded'), 'false', name);
      }
      await disclosure('Privacy & Security · Tab Locks').click();
      assert.equal(await disclosure('Privacy & Security · Tab Locks').getAttribute('aria-expanded'), 'true');
      const token = page.getByPlaceholder('Operator setup token');
      await token.waitFor({state:'visible'});
      assert.equal(await token.getAttribute('type'), 'password');
      assert.equal(await page.getByPlaceholder('New passphrase (16+ characters)').getAttribute('type'), 'password');
      await disclosure('Memory & conversation history').click();
      assert.equal(await disclosure('Memory & conversation history').getAttribute('aria-expanded'), 'true');
      await disclosure('Notifications').focus();
      await page.keyboard.press('Enter');
      assert.equal(await disclosure('Notifications').getAttribute('aria-expanded'), 'true');
      const rows = page.locator('#apolloConnectionsPanel .apollo-connected-service');
      assert.equal(await rows.count(), 5);
      assert.equal(await page.locator('[data-connection-id="google_calendar"] .apollo-connection-status').innerText(), 'Connected');
      assert.equal(await page.locator('[data-connection-id="canvas_calendar"] .apollo-connection-status').innerText(), 'Temporary service error');
      assert.equal(await page.locator('[data-connection-id="spotify"] img[src="/vendor/spotify/icon-green.svg"]').count(), 1);
      await page.locator('[data-connection-id="google_calendar"] summary').click();
      assert.match(await page.locator('[data-connection-id="google_calendar"] .apollo-connection-details').innerText(), /no separate disconnect/i);
      for (const theme of ['light','dark']) {
        await page.evaluate(theme => document.documentElement.setAttribute('data-theme', theme), theme);
        const width = await page.evaluate(() => document.documentElement.scrollWidth);
        assert.ok(width <= viewport.width + 1, `${theme} horizontal overflow ${width}`);
        await page.screenshot({path:`/private/tmp/apollo-settings-${mobile?'iphone':'desktop'}-${theme}.png`, fullPage:false});
      }
      await page.evaluate(() => window.openApollo());
      await page.waitForFunction(() => document.querySelector('#apolloView')?.classList.contains('active'));
      await page.evaluate(() => window.apolloOpenHistory());
      await page.locator('.apollo-history-group').first().waitFor();
      assert.equal(await page.locator('.apollo-history-group.is-empty').count(), 1);
      assert.equal(await page.locator('.apollo-history-group.is-empty').getAttribute('open'), null);
      assert.match(await page.locator('.apollo-history-card-title').allTextContents().then(rows => rows.join(' ')), /Conversation with an error/);
      await page.locator('#apolloHistorySearch').fill('application');
      await page.waitForTimeout(300);
      assert.equal(await page.locator('.apollo-history-card').count(), 1);
      assert.deepEqual(errors, []);
      console.log(`${mobile?'iPhone':'desktop'} Settings disclosures, connections, History and themes passed`);
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
