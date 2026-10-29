/* Isolated local fixture. The default run observes Studio for ten real minutes. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');

const base = process.env.APOLLO_TEST_URL || 'http://localhost:8906';
const elapsedMs = Number(process.env.APOLLO_ELAPSED_TEST_MS || 600000);
const passphrase = 'browser fixture passphrase 1234';

async function apiStatus(page, path) {
  return page.evaluate(async path => (await fetch(path, {cache:'no-store'})).status, path);
}
async function unlock(page) {
  const methods = page.locator('#apolloSecretMethods');
  if (!await methods.evaluate(node => node.open)) await methods.locator('summary').click();
  await page.locator('#apolloSecuritySecret').fill(passphrase);
  await page.getByRole('button', {name:'Unlock with passphrase'}).click();
  await page.waitForFunction(() => !document.body.classList.contains('apollo-security-conceal'));
}

(async () => {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const context = await browser.newContext({viewport:{width:1280,height:850}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base, {waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
    await page.evaluate(() => window.openSettings());
    await page.locator('.apollo-settings-disclosure').filter({hasText:'Privacy & Security'}).click();
    await page.getByPlaceholder('Operator setup token').fill('fixture-only-operator-token');
    await page.getByPlaceholder('New passphrase (16+ characters)').fill(passphrase);
    await page.getByRole('button', {name:'Set up security'}).click();
    await page.locator('.apollo-security-codes').waitFor();
    for (const resource of ['studio','settings']) {
      await page.locator(`input[data-resource="${resource}"]`).check();
      await page.locator(`select[data-resource="${resource}"]`).selectOption('leave');
    }
    await page.getByRole('button', {name:'Save security settings'}).click();
    await page.evaluate(() => window.openStudio());
    await page.getByText('Unlock Studio', {exact:true}).waitFor();
    await unlock(page);
    assert.equal(await apiStatus(page, '/api/studio/projects'), 200);

    const beginning = Date.now();
    while (Date.now() - beginning < elapsedMs) {
      await page.waitForTimeout(Math.min(30000, elapsedMs - (Date.now() - beginning)));
      assert.equal(await apiStatus(page, '/api/studio/projects'), 200, 'Studio API must remain authorized');
      assert.equal(await page.locator('#studioView').isVisible(), true, 'Studio must remain visible');
      assert.equal(await page.locator('body').evaluate(node => node.classList.contains('apollo-security-conceal')), false);
    }
    console.log(`Studio stayed unlocked for ${Math.floor((Date.now()-beginning)/1000)} real seconds`);

    const second = await context.newPage();
    second.on('pageerror', error => errors.push(error.message));
    await second.goto(base, {waitUntil:'domcontentloaded'});
    await second.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
    await second.evaluate(() => window.openStudio());
    await second.waitForFunction(() => document.body.dataset.apolloRoute === 'studio');
    assert.equal(await apiStatus(second, '/api/studio/projects'), 200);
    await page.bringToFront();
    assert.equal(await apiStatus(page, '/api/studio/projects'), 200, 'Visibility switch must not revoke Studio');
    await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
    await page.evaluate(() => window.openStudio());
    await page.waitForFunction(() => document.body.dataset.apolloRoute === 'studio');
    assert.equal(await apiStatus(page, '/api/studio/projects'), 200, 'Refresh must retain valid lease');
    await page.route('**/api/security/state', route => route.abort('failed'));
    await page.waitForTimeout(6000);
    assert.equal(await page.locator('body').evaluate(node => node.classList.contains('apollo-security-conceal')),
      false, 'A short status-network failure must not discard the visible Studio session');
    await page.unroute('**/api/security/state');
    await page.waitForTimeout(5500);
    assert.equal(await apiStatus(page, '/api/studio/projects'), 200);

    await page.evaluate(() => window.openHome());
    await page.waitForFunction(() => document.body.dataset.apolloRoute === 'home');
    assert.equal(await apiStatus(second, '/api/studio/projects'), 200, 'Another active Studio tab must keep its grant');
    await page.evaluate(() => window.openStudio());
    await page.getByText('Unlock Studio', {exact:true}).waitFor();
    await second.evaluate(() => window.openHome());
    await second.waitForFunction(() => document.body.dataset.apolloRoute === 'home');
    await second.waitForFunction(async () => (await fetch('/api/studio/projects')).status === 423);

    const fresh = await browser.newContext();
    const locked = await fresh.newPage();
    await locked.goto(base + '/?tab=settings', {waitUntil:'domcontentloaded'});
    await locked.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
    await locked.evaluate(() => window.openSettings());
    await locked.getByText('Verify security settings', {exact:true}).waitFor();
    assert.equal(await apiStatus(locked, '/api/security/passkeys'), 423);
    assert.equal(await locked.evaluate(async () => (await fetch('/api/security/policy', {
      method:'POST', headers:{'Content-Type':'application/json','X-Apollo-Request':'security'},
      body:JSON.stringify({tabs:{},privacy:'standard',protect_spotify:false})})).status), 423);
    const authorizedPasskeys = locked.waitForResponse(response =>
      response.url().endsWith('/api/security/passkeys') && response.status() === 200);
    await unlock(locked);
    await authorizedPasskeys;
    assert.equal(await apiStatus(locked, '/api/security/passkeys'), 423,
      'A bare API request without the tab identifier must still be denied');
    const sibling = await fresh.newPage();
    await sibling.goto(base, {waitUntil:'domcontentloaded'});
    await sibling.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
    assert.equal(await apiStatus(sibling, '/api/security/passkeys'), 423,
      'A second tab must not inherit the Settings grant');
    await sibling.evaluate(() => window.openSettings());
    await sibling.getByText('Verify security settings', {exact:true}).waitFor();
    await locked.reload({waitUntil:'domcontentloaded'});
    await locked.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
    assert.equal(await apiStatus(locked, '/api/security/passkeys'), 423,
      'Refreshing Settings must require a new per-tab verification');
    await locked.evaluate(() => window.openSettings());
    await locked.getByText('Verify security settings', {exact:true}).waitFor();
    assert.deepEqual(errors, []);
    console.log('Leave, multiple tabs, refresh, visibility, temporary network loss and locked Settings passed');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exit(1);});
