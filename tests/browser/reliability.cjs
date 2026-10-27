/* Run against reliability_fixture.py. External integrations are deterministic fixtures. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const origin = process.env.APOLLO_TEST_URL || 'http://127.0.0.1:8876';
const output = process.env.APOLLO_TEST_OUTPUT || '/tmp/apollo-browser-results';
fs.mkdirSync(output, {recursive: true});
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    for (const viewport of [{width: 1440, height: 1000}, {width: 390, height: 844}]) {
      const name = viewport.width < 500 ? 'iphone' : 'desktop';
      const context = await browser.newContext({viewport, timezoneId: 'Europe/Zurich', isMobile: name === 'iphone', hasTouch: name === 'iphone'});
      const page = await context.newPage();
      const errors = []; page.on('pageerror', error => errors.push(error.message));
      try {
        await context.request.get(origin + '/__test/health?status=reconnection_required');
        await page.goto(origin, {waitUntil: 'domcontentloaded'});
        await page.locator('#apolloConnectionBanner').waitFor({state: 'visible'});
        await page.locator('#apolloConnectionBanner').scrollIntoViewIfNeeded();
        await page.waitForFunction(() => document.querySelector('#homeView > .header').getBoundingClientRect().bottom <= document.getElementById('apolloConnectionBanner').getBoundingClientRect().top);
        await page.screenshot({path: `${output}/${name}-health.png`, animations: 'disabled'});
        await page.locator('#apolloDebriefText').getByText('Class and an upcoming deadline', {exact: true}).waitFor();
        await page.locator('#apolloDebriefText').getByText('Read more', {exact: true}).click();
        await page.getByText('Extra context appears only after expanding this story.', {exact: false}).waitFor();
        await page.locator('.apollo-debrief-feedback[data-feedback="not_interested"]').click();
        await page.waitForFunction(() => document.querySelector('[data-feedback="not_interested"]')?.getAttribute('aria-pressed') === 'true');
        const feedback = await (await context.request.get(origin + '/api/debrief')).json();
        assert.equal(feedback.feedback['fixture-news'], 'not_interested');
        await page.screenshot({path: `${output}/${name}-home.png`, fullPage: true});
        await page.locator('#apolloConnectionBanner > button').click();
        await page.locator('#settingsView.active').waitFor();
        await page.evaluate(() => window.openHome());
        await page.locator('#apolloConnectionBanner summary').click();
        await page.locator('#apolloConnectionBanner a').click();
        await page.waitForURL(origin + '/');
        await page.waitForFunction(() => document.getElementById('apolloConnectionBanner').hidden);
        await context.request.get(origin + '/__test/health?status=temporary_error');
        await page.evaluate(() => window.apolloRefreshConnectionHealth(true));
        assert.equal(await page.locator('#apolloConnectionBanner').isVisible(), false);
        console.log(`${name}: Home health, reconnect, outage and persistent feedback passed`);

        await page.evaluate(() => window.openRoutines());
        const water = page.locator('[data-water="710"]'); await water.waitFor();
        const before = await (await context.request.get(origin + '/api/routines?timezone=Europe%2FZurich')).json();
        let writes = 0;
        await page.route('**/api/routines/action', async route => {
          if (route.request().postDataJSON()?.action === 'log_water') { writes++; await new Promise(resolve => setTimeout(resolve, 250)); }
          await route.continue();
        });
        const rect = await water.boundingBox();
        await page.mouse.click(rect.x + rect.width / 2, rect.y + rect.height / 2, {clickCount: 3, delay: 30});
        await page.waitForFunction(() => !document.querySelector('[data-water="710"]')?.disabled);
        const after = await (await context.request.get(origin + '/api/routines?timezone=Europe%2FZurich')).json();
        assert.equal(after.hydration.total_ml - before.hydration.total_ml, 710);
        assert.equal(writes, 1);
        assert.equal(after.hydration.entries.length - before.hydration.entries.length, 1);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2), true);
        await page.screenshot({path: `${output}/${name}-water.png`, fullPage: true});
        console.log(`${name}: +710 mL exactly once and responsive layout passed`);

        const chatId = (await (await context.request.post(origin + '/api/chats', {data: {}})).json()).id;
        await page.evaluate(async id => { window.openApollo(); await window.apolloHistoryOpenChat(id); }, chatId);
        const png = await (await context.request.get(origin + '/fixture-image.png')).body();
        await page.locator('#apolloFileInput').setInputFiles([
          {name: 'photo.png', mimeType: 'image/png', buffer: png},
          {name: 'wrong-mime.dat', mimeType: 'application/octet-stream', buffer: png}
        ]);
        await page.locator('#apolloInput').fill('Describe these attachments.');
        await page.locator('#apolloSend').click();
        await page.waitForFunction(() => Array.from(document.querySelectorAll('.apollo-message.user img')).filter(img => img.complete && img.naturalWidth > 0).length >= 2);
        await page.waitForFunction(() => Array.from(document.querySelectorAll('.apollo-message.assistant img')).some(img => img.complete && img.naturalWidth > 0));
        const chat = await (await context.request.get(origin + '/api/chats/' + chatId)).json();
        assert.equal(chat.messages.filter(item => item.role === 'user').at(-1).attachments.length, 2);
        assert.equal(chat.messages.filter(item => item.role === 'user').at(-1).attachments[1].mime_type, 'image/png');
        await page.locator('.apollo-message.user img').last().click();
        await page.getByRole('dialog', {name: 'wrong-mime.dat'}).waitFor();
        await page.getByRole('button', {name: 'Close image preview'}).click();
        await page.evaluate(async id => { await window.apolloHistoryOpenChat(2); await window.apolloHistoryOpenChat(id); }, chatId);
        await page.waitForFunction(() => Array.from(document.querySelectorAll('.apollo-message.user img')).filter(img => img.complete && img.naturalWidth > 0).length >= 2);
        await page.reload({waitUntil: 'domcontentloaded'});
        await page.evaluate(async id => { window.openApollo(); await window.apolloHistoryOpenChat(id); }, chatId);
        await page.waitForFunction(() => Array.from(document.querySelectorAll('.apollo-message img')).filter(img => img.complete && img.naturalWidth > 0).length >= 3);
        await page.waitForFunction(() => Array.from(document.querySelectorAll('.apollo-message img')).every(img => img.naturalWidth > 0 && Number(getComputedStyle(img).opacity) > .95));
        const ratios = await page.locator('.apollo-message img').evaluateAll(images => images.map(img => img.getBoundingClientRect().width / img.getBoundingClientRect().height));
        assert.ok(ratios.every(ratio => Math.abs(ratio - 2) < .05));
        await page.screenshot({path: `${output}/${name}-chat.png`, fullPage: true, animations: 'disabled'});
        await page.evaluate(() => window.apolloAddMessage('assistant', '![Missing image](/api/chat-media/' + '0'.repeat(64) + ')', [], true));
        await page.locator('img[alt="Missing image"]').scrollIntoViewIfNeeded();
        await page.locator('.apollo-image-retry:visible').waitFor();
        assert.equal(await page.locator('.apollo-ui-figure.has-error').count(), 1);
        await page.evaluate(() => window.apolloAddMessage('user', 'Missing attachment', [{url: '/api/chat-attachments/999999', mime_type: 'image/png', filename: 'Lost upload'}], true));
        await page.locator('img[alt="Lost upload"]').scrollIntoViewIfNeeded();
        await page.locator('.apollo-message.user .apollo-ui-figure.has-error .apollo-image-status').waitFor({state: 'visible'});
        console.log(`${name}: upload, MIME repair, multiple images, Markdown, viewer, chat switch, refresh and errors passed`);
        assert.deepEqual(errors, []);
      } catch (error) {
        await page.screenshot({path: `${output}/${name}-failure.png`, fullPage: true});
        console.error('PAGE ERRORS:', errors);
        throw error;
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
