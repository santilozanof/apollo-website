/* Real local handler and SQLite, synthetic delayed model stream. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const origin = process.env.APOLLO_TEST_URL || 'http://127.0.0.1:8876';

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin, {waitUntil: 'domcontentloaded'});
    const chat = (await (await page.request.post(origin + '/api/chats', {data: {}})).json()).id;
    await page.evaluate(async id => { window.openApollo(); await window.apolloHistoryOpenChat(id); }, chat);
    await page.locator('#apolloInput').fill('Delayed fixture question');
    await page.locator('#apolloSend').click();
    await page.locator('.apollo-message.user').getByText('Delayed fixture question').waitFor();
    await page.evaluate(() => window.apolloHistoryNewChat());
    await page.waitForTimeout(600);
    assert.equal(await page.locator('#apolloSend').getAttribute('aria-label'), 'Send');
    await page.waitForFunction(async id => {
      const response = await fetch(`/api/chats/${id}`);
      const body = await response.json();
      return body.messages.some(message => message.role === 'assistant' && message.content.includes('Delayed fixture answer'));
    }, chat, {timeout: 20000});
    await page.evaluate(async id => window.apolloHistoryOpenChat(id), chat);
    await page.getByText('The response began after preparation.', {exact: true}).waitFor();

    const stopChat = (await (await page.request.post(origin + '/api/chats', {data: {}})).json()).id;
    await page.evaluate(async id => window.apolloHistoryOpenChat(id), stopChat);
    await page.locator('#apolloInput').fill('Slow fixture question');
    await page.locator('#apolloSend').click();
    await page.getByText('First complete sentence.', {exact: false}).waitFor();
    await page.locator('#apolloSend').click();
    await page.waitForFunction(async id => {
      const response = await fetch(`/api/chats/${id}`);
      const body = await response.json();
      return !body.messages.some(message => message.role === 'assistant' && message.content.includes('This arrives after the stop'));
    }, stopChat);
    const stopped = await (await page.request.get(origin + `/api/chats/${stopChat}/generations/active`)).json();
    assert.equal(stopped.generation, null);
    assert.deepEqual(errors, []);
    console.log('Background generation survives chat switch; explicit Stop and UI recovery passed');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
