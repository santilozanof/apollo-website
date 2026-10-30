/* Isolated local fixture: private reply and History share one progressive UI. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');

const base = process.env.APOLLO_TEST_URL || 'http://localhost:8908';
const passphrase = 'browser fixture passphrase 1234';

async function security(page, path, body) {
  return page.evaluate(async ({path, body}) => {
    const response = await fetch('/api/security/' + path, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type':'application/json','X-Apollo-Request':'security'},
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return {status:response.status, data:await response.json()};
  }, {path, body});
}

async function showInline(page, resource) {
  await page.evaluate(resource => {
    const mount = resource === 'history' ? document.querySelector('#apolloHistoryTrack')
      : document.querySelector('#apolloView');
    if (resource === 'private') {
      document.querySelector('#privacyUnlockFixture')?.remove();
      const holder = document.createElement('div');
      holder.id = 'privacyUnlockFixture';
      holder.style.cssText = 'width:min(100%, 680px);margin:90px auto 24px';
      mount.prepend(holder);
      window.__privacyUnlock = window.apolloSecurityUnlockInline(resource, holder);
      window.__privacyUnlock.catch(() => {});
    } else {
      mount.querySelector('.apollo-security-inline')?.remove();
      window.__privacyUnlock = window.apolloSecurityUnlockInline(resource, mount);
      window.__privacyUnlock.catch(() => {});
    }
  }, resource);
  await page.locator('.apollo-security-inline').first().waitFor();
}

async function checkLayout(page, resource, theme, size) {
  await page.evaluate(theme => document.documentElement.setAttribute('data-theme', theme), theme);
  await page.waitForTimeout(260);
  const card = page.locator('.apollo-security-inline').first();
  const box = await card.boundingBox();
  assert.ok(box && box.width <= (resource === 'history' ? 340 : 341), `${resource} width: ${box?.width}`);
  assert.ok(box.height < 190, `${resource} default height: ${box.height}`);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'no horizontal overflow');
  assert.equal(await page.getByRole('button', {name:'Use passphrase instead'}).isVisible(), true);
  assert.equal(await page.locator('.apollo-security-inline input[aria-label="Security passphrase"]').isVisible(), false,
    'collapsed credential field must be hidden');
  await card.screenshot({path:`/private/tmp/apollo-privacy-${resource}-${size}-${theme}.png`});
}

(async () => {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:900}});
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
    const recoveryCode = (await page.locator('.apollo-security-codes').textContent()).split(':').at(-1).trim().split(/\s+/)[0];
    const cdp = await context.newCDPSession(page);
    await cdp.send('WebAuthn.enable');
    await cdp.send('WebAuthn.addVirtualAuthenticator', {options:{protocol:'ctap2', transport:'internal',
      hasResidentKey:true, hasUserVerification:true, isUserVerified:true, automaticPresenceSimulation:true}});
    await page.getByRole('button', {name:'Add a passkey'}).click();
    await page.getByText('Passkey added.', {exact:true}).waitFor();
    await page.locator('input[name="protect_sensitive_chat"]').check();
    await page.locator('input[name="protect_history"]').check();
    await page.getByRole('button', {name:'Save security settings'}).click();
    await page.evaluate(() => window.openApollo());
    await page.waitForFunction(() => document.body.dataset.apolloRoute === 'apollo');

    await showInline(page, 'private');
    for (const theme of ['light','dark']) await checkLayout(page, 'private', theme, 'desktop');
    await page.getByRole('button', {name:'Use passphrase instead'}).click();
    await page.locator('.apollo-security-inline input[aria-label="Security passphrase"]').waitFor();
    assert.equal(await page.getByRole('button', {name:'Continue with passkey'}).count(), 0);
    await page.getByRole('button', {name:'Use recovery code'}).click();
    await page.locator('.apollo-security-inline input[aria-label="One-time recovery code"]').waitFor();
    await page.getByRole('button', {name:'Back'}).click();
    await page.getByRole('button', {name:'Continue with passkey'}).click();
    await page.waitForFunction(() => !document.querySelector('#privacyUnlockFixture .apollo-security-inline'));
    assert.equal((await security(page, 'state')).data.unlocked.private, true, 'real passkey grant');

    await security(page, 'revoke', {resource:'private'});
    await showInline(page, 'private');
    await page.getByRole('button', {name:'Use passphrase instead'}).click();
    await page.locator('.apollo-security-inline input[aria-label="Security passphrase"]').fill('wrong passphrase');
    await page.getByRole('button', {name:'Unlock', exact:true}).click();
    await page.getByRole('status').filter({hasText:/invalid|incorrect|failed/i}).first().waitFor();
    assert.equal((await security(page, 'state')).data.unlocked.private, false, 'failed verification grants nothing');
    await page.locator('.apollo-security-inline input[aria-label="Security passphrase"]').fill(passphrase);
    await page.getByRole('button', {name:'Unlock', exact:true}).click();
    await page.waitForFunction(() => !document.querySelector('#privacyUnlockFixture .apollo-security-inline'));
    assert.equal((await security(page, 'state')).data.unlocked.private, true, 'real passphrase grant');

    await security(page, 'revoke', {resource:'private'});
    await showInline(page, 'private');
    await page.getByRole('button', {name:'Use passphrase instead'}).click();
    await page.getByRole('button', {name:'Use recovery code'}).click();
    await page.locator('.apollo-security-inline input[aria-label="One-time recovery code"]').fill(recoveryCode);
    await page.getByRole('button', {name:'Unlock', exact:true}).click();
    await page.waitForFunction(() => !document.querySelector('#privacyUnlockFixture .apollo-security-inline'));
    assert.equal((await security(page, 'state')).data.unlocked.private, true, 'real recovery grant');
    await security(page, 'revoke', {resource:'private'});
    await showInline(page, 'private');
    await page.getByRole('button', {name:'Use passphrase instead'}).click();
    await page.getByRole('button', {name:'Use recovery code'}).click();
    await page.locator('.apollo-security-inline input[aria-label="One-time recovery code"]').fill(recoveryCode);
    await page.getByRole('button', {name:'Unlock', exact:true}).click();
    await page.getByRole('status').filter({hasText:/invalid|used|failed/i}).first().waitFor();
    assert.equal((await security(page, 'state')).data.unlocked.private, false, 'recovery remains one-time');
    await page.getByRole('button', {name:'Cancel verification'}).click();
    assert.equal(await page.locator('#privacyUnlockFixture .apollo-security-inline').count(), 0);

    await page.evaluate(() => window.apolloOpenHistory());
    await page.locator('#apolloHistoryStrip.open').waitFor();
    await page.locator('#apolloHistoryTrack .apollo-security-inline').waitFor();
    for (const theme of ['light','dark']) await checkLayout(page, 'history', theme, 'desktop');
    await page.setViewportSize({width:390,height:844});
    for (const theme of ['light','dark']) await checkLayout(page, 'history', theme, 'mobile');
    const historyBox = await page.locator('#apolloHistoryTrack .apollo-security-inline').boundingBox();
    assert.ok(historyBox.height < 844 * .23, 'History auth should occupy a small part of the sidebar');
    await page.getByRole('button', {name:'Use passphrase instead'}).click();
    await page.locator('.apollo-security-inline input[aria-label="Security passphrase"]').fill(passphrase);
    await page.getByRole('button', {name:'Unlock', exact:true}).click();
    await page.waitForFunction(() => !document.querySelector('#apolloHistoryTrack .apollo-security-inline'));
    assert.equal((await security(page, 'state')).data.unlocked.history, true, 'History grant');
    await page.evaluate(() => window.apolloCloseHistory());
    await page.waitForFunction(async () => (await (await fetch('/api/security/state')).json()).unlocked.history === false);

    await showInline(page, 'private');
    for (const theme of ['light','dark']) await checkLayout(page, 'private', theme, 'mobile');
    await page.getByRole('button', {name:'Cancel verification'}).click();
    assert.deepEqual(errors, []);
    console.log('Private response and History progressive unlock UI passed: desktop/mobile, light/dark, passkey, passphrase, recovery, cancellation, relock');
    await context.close();
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exit(1);});
