/* Isolated Apollo fixture; all connected-service responses below are synthetic. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const origin = process.env.APOLLO_TEST_URL || 'http://127.0.0.1:8876';

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    for (const viewport of [{width: 1440, height: 900}, {width: 390, height: 844}]) {
      const mobile = viewport.width < 500;
      const context = await browser.newContext({viewport, isMobile: mobile, hasTouch: mobile});
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const due = new Date(Date.now() + 6 * 3600000).toISOString();
      let tasks = [{id: 1, title: 'Assignment', source: 'canvas', active: true, completed: false, due_at: due},
        {id: 2, title: 'Task', source: 'apollo', active: true, completed: false, due_at: due}];
      let events = [{summary: 'Meeting', start: {dateTime: due}}];
      let whoop = {status: 'ready', summary: {recovery: {score: 29}}};
      const json = (route, body) => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
      await page.route('**/api/tasks', route => json(route, {tasks}));
      await page.route('**/api/connections', route => json(route, {integrations: [
        {id: 'google_calendar', connected: true}, {id: 'spotify', connected: true},
        {id: 'whoop', connected: true}, {id: 'canvas_calendar', connected: true}]}));
      await page.route('**/api/calendar/events?**', route => json(route, {events}));
      await page.route('**/api/music/analytics?**', route => json(route, {events: 12,
        period: {first_date: '2026-10-26'}, top: {artists: [{name: 'Verified Artist'}]}}));
      await page.route('**/api/whoop/summary', route => json(route, whoop));
      await page.goto(origin, {waitUntil: 'domcontentloaded'});
      await page.evaluate(() => window.openApollo());
      await page.locator('.apollo-pulse-item').first().waitFor();
      const labels = await page.locator('.apollo-pulse-item').allTextContents();
      await page.screenshot({path: `/private/tmp/apollo-pulse-${mobile ? 'iphone' : 'desktop'}.png`, animations: 'disabled'});
      assert.ok(labels.some(label => label.includes('Canvas')));
      assert.ok(labels.some(label => label.includes('recovery')));
      assert.ok(labels.length <= 3);
      assert.equal(await page.locator('.apollo-pulse-icon svg').count(), labels.length);
      const position = async () => page.evaluate(isMobile => {
        const rect = selector => {
          const r = document.querySelector(selector).getBoundingClientRect();
          return {top: r.top, bottom: r.bottom};
        };
        return {composer: rect('#apolloView .apollo-composer'),
          actions: rect(isMobile ? '#apolloMobileHistory' : '#apolloView .apollo-chat-actions')};
      }, mobile);
      const before = await position();
      await page.locator('#apolloPulse').evaluate(node => node.classList.add('is-hidden'));
      await page.waitForTimeout(320);
      const hidden = await position();
      await page.locator('#apolloPulse').evaluate(node => node.classList.remove('is-hidden'));
      await page.waitForTimeout(320);
      const visible = await position();
      for (const state of [hidden, visible]) {
        assert.ok(Math.abs(state.composer.top - before.composer.top) < 0.5);
        assert.ok(Math.abs(state.actions.top - before.actions.top) < 0.5);
      }
      await page.locator('.apollo-pulse-dismiss').first().click();
      await page.waitForFunction(first => ![...document.querySelectorAll('.apollo-pulse-item')]
        .some(button => button.textContent === first), labels[0]);
      const afterDismiss = await page.locator('.apollo-pulse-item').allTextContents();
      assert.ok(!afterDismiss.includes(labels[0]));
      tasks = [{id: 3, title: 'New task', source: 'apollo', active: true, completed: false,
        due_at: new Date(Date.now() + 2 * 3600000).toISOString()}];
      await page.evaluate(() => { apolloPulseLastRefresh = 0; return apolloPulseRefresh(true); });
      await page.getByRole('button', {name: 'Plan my tasks due soon', exact: true}).waitFor();
      tasks = [];
      events = [];
      whoop = {status: 'processing', summary: {}};
      await page.evaluate(() => { apolloPulseLastRefresh = 0; return apolloPulseRefresh(true); });
      const spotify = page.locator('.apollo-pulse-item').filter({hasText: 'Explore Spotify listening to Verified Artist'});
      await spotify.waitFor();
      const spotifyImage = spotify.locator('img');
      await spotifyImage.waitFor();
      assert.equal(await spotifyImage.evaluate(image => image.complete && image.naturalWidth > 0), true);
      await page.reload({waitUntil: 'domcontentloaded'});
      await page.evaluate(() => window.openApollo());
      await page.locator('.apollo-pulse-item').first().waitFor();
      assert.ok((await page.locator('.apollo-pulse-item').allTextContents()).some(label => label.includes('Verified Artist')));
      await page.locator('.apollo-pulse-item').filter({hasText: 'Explore Spotify listening to Verified Artist'}).click();
      await page.locator('.apollo-message.user').getByText('Explore my recent Spotify listening patterns', {exact: false}).waitFor();
      assert.deepEqual(errors, []);
      console.log(`${mobile ? 'iPhone' : 'desktop'} Pulse icons, sources, refresh, dismissal, and stationary controls passed`);
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
