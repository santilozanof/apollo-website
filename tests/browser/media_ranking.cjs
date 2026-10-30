/* Full Chat pipeline against synthetic local SQLite and mocked fixture artwork. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');

const base = process.env.APOLLO_TEST_URL || 'http://localhost:8910';

async function send(page, text) {
  await page.locator('#apolloInput').fill(text);
  await page.locator('#apolloSend').click();
  await page.waitForFunction(() => document.querySelector('#apolloSend')?.getAttribute('aria-label') === 'Send');
}

(async () => {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:900}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('https://i.scdn.co/image/apolloFixture*', route => {
      const index = Number(route.request().url().match(/apolloFixture(\d+)$/)?.[1]);
      if (index === 4) return route.abort('failed');
      const colors = ['#777777','#999999','#555555','#bbbbbb'];
      const body = `<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="${colors[index]}"/><circle cx="50" cy="50" r="24" fill="#dddddd"/></svg>`;
      return route.fulfill({status:200,contentType:'image/svg+xml',body});
    });
    await page.goto(base, {waitUntil:'domcontentloaded'});
    await page.evaluate(() => window.openApollo());
    const started = Date.now();
    await send(page, 'Show me my top five albums this month.');
    const firstMs = Date.now() - started;
    const rankings = page.locator('.apollo-ui-media-ranking');
    await rankings.first().waitFor();
    assert.ok(firstMs < 6000, `synthetic direct ranking took ${firstMs} ms`);
    assert.equal(await rankings.count(), 1);
    assert.equal(await rankings.first().locator('.apollo-ui-media-ranking-row').count(), 5);
    assert.equal(await page.locator('.apollo-entity-card').count(), 0);
    const first = rankings.first().locator('.apollo-ui-media-ranking-row').first();
    assert.match(await first.innerText(), /Fixture Album 1[\s\S]*10[\s\S]*min[\s\S]*verified/);
    assert.equal(await first.getAttribute('href'), 'https://open.spotify.com/album/' + 'F'.repeat(22));
    await page.waitForFunction(() => [...document.querySelectorAll('.apollo-ui-media-ranking-art img')]
      .filter(image => image.src.includes('apolloFixture4')).length === 0);
    assert.equal(await rankings.first().locator('.apollo-ui-media-ranking-art img').count(), 4,
      'failed artwork must fall back cleanly');
    assert.equal(await rankings.first().locator('.apollo-ui-media-ranking-art img').first().getAttribute('alt'),
      'Fixture Album 1 album artwork');

    for (const theme of ['light','dark']) {
      await page.evaluate(theme => document.documentElement.setAttribute('data-theme',theme), theme);
      await page.waitForTimeout(260);
      await rankings.first().screenshot({path:`/private/tmp/apollo-ranking-desktop-${theme}.png`});
      await page.screenshot({path:`/private/tmp/apollo-ranking-chat-desktop-${theme}.png`});
    }
    await page.setViewportSize({width:390,height:844});
    for (const theme of ['light','dark']) {
      await page.evaluate(theme => document.documentElement.setAttribute('data-theme',theme), theme);
      await page.waitForTimeout(260);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await rankings.first().screenshot({path:`/private/tmp/apollo-ranking-iphone-${theme}.png`});
    }

    await send(page, 'But with images.');
    await rankings.nth(1).waitFor();
    assert.equal(await rankings.nth(1).locator('.apollo-ui-media-ranking-row').count(), 5);
    assert.deepEqual(await rankings.first().locator('.apollo-ui-media-ranking-title').allTextContents(),
      await rankings.nth(1).locator('.apollo-ui-media-ranking-title').allTextContents(),
      'follow-up must reuse exactly the saved dataset');
    await send(page, 'Show my top five tracks ranked by listening minutes.');
    await rankings.nth(2).waitFor();
    assert.equal(await rankings.nth(2).locator('.apollo-ui-media-ranking-row').count(), 5);
    assert.match(await rankings.nth(2).locator('.apollo-ui-media-ranking-row').first().innerText(), /Fixture Track 1[\s\S]*10[\s\S]*min/);
    await send(page, 'Compare my top albums this month with last month.');
    await page.locator('.apollo-rich-table-wrap').last().waitFor();
    assert.equal(await rankings.count(), 3, 'comparison should use the existing table presentation');

    const chatId = await page.evaluate(() => window.apolloGetActiveChatId());
    const measured = await page.evaluate(async id => {
      const chat = await (await fetch('/api/chats/' + id, {cache:'no-store'})).json();
      const content = chat.messages.find(message => message.role === 'assistant' && message.content.includes('media_ranking')).content;
      const start = performance.now();
      for (let index = 0; index < 20; index += 1) window.ApolloGenUI.render(content);
      return (performance.now() - start) / 20;
    }, chatId);
    assert.ok(measured < 50, `ranking render cost ${measured.toFixed(1)} ms`);
    await page.reload({waitUntil:'domcontentloaded'});
    await page.evaluate(id => window.apolloHistoryOpenChat(id), chatId);
    await page.waitForFunction(() => document.querySelectorAll('.apollo-ui-media-ranking').length === 3);
    assert.equal(await page.locator('.apollo-ui-media-ranking-row').count(), 15);
    assert.deepEqual(errors, []);
    console.log(`MediaRanking Chat fixture passed: A–D, streaming, persistence, links, artwork fallback, mobile and themes; response ${firstMs} ms, render ${measured.toFixed(1)} ms`);
    await context.close();
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exit(1);});
