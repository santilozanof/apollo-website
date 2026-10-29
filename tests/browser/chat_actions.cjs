const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const origin = process.env.APOLLO_TEST_URL || 'http://127.0.0.1:8895';
(async () => {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    for (const viewport of [{width:1440,height:900},{width:390,height:844}]) {
      const mobile = viewport.width < 500;
      const context = await browser.newContext({viewport, isMobile:mobile, hasTouch:mobile});
      const page = await context.newPage();
      let retries = 0;
      await page.route('**/api/chats/7/generations', route => {
        retries++; return route.fulfill({status:200, contentType:'application/json', body:'{"id":"fixture-generation"}'});
      });
      await page.route('**/api/chats/7/generations/fixture-generation', route =>
        route.fulfill({status:200, contentType:'application/json', body:JSON.stringify({
          state:'complete', status:'Done', content:'Retried answer',
          message:{content:'Retried answer', attachments:[]}
        })}));
      await page.goto(origin, {waitUntil:'domcontentloaded'});
      await page.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
      await page.evaluate(() => {
        openApollo(); apolloChatId = 7;
        Object.defineProperty(navigator, 'clipboard', {configurable:true,
          value:{writeText:async value => { window.__copied = value; }}});
        apolloAddMessage('user','Question'); apolloAddMessage('assistant','Original answer');
      });
      const answer = page.locator('#apolloView .apollo-message.assistant').last();
      if (!mobile) await answer.hover();
      await answer.getByRole('button', {name:'Copy response'}).click();
      assert.equal(await page.evaluate(() => window.__copied), 'Original answer');
      await answer.getByRole('button', {name:'Retry response'}).click();
      await page.getByText('Retried answer', {exact:true}).waitFor();
      assert.equal(retries, 1);
      console.log(`${mobile?'iPhone':'desktop'} Copy and Retry interaction passed`);
      await context.close();
    }
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exit(1);});
