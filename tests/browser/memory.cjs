const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const base = process.env.APOLLO_TEST_URL || 'http://127.0.0.1:8876';
  for (const viewport of [{width:1440,height:1000},{width:390,height:844}]) {
    const page = await browser.newPage({viewport});
    const seed = await page.request.post(base + '/api/memory', {data:{content:`Fixture ${viewport.width}: prefers concise answers`,key:`browser-fixture-${viewport.width}`,category:'preference'}});
    assert.equal(seed.status(),200);
    await page.goto(base);
    await page.evaluate(() => window.openSettings());
    const controls = page.locator('#apolloMemoryControls');
    await controls.locator('summary').click();
    await controls.getByText(`Fixture ${viewport.width}: prefers concise answers`,{exact:true}).waitFor();
    const check = controls.getByLabel('Search past conversations when relevant');
    await Promise.all([page.waitForResponse(r=>r.url().endsWith('/memory/settings') && r.request().method()==='POST'), check.uncheck()]);
    const state = await (await page.request.get(base+'/api/memory')).json();
    assert.equal(state.settings.history_search,0);
    await controls.getByLabel('Conversation search',{exact:true}).fill('Paris');
    await controls.getByRole('button',{name:'Search',exact:true}).click();
    await controls.getByText('History search is disabled.',{exact:true}).waitFor();
    await check.check();
    await controls.getByLabel('Topic to exclude from recall').fill('<script>alert(1)</script>');
    await controls.getByRole('button',{name:'Exclude',exact:true}).click();
    await controls.getByRole('button',{name:'Allow topic: <script>alert(1)</script>',exact:true}).waitFor();
    assert.equal(await controls.locator('script').count(),0);
    page.once('dialog', dialog => dialog.accept(`Fixture ${viewport.width}: prefers detailed answers`));
    await controls.getByRole('button',{name:'Correct',exact:true}).click();
    await controls.getByText(`Fixture ${viewport.width}: prefers detailed answers`,{exact:true}).waitFor();
    await page.screenshot({path:`/tmp/apollo-memory-${viewport.width}.png`,fullPage:true});
    await controls.getByRole('button',{name:'Forget',exact:true}).click();
    await controls.getByText('No saved memories yet.',{exact:true}).waitFor();
    await page.close();
  }
  await browser.close();
  console.log('Memory Settings browser checks passed at desktop and mobile sizes.');
})().catch(error=>{console.error(error);process.exit(1);});
