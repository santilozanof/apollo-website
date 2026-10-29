/* Synthetic artwork and queue; checks real DOM and layout at desktop/iPhone sizes. */
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
      let playback = {playing:true, title:'Test Track', track_id:'first', artists:'Test Artist',
        artwork:'/tests/browser/fixture-art.svg?first', duration_ms:220000,
        connection_state:'connected', playback_state:'playing'};
      await page.route('**/api/now-playing', route => route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(playback)}));
      await page.route('**/api/spotify/queue**', route => route.fulfill({status:200, contentType:'application/json', body:JSON.stringify({
        current:{name:playback.title, artists:playback.artists, artwork:playback.artwork},
        queue:Array.from({length:30}, (_,i) => ({name:`Queue song ${i}`, artists:'Fixture Artist',
          duration_ms:190000, artwork:'/tests/browser/fixture-art.svg'}))})}));
      await page.goto(origin, {waitUntil:'domcontentloaded'});
      await page.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
      await page.evaluate(() => window.apolloRefreshGlobalMusic());
      await page.waitForFunction(() => document.querySelector('.card[data-section="music"]')?.classList.contains('is-playing'));
      let art = await page.evaluate(() => ({value:document.querySelector('.card[data-section="music"]').style.getPropertyValue('--apollo-home-artwork'),
        opacity:getComputedStyle(document.querySelector('.card[data-section="music"]'),'::before').opacity}));
      assert.match(art.value, /fixture-art/);
      assert.ok(Number(art.opacity) > 0);
      await page.evaluate(() => document.documentElement.setAttribute('data-theme','light'));
      assert.ok(Number(await page.locator('.card[data-section="music"]').evaluate(node => getComputedStyle(node,'::before').opacity)) > 0);
      await page.evaluate(() => document.documentElement.setAttribute('data-theme','dark'));
      playback = {...playback, playing:false, playback_state:'paused'};
      await page.evaluate(() => window.apolloRefreshGlobalMusic());
      await page.waitForFunction(() => !document.querySelector('.card[data-section="music"]').classList.contains('is-playing'));
      playback = {...playback, playing:true, playback_state:'playing', track_id:'second', artwork:'/tests/browser/fixture-art.svg?second'};
      await page.evaluate(() => window.apolloRefreshGlobalMusic());
      await page.waitForFunction(() => document.querySelector('.card[data-section="music"]').style.getPropertyValue('--apollo-home-artwork').includes('?second'));

      await page.evaluate(() => window.openMusic());
      await page.locator('#apolloNowPlaying:not(.is-loading)').waitFor();
      const before = await page.evaluate(() => {const view=document.querySelector('#musicView'); view.scrollTop=110; return view.scrollTop;});
      await page.locator('#apolloQueueTrigger').click();
      await page.locator('#apolloQueuePanel.is-open').waitFor();
      await page.waitForTimeout(360);
      assert.equal(await page.locator('#apolloQueuePanel').evaluate(node => node.parentElement === document.body), true);
      assert.equal(await page.locator('#apolloQueueScroll').evaluate(node => node.scrollHeight > node.clientHeight), true);
      await page.locator('#apolloQueueScroll').hover({force:true}).catch(() => {});
      await page.locator('#apolloQueueScroll').evaluate(node => {node.scrollTop = 180; node.dispatchEvent(new WheelEvent('wheel',{deltaY:200,bubbles:true}));});
      assert.ok(await page.locator('#apolloQueueScroll').evaluate(node => node.scrollTop > 0));
      assert.equal(await page.locator('#musicView').evaluate(node => node.scrollTop), before);
      assert.equal(await page.locator('body').evaluate(node => node.classList.contains('apollo-music-queue-open')), true);
      const panel = await page.locator('#apolloQueuePanel').boundingBox();
      assert.ok(panel.x >= -1 && panel.x + panel.width <= viewport.width + 1);
      assert.ok(panel.y >= -1 && panel.y + panel.height <= viewport.height + 1);
      await page.evaluate(() => document.documentElement.setAttribute('data-theme','light'));
      assert.equal(await page.locator('#apolloQueuePanel').isVisible(), true);
      await page.evaluate(() => document.documentElement.setAttribute('data-theme','dark'));
      await page.keyboard.press('Escape');
      await page.waitForFunction(() => !document.body.classList.contains('apollo-music-queue-open'));
      assert.equal(await page.locator('#musicView').evaluate(node => node.scrollTop), before);

      await page.evaluate(() => window.openApollo());
      await page.waitForFunction(() => document.querySelector('#apolloView')?.classList.contains('active'));
      await page.waitForTimeout(280);
      await page.evaluate(() => {apolloAddMessage('assistant','First answer'); apolloAddMessage('assistant','Second answer');});
      const messages = page.locator('#apolloView .apollo-message.assistant').filter({has:page.locator('.apollo-message-actions')});
      const first = messages.nth((await messages.count())-2), second = messages.last();
      const firstActions = first.locator('.apollo-message-actions'), secondActions = second.locator('.apollo-message-actions');
      const geometry = await first.evaluate(node => {
        const text=node.querySelector('.apollo-message-body').getBoundingClientRect();
        const paths=[...node.querySelector('.apollo-message-actions svg').children].map(child => child.getBoundingClientRect().left);
        return {text:text.left, icon:Math.min(...paths)};
      });
      assert.ok(Math.abs(geometry.text-geometry.icon)<3, JSON.stringify(geometry));
      if (mobile) {
        assert.ok(Number(await firstActions.evaluate(node => getComputedStyle(node).opacity)) > .5);
        assert.ok(await firstActions.locator('button').first().evaluate(node => node.getBoundingClientRect().width >= 44));
      } else {
        assert.equal(Number(await firstActions.evaluate(node => getComputedStyle(node).opacity)),0);
        await first.locator('.apollo-message-body').hover();
        await page.waitForTimeout(220);
        assert.ok(Number(await firstActions.evaluate(node => getComputedStyle(node).opacity)) > .9);
        assert.equal(Number(await secondActions.evaluate(node => getComputedStyle(node).opacity)),0);
        await firstActions.locator('button').first().hover();
        assert.ok(Number(await firstActions.evaluate(node => getComputedStyle(node).opacity)) > .9);
        await secondActions.locator('button').first().focus();
        await page.waitForTimeout(220);
        assert.ok(Number(await secondActions.evaluate(node => getComputedStyle(node).opacity)) > .9);
      }
      console.log(`${mobile?'iPhone':'desktop'} Home art, queue scroll/overlay and response actions passed`);
      await context.close();
    }
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exit(1);});
