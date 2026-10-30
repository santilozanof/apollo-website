/* Run against the isolated media_ranking_fixture.py server on localhost:8910. */
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:900},deviceScaleFactor:2});
    const historyReads = [];
    page.on('request', request => {
      if (/\/api\/chats(?:\/search|\/\d+)/.test(request.url())) historyReads.push(request.url());
    });
    await page.goto('http://localhost:8910/', {waitUntil:'domcontentloaded'});
    await page.locator('.apollo-home-quick button').first().waitFor();
    assert.equal(await page.locator('.apollo-home-quick button').count(), 4);
    assert.equal(await page.locator('.card[data-section="recent"]').count(), 0);
    assert.equal(historyReads.length, 0, 'Home must not fetch protected History data');

    async function focusCheck(inputSelector, wrapperSelector) {
      await page.evaluate(() => document.activeElement?.blur());
      const unfocusedBorder = await page.locator(wrapperSelector).evaluate(el => getComputedStyle(el).borderTopColor);
      await page.locator(inputSelector).focus();
      await page.waitForTimeout(80);
      const state = await page.evaluate(({inputSelector,wrapperSelector}) => {
        const inner = getComputedStyle(document.querySelector(inputSelector));
        const outer = getComputedStyle(document.querySelector(wrapperSelector));
        return {innerOutline:inner.outlineStyle, innerBorder:inner.borderTopWidth,
          outerBorder:outer.borderTopColor, outerRadius:outer.borderTopLeftRadius};
      }, {inputSelector,wrapperSelector});
      assert.equal(state.innerOutline, 'none', `${inputSelector} has a rectangular inner outline`);
      assert.equal(state.innerBorder, '0px', `${inputSelector} has a nested border`);
      assert.notEqual(state.outerBorder, unfocusedBorder, `${wrapperSelector} lacks keyboard focus`);
      assert.notEqual(state.outerRadius, '0px');
    }
    for (const theme of ['dark','light']) {
      await page.evaluate(theme => document.documentElement.setAttribute('data-theme', theme), theme);
      await page.waitForTimeout(120);
      await focusCheck('.ask-input', '.ask-box');
      const colors = await page.evaluate(() => {
        const el = document.querySelector('.card[data-section="quick-access"]');
        return [getComputedStyle(el).backgroundColor,
          getComputedStyle(document.querySelector('.ask-box')).borderTopColor];
      });
      for (const color of colors) {
        const rgb = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        if (rgb) assert.equal(rgb[1], rgb[2], `non-neutral color ${color}`),
          assert.equal(rgb[2], rgb[3], `non-neutral color ${color}`);
      }
      await page.screenshot({path:`/private/tmp/apollo-home-quick-desktop-${theme}.png`});
    }
    await page.locator('[data-apollo-quick="new-chat"]').click();
    await page.locator('.apollo-input').waitFor();
    await focusCheck('.apollo-input', '.apollo-composer');
    await page.evaluate(() => window.apolloNavigate('home'));
    await page.locator('[data-apollo-quick="university"]').click();
    await page.waitForFunction(() => document.body.dataset.apolloRoute === 'tasks');
    await page.evaluate(() => window.apolloNavigate('home'));
    await page.locator('[data-apollo-quick="music-insights"]').click();
    await page.waitForFunction(() => document.body.dataset.apolloRoute === 'music');
    await page.evaluate(() => window.apolloNavigate('home'));
    await page.setViewportSize({width:390,height:844});
    for (const theme of ['dark','light']) {
      await page.evaluate(theme => document.documentElement.setAttribute('data-theme', theme), theme);
      await page.waitForTimeout(120);
      await focusCheck('.ask-input', '.ask-box');
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.screenshot({path:`/private/tmp/apollo-home-quick-mobile-${theme}.png`});
    }
    console.log('Home Quick Access and rounded input focus passed: navigation, neutral colors, desktop/mobile, dark/light.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
