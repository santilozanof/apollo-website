const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const origin = process.env.APOLLO_TEST_URL || 'http://127.0.0.1:8892';

(async () => {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    for (const viewport of [{width:1440,height:900},{width:390,height:844}]) {
      const mobile = viewport.width < 500;
      const context = await browser.newContext({viewport, isMobile:mobile, hasTouch:mobile});
      const page = await context.newPage();
      await page.goto(origin, {waitUntil:'domcontentloaded'});
      await page.waitForFunction(() => !document.documentElement.classList.contains('apollo-booting'));
      await page.evaluate(async () => window.openApollo());
      await page.waitForFunction(() => document.querySelector('#apolloView')?.classList.contains('active'));
      await page.evaluate(() => {
        apolloWelcome.style.display = 'none';
        for (let i=0;i<30;i++) apolloAddMessage('assistant', `Earlier response ${i}: ${'Detail. '.repeat(25)}`, [], false);
        apolloChatScroll.begin();
        apolloMessages.scrollTop = apolloMessages.scrollHeight;
      });
      await page.locator('#apolloMessages').evaluate(node => {
        node.dispatchEvent(new WheelEvent('wheel',{deltaY:-150,bubbles:true}));
        node.scrollTop = 120;
      });
      await page.waitForTimeout(50);
      const before = await page.locator('#apolloMessages').evaluate(node => node.scrollTop);
      await page.evaluate(() => {
        apolloAddMessage('assistant', '# New answer\n\n' + 'Long streamed content. '.repeat(150), [], false);
        apolloChatScroll.changed();
      });
      await page.waitForTimeout(70);
      const after = await page.locator('#apolloMessages').evaluate(node => node.scrollTop);
      assert.ok(Math.abs(after-before)<2, `scroll moved ${before} → ${after}`);
      assert.equal(await page.locator('#apolloJumpLatest').isVisible(), true);
      await page.locator('#apolloJumpLatest').click();
      const distance = await page.locator('#apolloMessages').evaluate(node => node.scrollHeight-node.clientHeight-node.scrollTop);
      assert.ok(distance<2, `jump distance ${distance}`);
      await page.evaluate(() => {apolloShowTyping('Explain something'); apolloShowTyping('Explain something');});
      assert.equal(await page.locator('#apolloTyping').count(), 1);
      assert.equal(await page.locator('#apolloTyping .apollo-typing-dots span').count(), 3);
      console.log(`${mobile?'iPhone':'desktop'} scroll hold, jump control and stable typing dots passed`);
      await context.close();
    }
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exit(1);});
